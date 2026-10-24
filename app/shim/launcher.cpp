// OpenGOAL for PS5 - controller-driven launcher.
//
// Replaces the desktop (Tauri) launcher: pick Jak 1 / Jak 2 / Jak 3, change display settings, and
// start the engine, all with the DualSense. Rendered with Dear ImGui draw lists on the PS5 OpenGL
// stack (the same EGL context the engine then reuses).

#include <SDL3/SDL.h>

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#include <sys/stat.h>

#include "third-party/glad/include/glad/glad.h"
#include "third-party/imgui/imgui.h"
#include "third-party/stb_image/stb_image.h"
#include "third-party/imgui/imgui_impl_opengl3.h"

void ps5_log(const char* fmt, ...);
int ps5_qr_encode(const char* text, std::vector<uint8_t>* modules);
extern "C" void ps5_web_start(int port, const char* ip);
extern "C" const char* ps5_web_ip();
extern "C" void ps5_web_progress(unsigned long long* bytes, unsigned long long* total, char* game16);
extern "C" int ps5_import_state();
extern "C" int ps5_import_rc();
extern "C" const char* ps5_import_stage();
extern "C" bool ps5sdl_handoff_requested();
extern "C" void ps5sdl_launcher_owns_context(bool on);
extern "C" void ps5sdl_release_context_for_engine();
extern "C" bool ps5sdl_get_pad(uint32_t* buttons, uint8_t* sticks /* lx ly rx ry l2 r2 */);
extern "C" void ps5sdl_set_display_mode(int width, int height, int hz);

#include "ps5import.h"
#include "ps5launcher.h"

namespace {

enum : uint32_t {
  PAD_L3 = 0x2, PAD_R3 = 0x4, PAD_OPTIONS = 0x8, PAD_UP = 0x10, PAD_RIGHT = 0x20, PAD_DOWN = 0x40,
  PAD_LEFT = 0x80, PAD_L1 = 0x400, PAD_R1 = 0x800, PAD_TRIANGLE = 0x1000, PAD_CIRCLE = 0x2000,
  PAD_CROSS = 0x4000, PAD_SQUARE = 0x8000,
};

struct GameEntry {
  const char* id;
  const char* title;
  const char* subtitle;
  const char* title_upper;
};

const GameEntry kGames[] = {
    {"jak1", "Jak and Daxter", "The Precursor Legacy", "JAK AND DAXTER"},
    {"jak2", "Jak II", "", "JAK II"},
    {"jak3", "Jak 3", "", "JAK 3"},
};
constexpr int kGameCount = 3;

struct Resolution {
  int w, h;
  const char* label;
};
const Resolution kResolutions[] = {{1920, 1080, "1080p"}, {2560, 1440, "1440p"}, {3840, 2160, "4K (2160p)"}};

struct Screen {
  enum Id { Main, Settings, Controls, Import } id = Main;
};

bool dir_exists(const std::string& p) {
  struct stat st;
  return stat(p.c_str(), &st) == 0 && S_ISDIR(st.st_mode);
}

std::string game_dir(const char* id) { return std::string("/data/opengoal/") + id + "/data"; }

bool game_ready(const char* id) {
  const std::string base = game_dir(id);
  return dir_exists(base + "/out/" + id + "/fr3") && dir_exists(base + "/out/" + id + "/iso") &&  // obj/ is dev-only, not part of the PC-side install
         dir_exists(base + "/game/assets");
}

// ---- persistent settings ---------------------------------------------------------------------
Ps5Settings g_settings;
const char* kConfigPath = "/data/opengoal/config/ps5.cfg";

}  // namespace

Ps5Settings& ps5_settings() { return g_settings; }

void ps5_settings_load() {
  FILE* f = std::fopen(kConfigPath, "r");
  if (!f) return;
  char line[256];
  while (std::fgets(line, sizeof line, f)) {
    int v = 0;
    if (std::sscanf(line, "resolution=%d", &v) == 1) g_settings.resolution = std::clamp(v, 0, 2);
    else if (std::sscanf(line, "refresh=%d", &v) == 1) g_settings.refresh = 60;  // locked: the PS5 output is vsynced at 60 Hz
    else if (std::sscanf(line, "last_game=%d", &v) == 1) g_settings.last_game = std::clamp(v, 0, kGameCount - 1);
    else if (std::sscanf(line, "lang=%d", &v) == 1) g_settings.lang = std::clamp(v, 0, 1);
    else if (std::sscanf(line, "merge=%d", &v) == 1) g_settings.merge = v ? 1 : 0;
    else if (std::sscanf(line, "async=%d", &v) == 1) g_settings.async_md = v ? 1 : 0;
    else if (std::sscanf(line, "lazymips=%d", &v) == 1) g_settings.lazy_mips = v ? 1 : 0;
    else if (std::sscanf(line, "upscale=%d", &v) == 1) g_settings.upscale = std::clamp(v, 0, 4);
    else if (std::sscanf(line, "sharpness=%d", &v) == 1) g_settings.sharpness = std::clamp(v, 0, 10);
  }
  std::fclose(f);
}

void ps5_settings_save() {
  FILE* f = std::fopen(kConfigPath, "w");
  if (!f) {
    ps5_log("launcher: cannot write %s", kConfigPath);
    return;
  }
  std::fprintf(f, "resolution=%d\nrefresh=%d\nlast_game=%d\nlang=%d\nmerge=%d\nasync=%d\nlazymips=%d\nupscale=%d\nsharpness=%d\n",
               g_settings.resolution, g_settings.refresh, g_settings.last_game, g_settings.lang, g_settings.merge,
               g_settings.async_md, g_settings.lazy_mips, g_settings.upscale, g_settings.sharpness);
  std::fclose(f);
  // flag files read by appmain at the next start: present = non-default behaviour
  auto flag = [](const char* name, bool on) {
    const std::string path = std::string("/data/opengoal/config/") + name;
    if (on) {
      if (FILE* g = std::fopen(path.c_str(), "w")) { std::fputs("1", g); std::fclose(g); }
    } else {
      std::remove(path.c_str());
    }
  };
  flag("nomerge.txt", !g_settings.merge);
  flag("noasyncmultidraw.txt", !g_settings.async_md);
  flag("mipfast3.txt", g_settings.lazy_mips);
}

// In-game options menu (goal_src, docs/INGAME_SETTINGS.md) reads and writes the FSR settings through these.
extern "C" int ps5_ingame_get(int id) {
  const Ps5Settings& s = ps5_settings();
  return id == 0 ? s.upscale : id == 1 ? s.sharpness : -1;
}
extern "C" void ps5_ingame_set(int id, int v) {
  Ps5Settings& s = ps5_settings();
  if (id == 0) s.upscale = std::clamp(v, 0, 4);
  else if (id == 1) s.sharpness = std::clamp(v, 0, 10);
  ps5_settings_save();
}

