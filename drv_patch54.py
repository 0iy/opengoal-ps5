#!/usr/bin/env python3
"""Driver patch 54 (agent multidraw): make the two batch-queue sizes overridable at compile time. No behaviour change with the
defaults (8 batches in flight, 256 draws per batch). Build variants with EXTRA, e.g.
  EXTRA='-DPS5_INFLIGHT_BATCH_CAPACITY=16u -DPS5_MULTIDRAW_BATCH_CAPACITY=128u' bash drv_cc_cache.sh && bash drv_cc_backend.sh
Both objects (ps5_screen.o and ps5_agc_runtime_backend.o) MUST be built with the same values (they size parallel arrays)."""
import os

ROOT = os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src"))


def patch(rel, old, new):
    p = os.path.join(ROOT, rel)
    s = open(p, encoding="utf-8").read()
    if new in s:
        print(rel, "already patched")
        return
    assert s.count(old) == 1, (rel, s.count(old))
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print(rel, "ok")


patch("platform/ps5_scanout.h",
      "#define PS5_INFLIGHT_BATCH_CAPACITY 8u\n",
      "#ifndef PS5_INFLIGHT_BATCH_CAPACITY\n#define PS5_INFLIGHT_BATCH_CAPACITY 8u\n#endif\n")
patch("gallium/ps5/ps5_screen.h",
      "#define PS5_MULTIDRAW_BATCH_CAPACITY 256u\n",
      "#ifndef PS5_MULTIDRAW_BATCH_CAPACITY\n#define PS5_MULTIDRAW_BATCH_CAPACITY 256u\n#endif\n")
