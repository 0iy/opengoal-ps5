#!/usr/bin/env python3
"""Driver patch 32: buffer renaming for arena-backed buffers (all GL buffers live in the shared render arena).
Replaces the direct-memory variant of patch 31: fresh arena slots are taken for the buffer, the old slots are released
when the batch that may still read them has retired."""
import os

P = os.path.expanduser("~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_arena_spare" in s:
    print("already patched")
    raise SystemExit

a = s.index("struct ps5_buffer_spare {")
endmark = "   ++ps5_rename_count;\n   return true;\n}\n"
b = s.index(endmark, a) + len(endmark)
new = r'''struct ps5_arena_spare {
   unsigned first, count;
   uint64_t free_seq;
};
#define PS5_SPARE_MAX 4096u
static struct ps5_arena_spare ps5_spare_retired[PS5_SPARE_MAX];
static unsigned ps5_spare_retired_n;
static struct ps5_screen *ps5_spare_screen;
static unsigned long long ps5_rename_count, ps5_rename_fail, ps5_rename_alloc, ps5_rename_why[8];

void
ps5_driver_rename_stats(unsigned long long *renames, unsigned long long *fails, unsigned long long *allocs)
{
   *renames = ps5_rename_count; *fails = ps5_rename_fail; *allocs = ps5_rename_alloc;
}

void
ps5_driver_rename_why(unsigned long long *w)
{
   for (int i = 0; i < 8; ++i)
      w[i] = ps5_rename_why[i];
}

/* caller holds ps5_deferred_mutex; ps5_completed_sequence just advanced */
static void
ps5_buffer_reclaim_locked(void)
{
   if (!ps5_spare_retired_n || !ps5_spare_screen)
      return;
   simple_mtx_lock(&ps5_spare_screen->resource_mutex);
   for (unsigned i = 0; i < ps5_spare_retired_n;) {
      if (ps5_spare_retired[i].free_seq > ps5_completed_sequence) {
         ++i;
         continue;
      }
      ps5_render_arena_mark(ps5_spare_screen, ps5_spare_retired[i].first, ps5_spare_retired[i].count, false);
      ps5_spare_retired[i] = ps5_spare_retired[--ps5_spare_retired_n];
   }
   simple_mtx_unlock(&ps5_spare_screen->resource_mutex);
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

/* caller holds ps5_deferred_mutex. Gives the buffer fresh arena slots; false leaves it untouched. */
static bool
ps5_buffer_rename_locked(struct ps5_resource *buffer, bool keep_contents)
{
   static int enabled = -1;
   if (enabled < 0)
      enabled = getenv("PS5_NO_BUFFER_RENAME") == NULL;
   if (!enabled || buffer->base.target != PIPE_BUFFER || buffer->external_cpu_access || buffer->gpu_written ||
       !buffer->render_arena_slot_count || buffer->stencil_data || ps5_spare_retired_n >= PS5_SPARE_MAX) {
      ++ps5_rename_fail;
      ps5_rename_why[0] += !enabled; ps5_rename_why[1] += buffer->external_cpu_access; ps5_rename_why[2] += buffer->gpu_written;
      ps5_rename_why[3] += !buffer->render_arena_slot_count; ps5_rename_why[6] += ps5_spare_retired_n >= PS5_SPARE_MAX;
      return false;
   }
   struct ps5_screen *screen = (struct ps5_screen *)buffer->base.screen;
   struct ps5_resource fresh;
   memset(&fresh, 0, sizeof(fresh));
   fresh.base.target = PIPE_BUFFER;
   simple_mtx_lock(&screen->resource_mutex);
   const bool ok = ps5_render_arena_allocate(screen, &fresh, buffer->allocation_size, PS5_DIRECT_ALIGNMENT);
   simple_mtx_unlock(&screen->resource_mutex);
   if (!ok) {
      ++ps5_rename_fail;
      ps5_rename_why[5] += 1;
      return false;
   }
   pipe_resource_reference(&fresh.render_pool_owner, NULL); /* the buffer already owns a reference to the pool */
   if (keep_contents)
      memcpy(fresh.data, buffer->data, buffer->size);
   ps5_spare_screen = screen;
   ps5_spare_retired[ps5_spare_retired_n].first = buffer->render_arena_first_slot;
   ps5_spare_retired[ps5_spare_retired_n].count = buffer->render_arena_slot_count;
   ps5_spare_retired[ps5_spare_retired_n].free_seq = ps5_submitted_sequence + 1;
   ++ps5_spare_retired_n;
   buffer->data = fresh.data;
   buffer->render_arena_first_slot = fresh.render_arena_first_slot;
   buffer->render_arena_slot_count = fresh.render_arena_slot_count;
   buffer->texture_publication_epoch = 0;
   ++ps5_rename_count;
   return true;
}
'''
s = s[:a] + new + s[b:]
# the counters/why declared by patch 31 and the earlier hack are now part of the block above; drop the duplicates
dup = "static unsigned long long ps5_rename_count, ps5_rename_fail, ps5_rename_alloc, ps5_rename_why[8];\nvoid ps5_driver_rename_why(unsigned long long *w) { for (int i = 0; i < 8; ++i) w[i] = ps5_rename_why[i]; }\n"
if dup in s:
    s = s.replace(dup, "")
open(P, "w", encoding="utf-8").write(s)
print("ok")
