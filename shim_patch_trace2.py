#!/usr/bin/env python3
"""Shim patch: event 11 = time inside the real GL draw call (Mesa + driver), emitted for every R.Draw* / R.MultiDraw* call.
The time in event 10 (whole glfix wrapper) minus event 11 is the glfix conversion work."""
import os
import re

here = os.path.dirname(os.path.abspath(__file__))
g = os.path.join(here, "ps5shim", "glfix.cpp")
s = open(g, encoding="utf-8").read()
if "TRACE_REAL" in s:
    print("already patched")
    raise SystemExit
n = len(re.findall(r"\bR\.(Draw\w+|MultiDraw\w+)\(", s))
s = re.sub(r"\bR\.(Draw\w+|MultiDraw\w+)\(", r"rt_real(R.\1, ", s)
anchor = "struct DrawTimer {"
helper = """// TRACE_REAL: time of the real GL draw call
template <class F, class... A>
inline void rt_real(F f, A... a) {
  const uint64_t t = tsc();
  f(a...);
  trace_emit(11, t, tsc() - t, 0);
}
"""
assert s.count(anchor) == 1
# rt_real is used before DrawTimer is defined? the draw wrappers come later in the file; helper must precede the first use
first_use = s.index("rt_real(R.")
pos = s.index(anchor)
if first_use < pos:
    raise SystemExit("rt_real used before the helper position; move the helper")
s = s.replace(anchor, helper + anchor)
open(g, "w", encoding="utf-8").write(s)
print("replaced", n, "calls")
