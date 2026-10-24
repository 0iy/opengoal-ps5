#!/usr/bin/env python3
"""Driver patch 19: flush only the written part of the 4 KB descriptor bank (trailing all-zero 64-byte lines are skipped)
plus the copied-constant area, instead of the whole prefix on every draw. PS5_FULL_DESC_FLUSH=1 restores the old behaviour."""
import os
P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_flush_descriptor_table" in s:
    print("already patched"); raise SystemExit
a = "/* A draw may publish the completed private table after its last writer."
helper = """static void
ps5_flush_descriptor_table(const void *data, size_t bytes)
{
   static int full = -1;
   if (full < 0)
      full = getenv("PS5_FULL_DESC_FLUSH") != NULL;
   const size_t bank = MIN2(bytes, (size_t)PS5_CONSTANT_DATA_OFFSET);
   size_t used = bank;
   if (!full) {
      const uint64_t *w = data;
      while (used >= 64) {
         const uint64_t *line = w + (used - 64) / 8;
         if (line[0] | line[1] | line[2] | line[3] | line[4] | line[5] | line[6] | line[7])
            break;
         used -= 64;
      }
   }
   ps5_flush_gpu_data(data, used ? used : bank ? 64 : 0);
   if (bytes > bank)
      ps5_flush_gpu_data((const char *)data + bank, bytes - bank);
}

"""
assert s.count(a) == 1
s = s.replace(a, helper + a)
old = """   if (pending)
      *pending = MAX2(*pending, bytes);
   else
      ps5_flush_gpu_data(data, bytes);"""
new = """   if (pending)
      *pending = MAX2(*pending, bytes);
   else
      ps5_flush_descriptor_table(data, bytes);"""
assert s.count(old) == 1
s = s.replace(old, new)
for n in (0, 1):
    old = f"""   if (descriptor_bytes[{n}] && !ps5_desc_flush_skipped())
      ps5_flush_gpu_data(((struct ps5_resource *)context->descriptor_storage[{n}])->data,
                         descriptor_bytes[{n}]);"""
    new = f"""   if (descriptor_bytes[{n}] && !ps5_desc_flush_skipped())
      ps5_flush_descriptor_table(((struct ps5_resource *)context->descriptor_storage[{n}])->data,
                                 descriptor_bytes[{n}]);"""
    assert s.count(old) == 1, n
    s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
