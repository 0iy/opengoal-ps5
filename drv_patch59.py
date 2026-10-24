#!/usr/bin/env python3
"""Driver patch 59 (agent mipcost): glGenerateMipmap cost.  Run:  PS5_SRC=<src root> python3 drv_patch59.py
(default root ~/gl/src/ps5-opengl/src).  Idempotent; every replacement asserted.

Always on (free while the tracer is off): trace events
  137 ps5_generate_mipmap (arg = 1 ok)           138 ps5_blit_gpu_color (arg = 1 took the GPU path)
  139 util_blitter_blit_generic only             140 lazy flush (arg = levels generated), includes 137-like work
Env switches (default 0 = current behaviour), PS5_MIPFAST is a bit mask:
  1  lazy mips: glGenerateMipmap on an eligible GPU-blit texture only records (base,last) in the resource;
     the blit chain runs when the texture is first bound to a sampler in a draw, or touched by transfer_map
     (read, or level > 0), blit, resource_copy_region, or attached to a framebuffer at level > 0.  A newer request
     for a still-pending texture replaces the older one (that chain is never run).
  2  tail skip: stop the chain once both dimensions are <= PS5_MIPFAST_TAIL (default 2) for textures >= 32x32
     (levels 2x2 and 1x1 stay stale).
New static data: none except function-local `static int` scalars (two, in ps5_mipfast_env).  New struct fields:
3 bytes in struct ps5_resource (calloc'd, so zero)."""
import os

