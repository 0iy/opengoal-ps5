#!/usr/bin/env python3
"""Driver patch 25: GPU trace histogram (count and summed time per duration bucket) next to the top list."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c")
s = open(P, encoding="utf-8").read()
if "gputrace_hist_n" in s:
    print("already patched")
    raise SystemExit

old = "static int64_t gputrace_sum_ns, gputrace_groups;"
new = ("static int64_t gputrace_sum_ns, gputrace_groups;\n"
       "static int64_t gputrace_hist_n[8], gputrace_hist_ns[8];\n"
       "static const int64_t gputrace_edges_us[7] = {20, 50, 100, 200, 500, 1000, 3000};")
assert s.count(old) == 1
s = s.replace(old, new)

old = "    gputrace_sum_ns += dt;\n    ++gputrace_groups;\n"
new = ("    gputrace_sum_ns += dt;\n    ++gputrace_groups;\n"
       "    {\n        unsigned b = 0;\n        while (b < 7 && dt >= gputrace_edges_us[b] * 1000)\n            ++b;\n"
       "        ++gputrace_hist_n[b];\n        gputrace_hist_ns[b] += dt;\n    }\n")
assert s.count(old) == 1
s = s.replace(old, new)

old = '    int w = snprintf(out, n, "groups=%lld busy=%.1f ms top:", (long long)gputrace_groups, gputrace_sum_ns / 1e6);\n'
new = ('    int w = snprintf(out, n, "groups=%lld busy=%.1f ms hist(<20,<50,<100,<200,<500,<1000,<3000,>=3000 us) n:", (long long)gputrace_groups, gputrace_sum_ns / 1e6);\n'
       '    for (int b = 0; b < 8; ++b)\n        w += snprintf(out + w, n - (size_t)w, " %lld", (long long)gputrace_hist_n[b]);\n'
       '    w += snprintf(out + w, n - (size_t)w, " ms:");\n'
       '    for (int b = 0; b < 8; ++b)\n        w += snprintf(out + w, n - (size_t)w, " %.0f", gputrace_hist_ns[b] / 1e6);\n'
       '    w += snprintf(out + w, n - (size_t)w, " top:");\n')
assert s.count(old) == 1
s = s.replace(old, new)

old = "    gputrace_sum_ns = 0;\n    gputrace_groups = 0;\n    memset(gputrace_top"
new = "    gputrace_sum_ns = 0;\n    gputrace_groups = 0;\n    memset(gputrace_hist_n, 0, sizeof gputrace_hist_n);\n    memset(gputrace_hist_ns, 0, sizeof gputrace_hist_ns);\n    memset(gputrace_top"
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
