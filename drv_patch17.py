#!/usr/bin/env python3
"""Driver patch 17: with PS5_NO_BUFFER_FLUSH set, skip the CPU cache flush when a tiled render target / depth target
is sampled as a texture: the GPU wrote it and the CPU never touches it (no staging, no external CPU access)."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_gpu_owned_target" in s:
    print("already patched"); raise SystemExit
anchor = "struct ps5_batch_flush_cache {"
helper = """static bool
ps5_gpu_owned_target(const struct ps5_resource *texture)
{
   static int skip = -1;
   if (skip < 0)
      skip = getenv("PS5_NO_BUFFER_FLUSH") != NULL;
   return skip && !texture->external_cpu_access && !texture->depth_staging_size;
}

"""
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor)
old = """         ps5_flush_texture_backing(
            slot == 1 && !merged_geometry ? flush_cache : NULL, 2 + unit,
            texture,
            !multisampled && texture->base.target == PIPE_TEXTURE_2D"""
new = """         if (!ps5_gpu_owned_target(texture))
         ps5_flush_texture_backing(
            slot == 1 && !merged_geometry ? flush_cache : NULL, 2 + unit,
            texture,
            !multisampled && texture->base.target == PIPE_TEXTURE_2D"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