namespace {

struct Input {
  uint32_t buttons = 0, prev = 0;
  uint8_t sticks[6] = {128, 128, 128, 128, 0, 0};
  double hold_up = 0, hold_down = 0, hold_left = 0, hold_right = 0;
  bool pressed(uint32_t b) const { return (buttons & b) && !(prev & b); }
};

// Direction with key-repeat: fires on press, then after 0.4 s every 0.11 s.
bool repeat_fire(bool down, double& held, double dt) {
  if (!down) {
    held = 0;
    return false;
  }
  const bool first = held == 0;
  const double before = held;
  held += dt;
  if (first) return true;
  if (held < 0.4) return false;
  return std::floor((held - 0.4) / 0.11) != std::floor((before - 0.4) / 0.11) || before < 0.4;
}


struct Tex {
  unsigned id = 0;
  int w = 1, h = 1;
};
struct Textures {
  unsigned bg[3] = {0, 0, 0};
  Tex logo[3];
};

Tex upload_asset(const char* name) {
  Tex t;
  for (int i = 0; i < kPs5AssetCount; ++i) {
    if (std::strcmp(kPs5Assets[i].name, name) != 0) continue;
    int w = 0, h = 0, n = 0;
    unsigned char* px = stbi_load_from_memory(kPs5Assets[i].data, static_cast<int>(kPs5Assets[i].size), &w, &h, &n, 4);
    if (!px) {
      ps5_log("launcher: cannot decode %s", name);
      return t;
    }
    glGenTextures(1, &t.id);
    glBindTexture(GL_TEXTURE_2D, t.id);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    stbi_image_free(px);
    t.w = w;
    t.h = h;
    return t;
  }
  return t;
}

Textures load_textures() {
  Textures t;
  const char* bgs[3] = {"bg1.jpg", "bg2.jpg", "bg3.jpg"};
  const char* logos[3] = {"logo1.png", "logo2.png", "logo3.png"};
  for (int i = 0; i < 3; ++i) {
    t.bg[i] = upload_asset(bgs[i]).id;
    t.logo[i] = upload_asset(logos[i]);
  }
  return t;
}

void free_textures(Textures& t) {
  for (int i = 0; i < 3; ++i) {
    if (t.bg[i]) glDeleteTextures(1, &t.bg[i]);
    if (t.logo[i].id) glDeleteTextures(1, &t.logo[i].id);
  }
}

ImFont* g_font = nullptr;

void text(ImDrawList* dl, float size, ImVec2 pos, ImU32 col, const char* s) {
  dl->AddText(g_font, size, pos, col, s);
}

float text_width(float size, const char* s) { return g_font->CalcTextSizeA(size, 1e9f, 0, s).x; }

void centered(ImDrawList* dl, float size, float cx, float y, ImU32 col, const char* s) {
  text(dl, size, ImVec2(cx - text_width(size, s) * 0.5f, y), col, s);
}

enum Str {
  S_TITLE, S_LEAD, S_STEP1, S_STEP2, S_STEP3, S_ADDR, S_WAIT, S_RECV, S_EXTRACT, S_DECOMP, S_COMPILE, S_DONE, S_FAIL,
  S_KEEPON, S_HINT, S_ADD_ROW, S_LANG_ROW, S_MISSING, S_LOADING, S_PREPARE, S_BUSY, S_COUNT
};
const char* const kText[2][S_COUNT] = {
    {"Add your games",
     "Send your own copy of each game from your phone or PC. Nothing leaves your home network.",
     "1.  Connect your phone or PC to the same network as this PS5.",
     "2.  Scan the code or open the address below in a browser.",
     "3.  Pick a game, choose its .iso file and wait. This console does the rest.",
     "Address", "Waiting for a game...", "Receiving", "Unpacking the disc image...", "Analysing game data...",
     "Building the game...", "Done! Go back and press Play.",
     "Import failed. Is it an unmodified .iso of this game?",
     "Keep the console on. This takes a few minutes.", "Square: language     Circle: back",
     "Add games (import ISO)", "Language", "Game data missing - press Cross to add it", "Loading...", "Preparing tools...", "A game is being imported. Wait until it is done."},
    {"Spiele hinzufügen",
     "Schick deine eigene Kopie jedes Spiels vom Handy oder PC. Nichts verlässt dein Heimnetz.",
     "1.  Verbinde Handy oder PC mit demselben Netzwerk wie diese PS5.",
     "2.  Scanne den Code oder öffne die Adresse unten im Browser.",
     "3.  Wähle ein Spiel, dann die .iso-Datei, und warte. Den Rest erledigt die Konsole.",
     "Adresse", "Warte auf ein Spiel...", "Empfange", "Disc-Abbild wird entpackt...", "Spieldaten werden analysiert...",
     "Spiel wird gebaut...", "Fertig! Geh zurück und drücke Spielen.",
     "Import fehlgeschlagen. Ist es eine unveränderte .iso dieses Spiels?",
     "Lass die Konsole an. Das dauert einige Minuten.", "Quadrat: Sprache     Kreis: zurück",
     "Spiele hinzufügen (ISO importieren)", "Sprache", "Spieldaten fehlen - Kreuz drücken zum Hinzufügen", "Lade...", "Werkzeuge werden vorbereitet...", "Ein Spiel wird gerade importiert. Warte, bis es fertig ist."},
};
const char* tr(Str s) { return kText[g_settings.lang ? 1 : 0][s]; }
const char* L(const char* en, const char* de) { return g_settings.lang ? de : en; }

// Settings rows. Window mode, frame rate and V-Sync are not offered here: the games' own menus show them locked (engine/patch_ps5_ingame_settings.py).
enum SettingId { SET_RES, SET_MERGE, SET_ASYNC, SET_LAZYMIPS, SET_FSR, SET_SHARP, SET_LANG, SET_ADD, SET_COUNT };
struct SettingRow {
  const char* name;
  std::string value;
  bool enabled;
  const char* hint;
};
void build_rows(SettingRow* r) {
  auto onoff = [](int v) { return std::string(v ? L("On", "An") : L("Off", "Aus")); };
  r[SET_RES] = {L("Output resolution", "Ausgabeaufl\xc3\xb6sung"), kResolutions[g_settings.resolution].label, true,
                L("The game renders at this size. 4K needs far more GPU time. Applies at the next start.",
                  "Das Spiel rendert in dieser Gr\xc3\xb6\xc3\x9f\x65. 4K braucht viel mehr GPU-Zeit. Gilt ab dem n\xc3\xa4\x63hsten Start.")};
  r[SET_MERGE] = {L("Draw merging", "Draw-Zusammenfassung"), onoff(g_settings.merge), true,
                  L("Fewer GPU draw calls (about +10 fps in Jak 2). Turn off if you see broken geometry.",
                    "Weniger GPU-Aufrufe (ca. +10 fps in Jak 2). Bei kaputter Geometrie ausschalten.")};
  r[SET_ASYNC] = {L("Async GPU submit", "Asynchrones GPU-Senden"), onoff(g_settings.async_md), true,
                  L("Prepares draws on worker threads. Turn off to look for visual glitches.",
                    "Bereitet Draws in Arbeitsthreads vor. Zur Fehlersuche ausschalten.")};
  r[SET_LAZYMIPS] = {L("Lazy mipmaps (experimental)", "Faule Mipmaps (experimentell)"), onoff(g_settings.lazy_mips), true,
                     L("Skips unused mipmap work (about +2 fps in Jak 2). Distant surfaces may flicker.",
                       "\xc3\x9c\x62\x65rspringt unn\xc3\xb6tige Mipmap-Arbeit (ca. +2 fps in Jak 2). Ferne Fl\xc3\xa4\x63hen k\xc3\xb6nnen flackern.")};
  static const char* const kUpEn[] = {"Off", "Quality (83%)", "Balanced (67%)", "Performance (50%)", "Auto"};
  static const char* const kUpDe[] = {"Aus", "Qualit\xc3\xa4t (83%)", "Ausgewogen (67%)", "Leistung (50%)", "Auto"};
  r[SET_FSR] = {L("Upscaling (FSR)", "Hochskalierung (FSR)"), g_settings.lang ? kUpDe[g_settings.upscale] : kUpEn[g_settings.upscale], true,
                L("Renders below the output size and upscales with FSR 1.0. Auto lowers the size when the frame rate drops.",
                  "Rendert unter der Ausgabegr\xc3\xb6\xc3\x9f\x65 und skaliert mit FSR 1.0 hoch. Auto verkleinert bei niedriger Bildrate.")};
  r[SET_SHARP] = {L("Sharpness", "Sch\xc3\xa4rfe"), std::to_string(g_settings.sharpness), g_settings.upscale > 0,
                  L("FSR sharpening, 0 = off.", "FSR-Sch\xc3\xa4rfung, 0 = aus.")};
  r[SET_LANG] = {L("Language", "Sprache"), g_settings.lang ? "Deutsch" : "English", true, L("Launcher language.", "Sprache des Launchers.")};
  r[SET_ADD] = {tr(S_ADD_ROW), ">", true, L("Open the page to add or re-add a game.", "Seite zum Hinzuf\xc3\xbc\x67\x65n eines Spiels \xc3\xb6\x66\x66nen.")};
}

// ---- onboarding view helpers
std::string fmt_bytes(unsigned long long b) {
  char t[32];
  if (b >= (1ull << 30)) std::snprintf(t, sizeof t, "%.1f GB", double(b) / double(1ull << 30));
  else if (b >= (1ull << 20)) std::snprintf(t, sizeof t, "%.0f MB", double(b) / double(1ull << 20));
  else std::snprintf(t, sizeof t, "%.0f KB", double(b) / 1024.0);
  return t;
}
std::string fmt_eta(int s) {
  char t[32];
  if (s < 0) return "";
  if (s >= 120) std::snprintf(t, sizeof t, "%d min", (s + 30) / 60);
  else std::snprintf(t, sizeof t, "%d s", s);
  return t;
}
const char* stage_label(const Ps5GameStatus& st) {
  switch (st.phase) {
    case 1: return L("Uploading", "Hochladen");
    case 2: return L("Checking", "Pr\xc3\xbc\x66\x65n");
    case 3: return L("Queued", "In Warteschlange");
    case 4:
      switch (st.stage) {
        case 1: return L("Preparing", "Vorbereiten");
        case 2: return L("Unpacking", "Entpacken");
        case 3: return L("Decompiling", "Dekompilieren");
        case 4: return L("Building", "Bauen");
        default: return L("Installing", "Einrichten");
      }
    case 5: return L("Ready", "Bereit");
    case 6: return L("Failed", "Fehlgeschlagen");
    default: return st.installed ? L("Ready", "Bereit") : L("Waiting for ISO", "Warte auf ISO");
  }
}
const char* reason_text(const char* r) {
  struct R { const char* key; const char* en; const char* de; };
  static const R t[] = {
      {"notiso", "Not an .iso file", "Keine .iso-Datei"},
      {"tiny", "File too small to be a disc", "Datei zu klein f\xc3\xbcr eine Disc"},
      {"raw", "Raw .bin image: use an .iso", "Rohes .bin-Abbild: nutze eine .iso"},
      {"truncated", "Upload incomplete or file cut off", "Datei unvollst\xc3\xa4ndig"},
      {"nosys", "No game found on this disc", "Kein Spiel auf dieser Disc"},
      {"unknown", "Unknown disc", "Unbekannte Disc"},
      {"wrong_game", "This is a different game", "Das ist ein anderes Spiel"},
      {"toolchain", "Tools missing, reinstall the app", "Werkzeuge fehlen, App neu installieren"},
      {"unknown_disc", "Unknown or modified disc", "Unbekannte oder ver\xc3\xa4nderte Disc"},
      {"bad_contents", "Disc contents damaged", "Disc-Inhalt besch\xc3\xa4\x64igt"},
      {"bad_iso", "Damaged .iso", "Besch\xc3\xa4\x64igte .iso"},
      {"extract", "Unpacking failed", "Entpacken fehlgeschlagen"},
      {"decompile", "Decompiling failed", "Dekompilieren fehlgeschlagen"},
      {"compile", "Building failed", "Bauen fehlgeschlagen"},
  };
  for (const R& e : t) if (std::strcmp(e.key, r) == 0) return L(e.en, e.de);
  return L("Import failed", "Import fehlgeschlagen");
}

struct Overlay {
  bool active = false;
  unsigned tex = 0;        // the finished loading screen (background, dimming, logo, text)
  unsigned prog = 0, vao = 0;
  int u_alpha = -1, u_time = -1, u_res = -1, u_tex = -1;
  float S = 1.0f;
  double t0 = 0;           // seconds since the overlay started
  uint64_t last = 0;
  int real_frames = 0;     // consecutive frames with game-sized draw counts
  double fade = -1;        // >= 0: fade-out progress in seconds
} g_ov;

}  // namespace

