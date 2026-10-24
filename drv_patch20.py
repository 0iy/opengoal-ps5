#!/usr/bin/env python3
"""Driver patch 20: adaptive flip. A frame that took longer than 16.9 ms since the previous present flips at once (mode 2,
may tear) instead of waiting for the vsync after next, which turned 17 ms frames into 33 ms (30 fps + slow motion).
PS5_VSYNC_STRICT=1 keeps the old always-vsync flip."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "runtime_adaptive_flip_mode" in s:
    print("already patched"); raise SystemExit
anchor = "int ps5_agc_gate2_batch_present(unsigned buffer_index)\n{"
helper = """static uint32_t runtime_adaptive_flip_mode(void)
{
    static int adaptive = -1;
    static int64_t last;
    if (adaptive < 0)
        adaptive = getenv("PS5_VSYNC_STRICT") == NULL;
    const int64_t now = os_time_get_nano();
    const int64_t dt = last ? now - last : 0;
    last = now;
    /* late frame: flip immediately (2 = hsync) instead of waiting for the vsync after next (1 = vsync) */
    return adaptive && dt > 16900000 && dt < 100000000 ? 2u : 1u;
}

"""
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor)
old = """    if (!runtime_batch_api.set_flip(&command, (uint32_t)runtime_video_handle,
                                    (int)buffer_index, 1, (int64_t)marker) ||"""
new = """    if (!runtime_batch_api.set_flip(&command, (uint32_t)runtime_video_handle,
                                    (int)buffer_index, runtime_adaptive_flip_mode(), (int64_t)marker) ||"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
