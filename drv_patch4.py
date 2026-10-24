import os
p = os.path.expanduser('~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c')
s = open(p, encoding='utf-8').read()
def rep(old, new):
    global s
    assert s.count(old) == 1, old[:60]
    s = s.replace(old, new, 1)
# timing + stats for arena allocate
rep('''static bool
ps5_render_arena_allocate(struct ps5_screen *screen,
                          struct ps5_resource *resource, size_t size,
                          size_t alignment)
{''', '''static uint64_t ps5_arena_calls, ps5_arena_cycles, ps5_arena_bytes;
static unsigned ps5_arena_cursor;
static bool ps5_render_arena_allocate_inner(struct ps5_screen *screen,
                          struct ps5_resource *resource, size_t size,
                          size_t alignment);
static bool
ps5_render_arena_allocate(struct ps5_screen *screen,
                          struct ps5_resource *resource, size_t size,
                          size_t alignment)
{
   uint64_t t0 = ps5_my_tsc();
   bool r = ps5_render_arena_allocate_inner(screen, resource, size, alignment);
   ps5_arena_cycles += ps5_my_tsc() - t0;
   ++ps5_arena_calls;
   ps5_arena_bytes += size;
   return r;
}
static bool
ps5_render_arena_allocate_inner(struct ps5_screen *screen,
                          struct ps5_resource *resource, size_t size,
                          size_t alignment)
{''')
# next-fit: two-pass search starting at cursor
rep('''   for (unsigned first = 0;
        first + slots <= PS5_RENDER_ARENA_SLOT_COUNT; ++first) {
      if (screen->render_arena_bitmap[first / 64u] == UINT64_MAX) {
         first |= 63u;
         continue;
      }
      if (first % slot_alignment ||
          !ps5_render_arena_range_is_free(screen, first, slots))
         continue;
      ps5_render_arena_mark(screen, first, slots, true);''', '''   for (unsigned pass = 0; pass < 2; ++pass)
   for (unsigned first = pass ? 0 : ps5_arena_cursor;
        first + slots <= PS5_RENDER_ARENA_SLOT_COUNT &&
        (!pass || first < ps5_arena_cursor + slots); ++first) {
      if (screen->render_arena_bitmap[first / 64u] == UINT64_MAX) {
         first |= 63u;
         continue;
      }
      if (first % slot_alignment ||
          !ps5_render_arena_range_is_free(screen, first, slots))
         continue;
      ps5_arena_cursor = first + slots;
      ps5_render_arena_mark(screen, first, slots, true);''')
# no zeroing of buffers
rep('      memset(resource->data, 0, size);\n#ifdef AGC_RUNTIME_DIAGNOSTICS\n      printf("[ps5-gallium] shared-resource offset',
    '      if (resource->base.target != PIPE_BUFFER)\n         memset(resource->data, 0, size);\n#ifdef AGC_RUNTIME_DIAGNOSTICS\n      printf("[ps5-gallium] shared-resource offset')
# report
rep('   memset(ps5_sec, 0, sizeof ps5_sec);\n   ps5_my_last_print = now;',
    '   printf("[ps5-driver-arena] calls=%llu cycles=%llu bytes=%llu desc_hits=%llu desc_misses=%llu\n", (unsigned long long)ps5_arena_calls, (unsigned long long)ps5_arena_cycles, (unsigned long long)ps5_arena_bytes, (unsigned long long)ps5_my_dh, (unsigned long long)ps5_my_dm);\n   ps5_arena_calls = ps5_arena_cycles = ps5_arena_bytes = 0;\n   memset(ps5_sec, 0, sizeof ps5_sec);\n   ps5_my_last_print = now;')
rep('static uint64_t ps5_sec[8];', 'static uint64_t ps5_sec[8], ps5_my_dh, ps5_my_dm;')
rep('      ++context->descriptor_cache_hits;', '      ++context->descriptor_cache_hits; ++ps5_my_dh;')
rep('   ++context->descriptor_cache_misses;', '   ++context->descriptor_cache_misses; ++ps5_my_dm;')
open(p, 'w', encoding='utf-8').write(s)
print('ok')
