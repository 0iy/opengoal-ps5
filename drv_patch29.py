#!/usr/bin/env python3
"""Driver patch 29 (diagnostic): classify the forced drains of patch 28 by buffer bind flags and size."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_dbs_class" in s:
    print("already patched")
    raise SystemExit

old = "static unsigned long long ps5_dbs_calls, ps5_dbs_current, ps5_dbs_inflight, ps5_dbs_ns;\n"
new = (old +
       "static unsigned long long ps5_dbs_class[6], ps5_dbs_class_bytes[6];\n"
       "void\nps5_driver_drainbuf_classes(unsigned long long *n, unsigned long long *bytes)\n{\n"
       "   for (unsigned i = 0; i < 6; ++i) { n[i] = ps5_dbs_class[i]; bytes[i] = ps5_dbs_class_bytes[i]; }\n}\n")
assert s.count(old) == 1
s = s.replace(old, new)

old = "      ++ps5_dbs_current;\n"
new = ("      ++ps5_dbs_current;\n"
       "      if (base) {\n"
       "         const unsigned cls = (base->bind & PIPE_BIND_VERTEX_BUFFER) ? 0 : (base->bind & PIPE_BIND_INDEX_BUFFER) ? 1 :\n"
       "                              (base->bind & PIPE_BIND_CONSTANT_BUFFER) ? 2 : (base->bind & PIPE_BIND_SAMPLER_VIEW) ? 3 :\n"
       "                              (base->target != PIPE_BUFFER) ? 4 : 5;\n"
       "         ++ps5_dbs_class[cls];\n"
       "         ps5_dbs_class_bytes[cls] += base->width0;\n"
       "      }\n")
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
