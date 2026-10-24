#include <atomic>
#include <unistd.h>
#include <sys/resource.h>
#include <time.h>
// SDL3 compatibility shim for the PS5 port of OpenGOAL.
//
// Implements the subset of the SDL3 API that jak-project calls: one fullscreen window backed by
// EGL (PS5 OpenGL 4.6), the DualSense through scePad as the only gamepad, and no-op keyboard /
// mouse / clipboard. Types come from the real SDL3 headers so the game sources stay unmodified.

#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <SDL3/SDL.h>

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <deque>
#include <vector>
#include <sys/stat.h>
#include <sys/param.h>
#include <sys/cpuset.h>
#include <pthread_np.h>
#include <string>

#if __has_include(<ps5_opengl_display_modes.h>)
#include <ps5_opengl_display_modes.h>
#define PS5SDL_HAVE_MODES 1
#endif

extern "C" {
int sceUserServiceInitialize(void*);
int sceUserServiceGetInitialUser(int*);
int scePadInit(void);
int scePadOpen(int user, int type, int index, const void* param);
int scePadReadState(int handle, void* state);
struct ScePadVibrationParam {
  uint8_t largeMotor;
  uint8_t smallMotor;
};
struct ScePadLightBarParam {
  uint8_t r, g, b, a;
};
int scePadSetVibration(int handle, const ScePadVibrationParam* param);
int scePadSetLightBar(int handle, const ScePadLightBarParam* param);
}

void ps5_log(const char* fmt, ...);  // defined in the platform layer (UDP + console log)
extern "C" const void* ps5_gl_lookup(const char* name);  // generated gl_table.c
extern "C" void* ps5_glfix_lookup(const char* name);     // glfix.cpp

static uint64_t now_ns() {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return uint64_t(ts.tv_sec) * 1000000000ull + uint64_t(ts.tv_nsec);
}

namespace {

constexpr SDL_JoystickID kPadId = 1;

struct PadState {
  uint32_t buttons = 0;
  uint8_t lx = 128, ly = 128, rx = 128, ry = 128;
  uint8_t l2 = 0, r2 = 0;
};

// scePad button bits (DualSense / DS4 layout).
enum : uint32_t {
  PAD_L3 = 0x2,
  PAD_R3 = 0x4,
  PAD_OPTIONS = 0x8,
  PAD_UP = 0x10,
  PAD_RIGHT = 0x20,
  PAD_DOWN = 0x40,
  PAD_LEFT = 0x80,
  PAD_L2 = 0x100,
  PAD_R2 = 0x200,
  PAD_L1 = 0x400,
  PAD_R1 = 0x800,
  PAD_TRIANGLE = 0x1000,
  PAD_CIRCLE = 0x2000,
  PAD_CROSS = 0x4000,
  PAD_SQUARE = 0x8000,
  PAD_TOUCHPAD = 0x100000,
};

struct ButtonMap {
  uint32_t pad_bit;
  SDL_GamepadButton sdl;
};
const ButtonMap kButtons[] = {
    {PAD_CROSS, SDL_GAMEPAD_BUTTON_SOUTH},
    {PAD_CIRCLE, SDL_GAMEPAD_BUTTON_EAST},
    {PAD_SQUARE, SDL_GAMEPAD_BUTTON_WEST},
    {PAD_TRIANGLE, SDL_GAMEPAD_BUTTON_NORTH},
    {PAD_TOUCHPAD, SDL_GAMEPAD_BUTTON_BACK},
    {PAD_OPTIONS, SDL_GAMEPAD_BUTTON_START},
    {PAD_L3, SDL_GAMEPAD_BUTTON_LEFT_STICK},
    {PAD_R3, SDL_GAMEPAD_BUTTON_RIGHT_STICK},
    {PAD_L1, SDL_GAMEPAD_BUTTON_LEFT_SHOULDER},
    {PAD_R1, SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER},
    {PAD_UP, SDL_GAMEPAD_BUTTON_DPAD_UP},
    {PAD_DOWN, SDL_GAMEPAD_BUTTON_DPAD_DOWN},
    {PAD_LEFT, SDL_GAMEPAD_BUTTON_DPAD_LEFT},
    {PAD_RIGHT, SDL_GAMEPAD_BUTTON_DPAD_RIGHT},
};

struct Shim {
  int pad_handle = -1;
  bool pad_inited = false;
  bool added_sent = false;
  PadState cur{}, prev{};
  std::deque<SDL_Event> events;
  uint64_t tick_base = 0;
  uint64_t rumble_until_ns = 0;