extern "C" unsigned ps5_glfix_draw_total();

bool ps5_run_launcher(SDL_Window* window, LaunchChoice* out) {
  // --- ImGui on the PS5 GL stack
  IMGUI_CHECKVERSION();
  ImGui::CreateContext();
  ImGuiIO& io = ImGui::GetIO();
  io.IniFilename = nullptr;
  io.LogFilename = nullptr;
  io.ConfigFlags |= ImGuiConfigFlags_NoMouse;

  int W = 1920, H = 1080;
  SDL_GetWindowSizeInPixels(window, &W, &H);
  const float S = static_cast<float>(H) / 1080.0f;

  // font: Noto Sans JP from the game assets when present (all three games ship it), else ImGui's default
  g_font = nullptr;
  {
    const char* shipped = "/data/homebrew/LAPY77001/assets/NotoSansJP-Medium.ttf";
    struct stat fst;
    if (stat(shipped, &fst) == 0) g_font = io.Fonts->AddFontFromFileTTF(shipped, 0.0f);
  }
  for (const char* g : {"jak1", "jak2", "jak3"}) {
    if (g_font) break;
    const std::string path = game_dir(g) + "/game/assets/fonts/NotoSansJP-Medium.ttf";
    struct stat st;
    if (stat(path.c_str(), &st) == 0) {
      g_font = io.Fonts->AddFontFromFileTTF(path.c_str(), 0.0f);
      if (g_font) break;
    }
  }
  if (!g_font) g_font = io.Fonts->AddFontDefault();

  if (!ImGui_ImplOpenGL3_Init("#version 430")) {
    ps5_log("launcher: ImGui_ImplOpenGL3_Init failed");
    ImGui::DestroyContext();
    return false;
  }

  Input in;
  Screen scr;
  int sel = g_settings.last_game;
  int settings_sel = 0;
  int focus = 0;  // main screen: 0 = Play, 1 = Display, 2 = Controls
  Textures tex = load_textures();
  std::string toast;
  double toast_until = 0;
  bool done = false, start_game = false;
  const double freq = static_cast<double>(SDL_GetPerformanceFrequency());
  uint64_t last = SDL_GetPerformanceCounter();
  double now = 0;
  bool ready[kGameCount];
  for (int i = 0; i < kGameCount; ++i) ready[i] = game_ready(kGames[i].id);
  double rescan = 0;
  bool any_ready = false;
  ps5_web_start(8080, nullptr);
  std::string import_url = std::string("http://") + ps5_web_ip() + ":8080";
  std::vector<uint8_t> qr;
  const int qr_n = ps5_qr_encode(import_url.c_str(), &qr);
  double import_t0 = 0;
  bool launching = false, engine_started = false;
  double launch_t0 = 0, fade_t0 = 0;
  ps5sdl_launcher_owns_context(true);
  double enter_t0 = out->enter_animation ? 0.0001 : -1.0;
  if (!out->auto_game.empty()) {
    for (int i = 0; i < kGameCount; ++i) if (out->auto_game == kGames[i].id) sel = i;
    if (ready[sel] && out->on_start) {
      out->game = kGames[sel].id;
      out->project_path = game_dir(kGames[sel].id);
      start_game = true;
      launching = true;
      launch_t0 = 0.0001;
    }
  }
  for (int i = 0; i < kGameCount; ++i) any_ready = any_ready || ready[i];
  if (!any_ready) scr.id = Screen::Import;  // onboarding: forced until at least one game is installed

  while (!done) {
    const uint64_t t = SDL_GetPerformanceCounter();
    const double dt = std::min(0.1, static_cast<double>(t - last) / freq);
    last = t;
    now += dt;

    // ---- input
    in.prev = in.buttons;
    ps5sdl_get_pad(&in.buttons, in.sticks);
    const bool up = (in.buttons & PAD_UP) || in.sticks[1] < 60;
    const bool down = (in.buttons & PAD_DOWN) || in.sticks[1] > 196;
    const bool left = (in.buttons & PAD_LEFT) || in.sticks[0] < 60;
    const bool right = (in.buttons & PAD_RIGHT) || in.sticks[0] > 196;
    const bool f_up = repeat_fire(up, in.hold_up, dt), f_down = repeat_fire(down, in.hold_down, dt);
    const bool f_left = repeat_fire(left, in.hold_left, dt), f_right = repeat_fire(right, in.hold_right, dt);
    const bool confirm = in.pressed(PAD_CROSS), back = in.pressed(PAD_CIRCLE);

    rescan += dt;
    if (rescan > 2.0) {  // pick up game data copied while the launcher is open
      rescan = 0;
      any_ready = false;
      for (int i = 0; i < kGameCount; ++i) { ready[i] = game_ready(kGames[i].id); any_ready = any_ready || ready[i]; }
    }

    if (launching) {
      // input is ignored while the game starts
    } else if (!any_ready && scr.id != Screen::Import) {
      scr.id = Screen::Import;  // onboarding is mandatory
    } else if (scr.id == Screen::Main) {
      // Left/Right (or L1/R1) always pick the game. Up/Down move between Play and the two buttons below it;
      // on the lower row Left/Right switch between Settings and Controls.
      if (in.pressed(PAD_L1) || (focus == 0 && f_left)) sel = (sel + kGameCount - 1) % kGameCount;
      if (in.pressed(PAD_R1) || (focus == 0 && f_right)) sel = (sel + 1) % kGameCount;
      if (f_down && focus == 0) focus = 1;
      else if (f_up && focus != 0) focus = 0;
      else if (focus != 0 && f_left) focus = 1;
      else if (focus != 0 && f_right) focus = 2;
      if (in.pressed(PAD_TRIANGLE) || in.pressed(PAD_OPTIONS)) { scr.id = Screen::Settings; settings_sel = SET_RES; }
      if (in.pressed(PAD_SQUARE)) scr.id = Screen::Controls;
      if (confirm && focus == 1) { scr.id = Screen::Settings; settings_sel = SET_RES; }
      else if (confirm && focus == 2) scr.id = Screen::Controls;
      else if (confirm) {
        if (ready[sel] && ps5_import_state() == 1) {  // the extractor and the engine share process-wide state, so no Play while importing
          toast = tr(S_BUSY);
          toast_until = now + 4.0;
        } else if (ready[sel]) {
          g_settings.last_game = sel;
          ps5_settings_save();
          out->game = kGames[sel].id;
          out->project_path = game_dir(kGames[sel].id);
          start_game = true;
          if (out->on_start) {
            launching = true;  // animate, then boot the engine while the loading screen keeps running
            launch_t0 = now;
          } else {
            done = true;
          }
        } else {
          scr.id = Screen::Import;
        }
      }
    } else if (scr.id == Screen::Settings) {
      SettingRow rows[SET_COUNT];
      build_rows(rows);
      if (!rows[settings_sel].enabled) settings_sel = SET_RES;
      const int step = f_down ? 1 : (f_up ? SET_COUNT - 1 : 0);
      if (step) {
        do settings_sel = (settings_sel + step) % SET_COUNT;
        while (!rows[settings_sel].enabled);  // greyed rows are skipped
      }
      const int dir = f_left ? -1 : (f_right || confirm ? 1 : 0);
      if (dir != 0) {
        bool changed = true;
        switch (settings_sel) {
          case SET_RES: g_settings.resolution = (g_settings.resolution + 3 + dir) % 3; break;
          case SET_MERGE: g_settings.merge = 1 - g_settings.merge; break;
          case SET_ASYNC: g_settings.async_md = 1 - g_settings.async_md; break;
          case SET_LAZYMIPS: g_settings.lazy_mips = 1 - g_settings.lazy_mips; break;
          case SET_FSR: g_settings.upscale = (g_settings.upscale + 5 + dir) % 5; break;
          case SET_SHARP: g_settings.sharpness = std::clamp(g_settings.sharpness + dir, 0, 10); break;
          case SET_LANG: g_settings.lang = 1 - g_settings.lang; changed = false; break;
          case SET_ADD: scr.id = Screen::Import; changed = false; break;
          default: changed = false; break;
        }
        ps5_settings_save();
        if (changed) {
          toast = L("Applied: the game starts with these settings when you press Play", "Ãbernommen: das Spiel startet mit diesen Einstellungen, sobald du Spielen drÃ¼ckst");
          toast_until = now + 3.0;
        }
      }
      if (back) scr.id = Screen::Main;
    } else if (scr.id == Screen::Import) {
      if (in.pressed(PAD_SQUARE)) {
        g_settings.lang = 1 - g_settings.lang;
        ps5_settings_save();
      }
      if (back && any_ready) scr.id = Screen::Main;  // forced onboarding: no way out before one game is installed
    } else {
      if (back || confirm) scr.id = Screen::Main;
    }

    // ---- draw
    io.DisplaySize = ImVec2(static_cast<float>(W), static_cast<float>(H));
    io.DeltaTime = static_cast<float>(dt > 0 ? dt : 1.0 / 60.0);
    ImGui_ImplOpenGL3_NewFrame();
    ImGui::NewFrame();
    ImDrawList* dl = ImGui::GetBackgroundDrawList();
    const float w = static_cast<float>(W), h = static_cast<float>(H);

    const ImU32 kOrange = IM_COL32(249, 115, 22, 255);
    const ImU32 kAmber = IM_COL32(245, 158, 11, 255);
    const float sbw = 150 * S;  // sidebar width

    // full-bleed game artwork (greyed out while the game data is missing) + bottom-right shade
    if (tex.bg[sel]) {
      const ImU32 tint = ready[sel] ? IM_COL32(255, 255, 255, 255) : IM_COL32(110, 110, 110, 255);
      float zoom = 0.0f;
      if (launching) zoom = 0.07f * std::min(1.0f, float((now - launch_t0) / 0.9));
      else if (enter_t0 >= 0) zoom = 0.07f * (1.0f - std::min(1.0f, float((now - enter_t0) / 0.7)));
      dl->AddImage(static_cast<ImTextureID>(tex.bg[sel]), ImVec2(launching ? 0.0f : sbw, 0), ImVec2(w, h), ImVec2(zoom, zoom),
                   ImVec2(1 - zoom, 1 - zoom), tint);
    } else {
      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(14, 18, 36, 255));
    }
    dl->AddRectFilledMultiColor(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(0, 0, 0, 0), IM_COL32(0, 0, 0, 70),
                                IM_COL32(0, 0, 0, 235), IM_COL32(0, 0, 0, 90));
    dl->AddRectFilledMultiColor(ImVec2(sbw, h * 0.55f), ImVec2(w, h), IM_COL32(0, 0, 0, 0), IM_COL32(0, 0, 0, 0),
                                IM_COL32(0, 0, 0, 150), IM_COL32(0, 0, 0, 40));

    // sidebar: game logos, active one lit with an orange marker; cog at the bottom
    dl->AddRectFilled(ImVec2(0, 0), ImVec2(sbw, h), IM_COL32(11, 11, 11, 255));
    dl->AddLine(ImVec2(sbw, 0), ImVec2(sbw, h), IM_COL32(255, 255, 255, 14), 2 * S);
    for (int i = 0; i < kGameCount; ++i) {
      const float cy = (150 + i * 200) * S;
      const bool active = scr.id == Screen::Main && i == sel;
      const Tex& lg = tex.logo[i];
      if (lg.id) {
        const float lw = 112 * S, lh = lw * lg.h / lg.w;
        const ImU32 tint = active ? IM_COL32(255, 255, 255, 255) : IM_COL32(150, 150, 150, 115);
        dl->AddImage(static_cast<ImTextureID>(lg.id), ImVec2(sbw * 0.5f - lw * 0.5f, cy - lh * 0.5f),
                     ImVec2(sbw * 0.5f + lw * 0.5f, cy + lh * 0.5f), ImVec2(0, 0), ImVec2(1, 1), tint);
      }
      if (active) dl->AddRectFilled(ImVec2(0, cy - 38 * S), ImVec2(6 * S, cy + 38 * S), kOrange, 3 * S);
    }
    {  // cog
      const ImVec2 c(sbw * 0.5f, h - 100 * S);
      const bool active = scr.id == Screen::Settings;
      const ImU32 col = active ? IM_COL32(255, 255, 255, 255) : IM_COL32(150, 150, 150, 115);
      dl->AddCircle(c, 20 * S, col, 24, 8 * S);
      for (int k = 0; k < 8; ++k) {
        const float ang = k * 0.785398f;
        dl->AddLine(ImVec2(c.x + std::cos(ang) * 22 * S, c.y + std::sin(ang) * 22 * S),
                    ImVec2(c.x + std::cos(ang) * 33 * S, c.y + std::sin(ang) * 33 * S), col, 9 * S);
      }
      if (active) dl->AddRectFilled(ImVec2(0, c.y - 38 * S), ImVec2(6 * S, c.y + 38 * S), kOrange, 3 * S);
    }

    if (scr.id == Screen::Main) {
      // title block + buttons, bottom right (as in the desktop launcher)
      const float bw = 560 * S, bx = w - 70 * S - bw;
      const char* title = kGames[sel].title_upper;
      float y = h - 70 * S;
      const float rh = 70 * S, rg = 14 * S, rw = (bw - rg) * 0.5f;
      y -= rh;
      for (int k = 0; k < 2; ++k) {
        const bool f = focus == k + 1;
        const ImVec2 a(bx + k * (rw + rg), y), b(a.x + rw, y + rh);
        dl->AddRectFilled(a, b, f ? IM_COL32(20, 20, 20, 255) : IM_COL32(11, 11, 11, 255), 6 * S);
        dl->AddRect(a, b, f ? kOrange : IM_COL32(42, 42, 42, 255), 6 * S, 0, (f ? 4 : 2) * S);
        centered(dl, 32 * S, (a.x + b.x) * 0.5f, a.y + 17 * S,
                 f ? IM_COL32(255, 255, 255, 255) : IM_COL32(200, 200, 200, 255), k == 0 ? L("Settings", "Einstellungen") : L("Controls", "Steuerung"));
      }
      const float ph = 90 * S;
      y -= ph + 16 * S;
      {
        const bool f = focus == 0;
        const ImVec2 a(bx, y), b(bx + bw, y + ph);
        const bool rdy = ready[sel];
        dl->AddRectFilled(a, b, rdy ? (f ? IM_COL32(24, 55, 99, 255) : IM_COL32(19, 41, 75, 255)) : IM_COL32(40, 40, 40, 255), 6 * S);
        dl->AddRect(a, b, f ? kOrange : (rdy ? IM_COL32(30, 58, 102, 255) : IM_COL32(60, 60, 60, 255)), 6 * S, 0,
                    (f ? 4 : 2) * S);
        centered(dl, 54 * S, (a.x + b.x) * 0.5f, a.y + 14 * S,
                 rdy ? IM_COL32(235, 235, 235, 255) : IM_COL32(140, 140, 140, 255), rdy ? "Play" : L("Locked - add this game", "Gesperrt - Spiel hinzufÃ¼gen"));
      }
      y -= 20 * S;
      const char* sub = kGames[sel].subtitle;
      if (sub[0]) {
        y -= 46 * S;
        text(dl, 44 * S, ImVec2(w - 70 * S - text_width(44 * S, sub) + 2 * S, y + 2 * S), IM_COL32(0, 0, 0, 160), sub);
        text(dl, 44 * S, ImVec2(w - 70 * S - text_width(44 * S, sub), y), kAmber, sub);
      }
      y -= 62 * S;
      text(dl, 62 * S, ImVec2(w - 70 * S - text_width(62 * S, title) + 3 * S, y + 3 * S), IM_COL32(0, 0, 0, 170), title);
      text(dl, 62 * S, ImVec2(w - 70 * S - text_width(62 * S, title), y), IM_COL32(243, 244, 246, 255), title);
      // guide for a game that is not installed yet
      if (!ready[sel]) {
        char guide[200];
        std::snprintf(guide, sizeof guide, "%s %s", L("Locked. Open", "Gesperrt. \xc3\x96\x66\x66ne"), import_url.c_str());
        text(dl, 30 * S, ImVec2(sbw + 40 * S, h - 150 * S), IM_COL32(255, 200, 120, 255), guide);
        text(dl, 28 * S, ImVec2(sbw + 40 * S, h - 108 * S), IM_COL32(210, 214, 224, 220),
             L("on your phone or PC and drop your .iso of this game there.", "auf Handy oder PC und ziehe deine .iso dieses Spiels dorthin."));
      }
      text(dl, 26 * S, ImVec2(sbw + 40 * S, h - 62 * S), IM_COL32(210, 214, 224, 200),
           L("Left / Right or L1 / R1: game     Cross: select     Triangle: settings     Square: controls",
             "Links / Rechts oder L1 / R1: Spiel     Kreuz: ausw\xc3\xa4hlen     Dreieck: Einstellungen     Quadrat: Steuerung"));
    } else if (scr.id == Screen::Settings) {
      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 235));
      text(dl, 60 * S, ImVec2(sbw + 96 * S, 90 * S), IM_COL32(255, 255, 255, 255), L("Settings", "Einstellungen"));
      SettingRow rows[SET_COUNT];
      build_rows(rows);
      for (int i = 0; i < SET_COUNT; ++i) {
        const float y = (170 + i * 62 + (i >= SET_MERGE ? 26 : 0)) * S;  // gap between the fixed and the custom group
        const bool selected = (i == settings_sel), on = rows[i].enabled;
        const ImVec2 a(sbw + 96 * S, y), b(w - 96 * S, y + 54 * S);
        dl->AddRectFilled(a, b, selected ? IM_COL32(40, 52, 98, 255) : (on ? IM_COL32(24, 30, 56, 255) : IM_COL32(18, 18, 22, 255)), 16 * S);
        if (selected) dl->AddRect(a, b, kOrange, 16 * S, 0, 4 * S);
        const ImU32 nc = on ? IM_COL32(255, 255, 255, 255) : IM_COL32(110, 110, 120, 255);
        text(dl, 32 * S, ImVec2(a.x + 36 * S, y + 9 * S), nc, rows[i].name);
        char shown[128];
        if (on) std::snprintf(shown, sizeof shown, "<  %s  >", rows[i].value.c_str());
        else std::snprintf(shown, sizeof shown, "%s", rows[i].value.c_str());
        text(dl, 32 * S, ImVec2(b.x - 36 * S - text_width(32 * S, shown), y + 9 * S), on ? IM_COL32(255, 200, 120, 255) : IM_COL32(110, 110, 120, 255), shown);
      }
      {
        const float gy = (170 + SET_MERGE * 62 + 4) * S;
        text(dl, 22 * S, ImVec2(sbw + 96 * S, gy - 4 * S), IM_COL32(150, 160, 190, 255), L("CUSTOM", "ERWEITERT"));
      }
      text(dl, 28 * S, ImVec2(sbw + 96 * S, h - 120 * S), IM_COL32(200, 210, 240, 255), rows[settings_sel].hint);
      text(dl, 28 * S, ImVec2(sbw + 96 * S, h - 70 * S), IM_COL32(170, 180, 210, 255),
           L("Up / Down: choose     Left / Right or Cross: change     Circle: back", "Hoch / Runter: w\xc3\xa4hlen     Links / Rechts oder Kreuz: \xc3\xa4ndern     Kreis: zur\xc3\xbc\x63k"));
    } else if (scr.id == Screen::Import) {
      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 245));
      const float lx = sbw + 64 * S, rx = w - 64 * S;
      text(dl, 54 * S, ImVec2(lx, 50 * S), IM_COL32(255, 255, 255, 255), tr(S_TITLE));
      text(dl, 26 * S, ImVec2(lx, 118 * S), IM_COL32(170, 180, 210, 255),
           any_ready ? L("Add more games any time: drop the .iso files on the page below.",
                         "Weitere Spiele jederzeit hinzuf\xc3\xbc\x67\x65n: .iso-Dateien auf die Seite unten ziehen.")
                     : L("Add at least one game to start playing: drop your .iso on the page below.",
                         "F\xc3\xbc\x67\x65 mindestens ein Spiel hinzu: ziehe deine .iso auf die Seite unten."));
      // one live card per game
      const float gap = 22 * S, cw = (rx - lx - 2 * gap) / 3, cy = 172 * S, ch = 330 * S;
      for (int i = 0; i < kGameCount; ++i) {
        Ps5GameStatus st;
        std::memset(&st, 0, sizeof st);
        ps5_game_status(kGames[i].id, &st);
        {  // debug: fakestatus.txt shows one card per phase (upload 20 %, decompile 50 %, failed) without an import
          static int fake = -1;
          if (fake < 0) { struct stat fs; fake = stat("/data/opengoal/config/fakestatus.txt", &fs) == 0 ? 1 : 0; }
          if (fake) {
            std::memset(&st, 0, sizeof st);
            if (i == 0) { st.phase = 1; st.percent = 20; st.bytes = 900ull << 20; st.total = 4400ull << 20; st.speed_bps = 38u << 20; st.eta_s = 92; }
            else if (i == 1) { st.phase = 4; st.stage = 3; st.percent = 50; st.stage_percent = 62; st.elapsed_s = 140; }
            else { st.phase = 6; std::snprintf(st.reason, sizeof st.reason, "wrong_game"); }
          }
        }
        const bool installed = st.installed || ready[i];
        const bool busy = st.phase >= 1 && st.phase <= 4;
        const bool failed = st.phase == 6;
        const bool done = !busy && !failed && installed;
        const float cx = lx + i * (cw + gap);
        const ImVec2 a0(cx, cy), b0(cx + cw, cy + ch);
        dl->AddRectFilled(a0, b0, IM_COL32(18, 20, 30, 255), 14 * S);
        if (tex.bg[i]) dl->AddImageRounded(static_cast<ImTextureID>(tex.bg[i]), a0, ImVec2(b0.x, cy + 150 * S), ImVec2(0.2f, 0.2f), ImVec2(0.8f, 0.8f),
                                    done ? IM_COL32(255, 255, 255, 255) : IM_COL32(120, 120, 120, 255), 14 * S, ImDrawFlags_RoundCornersTop);
        const ImU32 edge = failed ? IM_COL32(248, 113, 113, 255) : done ? IM_COL32(74, 222, 128, 255) : busy ? kOrange : IM_COL32(50, 54, 70, 255);
        dl->AddRect(a0, b0, edge, 14 * S, 0, (busy ? 4 : 2) * S);
        const Tex& lg = tex.logo[i];
        if (lg.id) {
          const float lw = 150 * S, lh = lw * lg.h / lg.w;
          dl->AddImage(static_cast<ImTextureID>(lg.id), ImVec2(cx + 20 * S, cy + 20 * S), ImVec2(cx + 20 * S + lw, cy + 20 * S + lh));
        }
        // status line
        int pct = st.percent;
        if (pct < 0 && st.phase == 1 && st.total > 0) pct = int(100.0 * double(st.bytes) / double(st.total));
        char big[96];
        const char* label = stage_label(st);
        if (busy && pct >= 0) std::snprintf(big, sizeof big, "%s  %d%%", label, std::min(pct, 100));
        else std::snprintf(big, sizeof big, "%s", label);
        const ImU32 bigcol = failed ? IM_COL32(248, 113, 113, 255) : done ? IM_COL32(74, 222, 128, 255) : busy ? IM_COL32(255, 200, 120, 255) : IM_COL32(150, 156, 180, 255);
        text(dl, 34 * S, ImVec2(cx + 20 * S, cy + 168 * S), bigcol, big);
        // progress bar
        const float by = cy + 222 * S, bh = 14 * S, bx0 = cx + 20 * S, bx1 = cx + cw - 20 * S;
        dl->AddRectFilled(ImVec2(bx0, by), ImVec2(bx1, by + bh), IM_COL32(40, 44, 60, 255), bh * 0.5f);
        if (busy || done) {
          if (pct >= 0 || done) {
            const float fr = done ? 1.0f : std::min(1.0f, pct / 100.0f);
            dl->AddRectFilled(ImVec2(bx0, by), ImVec2(bx0 + (bx1 - bx0) * fr, by + bh), done ? IM_COL32(74, 222, 128, 255) : kOrange, bh * 0.5f);
          } else {  // unknown percent: moving segment
            const float seg = (bx1 - bx0) * 0.25f, t = std::fmod(float(now) * 0.9f, 1.0f) * ((bx1 - bx0) - seg);
            dl->AddRectFilled(ImVec2(bx0 + t, by), ImVec2(bx0 + t + seg, by + bh), kOrange, bh * 0.5f);
          }
        }
        // detail line
        char det[160] = "";
        if (failed) {
          std::snprintf(det, sizeof det, "%s", reason_text(st.reason));
        } else if (st.phase == 1 && st.total > 0) {
          std::snprintf(det, sizeof det, "%s / %s", fmt_bytes(st.bytes).c_str(), fmt_bytes(st.total).c_str());
        } else if (busy && st.stage_percent >= 0) {
          std::snprintf(det, sizeof det, "%s %d%%", label, st.stage_percent);
        } else if (!installed && !busy) {
          std::snprintf(det, sizeof det, "%s", L("Drop the .iso on the web page", ".iso auf die Webseite ziehen"));
        } else if (done) {
          std::snprintf(det, sizeof det, "%s", st.serial[0] ? st.serial : L("Installed", "Installiert"));
        }
        text(dl, 22 * S, ImVec2(cx + 20 * S, cy + 250 * S), IM_COL32(190, 198, 220, 255), det);
        if (busy) {
          char sp[96] = "";
          if (st.speed_bps > 0 && st.eta_s >= 0) std::snprintf(sp, sizeof sp, "%s/s  -  %s %s", fmt_bytes(st.speed_bps).c_str(), fmt_eta(st.eta_s).c_str(), L("left", "\xc3\xbc\x62rig"));
          else if (st.speed_bps > 0) std::snprintf(sp, sizeof sp, "%s/s", fmt_bytes(st.speed_bps).c_str());
          else if (st.elapsed_s > 0) std::snprintf(sp, sizeof sp, "%d s", st.elapsed_s);
          text(dl, 22 * S, ImVec2(cx + 20 * S, cy + 282 * S), IM_COL32(140, 148, 172, 255), sp);
        }
      }
      // how to + QR
      const float hy = cy + ch + 40 * S;
      const Str steps[3] = {S_STEP1, S_STEP2, S_STEP3};
      for (int i = 0; i < 3; ++i) text(dl, 28 * S, ImVec2(lx, hy + i * 54 * S), IM_COL32(220, 226, 246, 255), tr(steps[i]));
      text(dl, 30 * S, ImVec2(lx, hy + 3 * 54 * S + 8 * S), IM_COL32(255, 200, 120, 255), import_url.c_str());
      if (qr_n > 0) {
        const float mod = 8 * S, qz = 3 * mod, side = qr_n * mod + 2 * qz;
        const float qx = rx - side, qy = hy - 6 * S;
        dl->AddRectFilled(ImVec2(qx, qy), ImVec2(qx + side, qy + side), IM_COL32(255, 255, 255, 255), 8 * S);
        for (int y = 0; y < qr_n; ++y)
          for (int x = 0; x < qr_n; ++x)
            if (qr[size_t(y) * qr_n + x])
              dl->AddRectFilled(ImVec2(qx + qz + x * mod, qy + qz + y * mod), ImVec2(qx + qz + (x + 1) * mod, qy + qz + (y + 1) * mod), IM_COL32(0, 0, 0, 255));
      }
      const char* qt = ps5_import_queue_text();
      if (qt && qt[0]) text(dl, 28 * S, ImVec2(lx, h - 116 * S), kAmber, qt);
      if (ps5_import_state() == 1) text(dl, 24 * S, ImVec2(lx, h - 160 * S), IM_COL32(170, 180, 210, 255), tr(S_KEEPON));
      text(dl, 28 * S, ImVec2(lx, h - 66 * S), IM_COL32(170, 180, 210, 255),
           any_ready ? tr(S_HINT) : L("Square: language     Add at least one game to continue", "Quadrat: Sprache     F\xc3\xbc\x67\x65 mindestens ein Spiel hinzu, um fortzufahren"));
    } else {
      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 235));
      text(dl, 60 * S, ImVec2(sbw + 96 * S, 200 * S), IM_COL32(255, 255, 255, 255), "Controls");
      const char* lines[] = {"Left stick .......... Move",
                             "Right stick ......... Camera",
                             "Cross ............... Jump",
                             "Square .............. Punch / spin",
                             "Triangle ............ Pick up / throw",
                             "Circle .............. Dive / roll",
                             "L1 / R1 ............. Strafe / Camera snap",
                             "Options ............. Pause menu",
                             "PS button ........... Back to the PS5 home screen"};
      for (int i = 0; i < 9; ++i) text(dl, 38 * S, ImVec2(sbw + 140 * S, (320 + i * 62) * S), IM_COL32(220, 228, 250, 255), lines[i]);
      text(dl, 30 * S, ImVec2(sbw + 96 * S, h - 70 * S), IM_COL32(170, 180, 210, 255), "Circle: back");
    }

    if (now < toast_until && !toast.empty()) {
      const float tw = text_width(34 * S, toast.c_str()) + 80 * S;
      const float tx = (w - tw) * 0.5f, ty = h - 190 * S;
      dl->AddRectFilled(ImVec2(tx, ty), ImVec2(tx + tw, ty + 84 * S), IM_COL32(20, 20, 30, 235), 20 * S);
      dl->AddRect(ImVec2(tx, ty), ImVec2(tx + tw, ty + 84 * S), IM_COL32(255, 154, 40, 255), 20 * S, 0, 3 * S);
      text(dl, 34 * S, ImVec2(tx + 40 * S, ty + 22 * S), IM_COL32(255, 255, 255, 255), toast.c_str());
    }

    if (enter_t0 >= 0 && !launching) {  // fade in from black after returning from a game
      const float e = std::min(1.0f, float((now - enter_t0) / 0.7));
      dl->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), IM_COL32(0, 0, 0, int(255 * (1.0f - e * e * (3 - 2 * e)))));
      if (e >= 1.0f) enter_t0 = -1.0;
    }
    if (launching) {
      const float a = std::min(1.0f, float((now - launch_t0) / 0.7));       // UI fades out, logo fades in
      const float ease = a * a * (3 - 2 * a);
      dl->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), IM_COL32(0, 0, 0, int(215 * ease)));
      const Tex& lg = tex.logo[sel];
      if (lg.id) {
        const float lw = (380 + 80 * ease) * S, lh = lw * lg.h / lg.w;
        dl->AddImage(static_cast<ImTextureID>(lg.id), ImVec2(w * 0.5f - lw * 0.5f, h * 0.42f - lh * 0.5f),
                     ImVec2(w * 0.5f + lw * 0.5f, h * 0.42f + lh * 0.5f), ImVec2(0, 0), ImVec2(1, 1),
                     IM_COL32(255, 255, 255, int(255 * ease)));
      }
      // spinner: 12 dots, a bright head chasing around the circle
      const ImVec2 c(w * 0.5f, h * 0.70f);
      for (int k = 0; k < 12; ++k) {
        const float ang = k * 0.5235988f;
        const float phase = std::fmod(float(now) * 2.2f - k / 12.0f + 1.0f, 1.0f);
        const int al = int(255 * ease * (0.15f + 0.85f * (1.0f - phase)));
        dl->AddCircleFilled(ImVec2(c.x + std::cos(ang) * 34 * S, c.y + std::sin(ang) * 34 * S), 6 * S, IM_COL32(255, 183, 3, al));
      }
      centered(dl, 34 * S, w * 0.5f, h * 0.70f + 64 * S, IM_COL32(220, 225, 240, int(255 * ease)), tr(S_LOADING));
      if (a >= 1.0f && !engine_started) {
        engine_started = true;
        out->on_start(*out);  // boots the engine on its own thread
      }
      if (engine_started && ps5sdl_handoff_requested()) done = true;  // the engine thread keeps drawing this screen
    }

    ImGui::Render();
    glViewport(0, 0, W, H);
    glClearColor(0.05f, 0.06f, 0.12f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
    {  // debug: with launcher_shot.txt present, save a PPM of every new launcher view once it has been stable for 0.6 s
      static int last_view = -1, shot_n = 0;
      static double view_since = 0;
      const int view = int(scr.id) * 100 + settings_sel * 10 + focus + sel * 1000 + (scr.id == Screen::Import ? int(now / 6) * 100000 : 0);  // import view: one shot per 6 s
      if (view != last_view) { last_view = view; view_since = now; }
      struct stat fst;
      if (now - view_since > 0.6 && now - view_since < 0.7 && shot_n < 90 && stat("/data/opengoal/config/launcher_shot.txt", &fst) == 0) {
        std::vector<unsigned char> px(size_t(W) * H * 3), flip(size_t(W) * H * 3);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glReadPixels(0, 0, W, H, GL_RGB, GL_UNSIGNED_BYTE, px.data());
        for (int y = 0; y < H; ++y) std::memcpy(&flip[size_t(y) * W * 3], &px[size_t(H - 1 - y) * W * 3], size_t(W) * 3);
        char path[96];
        std::snprintf(path, sizeof path, "/data/opengoal/log/ls_%02d.ppm", shot_n++);
        if (FILE* f = std::fopen(path, "wb")) { std::fprintf(f, "P6\n%d %d\n255\n", W, H); std::fwrite(flip.data(), 1, flip.size(), f); std::fclose(f); }
      }
    }
    SDL_GL_SwapWindow(window);
  }

  if (engine_started) {
    // Bake the loading screen into one texture and build a tiny shader; the engine thread then only draws a
    // fullscreen quad plus an animated spinner over its first frames (ps5_loading_overlay, from SDL_GL_SwapWindow).
    unsigned fbo = 0, color = 0;
    glGenTextures(1, &color);
    glBindTexture(GL_TEXTURE_2D, color);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, color, 0);
    if (glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE) {
      io.DisplaySize = ImVec2(static_cast<float>(W), static_cast<float>(H));
      io.DeltaTime = 1.0f / 60.0f;
      ImGui_ImplOpenGL3_NewFrame();
      ImGui::NewFrame();
      ImDrawList* dl = ImGui::GetBackgroundDrawList();
      const float w = static_cast<float>(W), h = static_cast<float>(H);
      if (tex.bg[sel]) dl->AddImage(static_cast<ImTextureID>(tex.bg[sel]), ImVec2(0, 0), ImVec2(w, h), ImVec2(0.07f, 0.07f), ImVec2(0.93f, 0.93f), IM_COL32(255, 255, 255, 255));
      dl->AddRectFilled(ImVec2(0, 0), ImVec2(w, h), IM_COL32(0, 0, 0, 215));
      const Tex& lg = tex.logo[sel];
      if (lg.id) {
        const float lw = 460 * S, lh = lw * lg.h / lg.w;
        dl->AddImage(static_cast<ImTextureID>(lg.id), ImVec2(w * 0.5f - lw * 0.5f, h * 0.42f - lh * 0.5f), ImVec2(w * 0.5f + lw * 0.5f, h * 0.42f + lh * 0.5f), ImVec2(0, 0), ImVec2(1, 1), IM_COL32(255, 255, 255, 255));
      }
      centered(dl, 34 * S, w * 0.5f, h * 0.70f + 64 * S, IM_COL32(220, 225, 240, 255), tr(S_LOADING));
      ImGui::Render();
      glViewport(0, 0, W, H);
      glClearColor(0, 0, 0, 1);
      glClear(GL_COLOR_BUFFER_BIT);
      ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());
    }
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glDeleteFramebuffers(1, &fbo);

    static const char* kVert = "#version 430 core\nout vec2 uv;\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);uv=p;gl_Position=vec4(p*2.0-1.0,0.0,1.0);}\n";
    static const char* kFrag =
        "#version 430 core\nin vec2 uv;out vec4 o;uniform sampler2D tex;uniform float alpha;uniform float time;uniform vec2 res;\n"
        "void main(){vec4 c=texture(tex,uv);float a=1.0;\n"
        " vec2 p=uv*res;vec2 ctr=vec2(res.x*0.5,res.y*0.30);float S=res.y/1080.0;\n"
        " vec3 col=c.rgb;\n"
        " for(int k=0;k<12;++k){float ang=float(k)*0.5235988;vec2 d=ctr+vec2(cos(ang),-sin(ang))*34.0*S;\n"
        "  float ph=fract(time*2.2-float(k)/12.0+100.0);float br=0.15+0.85*(1.0-ph);\n"
        "  float m=smoothstep(6.0*S+1.0,6.0*S-1.0,length(p-d));col=mix(col,vec3(1.0,0.718,0.012),m*br);}\n"
        " o=vec4(col,alpha);}\n";
    auto compile = [](unsigned type, const char* src) {
      unsigned s = glCreateShader(type);
      glShaderSource(s, 1, &src, nullptr);
      glCompileShader(s);
      return s;
    };
    g_ov.prog = glCreateProgram();
    const unsigned vs = compile(GL_VERTEX_SHADER, kVert), fs = compile(GL_FRAGMENT_SHADER, kFrag);
    glAttachShader(g_ov.prog, vs);
    glAttachShader(g_ov.prog, fs);
    glLinkProgram(g_ov.prog);
    glDeleteShader(vs);
    glDeleteShader(fs);
    g_ov.u_alpha = glGetUniformLocation(g_ov.prog, "alpha");
    g_ov.u_time = glGetUniformLocation(g_ov.prog, "time");
    g_ov.u_res = glGetUniformLocation(g_ov.prog, "res");
    g_ov.u_tex = glGetUniformLocation(g_ov.prog, "tex");
    glGenVertexArrays(1, &g_ov.vao);
    g_ov.tex = color;
    g_ov.S = S;
    g_ov.t0 = 0;
    g_ov.active = true;
  }
  free_textures(tex);
  ImGui_ImplOpenGL3_Shutdown();
  ImGui::DestroyContext();
  glFinish();  // the baked loading screen must be complete before the engine thread uses it
  ps5_log("launcher: handing the GL context to the engine (overlay %s)", g_ov.active ? "on" : "off");
  if (engine_started) ps5sdl_release_context_for_engine();  // hand the context to the engine thread
  ps5sdl_launcher_owns_context(false);
  return start_game;
}

