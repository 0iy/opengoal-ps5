#!/usr/bin/env python3
"""Driver patch 18 (diagnostic): PS5_NO_DESC_FLUSH=1 skips the per-draw CPU cache flush of the descriptor tables."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_desc_flush_skipped" in s:
    print("already patched"); raise SystemExit
a = "/* A draw may publish the completed private table after its last writer."
helper = """static bool
ps5_desc_flush_skipped(void)
{
   static int skip = -1;
   if (skip < 0)
      skip = getenv("PS5_NO_DESC_FLUSH") != NULL;
   return skip;
}

"""
assert s.count(a) == 1
s = s.replace(a, helper + a)
old = """   if (pending)
      *pending = MAX2(*pending, bytes);
   else
      ps5_flush_gpu_data(data, bytes);"""
new = """   if (ps5_desc_flush_skipped())
      return;
   if (pending)
      *pending = MAX2(*pending, bytes);
   else
      ps5_flush_gpu_data(data, bytes);"""
assert s.count(old) == 1
s = s.replace(old, new)
for n in (0, 1):
    old = f"""   if (descriptor_bytes[{n}])
      ps5_flush_gpu_data(((struct ps5_resource *)context->descriptor_storage[{n}])->data,
                         descriptor_bytes[{n}]);"""
    new = f"""   if (descriptor_bytes[{n}] && !ps5_desc_flush_skipped())
      ps5_flush_gpu_data(((struct ps5_resource *)context->descriptor_storage[{n}])->data,
                         descriptor_bytes[{n}]);"""
    assert s.count(old) == 1, n
    s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
