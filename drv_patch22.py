#!/usr/bin/env python3
"""Driver patch 22 (experiment): PS5_BUFFER_MEM_TYPE=<n> allocates PIPE_BUFFER resources (vertex/index/uniform/descriptor
storage) with that SceKernel direct memory type instead of 12. GPU vertex/index fetch from CPU-coherent memory may be slow."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_resource_memory_type" in s:
    print("already patched"); raise SystemExit
anchor = "struct ps5_batch_flush_cache {"
helper = """static int
ps5_resource_memory_type(const struct pipe_resource *templ)
{
   static int buffer_type = -2;
   if (buffer_type == -2) {
      const char *e = getenv("PS5_BUFFER_MEM_TYPE");
      buffer_type = e ? atoi(e) : -1;
   }
   return templ->target == PIPE_BUFFER && buffer_type >= 0 ? buffer_type : PS5_DIRECT_MEMORY_TYPE;
}

"""
assert s.count(anchor) == 1
s = s.replace(anchor, helper + anchor)
old = """   allocation_status = sceKernelAllocateDirectMemory(
      0, direct_limit, allocation_size, allocation_alignment,
      PS5_DIRECT_MEMORY_TYPE, &resource->direct_start);"""
new = """   allocation_status = sceKernelAllocateDirectMemory(
      0, direct_limit, allocation_size, allocation_alignment,
      ps5_resource_memory_type(templ), &resource->direct_start);"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
