#!/usr/bin/env python3
"""Driver patch 31: buffer renaming.

A CPU write (glBufferSubData / glBufferData) to a buffer that queued draws still read used to submit the batch and wait
for the GPU (ps5_draw_batch_drain_buffer): ~135 times per frame in Jak 3, 13 ms of the 35 ms frame. Now the buffer gets
fresh storage (copy of the old contents unless the whole buffer is replaced); the old storage stays alive until the batch
that may read it has retired, then goes to a reuse pool. PS5_NO_BUFFER_RENAME=1 restores the old behaviour."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_buffer_rename" in s:
    print("already patched")
    raise SystemExit

# 1. machinery right after the sequence counters (before the retire function that must call the reclaim hook)
anchor = "static uint64_t ps5_submitted_sequence, ps5_completed_sequence;\n"
assert s.count(anchor) == 1
code = r'''
static bool ps5_deferred_batch_overlaps(const struct ps5_deferred_batch *batch, const struct ps5_resource *buffer);

struct ps5_buffer_spare {
   uint8_t *data;
   int64_t direct;
   size_t alloc;
   uint64_t free_seq;
};
#define PS5_SPARE_MAX 1024u
#define PS5_SPARE_READY_BYTES (96u << 20)
static struct ps5_buffer_spare ps5_spare_retired[PS5_SPARE_MAX], ps5_spare_ready[PS5_SPARE_MAX];
static unsigned ps5_spare_retired_n, ps5_spare_ready_n;
static size_t ps5_spare_ready_bytes;
static unsigned long long ps5_rename_count, ps5_rename_fail, ps5_rename_alloc;

void
ps5_driver_rename_stats(unsigned long long *renames, unsigned long long *fails, unsigned long long *allocs)
{
   *renames = ps5_rename_count; *fails = ps5_rename_fail; *allocs = ps5_rename_alloc;
}

/* caller holds ps5_deferred_mutex; ps5_completed_sequence just advanced */
static void
ps5_buffer_reclaim_locked(void)
{
   for (unsigned i = 0; i < ps5_spare_retired_n;) {
      if (ps5_spare_retired[i].free_seq > ps5_completed_sequence) {
         ++i;
         continue;
      }
      struct ps5_buffer_spare spare = ps5_spare_retired[i];
      ps5_spare_retired[i] = ps5_spare_retired[--ps5_spare_retired_n];
      if (ps5_spare_ready_n < PS5_SPARE_MAX && ps5_spare_ready_bytes + spare.alloc <= PS5_SPARE_READY_BYTES) {
         ps5_spare_ready[ps5_spare_ready_n++] = spare;
         ps5_spare_ready_bytes += spare.alloc;
      } else {
         ps5_release_resource_memory(spare.data, spare.alloc, spare.direct);
      }
   }
}

static bool
ps5_buffer_busy_locked(const struct ps5_resource *buffer)
{
   if (ps5_deferred_batch_overlaps(&ps5_deferred, buffer))
      return true;
   for (unsigned i = 0; i < ps5_inflight_count; ++i)
      if (ps5_deferred_batch_overlaps(&ps5_inflight[(ps5_inflight_head + i) % PS5_INFLIGHT_BATCH_CAPACITY], buffer))
         return true;
   return false;
}

/* caller holds ps5_deferred_mutex. Gives the buffer fresh storage; false leaves it untouched. */
static bool
ps5_buffer_rename_locked(struct ps5_resource *buffer, bool keep_contents)
{
   static int enabled = -1;
   if (enabled < 0)
      enabled = getenv("PS5_NO_BUFFER_RENAME") == NULL;
   if (!enabled || buffer->base.target != PIPE_BUFFER || buffer->external_cpu_access || buffer->gpu_written ||
       buffer->direct_start < 0 || buffer->render_arena_slot_count || buffer->stencil_data ||
       buffer->allocation_size > (2u << 20) || ps5_spare_retired_n >= PS5_SPARE_MAX) {
      ++ps5_rename_fail;
      return false;
   }
   struct ps5_buffer_spare fresh = {0};
   bool have = false;
   for (unsigned i = 0; i < ps5_spare_ready_n; ++i) {
      if (ps5_spare_ready[i].alloc == buffer->allocation_size) {
         fresh = ps5_spare_ready[i];
         ps5_spare_ready[i] = ps5_spare_ready[--ps5_spare_ready_n];
         ps5_spare_ready_bytes -= fresh.alloc;
         have = true;
         break;
      }
   }
   if (!have) {
      fresh.alloc = buffer->allocation_size;
      if (sceKernelAllocateDirectMemory(0, sceKernelGetDirectMemorySize(), fresh.alloc, PS5_DIRECT_ALIGNMENT,
                                        ps5_resource_memory_type(&buffer->base), &fresh.direct) != 0) {
         ++ps5_rename_fail;
         return false;
      }
      if (sceKernelMapDirectMemory((void **)&fresh.data, fresh.alloc, PS5_MAP_PROTECTION, 0, fresh.direct,
                                   PS5_DIRECT_ALIGNMENT) != 0 || !fresh.data) {
         sceKernelReleaseDirectMemory(fresh.direct, fresh.alloc);
         ++ps5_rename_fail;
         return false;
      }
      ++ps5_rename_alloc;
   }
   if (keep_contents)
      memcpy(fresh.data, buffer->data, buffer->size);
   struct ps5_buffer_spare old = {buffer->data, buffer->direct_start, buffer->allocation_size, ps5_submitted_sequence + 1};
   ps5_spare_retired[ps5_spare_retired_n++] = old;
   buffer->data = fresh.data;
   buffer->direct_start = fresh.direct;
   buffer->texture_publication_epoch = 0;
   ++ps5_rename_count;
   return true;
}
'''
s = s.replace(anchor, anchor + code)

# 2. reclaim hook when a batch retires
old = "   ps5_completed_sequence = batch->sequence;\n   ps5_deferred_batch_release(batch);\n"
new = "   ps5_completed_sequence = batch->sequence;\n   ps5_deferred_batch_release(batch);\n   ps5_buffer_reclaim_locked();\n"
assert s.count(old) == 1
s = s.replace(old, new)

# 3. ps5_buffer_subdata: rename instead of draining
old = """   if (!(usage & PIPE_MAP_UNSYNCHRONIZED))
      ps5_draw_batch_drain_buffer(resource);
   else
      ps5_invalidate_gpu_writes(buffer);
   memcpy(buffer->data + offset, data, size);
   /* UNSYNCHRONIZED writes may fill previously unused holes inside an already
    * published bounding range. Publish at the write, even without a drain. */
   ps5_flush_gpu_data(buffer->data + offset, size);"""
new = """   bool renamed = false;
   if (!(usage & PIPE_MAP_UNSYNCHRONIZED)) {
      simple_mtx_lock(&ps5_deferred_mutex);
      if (ps5_buffer_busy_locked(buffer))
         renamed = ps5_buffer_rename_locked(buffer, !(offset == 0 && size == buffer->size));
      simple_mtx_unlock(&ps5_deferred_mutex);
      if (!renamed)
         ps5_draw_batch_drain_buffer(resource);
   } else
      ps5_invalidate_gpu_writes(buffer);
   memcpy(buffer->data + offset, data, size);
   /* UNSYNCHRONIZED writes may fill previously unused holes inside an already
    * published bounding range. Publish at the write, even without a drain. */
   ps5_flush_gpu_data(buffer->data + (renamed ? 0 : offset), renamed ? buffer->size : size);"""
assert s.count(old) == 1
s = s.replace(old, new)
open(P, "w", encoding="utf-8").write(s)
print("ok")
