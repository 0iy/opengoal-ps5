#!/usr/bin/env python3
"""Driver patch 35 (diagnostic): which glGenerateMipmap calls still need the CPU path (forced GPU sync) and why."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_driver_mip_report" in s:
    print("already patched")
    raise SystemExit

# stats storage before ps5_generate_mipmap
d = s.index("ps5_generate_mipmap(struct pipe_context *context,")
d = s.rfind("static bool\n", 0, d)
helper = r'''struct ps5_mip_stat { unsigned fmt, w, h, target, base, last, bind; unsigned long long n, gpu_levels, cpu_levels; };
static struct ps5_mip_stat ps5_mip_stats[16];
static struct ps5_mip_stat *
ps5_mip_stat_for(const struct pipe_resource *r, unsigned base, unsigned last)
{
   for (unsigned i = 0; i < 16; ++i) {
      struct ps5_mip_stat *e = &ps5_mip_stats[i];
      if (e->n && e->fmt == r->format && e->w == r->width0 && e->h == r->height0 && e->target == r->target && e->base == base &&
          e->last == last && e->bind == r->bind)
         return e;
      if (!e->n) {
         e->fmt = r->format; e->w = r->width0; e->h = r->height0; e->target = r->target; e->base = base; e->last = last; e->bind = r->bind;
         return e;
      }
   }
   return NULL;
}
int
ps5_driver_mip_report(char *out, size_t n)
{
   int w = 0;
   out[0] = 0;
   for (unsigned i = 0; i < 16 && w < (int)n - 130; ++i) {
      struct ps5_mip_stat *e = &ps5_mip_stats[i];
      if (!e->n)
         break;
      w += snprintf(out + w, n - (size_t)w, " [fmt%u %ux%u t%u lv%u-%u bind%x n=%llu gpu=%llu cpu=%llu]", e->fmt, e->w, e->h, e->target, e->base,
                    e->last, e->bind, e->n, e->gpu_levels, e->cpu_levels);
   }
   memset(ps5_mip_stats, 0, sizeof ps5_mip_stats);
   return w;
}

'''
s = s[:d] + helper + s[d:]

old = "   bool ps5_mipmap_sync_cpu = false; /* true once the CPU may read what the GPU wrote */\n"
new = old + "   struct ps5_mip_stat *mip_stat = resource ? ps5_mip_stat_for(&resource->base, base_level, last_level) : NULL;\n   if (mip_stat)\n      ++mip_stat->n;\n"
assert s.count(old) == 1
s = s.replace(old, new)

old = "               if (mip_old) {\n                  ps5_draw_batch_drain_buffer(base);\n                  ps5_flush_gpu_data(resource->data, resource->size);\n               } else\n                  ps5_mipmap_sync_cpu = false;\n               continue;"
new = "               if (mip_stat)\n                  ++mip_stat->gpu_levels;\n" + old
assert s.count(old) == 1
s = s.replace(old, new)

old = "         if (!ps5_mipmap_sync_cpu) {\n            ps5_draw_batch_drain_buffer(base);"
new = "         if (mip_stat)\n            ++mip_stat->cpu_levels;\n" + old
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