  // window / EGL
  EGLDisplay dpy = EGL_NO_DISPLAY;
  EGLSurface surf = EGL_NO_SURFACE;
  EGLContext ctx = EGL_NO_CONTEXT;
  int win_w = 1920, win_h = 1080;
  std::string error;
} g;

struct FakeWindow {
  int w = 1920, h = 1080;
};
FakeWindow g_window;
int g_gamepad_token = 0;
int g_mode_w = 1920, g_mode_h = 1080, g_mode_hz = 60;  // display mode requested before EGL starts

int16_t stick_axis(uint8_t v) {
  const int x = static_cast<int>(v) - 128;
  const int s = x * 256;  // -32768 .. 32512
  return static_cast<int16_t>(s > 32767 ? 32767 : s);
}
int16_t trigger_axis(uint8_t v) {
  return static_cast<int16_t>((static_cast<int>(v) * 32767) / 255);
}

void ensure_pad() {
  if (g.pad_inited) return;
  g.pad_inited = true;
  sceUserServiceInitialize(nullptr);
  int user = 0;
  sceUserServiceGetInitialUser(&user);
  scePadInit();
  g.pad_handle = scePadOpen(user, 0, 0, nullptr);
  ps5_log("sdl-shim: scePadOpen user=0x%x handle=0x%x", user, g.pad_handle);
}

static std::atomic<uint32_t> g_inj_buttons{0};
static uint64_t g_inj_until_ns = 0;
extern "C" void ps5_pad_inject(unsigned buttons, unsigned ms) {
  g_inj_buttons = buttons;
  ps5_log("inject: buttons=0x%x for %u ms", buttons, ms);
  g_inj_until_ns = now_ns() + uint64_t(ms) * 1000000ull;
}

static uint64_t g_stick_until_ns = 0;
static uint8_t g_stick_lx = 128, g_stick_ly = 128;
extern "C" void ps5_stick_inject(unsigned lx, unsigned ly, unsigned ms) {
  g_stick_lx = uint8_t(lx);
  g_stick_ly = uint8_t(ly);
  g_stick_until_ns = now_ns() + uint64_t(ms) * 1000000ull;
}

void read_pad() {
  ensure_pad();
  if (g.pad_handle < 0) return;
  alignas(8) unsigned char raw[512] = {};
  const int rc = scePadReadState(g.pad_handle, raw);
  {
    static uint64_t last_diag = 0;
    if (now_ns() - last_diag > 3000000000ull) {
      last_diag = now_ns();
      ps5_log("pad: rc=0x%x raw=%02x%02x%02x%02x %02x%02x%02x%02x %02x%02x %02x%02x%02x%02x connected=%d", rc, raw[0], raw[1], raw[2], raw[3], raw[4], raw[5],
              raw[6], raw[7], raw[8], raw[9], raw[10], raw[11], raw[12], raw[13], raw[0x4c]);
    }
  }
  if (rc != 0) return;
  g.prev = g.cur;
  std::memcpy(&g.cur.buttons, raw, 4);
  if (now_ns() < g_inj_until_ns) g.cur.buttons |= g_inj_buttons;  // debug channel "press"
  if (now_ns() < g_stick_until_ns) { g.cur.lx = g_stick_lx; g.cur.ly = g_stick_ly; }  // debug channel "stick"
  g.cur.lx = raw[4];
  g.cur.ly = raw[5];
  g.cur.rx = raw[6];
  g.cur.ry = raw[7];
  g.cur.l2 = raw[8];
  g.cur.r2 = raw[9];
  if (g.cur.buttons != g.prev.buttons) ps5_log("pad: buttons=0x%08x lx=%u ly=%u rx=%u ry=%u l2=%u r2=%u", g.cur.buttons, g.cur.lx, g.cur.ly, g.cur.rx, g.cur.ry, g.cur.l2, g.cur.r2);
}

void push_axis(SDL_GamepadAxis axis, int16_t value) {
  SDL_Event e;
  std::memset(&e, 0, sizeof e);
  e.type = SDL_EVENT_GAMEPAD_AXIS_MOTION;
  e.gaxis.which = kPadId;
  e.gaxis.axis = axis;
  e.gaxis.value = value;
  g.events.push_back(e);
}

void generate_events() {
  if (!g.added_sent) {
    g.added_sent = true;
    SDL_Event e;
    std::memset(&e, 0, sizeof e);
    e.type = SDL_EVENT_GAMEPAD_ADDED;
    e.gdevice.which = kPadId;
    g.events.push_back(e);
  }
  read_pad();
  if (g.rumble_until_ns && now_ns() >= g.rumble_until_ns) {
    g.rumble_until_ns = 0;
    ScePadVibrationParam off{0, 0};
    scePadSetVibration(g.pad_handle, &off);
  }
  for (const auto& b : kButtons) {
    const bool was = (g.prev.buttons & b.pad_bit) != 0;
    const bool now = (g.cur.buttons & b.pad_bit) != 0;
    if (was != now) {
      SDL_Event e;
      std::memset(&e, 0, sizeof e);
      e.type = now ? SDL_EVENT_GAMEPAD_BUTTON_DOWN : SDL_EVENT_GAMEPAD_BUTTON_UP;
      e.gbutton.which = kPadId;
      e.gbutton.button = static_cast<Uint8>(b.sdl);
      e.gbutton.down = now;
      g.events.push_back(e);
    }
  }
  if (g.cur.lx != g.prev.lx) push_axis(SDL_GAMEPAD_AXIS_LEFTX, stick_axis(g.cur.lx));
  if (g.cur.ly != g.prev.ly) push_axis(SDL_GAMEPAD_AXIS_LEFTY, stick_axis(g.cur.ly));
  if (g.cur.rx != g.prev.rx) push_axis(SDL_GAMEPAD_AXIS_RIGHTX, stick_axis(g.cur.rx));
  if (g.cur.ry != g.prev.ry) push_axis(SDL_GAMEPAD_AXIS_RIGHTY, stick_axis(g.cur.ry));
  if (g.cur.l2 != g.prev.l2) push_axis(SDL_GAMEPAD_AXIS_LEFT_TRIGGER, trigger_axis(g.cur.l2));
  if (g.cur.r2 != g.prev.r2) push_axis(SDL_GAMEPAD_AXIS_RIGHT_TRIGGER, trigger_axis(g.cur.r2));
  g.prev = g.cur;
}

}  // namespace

// Window type seen by the game is opaque; hand out the single fake window.
struct SDL_Window : FakeWindow {};
struct SDL_Gamepad {
  int token;
};

