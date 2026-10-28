// OpenGOAL for PS5 - application entry: set up logging, open the display, run the launcher, start the engine.

#include <SDL3/SDL.h>
#include <errno.h>
#include <sys/stat.h>
#include <pthread.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include "ps5launcher.h"
#include "third-party/glad/include/glad/glad.h"

int gk_main(int argc, char** argv);  // game/main.cpp compiled with -Dmain=gk_main
void ps5_log(const char* fmt, ...);
void ps5_capture_stdio();
void ps5_install_crash_handler();
void ps5_inject_file_start();
void ps5_log_import_addrs();
extern "C" void ps5sdl_set_display_mode(int width, int height, int hz);

// 0777 regardless of umask: folders made by another user or an older build must stay writable for the game process
static void ensure_dir(const char* path) {
  if (mkdir(path, 0777) != 0 && errno != EEXIST) ps5_log("mkdir %s failed: errno %d (%s)", path, errno, strerror(errno));
  chmod(path, 0777);
}

extern "C" int sceSystemServiceLoadExec(const char* path, char* const argv[]);

// The engine is not re-entrant, so every game runs in a fresh process: after a game ends, or when a second game
// is picked, the app restarts itself. /data/opengoal/config/next.txt tells the new process what to do:
// "play <id>" starts that game with the start animation, "return <id>" shows the launcher with a fade-in.
static void relaunch_self(const char* mode, const std::string& game) {
  if (FILE* f = std::fopen("/data/opengoal/config/next.txt", "w")) {
    std::fprintf(f, "%s %s\n", mode, game.c_str());
    std::fclose(f);
  }
  static char arg0[] = "/app0/eboot.bin";
  char* const argv[] = {arg0, nullptr};
  ps5_log("relaunch: %s %s", mode, game.c_str());
  const int rc = sceSystemServiceLoadExec("/app0/eboot.bin", argv);
  ps5_log("relaunch failed rc=0x%x", rc);  // only reached when the console refuses
}

// The engine boots on its own thread when started from the launcher, so the launcher can keep drawing the loading
// screen until the engine asks for the GL context.
struct EngineRun {
  std::vector<std::string> args;
  std::vector<char*> argv;
  pthread_t thread{};
  int rc = 0;
  bool started = false;
};
static EngineRun g_engine;

static void* engine_thread(void*) {
  g_engine.rc = gk_main(static_cast<int>(g_engine.args.size()), g_engine.argv.data());
  return nullptr;
}

static void play_via_relaunch(const LaunchChoice& choice) {
  relaunch_self("play", choice.game);
  std::exit(0);
}

static Ps5Settings g_boot_cfg;
static void start_engine(const LaunchChoice& choice);

// Settings changed in the launcher (resolution, FSR, merge, ...) are read at process start, so a changed value restarts the
// app straight into the game (about 2 s); unchanged settings boot the engine in this process.
static void start_or_relaunch(const LaunchChoice& choice) {
  const Ps5Settings& c = ps5_settings();
  const bool changed = c.resolution != g_boot_cfg.resolution || c.upscale != g_boot_cfg.upscale || c.sharpness != g_boot_cfg.sharpness ||
                       c.merge != g_boot_cfg.merge || c.async_md != g_boot_cfg.async_md || c.lazy_mips != g_boot_cfg.lazy_mips;
  if (changed) play_via_relaunch(choice);
  else start_engine(choice);
}

static void start_engine(const LaunchChoice& choice) {
  // Folders the engine expects to exist in the project directory (the official data layout has them).
  for (const char* sub : {"goal_src", "goal_src/user", "log", "iso_data", "decompiler_out", "custom_assets"}) {
    ensure_dir((choice.project_path + "/" + sub).c_str());
  }
  ps5_log("launching %s from %s", choice.game.c_str(), choice.project_path.c_str());
  g_engine.argv.clear();
  g_engine.started = false;
  g_engine.args = {"gk", "-v", "--proj-path", choice.project_path, "--game", choice.game, "--", "-boot", "-fakeiso"};
  for (auto& a : g_engine.args) g_engine.argv.push_back(a.data());
  g_engine.argv.push_back(nullptr);
  pthread_attr_t attr;
  pthread_attr_init(&attr);
  pthread_attr_setstacksize(&attr, 64u << 20);
  g_engine.started = pthread_create(&g_engine.thread, &attr, engine_thread, nullptr) == 0;
}

