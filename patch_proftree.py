#!/usr/bin/env python3
"""Diagnostic patch for jak-project (run in WSL): log the renderer's own per-bucket profiler tree (Profiler::to_string)
for one frame out of every 240, through ps5_log, lines prefixed 'ptree:'."""
import os

import json
_REL = "game/graphics/opengl_renderer/OpenGLRenderer.cpp"
P = os.path.join(os.path.expanduser("~/jak"), json.loads(os.environ.get("SYNC_FILE_MAP") or "{}").get(_REL, _REL))  # SYNC_FILE_MAP: see sync_upstream.py
s = open(P, encoding="utf-8").read()
if "__ps5__ proftree" in s:
    print("already patched")
    raise SystemExit

old = "  m_profiler.finish();\n"
assert s.count(old) == 1
new = r'''  m_profiler.finish();
  {  // __ps5__ proftree
    static int ps5_tree_frame = 0;
    if (++ps5_tree_frame % 240 == 0) {
      const std::string tree = m_profiler.to_string();
      size_t pos = 0;
      while (pos < tree.size()) {
        size_t nl = tree.find('\n', pos);
        if (nl == std::string::npos) nl = tree.size();
        ps5_log("ptree: %.*s", int(nl - pos), tree.c_str() + pos);
        pos = nl + 1;
      }
    }
  }
'''
s = s.replace(old, new)
# declaration near the top of the file
inc = '#include "OpenGLRenderer.h"\n'
assert s.count(inc) == 1
s = s.replace(inc, inc + "\nvoid ps5_log(const char*, ...);  // __ps5__ proftree\n")
open(P, "w", encoding="utf-8").write(s)
print("ok")
