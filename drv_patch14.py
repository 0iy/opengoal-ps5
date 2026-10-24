#!/usr/bin/env python3
"""Driver patch 14: optionally skip the per-draw CPU cache flush of vertex and index buffer ranges (PS5_NO_BUFFER_FLUSH=1).
Buffer writes are published when they happen (buffer_subdata, transfer flush/unmap); the per-draw flush re-published
static data 30-60 MB per frame. GPU-written and persistently mapped buffers keep the old behaviour."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_buffer_flush_needed" in s:
    print("already patched")
    raise SystemExit

helper_anchor = """struct ps5_batch_flush_cache {"""
helper = """static bool
ps5_buffer_flush_needed(const struct ps5_resource *resource)
{
   static int skip = -1;
   if (skip < 0)
      skip = getenv("PS5_NO_BUFFER_FLUSH") != NULL;
   return !skip || resource->external_cpu_access || resource->gpu_written ||
          resource->base.target != PIPE_BUFFER;
}

"""
assert s.count(helper_anchor) == 1
s = s.replace(helper_anchor, helper + helper_anchor)

v_old = """         ps5_flush_batch_backing(
            vertex_resource->external_cpu_access ? NULL : flush_cache,
            2 + PS5_MAX_TEXTURE_UNITS + binding,
            (const void *)(vertex_address + binding_begin[binding]),
            binding_bytes[binding] - binding_begin[binding]);"""
v_new = """         if (ps5_buffer_flush_needed(vertex_resource))
            ps5_flush_batch_backing(
               vertex_resource->external_cpu_access ? NULL : flush_cache,
               2 + PS5_MAX_TEXTURE_UNITS + binding,
               (const void *)(vertex_address + binding_begin[binding]),
               binding_bytes[binding] - binding_begin[binding]);"""
assert s.count(v_old) == 1, s.count(v_old)
s = s.replace(v_old, v_new)

i_old = """      ps5_flush_batch_backing(
         index_resource->external_cpu_access ? NULL : flush_cache,
         2 + PS5_MAX_TEXTURE_UNITS + PIPE_MAX_ATTRIBS,
         index_resource->data + index_offset,
         (size_t)draws[0].count * info->index_size);"""
i_new = """      if (ps5_buffer_flush_needed(index_resource))
         ps5_flush_batch_backing(
            index_resource->external_cpu_access ? NULL : flush_cache,
            2 + PS5_MAX_TEXTURE_UNITS + PIPE_MAX_ATTRIBS,
            index_resource->data + index_offset,
            (size_t)draws[0].count * info->index_size);"""
assert s.count(i_old) == 1, s.count(i_old)
s = s.replace(i_old, i_new)
open(P, "w", encoding="utf-8").write(s)
print("buffer flush toggle added")