int ps5_app_main() {
  ensure_dir("/data/opengoal");
  ensure_dir("/data/opengoal/log");
  ensure_dir("/data/opengoal/config");
  ensure_dir("/data/opengoal/config/OpenGOAL");  // the engine writes <game>/settings here and fails with "Permission denied" when the folder is missing
  for (const char* g : {"jak1", "jak2", "jak3"}) {
    ensure_dir((std::string("/data/opengoal/config/OpenGOAL/") + g).c_str());
    ensure_dir((std::string("/data/opengoal/") + g).c_str());
  }
  // compiled shaders are kept between runs (see the driver's shader cache); first use of a shader no longer stalls
  ensure_dir("/data/opengoal/cache");
  ensure_dir("/data/opengoal/cache/shaders");
  setenv("PS5_SHADER_CACHE_DIR", "/data/opengoal/cache/shaders", 1);
  { struct stat nf; if (stat("/data/opengoal/config/noflush.txt", &nf) == 0) setenv("PS5_NO_BUFFER_FLUSH", "1", 1); }  // experiment flag
  { struct stat nf; if (stat("/data/opengoal/config/nodescflush.txt", &nf) == 0) setenv("PS5_NO_DESC_FLUSH", "1", 1); }  // diagnostic flag
  { struct stat nf; if (stat("/data/opengoal/config/fulldescflush.txt", &nf) == 0) setenv("PS5_FULL_DESC_FLUSH", "1", 1); }  // A/B flag: old whole-bank descriptor flush
  if (FILE* mf = std::fopen("/data/opengoal/config/buffermem.txt", "r")) {  // experiment: memory type for vertex/index/uniform buffers
    int t = -1;
    if (std::fscanf(mf, "%d", &t) == 1 && t >= 0) setenv("PS5_BUFFER_MEM_TYPE", std::to_string(t).c_str(), 1);
    std::fclose(mf);
  }
  if (FILE* ff = std::fopen("/data/opengoal/config/flipmode.txt", "r")) {  // experiment: force the flip mode (1 vsync, 2 immediate)
    int m = 0;
    if (std::fscanf(ff, "%d", &m) == 1 && m > 0) setenv("PS5_FLIP_MODE", std::to_string(m).c_str(), 1);
    std::fclose(ff);
  }
  if (FILE* wf = std::fopen("/data/opengoal/config/workeryield.txt", "r")) {  // experiment: idle prep workers yield after N spins
    int n = -1;
    if (std::fscanf(wf, "%d", &n) == 1 && n >= 0) setenv("PS5_WORKER_YIELD", std::to_string(n).c_str(), 1);
    std::fclose(wf);
  }
  { struct stat nf; if (stat("/data/opengoal/config/glthread.txt", &nf) == 0) { setenv("PS5_GLTHREAD", "1", 1); } }  // experiment: Mesa GL command thread
  { struct stat nf; if (stat("/data/opengoal/config/norename.txt", &nf) == 0) setenv("PS5_NO_BUFFER_RENAME", "1", 1); }  // A/B: disable buffer renaming
  { struct stat nf; if (stat("/data/opengoal/config/spinwait.txt", &nf) == 0) setenv("PS5_SPIN_WAIT", "1", 1); }
  { struct stat nf; if (stat("/data/opengoal/config/nomipcpu.txt", &nf) == 0) setenv("PS5_MIP_SKIP_CPU", "1", 1); }
  { struct stat nf; if (stat("/data/opengoal/config/nomultidraw.txt", &nf) == 0) setenv("PS5_NO_MULTIDRAW", "1", 1); }  // A/B: no synchronous multi-draw batches, driver patch 46
  { struct stat nf; if (stat("/data/opengoal/config/syncdebug.txt", &nf) == 0) { setenv("PS5_SYNC_DEBUG", "1", 1); setenv("PS5_NO_COMBINE", "1", 1); } }  // glitch classification, driver patch 52
  { struct stat nf; if (stat("/data/opengoal/config/noasyncmultidraw.txt", &nf) != 0) setenv("PS5_ASYNC_MULTIDRAW", "1", 1); }  // driver patch 53, default on
  { struct stat nf; if (stat("/data/opengoal/config/nomerge.txt", &nf) != 0) setenv("PS5_MERGE_DRAWS", "1", 1); }  // shim merge patch, default on
  { struct stat nf; if (stat("/data/opengoal/config/mergestats.txt", &nf) == 0) setenv("PS5_MERGE_STATS", "1", 1); }
  { struct stat nf; if (stat("/data/opengoal/config/mipfast.txt", &nf) == 0) setenv("PS5_MIPFAST", "1", 1); }  // driver patch 59 (bit 1 lazy mips)
  { struct stat nf; if (stat("/data/opengoal/config/mipfast3.txt", &nf) == 0) setenv("PS5_MIPFAST", "3", 1); }  // lazy + tail skip
  { struct stat nf; if (stat("/data/opengoal/config/waitus100.txt", &nf) == 0) setenv("PS5_WAIT_US", "100", 1); }  // driver patch 60
  { struct stat nf; if (stat("/data/opengoal/config/workerdiag.txt", &nf) == 0) setenv("PS5_WORKER_DIAG", "1", 1); }
  { struct stat nf; if (stat("/data/opengoal/config/asyncswap.txt", &nf) == 0) setenv("PS5_ASYNC_SWAP", "1", 1); }  // driver patch 55
  { struct stat nf; if (stat("/data/opengoal/config/triplebuffer.txt", &nf) == 0) setenv("PS5_TRIPLE_BUFFER", "1", 1); }  // driver patch 55
  { struct stat nf; if (stat("/data/opengoal/config/presentlog.txt", &nf) == 0) setenv("PS5_PRESENT_LOG", "1", 1); }  // driver patch 55
  { struct stat nf; if (stat("/data/opengoal/config/drawcost.txt", &nf) == 0) setenv("PS5_DRAWCOST", "7", 1); }  // driver patch 56, bit mask 1+2+4
  { struct stat nf; if (stat("/data/opengoal/config/rtfastflush.txt", &nf) == 0) setenv("PS5_RT_FAST_FLUSH", "1", 1); }  // driver patch 57  // A/B: skip the CPU mip filter (drains the GPU), driver patch 44  // A/B: old 1 ms sleeps while waiting for the GPU
  { struct stat nf; if (stat("/data/opengoal/config/gputrace.txt", &nf) == 0) setenv("PS5_GPU_TRACE", "1", 1); }  // diagnostic: GPU completion trace
  { struct stat nf; if (stat("/data/opengoal/config/nocombine.txt", &nf) == 0) setenv("PS5_NO_COMBINE", "1", 1); }  // diagnostic: no command-group combining
  { struct stat nf; if (stat("/data/opengoal/config/adaptiveflip.txt", &nf) != 0) setenv("PS5_VSYNC_STRICT", "1", 1); }  // adaptive (tearing) flip only when adaptiveflip.txt exists: measured no gain yet
  ps5_install_crash_handler();
  ps5_inject_file_start();
  ps5_log_import_addrs();
  if (FILE* pf = std::fopen("/data/opengoal/config/prepcpu.txt", "r")) {  // optional: "<base cpu> <step>" for the async prep workers
    int base = 0, step = 0;
    if (std::fscanf(pf, "%d %d", &base, &step) == 2) {
      setenv("PS5_PREP_BASE", std::to_string(base).c_str(), 1);
      setenv("PS5_PREP_STEP", std::to_string(step).c_str(), 1);
      ps5_log("prep workers: cpu base=%d step=%d", base, step);
    }
    std::fclose(pf);
  }
  ps5_log("opengoal-ps5: start");
  ps5_capture_stdio();

  ps5_settings_load();
  static const int kW[] = {1920, 2560, 3840}, kH[] = {1080, 1440, 2160};
  const Ps5Settings& cfg = ps5_settings();
  g_boot_cfg = cfg;  // what this process started with: the launcher compares against it when Play is pressed
  {  // dynamic resolution + FSR (docs/FSR.md). Developer flag files win over ps5.cfg.
    static const char* const kScale[] = {nullptr, "83", "67", "50", "auto"};
    if (cfg.upscale > 0 && cfg.upscale <= 4) {
      setenv("PS5_RENDER_SCALE", kScale[cfg.upscale], 1);
      setenv("PS5_FSR_SHARP", std::to_string(cfg.sharpness).c_str(), 1);
      setenv("PS5_FSR_REFRESH", std::to_string(cfg.refresh).c_str(), 1);
    }
    int rs = 0;
    if (FILE* rf = std::fopen("/data/opengoal/config/renderscale.txt", "r")) {  // content: 33..100 or 0 (= auto)
      if (std::fscanf(rf, "%d", &rs) == 1 && rs >= 0) setenv("PS5_RENDER_SCALE", rs >= 100 ? "100" : (rs == 0 ? "auto" : std::to_string(rs).c_str()), 1);
      std::fclose(rf);
    }
    struct stat nf;
    if (stat("/data/opengoal/config/nofsr.txt", &nf) == 0) setenv("PS5_FSR", "0", 1);  // scaled render, plain bilinear blit
    if (FILE* sf = std::fopen("/data/opengoal/config/fsrsharp.txt", "r")) {            // content: 0..10
      int v = 0;
      if (std::fscanf(sf, "%d", &v) == 1 && v >= 0 && v <= 10) setenv("PS5_FSR_SHARP", std::to_string(v).c_str(), 1);
      std::fclose(sf);
    }
  }
  ps5sdl_set_display_mode(kW[cfg.resolution], kH[cfg.resolution], cfg.refresh);
  ps5_log("display: %dx%d @ %d Hz", kW[cfg.resolution], kH[cfg.resolution], cfg.refresh);

  // Display + GL context for the launcher (the engine reuses it afterwards).
  if (!SDL_Init(SDL_INIT_VIDEO)) {
    ps5_log("SDL_Init failed");
    return 1;
  }
  SDL_Window* window = SDL_CreateWindow("OpenGOAL", kW[cfg.resolution], kH[cfg.resolution], SDL_WINDOW_OPENGL);
  SDL_GLContext ctx = SDL_GL_CreateContext(window);
  if (!ctx || !SDL_GL_MakeCurrent(window, ctx) || !gladLoadGLLoader((GLADloadproc)SDL_GL_GetProcAddress)) {
    ps5_log("launcher: OpenGL init failed");
    return 2;
  }
  SDL_GL_SetSwapInterval(1);
  ps5_log("launcher: GL %s | %s", (const char*)glGetString(GL_VERSION), (const char*)glGetString(GL_RENDERER));

  bool first_round = true;
launcher_round:
  LaunchChoice choice;
  bool auto_launch = false;
  if (first_round) {  // developer hook: /data/opengoal/config/autolaunch.txt holds a game id; it is consumed (deleted) on use
    char id[16] = {0};
    if (FILE* f = std::fopen("/data/opengoal/config/autolaunch.txt", "r")) {
      if (std::fscanf(f, "%15s", id) == 1) {
        choice.game = id;
        choice.project_path = std::string("/data/opengoal/") + id + "/data";
        auto_launch = true;
      }
      std::fclose(f);
      std::remove("/data/opengoal/config/autolaunch.txt");
    }
  }
  if (first_round) {  // what the previous process asked for (see relaunch_self)
    char mode[16] = {0}, id[16] = {0};
    if (FILE* f = std::fopen("/data/opengoal/config/next.txt", "r")) {
      if (std::fscanf(f, "%15s %15s", mode, id) == 2) {
        if (std::strcmp(mode, "play") == 0) choice.auto_game = id;
        else if (std::strcmp(mode, "return") == 0) choice.enter_animation = true;
      }
      std::fclose(f);
      std::remove("/data/opengoal/config/next.txt");
    }
  }
  if (!auto_launch) choice.on_start = first_round ? start_or_relaunch : play_via_relaunch;
  if (!auto_launch && !ps5_run_launcher(window, &choice)) {
    ps5_log("launcher: quit");
    return 0;
  }

  int rc = 0;
  if (g_engine.started) {
    pthread_join(g_engine.thread, nullptr);  // started by the launcher after the start animation
    rc = g_engine.rc;
  } else {
    for (const char* sub : {"goal_src", "goal_src/user", "log", "iso_data", "decompiler_out", "custom_assets"}) {
      ensure_dir((choice.project_path + "/" + sub).c_str());
    }
    std::vector<std::string> args = {"gk",      "-v",   "--proj-path", choice.project_path, "--game",
                                     choice.game, "--",   "-boot",       "-fakeiso"};
    std::vector<char*> argv;
    for (auto& a : args) argv.push_back(a.data());
    argv.push_back(nullptr);
    rc = gk_main(static_cast<int>(args.size()), argv.data());
  }
  ps5_log("gk_main returned %d", rc);
  if (auto_launch) return rc;
  relaunch_self("return", choice.game);  // fresh process, launcher fades in; only returns if the console refused
  choice.enter_animation = true;
  // "Quit game" in the game's menu: back to the launcher (display, surface and GL context are still alive)
  first_round = false;
  SDL_GL_MakeCurrent(window, ctx);
  glDisable(GL_SCISSOR_TEST);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_BLEND);
  goto launcher_round;
}
