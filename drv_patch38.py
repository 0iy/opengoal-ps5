#!/usr/bin/env python3
"""Driver patch 38 (diagnostic): per glClear call: which path ran (GPU depth/stencil, CPU depth/stencil, GPU color, CPU color),
framebuffer size, time. Reported by ps5_driver_clear_report()."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_clear_report" in s:
    print("already patched")
    raise SystemExit

d = s.index("ps5_clear(struct pipe_context *base, unsigned buffers,")
d = s.rfind("static void\n", 0, d)
helper = r'''struct ps5_clear_stat { unsigned buffers, w, h, ncb, path; unsigned long long n, ns, max_ns; };
static struct ps5_clear_stat ps5_clear_stats[16];
struct ps5_clear_scope { unsigned buffers, w, h, ncb; unsigned path; int64_t t0; };
static void
ps5_clear_scope_end(struct ps5_clear_scope *sc)
{
   const int64_t dt = os_time_get_nano() - sc->t0;
   for (unsigned i = 0; i < 16; ++i) {
      struct ps5_clear_stat *e = &ps5_clear_stats[i];
      if (!e->n || (e->buffers == sc->buffers && e->w == sc->w && e->h == sc->h && e->ncb == sc->ncb && e->path == sc->path)) {
         e->buffers = sc->buffers; e->w = sc->w; e->h = sc->h; e->ncb = sc->ncb; e->path = sc->path;
         ++e->n; e->ns += (unsigned long long)dt;
         if ((unsigned long long)dt > e->max_ns) e->max_ns = (unsigned long long)dt;
         return;
      }
   }
}
int
ps5_driver_clear_report(char *out, size_t n)
{
   int w = 0;
   out[0] = 0;
   for (unsigned i = 0; i < 16 && w < (int)n - 130; ++i) {
      struct ps5_clear_stat *e = &ps5_clear_stats[i];
      if (!e->n)
         break;
      w += snprintf(out + w, n - (size_t)w, " [buf%x %ux%u cb%u path%u n=%llu %.2fms max %.2fms]", e->buffers, e->w, e->h, e->ncb, e->path, e->n,
                    e->ns / 1e6, e->max_ns / 1e6);
   }
   memset(ps5_clear_stats, 0, sizeof ps5_clear_stats);
   return w;
}

'''
s = s[:d] + helper + s[d:]

# scope at the beginning of ps5_clear, path markers at the branches
old = "   struct ps5_context *context = (struct ps5_context *)base;\n   struct ps5_resource *resource;\n\n   if (context && context->render_condition_query)\n      ps5_draw_batch_drain_query(context->render_condition_query);"
new = ("   struct ps5_context *context = (struct ps5_context *)base;\n   struct ps5_resource *resource;\n"
       "   struct ps5_clear_scope clear_scope __attribute__((cleanup(ps5_clear_scope_end))) =\n"
       "      {buffers, context ? context->framebuffer.width : 0, context ? context->framebuffer.height : 0,\n"
       "       context ? context->framebuffer.nr_cbufs : 0, 0, os_time_get_nano()};\n\n"
       "   if (context && context->render_condition_query)\n      ps5_draw_batch_drain_query(context->render_condition_query);")
assert s.count(old) == 1
s = s.replace(old, new)

old = "         ps5_draw_batch_drain_buffer(resource ? &resource->base : NULL);\n         if (!ps5_clear_depth_stencil(context, depth_buffers, stencil_clear_mask,"
new = "         clear_scope.path |= 1; /* CPU depth/stencil */\n         ps5_draw_batch_drain_buffer(resource ? &resource->base : NULL);\n         if (!ps5_clear_depth_stencil(context, depth_buffers, stencil_clear_mask,"
assert s.count(old) == 1
s = s.replace(old, new)

old = "   if (ps5_clear_gpu_color(context, buffers, color_clear_mask, scissor_state, color)) {\n      buffers &= ~PIPE_CLEAR_COLOR;"
new = "   if (ps5_clear_gpu_color(context, buffers, color_clear_mask, scissor_state, color)) {\n      clear_scope.path |= 2; /* GPU color */\n      buffers &= ~PIPE_CLEAR_COLOR;"
assert s.count(old) == 1
s = s.replace(old, new)

old = "   if (context)\n      for (unsigned i = 0; i < context->framebuffer.nr_cbufs; ++i)\n         if (buffers & (PIPE_CLEAR_COLOR0 << i))\n            ps5_draw_batch_drain_buffer(context->framebuffer.cbufs[i].texture);"
new = "   if (context)\n      for (unsigned i = 0; i < context->framebuffer.nr_cbufs; ++i)\n         if (buffers & (PIPE_CLEAR_COLOR0 << i)) {\n            clear_scope.path |= 4; /* CPU color */\n            ps5_draw_batch_drain_buffer(context->framebuffer.cbufs[i].texture);\n         }"
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
