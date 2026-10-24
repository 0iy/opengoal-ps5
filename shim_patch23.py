#!/usr/bin/env python3
"""App side of driver patch 23: prints the GPU trace line, resets the per-frame group index, reads the config flags."""
p = "ps5shim/ps5sdl.cpp"
t = open(p, encoding="utf-8").read()
if "ps5_driver_gputrace_report" not in t:
    old = "    {  // draws that waited for the pending flip, and how long (driver patch 21)"
    assert t.count(old) == 1
    add = """    {  // GPU time per command group (driver patch 23, only with gputrace.txt)
      char gt[400];
      if (ps5_driver_gputrace_report(gt, sizeof gt) > 0) ps5_log("gpu: %s", gt);
    }
"""
    t = t.replace(old, add + old)
    t = t.replace('extern "C" void ps5_loading_overlay(int w, int h);',
                  'extern "C" int ps5_driver_gputrace_report(char*, size_t);\nextern "C" void ps5_driver_gputrace_frame();\nextern "C" void ps5_loading_overlay(int w, int h);', 1)
    t = t.replace("bool SDL_GL_SwapWindow(SDL_Window*) {\n  ps5_profile_tick();",
                  "bool SDL_GL_SwapWindow(SDL_Window*) {\n  ps5_driver_gputrace_frame();\n  ps5_profile_tick();", 1)
    open(p, "w", encoding="utf-8").write(t)
q = "ps5shim/appmain.cpp"
s = open(q, encoding="utf-8").read()
if "gputrace.txt" not in s:
    a = '  { struct stat nf; if (stat("/data/opengoal/config/adaptiveflip.txt", &nf) != 0)'
    assert s.count(a) == 1
    s = s.replace(a, '  { struct stat nf; if (stat("/data/opengoal/config/gputrace.txt", &nf) == 0) setenv("PS5_GPU_TRACE", "1", 1); }  // diagnostic: GPU completion trace\n'
                  '  { struct stat nf; if (stat("/data/opengoal/config/nocombine.txt", &nf) == 0) setenv("PS5_NO_COMBINE", "1", 1); }  // diagnostic: no command-group combining\n' + a)
    open(q, "w", encoding="utf-8").write(s)
print("ok")