// Called by the SDL shim right before every swap on the engine's render thread. Draws the baked loading screen over
// the first (black) frames, then fades it out once the game renders real content (many draws per frame).
extern "C" __attribute__((force_align_arg_pointer)) void ps5_loading_overlay(int W, int H) {
  if (!g_ov.active) return;
  const uint64_t tnow = SDL_GetPerformanceCounter();
  const double freq = static_cast<double>(SDL_GetPerformanceFrequency());
  const double dt = g_ov.last ? std::min(0.1, static_cast<double>(tnow - g_ov.last) / freq) : 1.0 / 60.0;
  g_ov.last = tnow;
  g_ov.t0 += dt;
  static int logged = 0;
  if (logged < 40 || logged % 120 == 0)
    ps5_log("overlay: t=%.2f draws=%u real=%d fade=%.2f", g_ov.t0, ps5_glfix_draw_total(), g_ov.real_frames, g_ov.fade);
  ++logged;
  if (ps5_glfix_draw_total() > 8) {  // the boot frames draw ~2 things; the first game frame draws more
    if (++g_ov.real_frames >= 2 && g_ov.fade < 0) { g_ov.fade = 0; ps5_log("overlay: fade out at t=%.2f draws=%u", g_ov.t0, ps5_glfix_draw_total()); }
  } else {
    g_ov.real_frames = 0;
  }
  if (g_ov.t0 > 150.0 && g_ov.fade < 0) g_ov.fade = 0;  // never keep it forever
  float alpha = 1.0f;
  if (g_ov.fade >= 0) {
    g_ov.fade += dt;
    alpha = 1.0f - std::min(1.0f, float(g_ov.fade / 0.6));
  }
  // save the few pieces of state this touches
  GLint prog = 0, vao = 0, fb = 0, tex0 = 0, active = 0, vp[4] = {0, 0, 0, 0};
  glGetIntegerv(GL_CURRENT_PROGRAM, &prog);
  glGetIntegerv(GL_VERTEX_ARRAY_BINDING, &vao);
  glGetIntegerv(GL_FRAMEBUFFER_BINDING, &fb);
  glGetIntegerv(GL_ACTIVE_TEXTURE, &active);
  glGetIntegerv(GL_VIEWPORT, vp);
  glActiveTexture(GL_TEXTURE0);
  glGetIntegerv(GL_TEXTURE_BINDING_2D, &tex0);
  const GLboolean blend = glIsEnabled(GL_BLEND), depth = glIsEnabled(GL_DEPTH_TEST), cull = glIsEnabled(GL_CULL_FACE),
                  scissor = glIsEnabled(GL_SCISSOR_TEST), stencil = glIsEnabled(GL_STENCIL_TEST);
  GLboolean cmask[4];
  glGetBooleanv(GL_COLOR_WRITEMASK, cmask);

  glBindFramebuffer(GL_FRAMEBUFFER, 0);
  glViewport(0, 0, W, H);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_CULL_FACE);
  glDisable(GL_SCISSOR_TEST);
  glDisable(GL_STENCIL_TEST);
  glEnable(GL_BLEND);
  glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
  glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
  glUseProgram(g_ov.prog);
  glBindVertexArray(g_ov.vao);
  glBindTexture(GL_TEXTURE_2D, g_ov.tex);
  glUniform1i(g_ov.u_tex, 0);
  glUniform1f(g_ov.u_alpha, alpha);
  glUniform1f(g_ov.u_time, static_cast<float>(g_ov.t0));
  glUniform2f(g_ov.u_res, static_cast<float>(W), static_cast<float>(H));
  glDrawArrays(GL_TRIANGLES, 0, 3);

  glBindTexture(GL_TEXTURE_2D, static_cast<unsigned>(tex0));
  glActiveTexture(static_cast<unsigned>(active));
  glBindVertexArray(static_cast<unsigned>(vao));
  glUseProgram(static_cast<unsigned>(prog));
  glBindFramebuffer(GL_FRAMEBUFFER, static_cast<unsigned>(fb));
  glViewport(vp[0], vp[1], vp[2], vp[3]);
  glColorMask(cmask[0], cmask[1], cmask[2], cmask[3]);
  if (!blend) glDisable(GL_BLEND);
  if (depth) glEnable(GL_DEPTH_TEST);
  if (cull) glEnable(GL_CULL_FACE);
  if (scissor) glEnable(GL_SCISSOR_TEST);
  if (stencil) glEnable(GL_STENCIL_TEST);
  if (g_ov.fade >= 0 && alpha <= 0.0f) {
    g_ov.active = false;
    glDeleteTextures(1, &g_ov.tex);
    glDeleteProgram(g_ov.prog);
    glDeleteVertexArrays(1, &g_ov.vao);
  }
}