ROOT = os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src"))
P = os.path.join(ROOT, "gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "PS5_MIPFAST" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:80])
    s = s.replace(old, new)


# 1. resource fields + helpers (after the struct)
rep("""   unsigned render_arena_first_slot;
   unsigned render_arena_slot_count;
};
""", """   unsigned render_arena_first_slot;
   unsigned render_arena_slot_count;
   uint8_t mip_lazy, mip_lazy_base, mip_lazy_last; /* PS5_MIPFAST&1: mip chain requested, not generated yet */
};

static void ps5_mip_lazy_flush(struct ps5_context *context, struct ps5_resource *resource);
static inline int
ps5_mipfast_env(int which) /* 0: PS5_MIPFAST bit mask, 1: PS5_MIPFAST_TAIL */
{
   static int bits = -1, tail = -1;
   if (bits < 0) {
      const char *e = getenv("PS5_MIPFAST"), *t = getenv("PS5_MIPFAST_TAIL");
      bits = e ? (int)strtol(e, NULL, 0) : 0;
      tail = t ? atoi(t) : 2;
   }
   return which ? tail : bits;
}
#define PS5_MIPEV_BEGIN(t0) const int64_t t0 = ps5_driver_trace_hook ? os_time_get_nano() : 0
#define PS5_MIPEV_END(ev, t0, a) do { if (t0) ps5_driver_trace_hook((ev), (unsigned long long)(t0), \\
   (unsigned long long)(os_time_get_nano() - (t0)), (unsigned long long)(a)); } while (0)
""")

# 2. timing wrapper around ps5_blit_gpu_color
rep("""static bool
ps5_blit_gpu_color(struct ps5_context *context, const struct pipe_blit_info *info)
{
""", """static bool ps5_blit_gpu_color_inner(struct ps5_context *context, const struct pipe_blit_info *info);
static bool
ps5_blit_gpu_color(struct ps5_context *context, const struct pipe_blit_info *info)
{
   PS5_MIPEV_BEGIN(t0);
   const bool r = ps5_blit_gpu_color_inner(context, info);
   PS5_MIPEV_END(138, t0, r);
   return r;
}

static bool
ps5_blit_gpu_color_inner(struct ps5_context *context, const struct pipe_blit_info *info)
{
""")

# 3. blit_generic timing
rep("""   context->deferred_blitter_draw = true;
   const struct pipe_scissor_state clip = {""", """   PS5_MIPEV_BEGIN(bg_t0);
   context->deferred_blitter_draw = true;
   const struct pipe_scissor_state clip = {""")
rep("""   context->deferred_blitter_draw = false;
   pipe_sampler_view_reference(&view, NULL);
""", """   context->deferred_blitter_draw = false;
   PS5_MIPEV_END(139, bg_t0, 0);
   pipe_sampler_view_reference(&view, NULL);
""")

# 4. ps5_blit entry: pending mips of source / destination
rep("""   /* u_blitter suspends query accounting; deferred slots retain that state. */
   if (ps5_blit_gpu_color(ps5, info))
      return;
""", """   if ((ps5_mipfast_env(0) & 1) && info && !(ps5->blitter && ps5->blitter->running)) {
      ps5_mip_lazy_flush(ps5, (struct ps5_resource *)info->src.resource);
      ps5_mip_lazy_flush(ps5, (struct ps5_resource *)info->dst.resource);
   }
   /* u_blitter suspends query accounting; deferred slots retain that state. */
   if (ps5_blit_gpu_color(ps5, info))
      return;
""")

# 5. generate_mipmap: wrapper (lazy request) + impl (old body)
rep("""static bool
ps5_generate_mipmap(struct pipe_context *context,
                    struct pipe_resource *base,
                    enum pipe_format format,
                    unsigned base_level, unsigned last_level,
                    unsigned first_layer, unsigned last_layer)
{
""", """static bool ps5_generate_mipmap_impl(struct pipe_context *context, struct pipe_resource *base, enum pipe_format format,
                                     unsigned base_level, unsigned last_level, unsigned first_layer,
                                     unsigned last_layer, bool counted);

/* Only requests the GPU blit chain would fully handle (exact halvings, single layer 2D, render-target colour). */
static bool
ps5_mip_lazy_eligible(const struct ps5_resource *r, enum pipe_format format, unsigned base_level, unsigned last_level,
                      unsigned first_layer, unsigned last_layer)
{
   if (!r || r->base.target != PIPE_TEXTURE_2D || format != r->base.format || first_layer || last_layer ||
       base_level >= last_level || last_level > r->base.last_level || last_level >= 16 ||
       last_level >= ARRAY_SIZE(r->level_stride) || !r->data || r->base.nr_samples > 1 ||
       !(r->base.bind & PIPE_BIND_RENDER_TARGET) || (r->base.bind & PIPE_BIND_DISPLAY_TARGET) ||
       !PS5_ENABLE_TEXTURE_MIPMAP_CANDIDATE || !ps5_linear_sampled_layout(&r->base) ||
       (format != PIPE_FORMAT_R8G8B8A8_UNORM && format != PIPE_FORMAT_R8_UNORM &&
        format != PIPE_FORMAT_R8G8_UNORM && format != PIPE_FORMAT_R16G16B16A16_FLOAT))
      return false;
   for (unsigned level = base_level + 1; level <= last_level; ++level) {
      const unsigned sw = MAX2(r->base.width0 >> (level - 1), 1u), sh = MAX2(r->base.height0 >> (level - 1), 1u);
      const unsigned dw = MAX2(r->base.width0 >> level, 1u), dh = MAX2(r->base.height0 >> level, 1u);
      if (!((sw == 2u * dw || sw == 1) && (sh == 2u * dh || sh == 1)))
         return false;
   }
   return true;
}

static void
ps5_mip_lazy_flush(struct ps5_context *context, struct ps5_resource *resource)
{
   if (!resource || !resource->mip_lazy)
      return;
   const unsigned base_level = resource->mip_lazy_base, last_level = resource->mip_lazy_last;
   resource->mip_lazy = 0; /* clear first: the blits below sample and render this resource */
   PS5_MIPEV_BEGIN(t0);
   ps5_generate_mipmap_impl(&context->base, &resource->base, resource->base.format, base_level, last_level, 0, 0, true);
   PS5_MIPEV_END(140, t0, last_level - base_level);
}

static bool
ps5_generate_mipmap(struct pipe_context *context,
                    struct pipe_resource *base,
                    enum pipe_format format,
                    unsigned base_level, unsigned last_level,
                    unsigned first_layer, unsigned last_layer)
{
   struct ps5_resource *resource = (struct ps5_resource *)base;
   PS5_MIPEV_BEGIN(t0);
   bool ok;
   if ((ps5_mipfast_env(0) & 1) &&
       ps5_mip_lazy_eligible(resource, format, base_level, last_level, first_layer, last_layer)) {
      struct ps5_mip_stat *stat = ps5_mip_stat_for(base, base_level, last_level);
      if (stat)
         ++stat->n;
      /* A pending chain from another base level is run now: merging could overwrite explicitly set levels. */
      if (resource->mip_lazy && resource->mip_lazy_base != base_level)
         ps5_mip_lazy_flush((struct ps5_context *)context, resource);
      resource->mip_lazy_base = (uint8_t)base_level;
      resource->mip_lazy_last = (uint8_t)MAX2(last_level, resource->mip_lazy ? resource->mip_lazy_last : 0u);
      resource->mip_lazy = 1;
      ok = true;
   } else {
      ps5_mip_lazy_flush((struct ps5_context *)context, resource);
      ok = ps5_generate_mipmap_impl(context, base, format, base_level, last_level, first_layer, last_layer, false);
   }
   PS5_MIPEV_END(137, t0, ok);
   return ok;
}

static bool
ps5_generate_mipmap_impl(struct pipe_context *context,
                         struct pipe_resource *base,
                         enum pipe_format format,
                         unsigned base_level, unsigned last_level,
                         unsigned first_layer, unsigned last_layer,
                         bool counted)
{
""")
rep("""   if (mip_stat)
      ++mip_stat->n;
   if (mip_old)""", """   if (mip_stat && !counted)
      ++mip_stat->n;
   if (mip_old)""")
rep("""      unsigned dst_height = MAX2(resource->base.height0 >> level, 1u);
      unsigned dst_first = first_layer;
""", """      unsigned dst_height = MAX2(resource->base.height0 >> level, 1u);
      if ((ps5_mipfast_env(0) & 2) && resource->base.width0 >= 32 && resource->base.height0 >= 32 &&
          dst_width <= (unsigned)ps5_mipfast_env(1) && dst_height <= (unsigned)ps5_mipfast_env(1))
         break; /* tail levels stay stale */
      unsigned dst_first = first_layer;
""")

# 6. transfer_map: reads and level > 0 writes need the mips
rep("""   (void)context;
   if (!out_transfer)
      return NULL;
   *out_transfer = NULL;
""", """   if (resource && resource->mip_lazy && (level || (usage & PIPE_MAP_READ)))
      ps5_mip_lazy_flush((struct ps5_context *)context, resource);
   (void)context;
   if (!out_transfer)
      return NULL;
   *out_transfer = NULL;
""")

# 7. resource_copy_region
rep("""{
   if (ps5_copy_identical_image(dst, dst_level, dst_x, dst_y, dst_z, src, src_level, src_box))
      return;
""", """{
   if (ps5_mipfast_env(0) & 1) {
      ps5_mip_lazy_flush((struct ps5_context *)base, (struct ps5_resource *)src);
      if (dst_level)
         ps5_mip_lazy_flush((struct ps5_context *)base, (struct ps5_resource *)dst);
   }
   if (ps5_copy_identical_image(dst, dst_level, dst_x, dst_y, dst_z, src, src_level, src_box))
      return;
""")

# 8. set_framebuffer_state: attaching a mip level > 0 of a pending texture
rep("""   struct ps5_context *context = (struct ps5_context *)base;
   unsigned max_targets = PS5_ENABLE_MRT_CANDIDATE
                             ? PS5_MAX_RENDER_TARGETS : 1;
""", """   struct ps5_context *context = (struct ps5_context *)base;
   unsigned max_targets = PS5_ENABLE_MRT_CANDIDATE
                             ? PS5_MAX_RENDER_TARGETS : 1;
   if ((ps5_mipfast_env(0) & 1) && framebuffer && !(context->blitter && context->blitter->running)) {
      for (unsigned i = 0; i < framebuffer->nr_cbufs && i < PIPE_MAX_COLOR_BUFS; ++i)
         if (framebuffer->cbufs[i].texture && framebuffer->cbufs[i].level)
            ps5_mip_lazy_flush(context, (struct ps5_resource *)framebuffer->cbufs[i].texture);
      if (framebuffer->zsbuf.texture && framebuffer->zsbuf.level)
         ps5_mip_lazy_flush(context, (struct ps5_resource *)framebuffer->zsbuf.texture);
   }
""")

# 9. draw: textures bound for sampling need their mips (fragment and vertex stage only)
rep("""   if (!ps5_driver_trace_hook) {
      ps5_draw_vbo_reported(base, info, drawid_offset, indirect, draws, num_draws);
      return;
   }
""", """   if ((ps5_mipfast_env(0) & 1) && !(((struct ps5_context *)base)->blitter && ((struct ps5_context *)base)->blitter->running)) {
      struct ps5_context *mc = (struct ps5_context *)base;
      for (unsigned stage = 0; stage < 2; ++stage)
         for (unsigned unit = 0; unit < PS5_MAX_TEXTURE_UNITS; ++unit)
            if (mc->sampler_views[stage][unit] && mc->sampler_views[stage][unit]->texture)
               ps5_mip_lazy_flush(mc, (struct ps5_resource *)mc->sampler_views[stage][unit]->texture);
   }
   if (!ps5_driver_trace_hook) {
      ps5_draw_vbo_reported(base, info, drawid_offset, indirect, draws, num_draws);
      return;
   }
""")

open(P, "w", encoding="utf-8").write(s)
print("ok")
