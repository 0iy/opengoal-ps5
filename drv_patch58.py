#!/usr/bin/env python3
"""Driver patch 58: finer trace events inside the draw path (only while the tracer is armed).
131 ps5_prepare_constant, 132 ps5_prepare_texture, 133 ps5_flush_descriptor_table_ex (inside ps5_draw_vbo_locked),
134 ps5_batch_copy_descriptors, 135 ps5_batch_retain_resources, 136 ps5_multidraw_eligible (inside ps5_try_deferred_draw).
Implemented with function-like macros that call the real function through (name)(...); no new data."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "PS5_TIMED" in s:
    print("already patched")
    raise SystemExit

NL = chr(10)
timed = NL.join([
    "#define PS5_TIMED(ev, call) ({ const int64_t ps5_tt0 = ps5_driver_trace_hook ? os_time_get_nano() : 0; \\",
    "   __typeof__(call) ps5_tr = (call); \\",
    "   if (ps5_tt0) ps5_driver_trace_hook(ev, (unsigned long long)ps5_tt0, (unsigned long long)(os_time_get_nano() - ps5_tt0), 0); \\",
    "   ps5_tr; })",
    "#define PS5_TIMED_VOID(ev, call) do { const int64_t ps5_tt0 = ps5_driver_trace_hook ? os_time_get_nano() : 0; \\",
    "   call; \\",
    "   if (ps5_tt0) ps5_driver_trace_hook(ev, (unsigned long long)ps5_tt0, (unsigned long long)(os_time_get_nano() - ps5_tt0), 0); } while (0)",
    ""])

# 1. draw_vbo_locked: macros right before its definition
anchor = "static void" + NL + "ps5_draw_vbo_locked(struct pipe_context *base,"
assert s.count(anchor) == 1, s.count(anchor)
locked_macros = timed + NL.join([
    "#define ps5_prepare_constant(...) PS5_TIMED(131, (ps5_prepare_constant)(__VA_ARGS__))",
    "#define ps5_prepare_texture(...) PS5_TIMED(132, (ps5_prepare_texture)(__VA_ARGS__))",
    "#define ps5_flush_descriptor_table_ex(...) PS5_TIMED_VOID(133, (ps5_flush_descriptor_table_ex)(__VA_ARGS__))",
    ""])
s = s.replace(anchor, locked_macros + anchor)

# 2. try_deferred_draw: macros right before its definition
anchor = "static bool" + NL + "ps5_try_deferred_draw(struct pipe_context *base,"
assert s.count(anchor) == 1, s.count(anchor)
deferred_macros = NL.join([
    "#define ps5_batch_copy_descriptors(...) PS5_TIMED(134, (ps5_batch_copy_descriptors)(__VA_ARGS__))",
    "#define ps5_batch_retain_resources(...) PS5_TIMED(135, (ps5_batch_retain_resources)(__VA_ARGS__))",
    "#define ps5_multidraw_eligible(...) PS5_TIMED(136, (ps5_multidraw_eligible)(__VA_ARGS__))",
    ""])
s = s.replace(anchor, deferred_macros + anchor)
open(P, "w", encoding="utf-8").write(s)
print("ok")
