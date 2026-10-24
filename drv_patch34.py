#!/usr/bin/env python3
"""Driver patch 34 (diagnostic): blits that the GPU path declined (software blit with GPU drain): count, time and the
distinct (mask, formats, size, samples) keys. Reported by ps5_driver_blit_report()."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_blit_report" in s:
    print("already patched")
    raise SystemExit

anchor = "static bool ps5_blit_gpu_color(struct ps5_context *context, const struct pipe_blit_info *info);"
if anchor not in s:
    # find the definition line of ps5_blit to insert the helpers before it
    d = s.index("ps5_blit(struct pipe_context *context, const struct pipe_blit_info *info)\n{")
    d = s.rfind("static void\n", 0, d)
else:
    d = s.index(anchor)
helper = r'''struct ps5_blit_stat { uint32_t mask, sfmt, dfmt, sw, sh, dw, dh, samples; unsigned long long n, ns; };
static struct ps5_blit_stat ps5_blit_stats[16];
static unsigned long long ps5_blit_sw_total, ps5_blit_sw_ns;
struct ps5_blit_scope { struct ps5_blit_stat *stat; int64_t t0; };
static void
ps5_blit_scope_end(struct ps5_blit_scope *scope)
{
   const int64_t dt = os_time_get_nano() - scope->t0;
   ps5_blit_sw_ns += (unsigned long long)dt;
   if (scope->stat)
      scope->stat->ns += (unsigned long long)dt;
}
static struct ps5_blit_stat *
ps5_blit_stat_for(const struct pipe_blit_info *info)
{
   if (!info || !info->src.resource || !info->dst.resource)
      return NULL;
   struct ps5_blit_stat key = {info->mask, info->src.format, info->dst.format, info->src.box.width < 0 ? -info->src.box.width : info->src.box.width,
                               info->src.box.height < 0 ? -info->src.box.height : info->src.box.height, info->dst.box.width, info->dst.box.height,
                               info->src.resource->nr_samples, 0, 0};
   for (unsigned i = 0; i < 16; ++i) {
      struct ps5_blit_stat *e = &ps5_blit_stats[i];
      if (e->n && e->mask == key.mask && e->sfmt == key.sfmt && e->dfmt == key.dfmt && e->sw == key.sw && e->sh == key.sh &&
          e->dw == key.dw && e->dh == key.dh && e->samples == key.samples)
         return e;
      if (!e->n) {
         *e = key;
         return e;
      }
   }
   return NULL;
}
int
ps5_driver_blit_report(char *out, size_t n)
{
   int w = snprintf(out, n, "software blits=%llu %.1f ms:", ps5_blit_sw_total, ps5_blit_sw_ns / 1e6);
   for (unsigned i = 0; i < 16 && w < (int)n - 120; ++i) {
      struct ps5_blit_stat *e = &ps5_blit_stats[i];
      if (!e->n)
         break;
      w += snprintf(out + w, n - (size_t)w, " [mask%x fmt%u>%u %ux%u>%ux%u s%u n=%llu %.1fms]", e->mask, e->sfmt, e->dfmt, e->sw, e->sh, e->dw, e->dh,
                    e->samples, e->n, e->ns / 1e6);
   }
   memset(ps5_blit_stats, 0, sizeof ps5_blit_stats);
   ps5_blit_sw_total = 0;
   ps5_blit_sw_ns = 0;
   return w;
}

'''
s = s[:d] + helper + s[d:]

old = "   if (ps5_blit_gpu_color(ps5, info))\n      return;\n   ps5_draw_batch_drain_buffer(info ? info->src.resource : NULL);"
new = ("   if (ps5_blit_gpu_color(ps5, info))\n      return;\n"
       "   struct ps5_blit_scope blit_scope __attribute__((cleanup(ps5_blit_scope_end))) = {ps5_blit_stat_for(info), os_time_get_nano()};\n"
       "   ++ps5_blit_sw_total;\n"
       "   if (blit_scope.stat)\n      ++blit_scope.stat->n;\n"
       "   ps5_draw_batch_drain_buffer(info ? info->src.resource : NULL);")
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
