#pragma once
// Launcher interface shared by the PS5 shim sources.
#include <cstddef>
#include <string>

struct SDL_Window;

struct Ps5Settings {
  int resolution = 0;  // 0 = 1080p, 1 = 1440p, 2 = 2160p
  int refresh = 60;    // 60 or 120 Hz
  int last_game = 0;   // index of the game selected last time
  int lang = 0;        // 0 = English, 1 = Deutsch
  int merge = 1;       // draw merging (1 = on)
  int async_md = 1;    // asynchronous multi-draw submit (1 = on)
  int upscale = 0;     // 0 off, 1 quality 83%, 2 balanced 67%, 3 performance 50%, 4 auto (FSR 1.0)
  int sharpness = 7;   // FSR RCAS strength 0..10
  int lazy_mips = 0;   // lazy / reduced mipmap generation, experimental (1 = on)
};

struct LaunchChoice {
  std::string game;          // "jak1" / "jak2" / "jak3"
  std::string project_path;  // directory passed to gk --proj-path
  // Called once the start animation is over; the engine must boot on another thread so the launcher can keep
  // drawing the loading screen until the engine takes over the GL context.
  void (*on_start)(const LaunchChoice&) = nullptr;
  std::string auto_game;      // set: skip the menu and run the start animation for this game right away
  bool enter_animation = false;  // set: fade the launcher in (coming back from a game)
};

Ps5Settings& ps5_settings();
void ps5_settings_load();
void ps5_settings_save();  // also writes the flag files the app reads at start (nomerge.txt, noasyncmultidraw.txt, mipfast3.txt)

// Runs the launcher until the player picks a game (returns true, fills `out`) or quits (false).
bool ps5_run_launcher(SDL_Window* window, LaunchChoice* out);

struct Ps5Asset {
  const char* name;
  const unsigned char* data;
  size_t size;
};
extern const Ps5Asset kPs5Assets[];
extern const int kPs5AssetCount;
