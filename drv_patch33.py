#!/usr/bin/env python3
"""Driver patch 33: glGenerateMipmap without GPU waits.

The old path drained the queued batch (GPU wait) before it started and again after every GPU blit level, and printed a
line per call. Jak 2/3 regenerate the mip chain of ~10 animated textures per frame (TextureAnimator), 1 ms each.
Now: no leading drain; the GPU blit chain runs queue-ordered; only a CPU-filtered level synchronises, once, when it
needs the data. All power-of-two levels use GPU blits (PS5_MIPMAP_GPU_MIN_PIXELS, default 4).
PS5_MIPMAP_OLD=1 restores the old behaviour."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_mipmap_sync_cpu" in s:
    print("already patched")
    raise SystemExit

head = """   struct ps5_resource *resource = (struct ps5_resource *)base;
   unsigned format_size;
   bool depth;
   unsigned components;

   ps5_draw_batch_drain_buffer(base);
   if (!PS5_ENABLE_TEXTURE_MIPMAP_CANDIDATE || !resource ||"""
new_head = """   struct ps5_resource *resource = (struct ps5_resource *)base;
   unsigned format_size;
   bool depth;
   unsigned components;
   static int mip_old = -1, mip_min_pixels = -1;
   if (mip_old < 0) {
      const char *e = getenv("PS5_MIPMAP_OLD"), *m = getenv("PS5_MIPMAP_GPU_MIN_PIXELS");
      mip_old = e != NULL;
      mip_min_pixels = m ? atoi(m) : 4;
   }
   bool ps5_mipmap_sync_cpu = false; /* true once the CPU may read what the GPU wrote */
   if (mip_old)
      ps5_draw_batch_drain_buffer(base);
   if (!PS5_ENABLE_TEXTURE_MIPMAP_CANDIDATE || !resource ||"""
assert s.count(head) == 1
s = s.replace(head, new_head)

old = """   ps5_flush_gpu_data(resource->data, resource->size);
   for (unsigned level = base_level + 1; level <= last_level; ++level) {"""
new = """   if (mip_old) {
      ps5_flush_gpu_data(resource->data, resource->size);
      ps5_mipmap_sync_cpu = true;
   }
   for (unsigned level = base_level + 1; level <= last_level; ++level) {"""
assert s.count(old) == 1
s = s.replace(old, new)

old = "             (uint64_t)dst_width * dst_height >= PS5_GPU_BLIT_MIN_PIXELS) {\n            struct pipe_blit_info blit = {0};"
new = "             (uint64_t)dst_width * dst_height >= (mip_old ? PS5_GPU_BLIT_MIN_PIXELS : (unsigned)mip_min_pixels)) {\n            struct pipe_blit_info blit = {0};"
assert s.count(old) == 1
s = s.replace(old, new)

old = """               /* A later mip can fall back to CPU filtering of this output. */
               ps5_draw_batch_drain_buffer(base);
               ps5_flush_gpu_data(resource->data, resource->size);
               continue;"""
new = """               /* A later mip can fall back to CPU filtering of this output: it synchronises then (below). */
               if (mip_old) {
                  ps5_draw_batch_drain_buffer(base);
                  ps5_flush_gpu_data(resource->data, resource->size);
               } else
                  ps5_mipmap_sync_cpu = false;
               continue;"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """         unsigned src_z0 = resource->base.target == PIPE_TEXTURE_3D
                              ? (unsigned)((uint64_t)layer * src_depth /
                                           dst_depth)
                              : layer;"""
new = """         if (!ps5_mipmap_sync_cpu) {
            ps5_draw_batch_drain_buffer(base);
            ps5_flush_gpu_data(resource->data, resource->size);
            ps5_mipmap_sync_cpu = true;
         }
         unsigned src_z0 = resource->base.target == PIPE_TEXTURE_3D
                              ? (unsigned)((uint64_t)layer * src_depth /
                                           dst_depth)
                              : layer;"""
assert s.count(old) == 1
s = s.replace(old, new)

old = """   ps5_flush_gpu_data(resource->data, resource->size);
   printf("[ps5-gallium] generate-mipmap format=%u levels=%u-%u layers=%u-%u\\n",
          format, base_level, last_level, first_layer, last_layer);
   return true;"""
new = """   if (ps5_mipmap_sync_cpu)
      ps5_flush_gpu_data(resource->data, resource->size);
   return true;"""
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
