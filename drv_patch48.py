#!/usr/bin/env python3
"""Driver patch 48: draw path trace events. 122 = whole ps5_draw_vbo_reported (Mesa -> driver entry to return),
121 = ps5_agc_gate2_run (hand-over of the draw to the async prep workers). Only active while the shim tracer is recording
(ps5_driver_trace_hook set). No new static data."""
import os

base = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(base, encoding="utf-8").read()
if "ps5_draw_vbo_traced" in s:
    print("already patched")
    raise SystemExit

old = "   context->last_draw_status = ps5_agc_gate2_run();\n   ps5_ck[6] = ps5_my_tsc();"
new = ("   const int64_t g2_t0 = ps5_driver_trace_hook ? os_time_get_nano() : 0;\n"
       "   context->last_draw_status = ps5_agc_gate2_run();\n"
       "   if (g2_t0)\n"
       "      ps5_driver_trace_hook(121, (unsigned long long)g2_t0, (unsigned long long)(os_time_get_nano() - g2_t0), 0);\n"
       "   ps5_ck[6] = ps5_my_tsc();")
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)

old = "   context->base.draw_vbo = ps5_draw_vbo_reported;"
assert s.count(old) == 1
s = s.replace(old, "   context->base.draw_vbo = ps5_draw_vbo_traced;")

# wrapper after the end of ps5_draw_vbo_reported
start = s.index("static void\nps5_draw_vbo_reported(struct pipe_context *base")
end = s.index("\n}\n", start) + 3
wrapper = """
static void
ps5_draw_vbo_traced(struct pipe_context *base, const struct pipe_draw_info *info,
                    unsigned drawid_offset,
                    const struct pipe_draw_indirect_info *indirect,
                    const struct pipe_draw_start_count_bias *draws,
                    unsigned num_draws)
{
   if (!ps5_driver_trace_hook) {
      ps5_draw_vbo_reported(base, info, drawid_offset, indirect, draws, num_draws);
      return;
   }
   const int64_t t0 = os_time_get_nano();
   ps5_draw_vbo_reported(base, info, drawid_offset, indirect, draws, num_draws);
   ps5_driver_trace_hook(122, (unsigned long long)t0, (unsigned long long)(os_time_get_nano() - t0), num_draws);
}
"""
s = s[:end] + wrapper + s[end:]
open(base, "w", encoding="utf-8").write(s)
print("ok")