extern "C" {

// ---- PS5 launcher hooks ----------------------------------------------------------------------
void ps5sdl_set_display_mode(int width, int height, int hz) {
  g_mode_w = width;
  g_mode_h = height;
  g_mode_hz = hz;
}

// Current pad state for the launcher: buttons + sticks {lx, ly, rx, ry, l2, r2}.
bool ps5sdl_get_pad(uint32_t* buttons, uint8_t* sticks) {
  read_pad();
  if (g.pad_handle < 0) return false;
  *buttons = g.cur.buttons;
  sticks[0] = g.cur.lx;
  sticks[1] = g.cur.ly;
  sticks[2] = g.cur.rx;
  sticks[3] = g.cur.ry;
  sticks[4] = g.cur.l2;
  sticks[5] = g.cur.r2;
  return true;
}

// ---- init / misc -------------------------------------------------------------------------
bool SDL_Init(SDL_InitFlags) { return true; }
bool SDL_InitSubSystem(SDL_InitFlags) { return true; }
void SDL_QuitSubSystem(SDL_InitFlags) {}
void SDL_Quit(void) {}
bool SDL_ClearError(void) {
  g.error.clear();
  return true;
}
const char* SDL_GetError(void) { return g.error.c_str(); }
bool SDL_SetHint(const char*, const char*) { return true; }
int SDL_GetVersion(void) { return SDL_VERSION; }
const char* SDL_GetCurrentVideoDriver(void) { return "ps5"; }
void SDL_free(void* p) { std::free(p); }
bool SDL_OpenURL(const char*) { return false; }

Uint64 SDL_GetPerformanceCounter(void) {
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<Uint64>(ts.tv_sec) * 1000000000ull + static_cast<Uint64>(ts.tv_nsec);
}
Uint64 SDL_GetPerformanceFrequency(void) { return 1000000000ull; }

// ---- clipboard / cursor / text input (no-ops) -----------------------------------------------
bool SDL_SetClipboardText(const char*) { return true; }
bool SDL_HasClipboardText(void) { return false; }
char* SDL_GetClipboardText(void) {
  char* s = static_cast<char*>(std::malloc(1));
  s[0] = 0;
  return s;
}
bool SDL_ShowCursor(void) { return true; }
bool SDL_HideCursor(void) { return true; }
SDL_Cursor* SDL_CreateSystemCursor(SDL_SystemCursor) { return nullptr; }
void SDL_DestroyCursor(SDL_Cursor*) {}
bool SDL_SetCursor(SDL_Cursor*) { return true; }
bool SDL_CaptureMouse(bool) { return true; }
bool SDL_StartTextInput(SDL_Window*) { return true; }
bool SDL_StopTextInput(SDL_Window*) { return true; }
bool SDL_TextInputActive(SDL_Window*) { return false; }
bool SDL_SetTextInputArea(SDL_Window*, const SDL_Rect*, int) { return true; }
SDL_Keymod SDL_GetModState(void) { return 0; }
SDL_Window* SDL_GetKeyboardFocus(void) { return nullptr; }
SDL_Window* SDL_GetMouseFocus(void) { return nullptr; }
SDL_MouseButtonFlags SDL_GetGlobalMouseState(float* x, float* y) {
  if (x) *x = 0;
  if (y) *y = 0;
  return 0;
}
void SDL_WarpMouseInWindow(SDL_Window*, float, float) {}

// ---- surfaces (window icon) --------------------------------------------------------------
SDL_Surface* SDL_CreateSurfaceFrom(int, int, SDL_PixelFormat, void*, int) { return nullptr; }
void SDL_DestroySurface(SDL_Surface*) {}
bool SDL_SetWindowIcon(SDL_Window*, SDL_Surface*) { return true; }

// ---- window --------------------------------------------------------------------------------
SDL_Window* SDL_CreateWindow(const char*, int w, int h, SDL_WindowFlags) {
  static SDL_Window win;
  win.w = w > 0 ? w : 1920;
  win.h = h > 0 ? h : 1080;
  return &win;
}
void SDL_DestroyWindow(SDL_Window*) {}
bool SDL_GetWindowSize(SDL_Window*, int* w, int* h) {
  if (w) *w = g.win_w;
  if (h) *h = g.win_h;
  return true;
}
bool SDL_GetWindowSizeInPixels(SDL_Window*, int* w, int* h) { return SDL_GetWindowSize(nullptr, w, h); }
bool SDL_GetWindowPosition(SDL_Window*, int* x, int* y) {
  if (x) *x = 0;
  if (y) *y = 0;
  return true;
}
float SDL_GetWindowDisplayScale(SDL_Window*) { return 1.0f; }
SDL_WindowFlags SDL_GetWindowFlags(SDL_Window*) { return SDL_WINDOW_OPENGL | SDL_WINDOW_FULLSCREEN | SDL_WINDOW_INPUT_FOCUS; }
SDL_WindowID SDL_GetWindowID(SDL_Window*) { return 1; }
bool SDL_GetWindowRelativeMouseMode(SDL_Window*) { return false; }
bool SDL_SetWindowRelativeMouseMode(SDL_Window*, bool) { return true; }
bool SDL_SetWindowSize(SDL_Window*, int, int) { return true; }
bool SDL_SetWindowPosition(SDL_Window*, int, int) { return true; }
bool SDL_SetWindowFullscreen(SDL_Window*, bool) { return true; }
bool SDL_SetWindowFullscreenMode(SDL_Window*, const SDL_DisplayMode*) { return true; }

// ---- OpenGL via EGL ------------------------------------------------------------------------
bool SDL_GL_SetAttribute(SDL_GLAttr, int) { return true; }

// Handoff of the GL context: while the engine boots on its own thread the launcher keeps drawing the loading screen.
// phase: 0 = launcher not drawing, 1 = launcher thread owns the context, 2 = engine asked for it, 3 = released.
static std::atomic<int> g_gl_phase{0};
extern "C" void ps5sdl_launcher_owns_context(bool on) { g_gl_phase = on ? 1 : 0; }
extern "C" bool ps5sdl_handoff_requested() { return g_gl_phase.load() == 2; }
extern "C" void ps5sdl_release_context_for_engine() {
  eglMakeCurrent(g.dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
  g_gl_phase = 3;
}
static void wait_for_launcher_release() {
  int expected = 1;
  if (!g_gl_phase.compare_exchange_strong(expected, 2)) return;  // launcher not drawing
  for (int i = 0; i < 15000 && g_gl_phase.load() == 2; ++i) usleep(1000);  // up to 15 s; the launcher moves 2 -> 3 -> 0
  if (g_gl_phase.load() == 2) ps5_log("sdl-shim: launcher did not release the GL context in time");
}

SDL_GLContext SDL_GL_CreateContext(SDL_Window*) {
  if (g.ctx != EGL_NO_CONTEXT) {  // the launcher already made one: the engine reuses it
    wait_for_launcher_release();
    eglMakeCurrent(g.dpy, g.surf, g.surf, g.ctx);
    return reinterpret_cast<SDL_GLContext>(g.ctx);
  }
#ifdef PS5SDL_HAVE_MODES
  g.dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
  eglSetDisplayModePS5(g.dpy, g_mode_w, g_mode_h);
  eglSetDisplayRefreshPS5(g.dpy, g_mode_hz);
#else
  g.dpy = eglGetDisplay(EGL_DEFAULT_DISPLAY);
#endif
  EGLint major = 0, minor = 0, count = 0;
  if (g.dpy == EGL_NO_DISPLAY || !eglInitialize(g.dpy, &major, &minor) || !eglBindAPI(EGL_OPENGL_API)) {
    g.error = "eglInitialize failed";
    ps5_log("sdl-shim: eglInitialize failed");
    return nullptr;
  }
  const EGLint cfg_attr[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                             EGL_RED_SIZE,     8,              EGL_GREEN_SIZE,      8,
                             EGL_BLUE_SIZE,    8,              EGL_ALPHA_SIZE,      8,
                             EGL_DEPTH_SIZE,   24,             EGL_STENCIL_SIZE,    8,
                             EGL_NONE};
  EGLConfig config = nullptr;
  if (!eglChooseConfig(g.dpy, cfg_attr, &config, 1, &count) || count != 1) {
    // retry without depth/stencil constraints
    const EGLint cfg_min[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                              EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
                              EGL_NONE};
    if (!eglChooseConfig(g.dpy, cfg_min, &config, 1, &count) || count != 1) {
      g.error = "eglChooseConfig failed";
      ps5_log("sdl-shim: eglChooseConfig failed");
      return nullptr;
    }
  }
  g.surf = eglCreateWindowSurface(g.dpy, config, (EGLNativeWindowType)0, nullptr);
  const EGLint ctx_attr[] = {EGL_CONTEXT_MAJOR_VERSION_KHR,
                             4,
                             EGL_CONTEXT_MINOR_VERSION_KHR,
                             6,
                             EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR,
                             EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR,
                             EGL_NONE};
  g.ctx = eglCreateContext(g.dpy, config, EGL_NO_CONTEXT, ctx_attr);
  if (g.surf == EGL_NO_SURFACE || g.ctx == EGL_NO_CONTEXT || !eglMakeCurrent(g.dpy, g.surf, g.surf, g.ctx)) {
    g.error = "EGL surface/context creation failed";
    ps5_log("sdl-shim: EGL surface/context failed");
    return nullptr;
  }
  EGLint w = 0, h = 0;
  eglQuerySurface(g.dpy, g.surf, EGL_WIDTH, &w);
  eglQuerySurface(g.dpy, g.surf, EGL_HEIGHT, &h);
  if (w > 0 && h > 0) {
    g.win_w = w;
    g.win_h = h;
  }
  ps5_log("sdl-shim: EGL %d.%d ok, surface %dx%d", major, minor, g.win_w, g.win_h);
  return reinterpret_cast<SDL_GLContext>(g.ctx);
}

bool SDL_GL_MakeCurrent(SDL_Window*, SDL_GLContext) {
  wait_for_launcher_release();
  return eglMakeCurrent(g.dpy, g.surf, g.surf, g.ctx) == EGL_TRUE;
}
bool SDL_GL_DestroyContext(SDL_GLContext) {
  if (g.ctx != EGL_NO_CONTEXT) {  // keep display, surface and context: the launcher reuses them after the game quits
    eglMakeCurrent(g.dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    return true;
  }
  if (g.dpy != EGL_NO_DISPLAY) {
    eglMakeCurrent(g.dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    if (g.ctx != EGL_NO_CONTEXT) eglDestroyContext(g.dpy, g.ctx);
    if (g.surf != EGL_NO_SURFACE) eglDestroySurface(g.dpy, g.surf);
    eglTerminate(g.dpy);
  }
  g.ctx = EGL_NO_CONTEXT;
  g.surf = EGL_NO_SURFACE;
  g.dpy = EGL_NO_DISPLAY;
  return true;
}
SDL_FunctionPointer SDL_GL_GetProcAddress(const char* name) {
  // index-format adaptation layer (glfix.cpp) sits in front of the driver for a few entry points
  if (void* w = ps5_glfix_lookup(name)) return reinterpret_cast<SDL_FunctionPointer>(w);
  if (SDL_FunctionPointer p = reinterpret_cast<SDL_FunctionPointer>(eglGetProcAddress(name))) return p;
  // core entry points are plain exports of the PS5 OpenGL library, not EGL-resolvable
  return reinterpret_cast<SDL_FunctionPointer>(const_cast<void*>(ps5_gl_lookup(name)));
}
bool SDL_GL_SetSwapInterval(int interval) { return eglSwapInterval(g.dpy, interval) == EGL_TRUE; }
extern "C" void ps5_profile_tick();

// Debug aid: with /data/opengoal/config/shot.txt present, save the frame (binary PPM) every ~20 s of play.
extern "C" unsigned ps5_glfix_end_frame();
extern "C" bool ps5_dbg_shot_pending();
extern "C" bool ps5_dbg_shot_screen();
extern "C" void ps5_dbg_shot_deliver(int w, int h, const unsigned char* rgb);
static void maybe_capture_frame(int w, int h) {
  const unsigned main_fbo = ps5_glfix_end_frame();
  if (ps5_dbg_shot_pending()) {  // on-demand capture requested over the debug channel
    using BindFn = void (*)(unsigned, unsigned);
    using PixFn = void (*)(unsigned, int);
    using ReadFn = void (*)(int, int, int, int, unsigned, unsigned, void*);
    auto bind = reinterpret_cast<BindFn>(const_cast<void*>(ps5_gl_lookup("glBindFramebuffer")));
    auto pixelstore = reinterpret_cast<PixFn>(const_cast<void*>(ps5_gl_lookup("glPixelStorei")));
    auto readpix = reinterpret_cast<ReadFn>(const_cast<void*>(ps5_gl_lookup("glReadPixels")));
    if (bind && pixelstore && readpix) {
      std::vector<unsigned char> px(size_t(w) * h * 3), flipped(size_t(w) * h * 3);
      bind(0x8CA8, (ps5_dbg_shot_screen() || !main_fbo) ? 0u : main_fbo);
      pixelstore(0x0D05, 1);
      readpix(0, 0, w, h, 0x1907, 0x1401, px.data());
      for (int y = 0; y < h; ++y)
        std::memcpy(flipped.data() + size_t(y) * w * 3, px.data() + size_t(h - 1 - y) * w * 3, size_t(w) * 3);
      ps5_dbg_shot_deliver(w, h, flipped.data());
    }
  }
  // shot.txt holds the times (seconds after the first frame) at which to save a frame, e.g. "12 25 40"
  static double times[8];
  static int ntimes = -1, next = 0;
  static uint64_t t0 = 0;
  if (ntimes < 0) {
    ntimes = 0;
    if (FILE* f = std::fopen("/data/opengoal/config/shot.txt", "r")) {
      double v;
      while (ntimes < 8 && std::fscanf(f, "%lf", &v) == 1) times[ntimes++] = v;
      std::fclose(f);
    }
    t0 = now_ns();
    ps5_log("capture: %d shot time(s)", ntimes);
  }
  if (next >= ntimes || (now_ns() - t0) / 1e9 < times[next]) return;
  const int shots = next++;
  std::vector<unsigned char> px(size_t(w) * h * 3);
  using BindFn = void (*)(unsigned, unsigned);
  using PixFn = void (*)(unsigned, int);
  using ReadFn = void (*)(int, int, int, int, unsigned, unsigned, void*);
  auto bind = reinterpret_cast<BindFn>(const_cast<void*>(ps5_gl_lookup("glBindFramebuffer")));
  auto pixelstore = reinterpret_cast<PixFn>(const_cast<void*>(ps5_gl_lookup("glPixelStorei")));
  auto readpix = reinterpret_cast<ReadFn>(const_cast<void*>(ps5_gl_lookup("glReadPixels")));
  if (!bind || !pixelstore || !readpix) return;
  if (!main_fbo) return;
  static const bool from_screen = [] { struct stat st; return stat("/data/opengoal/config/shotscreen.txt", &st) == 0; }();  // shot of the final window image (after FSR) instead of the render buffer
  bind(0x8CA8 /*GL_READ_FRAMEBUFFER*/, from_screen ? 0u : main_fbo);
  pixelstore(0x0D05 /*GL_PACK_ALIGNMENT*/, 1);
  readpix(0, 0, w, h, 0x1907 /*GL_RGB*/, 0x1401 /*GL_UNSIGNED_BYTE*/, px.data());
  char path[96];
  std::snprintf(path, sizeof path, "/data/opengoal/log/shot%d.ppm", shots);
  if (FILE* f = std::fopen(path, "wb")) {
    std::fprintf(f, "P6\n%d %d\n255\n", w, h);
    for (int y = h - 1; y >= 0; --y) std::fwrite(px.data() + size_t(y) * w * 3, 1, size_t(w) * 3, f);
    std::fclose(f);
    ps5_log("captured %s", path);
  }
}

// ---- per-thread CPU usage (engine threads register themselves, see apply_ps5_patches.py) ----
// pthread_getcpuclockid is not usable on the PS5, so each thread reads its own CPU clock inside a SIGUSR2 handler.
#include <pthread.h>
#include <signal.h>
namespace {
struct RegThread { char name[24]; pthread_t tid; volatile uint64_t cpu; uint64_t last_cpu; };
RegThread g_threads[16];
std::atomic<int> g_thread_count{0};
void thread_cpu_handler(int) {
  const pthread_t me = pthread_self();
  const int cnt = g_thread_count.load() < 16 ? g_thread_count.load() : 16;
  for (int i = 0; i < cnt; ++i)
    if (pthread_equal(g_threads[i].tid, me)) {
      timespec ts{};
      clock_gettime(14 /*CLOCK_THREAD_CPUTIME_ID*/, &ts);
      g_threads[i].cpu = uint64_t(ts.tv_sec) * 1000000000ull + uint64_t(ts.tv_nsec);
    }
}
}  // namespace
extern "C" void ps5_thread_register(const char* name) {
  const int i = g_thread_count.fetch_add(1);
  if (i >= 16) return;
  std::strncpy(g_threads[i].name, name, 23);
  g_threads[i].tid = pthread_self();
  g_threads[i].cpu = 0;
  g_threads[i].last_cpu = 0;
  static std::atomic<bool> installed{false};
  if (!installed.exchange(true)) {
    struct sigaction sa;
    std::memset(&sa, 0, sizeof sa);
    sa.sa_handler = thread_cpu_handler;
    sa.sa_flags = SA_RESTART;
    sigaction(SIGUSR2, &sa, nullptr);
  }
}
// "threads: EE=85% ..." since the previous call (wall_ns = interval)
static void log_thread_cpu(uint64_t wall_ns) {
  const int cnt = g_thread_count.load() < 16 ? g_thread_count.load() : 16;
  for (int i = 0; i < cnt; ++i) pthread_kill(g_threads[i].tid, SIGUSR2);
  usleep(3000);
  char buf[256];
  int n = 0;
  for (int i = 0; i < cnt && n < 230; ++i) {
    const uint64_t cpu = g_threads[i].cpu;
    const double pct = (g_threads[i].last_cpu && cpu) ? 100.0 * double(cpu - g_threads[i].last_cpu) / double(wall_ns) : 0.0;
    g_threads[i].last_cpu = cpu;
    n += std::snprintf(buf + n, sizeof buf - size_t(n), " %s=%.0f%%", g_threads[i].name, pct);
  }
  buf[n] = 0;
  ps5_log("threads:%s", buf);
}
extern "C" void ps5_driver_present_wait_stats(unsigned long long*, unsigned long long*, unsigned long long*);
extern "C" int ps5_driver_gputrace_report(char*, size_t);
extern "C" void ps5_driver_gputrace_frame();
extern "C" void ps5_driver_drainbuf_stats(unsigned long long*, unsigned long long*, unsigned long long*, unsigned long long*);
extern "C" void ps5_driver_drainbuf_classes(unsigned long long*, unsigned long long*);
extern "C" unsigned ps5_driver_drainbuf_sites(uintptr_t*, unsigned long long*, unsigned long long*);
extern "C" void ps5_driver_rename_stats(unsigned long long*, unsigned long long*, unsigned long long*);
extern "C" void ps5_driver_rename_why(unsigned long long*);
extern "C" int ps5_driver_blit_report(char*, size_t);
extern "C" int ps5_driver_mip_report(char*, size_t);
extern "C" void ps5_driver_backpressure_stats(unsigned long long*, unsigned long long*, unsigned long long*, unsigned long long*);
extern "C" void ps5_glfix_frame_end(double);
extern "C" int ps5_driver_clear_report(char*, size_t);
extern "C" void ps5_driver_scanout_reasons(unsigned long long*, unsigned long long*, unsigned long long*, unsigned long long*);
extern "C" void ps5_loading_overlay(int w, int h);
extern "C" void ps5_trace_frame_tick(uint64_t frame_no, uint64_t interval_ns);
extern "C" int sceSystemServicePowerTick(void);
extern "C" unsigned ps5_glfix_draw_total();
extern "C" void ps5_driver_flush_counters(unsigned long long*, unsigned long long*);
extern "C" void ps5_driver_wait_sites(unsigned long long*, unsigned long long*);
extern "C" unsigned ps5_driver_drain_counters(unsigned*, unsigned*);
extern "C" void ps5_driver_flush_classes(unsigned long long[4][2], unsigned long long[4][2]);
extern "C" unsigned ps5_driver_flush_callers(uintptr_t*, unsigned long long*, unsigned long long*);
extern "C" void ps5_glfix_counters(unsigned long long*, unsigned long long*, unsigned long long*, unsigned long long*, unsigned long long*);
bool SDL_GL_SwapWindow(SDL_Window*) {
  ps5_driver_gputrace_frame();
  ps5_profile_tick();
  {  // optional: /data/opengoal/config/renderpin.txt holds a CPU number to pin the swapping (render) thread to
    static thread_local bool pin_done = false;
    if (!pin_done) {
      pin_done = true;
      if (FILE* pf = std::fopen("/data/opengoal/config/renderpin.txt", "r")) {
        int cpu = -1;
        if (std::fscanf(pf, "%d", &cpu) == 1 && cpu >= 0 && cpu < 64) {
          cpuset_t one;
          CPU_ZERO(&one);
          CPU_SET(cpu, &one);
          const int rc = cpuset_setaffinity(CPU_LEVEL_WHICH, CPU_WHICH_TID, -1, sizeof one, &one);
          ps5_log("render thread pinned to cpu %d: rc=%d", cpu, rc);
        }
        std::fclose(pf);
      }
    }
  }
  {  // tell the system the user is active: no rest mode while the app runs, even when only the debug channel injects input
    static uint64_t last_tick = 0;
    const uint64_t tn = now_ns();
    if (tn - last_tick > 5000000000ull) {
      last_tick = tn;
      sceSystemServicePowerTick();
    }
  }
  if (g_gl_phase.load() == 0 || g_gl_phase.load() == 3) ps5_loading_overlay(g.win_w, g.win_h);
  static uint64_t window_start = 0, swap_ns = 0, last_end = 0, outside_ns = 0;
  static int frames = 0;
  maybe_capture_frame(g.win_w, g.win_h);
  const uint64_t before = now_ns();
  const uint64_t last_end_prev = last_end;
  if (last_end) outside_ns += before - last_end;
  const bool ok = eglSwapBuffers(g.dpy, g.surf) == EGL_TRUE;
  const uint64_t t = now_ns();
  last_end = t;
  swap_ns += t - before;
  static uint64_t prev_swap_t = 0, max_interval = 0;
  static int slow20 = 0, slow33 = 0;
  if (prev_swap_t) {
    const uint64_t iv = t - prev_swap_t;
    static uint64_t last_slow_log = 0;
    // log hitches with what happened during them, at most twice a second (sustained 30 fps would flood the log)
    if (iv > 25000000ull && (t - last_slow_log > 500000000ull || iv > 60000000ull)) {
      last_slow_log = t;
      static unsigned long long l_bdc = 0, l_bdb = 0, l_bsc = 0, l_bsb = 0, l_dc = 0;
      unsigned long long bdc, bdb, bsc, bsb, dc;
      ps5_glfix_counters(&bdc, &bdb, &bsc, &bsb, &dc);
      static unsigned long long l_fc = 0, l_fb = 0;
      unsigned long long fc, fb;
      ps5_driver_flush_counters(&fc, &fb);
      ps5_log("slowframe: %.1f ms, draws=%u, render-since-swap=%.1f ms, BufferData +%llu calls +%llu KB, SubData +%llu calls +%llu KB, draw-cycles +%llu M, cache flush +%llu calls +%llu KB",
              iv / 1e6, ps5_glfix_draw_total(), (before - last_end_prev) / 1e6, bdc - l_bdc, (bdb - l_bdb) >> 10, bsc - l_bsc, (bsb - l_bsb) >> 10,
              (dc - l_dc) >> 20, fc - l_fc, (fb - l_fb) >> 10);
      l_fc = fc; l_fb = fb;
      { uintptr_t fa[48]; unsigned long long fcs[48], fbs[48]; static unsigned long long pcs[48], pbs[48]; const unsigned fn = ps5_driver_flush_callers(fa, fcs, fbs); for (unsigned fi = 0; fi < fn; ++fi) { if (fbs[fi] - pbs[fi] > (1ull << 20)) ps5_log("  flush caller %llx: +%llu calls +%llu KB", (unsigned long long)fa[fi], fcs[fi] - pcs[fi], (fbs[fi] - pbs[fi]) >> 10); pcs[fi] = fcs[fi]; pbs[fi] = fbs[fi]; } }
      { unsigned long long cc[4][2], cb[4][2]; static unsigned long long pcb[4][2]; ps5_driver_flush_classes(cc, cb); ps5_log("  flush classes KB (nobatch/batch): depth %llu/%llu tex %llu/%llu vert %llu/%llu idx %llu/%llu", (cb[0][0]-pcb[0][0])>>10, (cb[0][1]-pcb[0][1])>>10, (cb[1][0]-pcb[1][0])>>10, (cb[1][1]-pcb[1][1])>>10, (cb[2][0]-pcb[2][0])>>10, (cb[2][1]-pcb[2][1])>>10, (cb[3][0]-pcb[3][0])>>10, (cb[3][1]-pcb[3][1])>>10); for (int a = 0; a < 4; ++a) for (int b = 0; b < 2; ++b) pcb[a][b] = cb[a][b]; }
      { unsigned dl[24], dh[24]; const unsigned dn = ps5_driver_drain_counters(dl, dh); static unsigned dlast[24]; char dbuf[256]; int dp = 0; for (unsigned di = 0; di < dn && dp < 230; ++di) { dp += std::snprintf(dbuf + dp, sizeof dbuf - size_t(dp), " L%u:+%u", dl[di], dh[di] - dlast[di]); dlast[di] = dh[di]; } dbuf[dp] = 0; ps5_log("  drains since last:%s", dbuf); }
      l_bdc = bdc; l_bdb = bdb; l_bsc = bsc; l_bsb = bsb; l_dc = dc;
    }
    ps5_glfix_frame_end(iv / 1e6);
    if (iv > max_interval) max_interval = iv;
    if (iv > 20000000ull) ++slow20;
    if (iv > 33500000ull) ++slow33;
  }
  { static uint64_t fno = 0; ps5_trace_frame_tick(++fno, prev_swap_t ? t - prev_swap_t : 0); }
  prev_swap_t = t;
  // frame-rate counter (one log line every 3 seconds): fps, time inside the swap, time spent rendering
  if (!window_start) window_start = t;
  ++frames;
  if (t - window_start >= 3000000000ull) {
    static uint64_t last_cpu = 0;
    timespec cts{};
    clock_gettime(14 /*CLOCK_THREAD_CPUTIME_ID*/, &cts);
    const uint64_t cpu = uint64_t(cts.tv_sec) * 1000000000ull + uint64_t(cts.tv_nsec);
    ps5_log("fps: %.1f  (swap %.1f ms, render %.1f ms per frame, thread cpu %.1f ms per frame)", frames * 1e9 / double(t - window_start),
            swap_ns / 1e6 / frames, outside_ns / 1e6 / frames, (cpu - last_cpu) / 1e6 / frames);
    last_cpu = cpu;
    { static uint64_t last_thr = 0; log_thread_cpu(last_thr ? t - last_thr : 3000000000ull); last_thr = t; }
    {  // GPU time per command group (driver patch 23, only with gputrace.txt)
      char gt[640];
      if (ps5_driver_gputrace_report(gt, sizeof gt) > 0) ps5_log("gpu: %s", gt);
    }
    {  // back-pressure: CPU blocked because 8 batches are in flight (driver patch 37)
      static unsigned long long bf = 0, bw = 0, bn = 0, bs = 0;
      unsigned long long f1, w1, n1, s1;
      ps5_driver_backpressure_stats(&f1, &w1, &n1, &s1);
      ps5_log("backpressure: %llu batch flushes, %llu waited for the GPU (%.1f ms total, %.2f ms/frame); batch submit %.2f ms/frame", f1 - bf, w1 - bw,
              (n1 - bn) / 1e6, (n1 - bn) / 1e6 / double(frames ? frames : 1), (s1 - bs) / 1e6 / double(frames ? frames : 1));
      bf = f1; bw = w1; bn = n1; bs = s1;
    }
    {  // wait-site accounting (driver patch 43): wall time per frame the render thread spent waiting, per site
      static unsigned long long pw[4] = {0, 0, 0, 0}, pn[4] = {0, 0, 0, 0};
      unsigned long long w1[4], n1[4];
      ps5_driver_wait_sites(w1, n1);
      const double fr = double(frames ? frames : 1);
      ps5_log("waits per frame: batch-retire %.2f ms (%llu), frame-complete %.2f ms (%llu), flip %.2f ms (%llu), async-collect %.2f ms (%llu)",
              (w1[0] - pw[0]) / 1e6 / fr, n1[0] - pn[0], (w1[1] - pw[1]) / 1e6 / fr, n1[1] - pn[1], (w1[2] - pw[2]) / 1e6 / fr, n1[2] - pn[2],
              (w1[3] - pw[3]) / 1e6 / fr, n1[3] - pn[3]);
      for (int k = 0; k < 4; ++k) { pw[k] = w1[k]; pn[k] = n1[k]; }
    }
    {  // why draws were treated as scanout writers (driver patch 40)
      static unsigned long long wc = 0, wn = 0, wt = 0, wi = 0;
      unsigned long long c, n1, t1, i1;
      ps5_driver_scanout_reasons(&c, &n1, &t1, &i1);
      ps5_log("scanout-writer checks: %llu, yes because pool unknown %llu, target null %llu, target in pool %llu", c - wc, n1 - wn, t1 - wt, i1 - wi);
      wc = c; wn = n1; wt = t1; wi = i1;
    }
    {  // glClear paths (driver patch 38): path bits 1 = CPU depth/stencil, 2 = GPU color, 4 = CPU color
      static char cb[900];
      if (ps5_driver_clear_report(cb, sizeof cb) > 0) ps5_log("clear:%s", cb);
    }
    {  // glGenerateMipmap calls (driver patch 35)
      static char mb[1100];
      if (ps5_driver_mip_report(mb, sizeof mb) > 0) ps5_log("mip:%s", mb);
    }
    {  // blits the GPU path declined (driver patch 34)
      char bb[700];
      if (ps5_driver_blit_report(bb, sizeof bb) > 0) ps5_log("blit: %s", bb);
    }
    {  // buffer renames instead of GPU waits (driver patch 31)
      static unsigned long long pr = 0, pf = 0, pa = 0;
      unsigned long long r, f, a;
      ps5_driver_rename_stats(&r, &f, &a);
      ps5_log("buffer-rename: %llu renamed, %llu refused, %llu fresh allocations", r - pr, f - pf, a - pa);
      pr = r; pf = f; pa = a;
      { unsigned long long w[8]; ps5_driver_rename_why(w); ps5_log("buffer-rename refused because (cumulative): off %llu external %llu gpu_written %llu no_direct %llu arena %llu too_big %llu pool_full %llu", w[0], w[1], w[2], w[3], w[4], w[5], w[6]); }
    }
    {  // CPU accesses to buffers still used by queued draws (driver patch 28)
      static unsigned long long dc = 0, dcur = 0, dinf = 0, dns = 0;
      unsigned long long c, cur, inf, n;
      ps5_driver_drainbuf_stats(&c, &cur, &inf, &n);
      ps5_log("drain-buffer: %llu calls, %llu forced submit+GPU wait, %llu waited on an in-flight batch, %.1f ms blocked (%.2f ms/frame)",
              c - dc, cur - dcur, inf - dinf, (n - dns) / 1e6, (n - dns) / 1e6 / double(frames ? frames : 1));
      dc = c; dcur = cur; dinf = inf; dns = n;
      {
        uintptr_t sa[16]; unsigned long long sn[16], sb[16];
        const unsigned sc = ps5_driver_drainbuf_sites(sa, sn, sb);
        char sbuf[300]; int sp = 0;
        for (unsigned k = 0; k < sc && sp < 250; ++k) sp += std::snprintf(sbuf + sp, sizeof sbuf - size_t(sp), " %llx:%llu(%lluKB)", (unsigned long long)sa[k], sn[k], sb[k] >> 10);
        sbuf[sp] = 0;
        ps5_log("drain-buffer sites (cumulative):%s", sbuf);
      }
      {
        static unsigned long long pn[6] = {}, pb[6] = {};
        unsigned long long cn[6], cb[6];
        ps5_driver_drainbuf_classes(cn, cb);
        ps5_log("drain-buffer classes (n, KB): vertex %llu/%llu index %llu/%llu constant %llu/%llu sampler %llu/%llu texture %llu/%llu other %llu/%llu",
                cn[0]-pn[0], (cb[0]-pb[0])>>10, cn[1]-pn[1], (cb[1]-pb[1])>>10, cn[2]-pn[2], (cb[2]-pb[2])>>10,
                cn[3]-pn[3], (cb[3]-pb[3])>>10, cn[4]-pn[4], (cb[4]-pb[4])>>10, cn[5]-pn[5], (cb[5]-pb[5])>>10);
        for (int k = 0; k < 6; ++k) { pn[k] = cn[k]; pb[k] = cb[k]; }
      }
    }
    {  // draws that waited for the pending flip, and how long (driver patch 21)
      static unsigned long long pc = 0, ps = 0, pn = 0;
      unsigned long long c, s2, n;
      ps5_driver_present_wait_stats(&c, &s2, &n);
      ps5_log("present-wait: %llu draws checked, %llu waited (%.1f ms total, %.2f ms per frame)", c - pc, s2 - ps, (n - pn) / 1e6, (n - pn) / 1e6 / double(frames ? frames : 1));
      pc = c; ps = s2; pn = n;
    }
    static double last_u = 0, last_s = 0;
    rusage ru{};
    if (getrusage(1 /*RUSAGE_THREAD*/, &ru) == 0) {
      const double u = ru.ru_utime.tv_sec * 1e3 + ru.ru_utime.tv_usec / 1e3, sy = ru.ru_stime.tv_sec * 1e3 + ru.ru_stime.tv_usec / 1e3;
      ps5_log("thread time per frame: user %.1f ms, system %.1f ms, nvcsw %ld nivcsw %ld", (u - last_u) / frames, (sy - last_s) / frames, ru.ru_nvcsw, ru.ru_nivcsw);
      last_u = u; last_s = sy;
    }
    ps5_log("frametime: max %.1f ms, frames over 20 ms: %d, over 33 ms: %d (of %d)", max_interval / 1e6, slow20, slow33, frames);
    max_interval = 0; slow20 = slow33 = 0;
    frames = 0;
    swap_ns = outside_ns = 0;
    window_start = t;
  }
  return ok;
}

// ---- events ---------------------------------------------------------------------------------
bool SDL_PollEvent(SDL_Event* event) {
  if (g.events.empty()) generate_events();
  if (g.events.empty()) return false;
  if (event) *event = g.events.front();
  g.events.pop_front();
  return true;
}

// ---- gamepad ---------------------------------------------------------------------------------
SDL_JoystickID* SDL_GetGamepads(int* count) {
  ensure_pad();
  auto* ids = static_cast<SDL_JoystickID*>(std::malloc(2 * sizeof(SDL_JoystickID)));
  ids[0] = kPadId;
  ids[1] = 0;
  if (count) *count = 1;
  return ids;
}
SDL_JoystickID* SDL_GetJoysticks(int* count) { return SDL_GetGamepads(count); }
bool SDL_IsGamepad(SDL_JoystickID id) { return id == kPadId; }
SDL_Gamepad* SDL_OpenGamepad(SDL_JoystickID) {
  static SDL_Gamepad pad{1};
  return &pad;
}
void SDL_CloseGamepad(SDL_Gamepad*) {}
SDL_Gamepad* SDL_GetGamepadFromID(SDL_JoystickID) { return SDL_OpenGamepad(kPadId); }
SDL_JoystickID SDL_GetGamepadID(SDL_Gamepad*) { return kPadId; }
const char* SDL_GetGamepadName(SDL_Gamepad*) { return "DualSense Wireless Controller"; }
const char* SDL_GetGamepadNameForID(SDL_JoystickID) { return "DualSense Wireless Controller"; }
bool SDL_GamepadConnected(SDL_Gamepad*) { return true; }

bool SDL_GetGamepadButton(SDL_Gamepad*, SDL_GamepadButton button) {
  for (const auto& b : kButtons)
    if (b.sdl == button) return (g.cur.buttons & b.pad_bit) != 0;
  return false;
}
Sint16 SDL_GetGamepadAxis(SDL_Gamepad*, SDL_GamepadAxis axis) {
  switch (axis) {
    case SDL_GAMEPAD_AXIS_LEFTX: return stick_axis(g.cur.lx);
    case SDL_GAMEPAD_AXIS_LEFTY: return stick_axis(g.cur.ly);
    case SDL_GAMEPAD_AXIS_RIGHTX: return stick_axis(g.cur.rx);
    case SDL_GAMEPAD_AXIS_RIGHTY: return stick_axis(g.cur.ry);
    case SDL_GAMEPAD_AXIS_LEFT_TRIGGER: return trigger_axis(g.cur.l2);
    case SDL_GAMEPAD_AXIS_RIGHT_TRIGGER: return trigger_axis(g.cur.r2);
    default: return 0;
  }
}
bool SDL_RumbleGamepad(SDL_Gamepad*, Uint16 low, Uint16 high, Uint32 duration_ms) {
  if (g.pad_handle < 0) return false;
  ScePadVibrationParam p{static_cast<uint8_t>(low >> 8), static_cast<uint8_t>(high >> 8)};
  scePadSetVibration(g.pad_handle, &p);
  g.rumble_until_ns = (low || high) && duration_ms ? now_ns() + uint64_t(duration_ms) * 1000000ull : 0;
  return true;
}
bool SDL_RumbleGamepadTriggers(SDL_Gamepad*, Uint16, Uint16, Uint32) { return true; }
bool SDL_SendGamepadEffect(SDL_Gamepad*, const void*, int) { return true; }
bool SDL_SetGamepadLED(SDL_Gamepad*, Uint8 r, Uint8 b_, Uint8 gr) {
  if (g.pad_handle < 0) return false;
  ScePadLightBarParam p{r, gr, b_, 255};
  scePadSetLightBar(g.pad_handle, &p);
  return true;
}
int SDL_AddGamepadMappingsFromFile(const char*) { return 0; }

// ---- joystick view of the same pad ------------------------------------------------------------
SDL_Joystick* SDL_GetGamepadJoystick(SDL_Gamepad*) {
  static int token;
  return reinterpret_cast<SDL_Joystick*>(&token);
}
int SDL_GetNumJoystickAxes(SDL_Joystick*) { return 6; }
SDL_JoystickID SDL_GetJoystickID(SDL_Joystick*) { return kPadId; }
SDL_GUID SDL_GetJoystickGUID(SDL_Joystick*) {
  SDL_GUID guid;
  std::memset(&guid, 0, sizeof guid);
  guid.data[0] = 0x03;  // USB bus
  guid.data[4] = 0x4c;  // Sony vendor 0x054c
  guid.data[5] = 0x05;
  guid.data[8] = 0xe6;  // DualSense product 0x0ce6
  guid.data[9] = 0x0c;
  return guid;
}
void SDL_GUIDToString(SDL_GUID guid, char* buf, int len) {
  static const char hex[] = "0123456789abcdef";
  if (len < 33) return;
  for (int i = 0; i < 16; ++i) {
    buf[i * 2] = hex[guid.data[i] >> 4];
    buf[i * 2 + 1] = hex[guid.data[i] & 15];
  }
  buf[32] = 0;
}
Sint16 SDL_GetJoystickAxis(SDL_Joystick*, int axis) {
  switch (axis) {
    case 0: return stick_axis(g.cur.lx);
    case 1: return stick_axis(g.cur.ly);
    case 2: return stick_axis(g.cur.rx);
    case 3: return stick_axis(g.cur.ry);
    case 4: return trigger_axis(g.cur.l2);
    case 5: return trigger_axis(g.cur.r2);
    default: return 0;
  }
}
SDL_PropertiesID SDL_GetGamepadProperties(SDL_Gamepad*) { return 1; }
bool SDL_GetBooleanProperty(SDL_PropertiesID, const char* name, bool default_value) {
  if (!name) return default_value;
  if (!std::strcmp(name, SDL_PROP_GAMEPAD_CAP_RUMBLE_BOOLEAN) ||
      !std::strcmp(name, SDL_PROP_GAMEPAD_CAP_RGB_LED_BOOLEAN) ||
      !std::strcmp(name, SDL_PROP_GAMEPAD_CAP_TRIGGER_RUMBLE_BOOLEAN))
    return true;
  return default_value;
}
SDL_GamepadType SDL_GetGamepadType(SDL_Gamepad*) { return SDL_GAMEPAD_TYPE_PS5; }
const char* SDL_GetGamepadStringForAxis(SDL_GamepadAxis axis) {
  switch (axis) {
    case SDL_GAMEPAD_AXIS_LEFTX: return "leftx";
    case SDL_GAMEPAD_AXIS_LEFTY: return "lefty";
    case SDL_GAMEPAD_AXIS_RIGHTX: return "rightx";
    case SDL_GAMEPAD_AXIS_RIGHTY: return "righty";
    case SDL_GAMEPAD_AXIS_LEFT_TRIGGER: return "lefttrigger";
    case SDL_GAMEPAD_AXIS_RIGHT_TRIGGER: return "righttrigger";
    default: return nullptr;
  }
}
const char* SDL_GetGamepadStringForButton(SDL_GamepadButton button) {
  switch (button) {
    case SDL_GAMEPAD_BUTTON_SOUTH: return "a";
    case SDL_GAMEPAD_BUTTON_EAST: return "b";
    case SDL_GAMEPAD_BUTTON_WEST: return "x";
    case SDL_GAMEPAD_BUTTON_NORTH: return "y";
    case SDL_GAMEPAD_BUTTON_BACK: return "back";
    case SDL_GAMEPAD_BUTTON_START: return "start";
    case SDL_GAMEPAD_BUTTON_LEFT_STICK: return "leftstick";
    case SDL_GAMEPAD_BUTTON_RIGHT_STICK: return "rightstick";
    case SDL_GAMEPAD_BUTTON_LEFT_SHOULDER: return "leftshoulder";
    case SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER: return "rightshoulder";
    case SDL_GAMEPAD_BUTTON_DPAD_UP: return "dpup";
    case SDL_GAMEPAD_BUTTON_DPAD_DOWN: return "dpdown";
    case SDL_GAMEPAD_BUTTON_DPAD_LEFT: return "dpleft";
    case SDL_GAMEPAD_BUTTON_DPAD_RIGHT: return "dpright";
    default: return nullptr;
  }
}

// ---- displays: one HDMI output -------------------------------------------------------------------
static SDL_DisplayMode* display_mode() {
  static SDL_DisplayMode m;
  std::memset(&m, 0, sizeof m);
  m.displayID = 1;
  m.format = SDL_PIXELFORMAT_ARGB8888;
  m.w = g.win_w;
  m.h = g.win_h;
  m.pixel_density = 1.0f;
  m.refresh_rate = 60.0f;
  m.refresh_rate_numerator = 60;
  m.refresh_rate_denominator = 1;
  return &m;
}
SDL_DisplayID* SDL_GetDisplays(int* count) {
  auto* ids = static_cast<SDL_DisplayID*>(std::malloc(2 * sizeof(SDL_DisplayID)));
  ids[0] = 1;
  ids[1] = 0;
  if (count) *count = 1;
  return ids;
}
const char* SDL_GetDisplayName(SDL_DisplayID) { return "PS5 HDMI Output"; }
bool SDL_GetDisplayBounds(SDL_DisplayID, SDL_Rect* rect) {
  if (rect) *rect = SDL_Rect{0, 0, g.win_w, g.win_h};
  return true;
}
SDL_DisplayID SDL_GetDisplayForWindow(SDL_Window*) { return 1; }
const SDL_DisplayMode* SDL_GetCurrentDisplayMode(SDL_DisplayID) { return display_mode(); }
const SDL_DisplayMode* SDL_GetDesktopDisplayMode(SDL_DisplayID) { return display_mode(); }
SDL_DisplayMode** SDL_GetFullscreenDisplayModes(SDL_DisplayID, int* count) {
  auto* block = static_cast<SDL_DisplayMode**>(std::malloc(2 * sizeof(SDL_DisplayMode*)));
  block[0] = display_mode();
  block[1] = nullptr;
  if (count) *count = 1;
  return block;
}
SDL_DisplayOrientation SDL_GetCurrentDisplayOrientation(SDL_DisplayID) { return SDL_ORIENTATION_LANDSCAPE; }
bool SDL_SyncWindow(SDL_Window*) { return true; }

// ---- keyboard / mouse state (none attached) ---------------------------------------------------------
const char* SDL_GetKeyName(SDL_Keycode) { return ""; }
const bool* SDL_GetKeyboardState(int* numkeys) {
  static bool keys[SDL_SCANCODE_COUNT];
  if (numkeys) *numkeys = SDL_SCANCODE_COUNT;
  return keys;
}
SDL_MouseButtonFlags SDL_GetMouseState(float* x, float* y) {
  if (x) *x = 0;
  if (y) *y = 0;
  return 0;
}
SDL_MouseButtonFlags SDL_GetRelativeMouseState(float* x, float* y) { return SDL_GetMouseState(x, y); }
SDL_Scancode SDL_GetScancodeFromKey(SDL_Keycode, SDL_Keymod* modstate) {
  if (modstate) *modstate = 0;
  return SDL_SCANCODE_UNKNOWN;
}

}  // extern "C"
