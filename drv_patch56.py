#!/usr/bin/env python3
"""Driver patch 56 (drawcost): env-switchable per-draw CPU savings in ps5_screen.c. Root: $PS5_SRC (default ~/gl/src/ps5-opengl/src).

All behaviour is off by default. One env var PS5_DRAWCOST (integer, bit mask; shim config file name proposal: drawcost.txt):
  1  encode only viewport/scissor[0] in ps5_encode_graphics_state (PS5_ENABLE_VIEWPORT_ARRAY_CANDIDATE is 0: slots 1..15 are never read)
  2  descriptor-table flushes in ps5_draw_vbo_locked use clflushopt without a trailing mfence each; one mfence before the job hand-over
  4  do not printf "multi-draw-batched" per glMultiDrawElements call
Always on when a trace is armed (ps5_driver_trace_hook set, no env needed): trace event 130 per draw, see docs/agent_drawcost.md.
New static data: one function-local `static int` in ps5_dc_flags() and one in ps5_dc_defer_fence(). No arrays.
"""
import os

P = os.path.join(os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src")), "gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "PS5_DRAWCOST" in s:
    print("already patched")
    raise SystemExit


def rep(old, new):
    global s
    assert s.count(old) == 1, (s.count(old), old[:80])
    s = s.replace(old, new)


# 1. flag helper + viewport loop bound
rep("static bool\nps5_encode_graphics_state(const struct ps5_context *context,\n",
    """/* PS5_DRAWCOST bit mask, read once. */
static unsigned
ps5_dc_flags(void)
{
   static int v = -1;
   if (v < 0) {
      const char *e = getenv("PS5_DRAWCOST");
      v = e ? (int)strtol(e, NULL, 0) : 0;
   }
   return (unsigned)v;
}

static bool
ps5_encode_graphics_state(const struct ps5_context *context,
""")
rep("   for (viewport_index = 0; viewport_index < PS5_MAX_VIEWPORTS;\n        ++viewport_index) {\n      const unsigned source =",
    "   for (viewport_index = 0;\n        viewport_index < ((PS5_ENABLE_VIEWPORT_ARRAY_CANDIDATE || !(ps5_dc_flags() & 1u))\n                          ? PS5_MAX_VIEWPORTS : 1u);\n        ++viewport_index) {\n      const unsigned source =")

# 2. flush without per-call fence
rep("""static void
ps5_flush_descriptor_table(const void *data, size_t bytes)
{
""", """__attribute__((target("clflushopt"))) static void
ps5_clflushopt_nofence(const void *address, size_t bytes)
{
   uintptr_t p = (uintptr_t)address & ~(uintptr_t)63;
   const uintptr_t end = (uintptr_t)address + bytes;
   for (; p < end; p += 64)
      __builtin_ia32_clflushopt((void *)p);
}

/* PS5_DRAWCOST bit 2 and the CPU has CLFLUSHOPT (same cpuid test as ps5_fast_flush). */
static bool
ps5_dc_defer_fence(void)
{
   static int opt = -1;
   if (!(ps5_dc_flags() & 2u))
      return false;
   if (opt < 0) {
      unsigned a = 7, b = 0, c = 0, d = 0;
      __asm__ volatile("cpuid" : "+a"(a), "=b"(b), "+c"(c), "=d"(d));
      opt = (b & (1u << 23)) ? 1 : 0;
   }
   return opt;
}

/* Same bookkeeping as ps5_flush_gpu_data, but the ordering fence is left to ps5_flush_fence_dc(). */
static void
ps5_flush_gpu_data_dc(const void *address, size_t bytes)
{
   if (!bytes)
      return;
   if (!ps5_dc_defer_fence()) {
      ps5_flush_gpu_data(address, bytes);
      return;
   }
   __atomic_fetch_add(&ps5_flush_total_calls, 1, __ATOMIC_RELAXED);
   __atomic_fetch_add(&ps5_flush_total_bytes, bytes, __ATOMIC_RELAXED);
   ps5_clflushopt_nofence(address, bytes);
}

static void
ps5_flush_fence_dc(void)
{
   if (ps5_dc_defer_fence())
      __builtin_ia32_mfence();
}

static void
ps5_flush_descriptor_table_ex(const void *data, size_t bytes, bool dc)
{
""")
rep("""   ps5_flush_gpu_data(data, used ? used : bank ? 64 : 0);
   if (bytes > bank)
      ps5_flush_gpu_data((const char *)data + bank, bytes - bank);
}
""", """   if (dc) {
      ps5_flush_gpu_data_dc(data, used ? used : bank ? 64 : 0);
      if (bytes > bank)
         ps5_flush_gpu_data_dc((const char *)data + bank, bytes - bank);
      return;
   }
   ps5_flush_gpu_data(data, used ? used : bank ? 64 : 0);
   if (bytes > bank)
      ps5_flush_gpu_data((const char *)data + bank, bytes - bank);
}

static void
ps5_flush_descriptor_table(const void *data, size_t bytes)
{
   ps5_flush_descriptor_table_ex(data, bytes, false);
}
""")
rep("""      ps5_flush_gpu_data(descriptor_resource->data,
                         descriptor_index * 16);""",
    """      ps5_flush_gpu_data_dc(descriptor_resource->data,
                            descriptor_index * 16);""")
rep("""      ps5_flush_descriptor_table(((struct ps5_resource *)context->descriptor_storage[0])->data,
                                 descriptor_bytes[0]);""",
    """      ps5_flush_descriptor_table_ex(((struct ps5_resource *)context->descriptor_storage[0])->data,
                                    descriptor_bytes[0], true);""")
rep("""      ps5_flush_descriptor_table(((struct ps5_resource *)context->descriptor_storage[1])->data,
                                 descriptor_bytes[1]);""",
    """      ps5_flush_descriptor_table_ex(((struct ps5_resource *)context->descriptor_storage[1])->data,
                                    descriptor_bytes[1], true);""")
# one fence before anything can consume the flushed lines (job hand-over publishes with a release store)
rep("""   if (submitted)
      *submitted = true;
   ps5_ck[5] = ps5_my_tsc();""", """   ps5_flush_fence_dc();
   if (submitted)
      *submitted = true;
   ps5_ck[5] = ps5_my_tsc();""")

# 3. stage timing trace event 130 (only when the shim tracer is armed)
rep("   ps5_ck[0] = ps5_my_tsc();\n   if (submitted)\n      *submitted = false;",
    "   ps5_ck[0] = ps5_my_tsc();\n   const int64_t dc_t0 = ps5_driver_trace_hook ? os_time_get_nano() : 0;\n   if (submitted)\n      *submitted = false;")
rep("   ps5_ck[6] = ps5_my_tsc();\n   for (int i = 1; i < 7; ++i) ps5_sec[i - 1] += ps5_ck[i] - ps5_ck[i - 1];\n",
    """   ps5_ck[6] = ps5_my_tsc();
   for (int i = 1; i < 7; ++i) ps5_sec[i - 1] += ps5_ck[i] - ps5_ck[i - 1];
   if (dc_t0 && ps5_ck[6] > ps5_ck[0]) {
      /* event 130: dur = whole call (ns); arg = six stage times, 10 bits each, units of 100 ns:
       * bounds | framebuffer | state+variants+vertex descriptors | prepare (constants, textures, flushes) | gate2 setters | gate2_run */
      const uint64_t dc_ns = (uint64_t)(os_time_get_nano() - dc_t0);
      const uint64_t dc_cy = ps5_ck[6] - ps5_ck[0];
      unsigned long long packed = 0;
      for (int i = 0; i < 6; ++i) {
         uint64_t u = (ps5_ck[i + 1] - ps5_ck[i]) * dc_ns / dc_cy / 100u;
         packed |= (unsigned long long)(u > 1023u ? 1023u : u) << (10 * i);
      }
      ps5_driver_trace_hook(130, (unsigned long long)dc_t0, (unsigned long long)dc_ns, packed);
   }
""")

# 4. optional: no printf per multi-draw
rep("""   printf("[ps5-gallium] multi-draw-batched draws=%u result=%d\\n",
          num_draws, context->last_draw_status);""",
    """   if (!(ps5_dc_flags() & 4u))
      printf("[ps5-gallium] multi-draw-batched draws=%u result=%d\\n",
             num_draws, context->last_draw_status);""")

open(P, "w", encoding="utf-8").write(s)
print("ok")
