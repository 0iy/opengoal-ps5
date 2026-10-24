#!/usr/bin/env python3
"""Driver patch 21 (diagnostic): count draws that wait for the pending flip in runtime_video_prepare_draw and the time spent."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_present_wait_stats" in s:
    print("already patched"); raise SystemExit
old = """#ifdef PS5_RUNTIME_WRITES_SCANOUT
    if (PS5_RUNTIME_WRITES_SCANOUT())
#endif
        if (ps5_agc_gate2_wait_present() != 0)
            return -1;
#endif
    return runtime_video_registered ? 0 : -1;"""
new = """#ifdef PS5_RUNTIME_WRITES_SCANOUT
    ++runtime_pw_calls;
    if (PS5_RUNTIME_WRITES_SCANOUT())
#endif
    {
        ++runtime_pw_scanout;
        const int64_t t0 = os_time_get_nano();
        const int wr = ps5_agc_gate2_wait_present();
        runtime_pw_ns += (uint64_t)(os_time_get_nano() - t0);
        if (wr != 0)
            return -1;
    }
#endif
    return runtime_video_registered ? 0 : -1;"""
assert s.count(old) == 1
s = s.replace(old, new)
anchor = "static int runtime_video_prepare_draw(void)\n{"
helper = """static unsigned long long runtime_pw_calls, runtime_pw_scanout, runtime_pw_ns;
void ps5_driver_present_wait_stats(unsigned long long *calls, unsigned long long *scanout, unsigned long long *ns)
{
    *calls = runtime_pw_calls; *scanout = runtime_pw_scanout; *ns = runtime_pw_ns;
}

"""
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor)
open(P, "w", encoding="utf-8").write(s)
print("ok")
