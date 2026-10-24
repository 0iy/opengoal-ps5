#!/usr/bin/env python3
"""Driver patch 55: asynchronous swap and triple-buffered scanout (design and results: docs/agent_present.md).

Two runtime switches, both default off (behaviour identical to before, except that the display pool now has three 32 MiB
slots and the offscreen arena starts 32 MiB later):
  PS5_ASYNC_SWAP=1     eglSwapBuffers treats swap_interval as 0: no ST_FLUSH_WAIT, no full-wait submit_lock. The flip is
                       already queued at the GPU tail; the next frame's first scanout write waits for it as before.
  PS5_TRIPLE_BUFFER=1  implies async swap. Registers three VideoOut buffers, EGL rotates 0,1,2, up to two flips in flight:
                       a scanout write waits only until <= 1 flip is outstanding (before: 0).
Root of the source tree: env PS5_SRC (default ~/gl/src/ps5-opengl/src). Idempotent."""
import os

ROOT = os.path.expanduser(os.environ.get("PS5_SRC", "~/gl/src/ps5-opengl/src"))
if "PS5_TRIPLE_BUFFER" in open(os.path.join(ROOT, "platform/ps5_agc_native_runtime.c"), encoding="utf-8").read():
    print("already patched")
    raise SystemExit


def edit(rel, pairs):
    p = os.path.join(ROOT, rel)
    s = open(p, encoding="utf-8").read()
    for old, new in pairs:
        assert s.count(old) == 1, (rel, s.count(old), old[:70])
        s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)


# ---- layout: three display slots -------------------------------------------------------------------------------
edit("platform/ps5_scanout.h", [(
    "#define PS5_SCANOUT_POOL_BYTES (2u * PS5_SCANOUT_BYTES)",
    "/* Display slots in the pool; PS5_TRIPLE_BUFFER=1 registers the third one at run time. */\n"
    "#define PS5_SCANOUT_BUFFERS 3u\n"
    "#define PS5_SCANOUT_POOL_BYTES (PS5_SCANOUT_BUFFERS * PS5_SCANOUT_BYTES)")])

edit("gallium/ps5/ps5_screen.c", [
    ("#define PS5_RENDER_ARENA_OFFSET (2u * PS5_RENDER_TARGET_BYTES)",
     "#define PS5_RENDER_ARENA_OFFSET (PS5_SCANOUT_BUFFERS * PS5_RENDER_TARGET_BYTES)"),
    ("       buffer_index != 1 ||\n       owner->allocation_size < 2u * PS5_RENDER_TARGET_BYTES)",
     "       buffer_index < 1 || buffer_index >= PS5_SCANOUT_BUFFERS ||\n"
     "       owner->allocation_size < PS5_SCANOUT_BUFFERS * PS5_RENDER_TARGET_BYTES)"),
])

# ---- EGL: three targets, rotation, async swap ------------------------------------------------------------------
edit("egl/ps5_egl.c", [
    ("   struct pipe_resource *targets[2];", "   struct pipe_resource *targets[3];"),
    ("   struct pipe_resource *scanout[2];", "   struct pipe_resource *scanout[3];"),
    ("""      if (ps5_display.scanout[0])
         ps5_display.scanout[1] = ps5_display_target_alias(
            ps5_display.scanout[0], 1);
      if (!ps5_display.scanout[0] || !ps5_display.scanout[1]) {
         pipe_resource_reference(&ps5_display.scanout[1], NULL);""",
     """      if (ps5_display.scanout[0]) {
         ps5_display.scanout[1] = ps5_display_target_alias(
            ps5_display.scanout[0], 1);
         ps5_display.scanout[2] = ps5_display_target_alias(
            ps5_display.scanout[0], 2);
      }
      if (!ps5_display.scanout[0] || !ps5_display.scanout[1] ||
          !ps5_display.scanout[2]) {
         pipe_resource_reference(&ps5_display.scanout[2], NULL);
         pipe_resource_reference(&ps5_display.scanout[1], NULL);"""),
    ("   pipe_resource_reference(&ps5_display.scanout[1], NULL);\n   pipe_resource_reference(&ps5_display.scanout[0], NULL);\n   st_screen_destroy",
     "   pipe_resource_reference(&ps5_display.scanout[2], NULL);\n   pipe_resource_reference(&ps5_display.scanout[1], NULL);\n"
     "   pipe_resource_reference(&ps5_display.scanout[0], NULL);\n   st_screen_destroy"),
    ("   pipe_resource_reference(&surface->targets[1], ps5_display.scanout[1]);\n",
     "   pipe_resource_reference(&surface->targets[1], ps5_display.scanout[1]);\n"
     "   pipe_resource_reference(&surface->targets[2], ps5_display.scanout[2]);\n"),
    ("   if (!surface->depth_stencil) {\n      pipe_resource_reference(&surface->targets[1], NULL);\n      pipe_resource_reference(&surface->targets[0], NULL);\n      free(surface);\n      ps5_set_error(EGL_BAD_ALLOC);\n      return EGL_NO_SURFACE;\n   }\n   ps5_init_surface(surface, PS5_EGL_WIDTH, PS5_EGL_HEIGHT, true);",
     "   if (!surface->depth_stencil) {\n      pipe_resource_reference(&surface->targets[2], NULL);\n      pipe_resource_reference(&surface->targets[1], NULL);\n      pipe_resource_reference(&surface->targets[0], NULL);\n      free(surface);\n      ps5_set_error(EGL_BAD_ALLOC);\n      return EGL_NO_SURFACE;\n   }\n   ps5_init_surface(surface, PS5_EGL_WIDTH, PS5_EGL_HEIGHT, true);"),
    ("   pipe_resource_reference(&surface->depth_stencil, NULL);\n   pipe_resource_reference(&surface->targets[1], NULL);\n   pipe_resource_reference(&surface->targets[0], NULL);\n   struct ps5_egl_surface **link",
     "   pipe_resource_reference(&surface->depth_stencil, NULL);\n   pipe_resource_reference(&surface->targets[2], NULL);\n   pipe_resource_reference(&surface->targets[1], NULL);\n   pipe_resource_reference(&surface->targets[0], NULL);\n   struct ps5_egl_surface **link"),
    ("int ps5_agc_gate2_shutdown_present(void) __attribute__((weak));\n",
     """int ps5_agc_gate2_shutdown_present(void) __attribute__((weak));
int ps5_agc_gate2_scanout_buffers(void) __attribute__((weak));

static unsigned
ps5_scanout_buffer_count(void)
{
   return ps5_agc_gate2_scanout_buffers && ps5_agc_gate2_scanout_buffers() == 3 ? 3u : 2u;
}

/* PS5_ASYNC_SWAP=1 (or triple buffering): do not wait for the GPU at swap. */
static bool
ps5_async_swap(void)
{
   static int async = -1;
   if (async < 0) {
      const char *e = getenv("PS5_ASYNC_SWAP");
      async = (e && *e && *e != '0') || ps5_scanout_buffer_count() == 3;
   }
   return async;
}
"""),
    ("   _mesa_glthread_finish(ps5_current_context->st->ctx);\n   st_context_flush(ps5_current_context->st,\n                    ST_FLUSH_FRONT | ST_FLUSH_END_OF_FRAME |\n                       ((!surface->window || surface->swap_interval) ?",
     "   const bool sync_swap = surface->swap_interval && !ps5_async_swap();\n"
     "   _mesa_glthread_finish(ps5_current_context->st->ctx);\n   st_context_flush(ps5_current_context->st,\n                    ST_FLUSH_FRONT | ST_FLUSH_END_OF_FRAME |\n                       ((!surface->window || sync_swap) ?"),
    ("      if (surface->swap_interval)\n         ps5_screen_submit_lock(ps5_display.screen);",
     "      if (sync_swap)\n         ps5_screen_submit_lock(ps5_display.screen);"),
    ("         present_status = ps5_agc_gate2_present(surface->buffer_index,\n                                                surface->swap_interval);",
     "         present_status = ps5_agc_gate2_present(surface->buffer_index,\n                                                sync_swap);"),
    ("   surface->buffer_index ^= 1u;", "   surface->buffer_index = (surface->buffer_index + 1u) % ps5_scanout_buffer_count();"),
])

# ---- runtime: flip tracking, three registered buffers ---------------------------------------------------------
RT = "platform/ps5_agc_native_runtime.c"
WAIT_BLOCK = r'''int ps5_agc_gate2_scanout_buffers(void)
{
    static int n;
    if (!n) {
        const char *e = getenv("PS5_TRIPLE_BUFFER");
        n = e && *e && *e != '0' ? 3 : 2;
        printf("[ps5-present] scanout buffers=%d\n", n);
    }
    return n;
}

#ifdef PS5_GPU_PRESENT_BATCH
/* Triple buffering: wait until at most `limit` flips are outstanding (the newest one is
 * runtime_gpu_present_marker, the one before it runtime_flip_prev_marker, 0 = none).
 * Flips complete in order; flipArg (status[3]) is assumed to be the argument of the last completed
 * flip. Every completion test also needs is_flip_pending to agree, so a wrong assumption cannot
 * release a buffer that is still queued. limit 0 is the strict drain. */
static int runtime_present_wait(unsigned limit)
{
    static int verbose = -1;
    if (!runtime_gpu_present_deferred || runtime_gpu_present_buffer < 0)
        return 0;
    if (verbose < 0)
        verbose = getenv("PS5_PRESENT_LOG") != NULL;
    for (unsigned waits = 0; waits <= 100000; ++waits) {
        uint64_t status[16] = {0};
        int result = runtime_video_api.get_flip_status(runtime_video_handle, status);
        if (result != 0)
            return result;
        int pending = runtime_video_api.is_flip_pending(runtime_video_handle);
        if (pending < 0)
            return pending;
        if (verbose && waits == 0)
            printf("[ps5-present] wait limit=%u pending=%d count=%llu arg=%llx cur=%llx prev=%llx\n", limit,
                   pending, (unsigned long long)status[0], (unsigned long long)status[3],
                   (unsigned long long)runtime_gpu_present_marker,
                   (unsigned long long)runtime_flip_prev_marker);
        if (!pending && status[3] >= runtime_gpu_present_marker) {
            runtime_gpu_present_buffer = -1;
            runtime_gpu_present_deferred = 0;
            runtime_flip_prev_marker = 0;
            if (!runtime_gpu_present_is_cpu)
                ++runtime_gpu_present_count;
            runtime_gpu_present_is_cpu = 0;
            return 0;
        }
        if (runtime_flip_prev_marker && pending <= 1 && status[3] >= runtime_flip_prev_marker)
            runtime_flip_prev_marker = 0;
        if (limit >= 1 && !runtime_flip_prev_marker)
            return 0;
        if (waits == 100000)
            return -1;
        if (ps5_sleep_wait_mode()) {
            const int64_t wsite_t0 = os_time_get_nano();
            result = sceKernelUsleep(UINT32_C(1000));
            ps5_wsite_add(2, wsite_t0);
            if (result != 0)
                return result;
        } else {
            const int64_t until = os_time_get_nano() + 20000;
            while (os_time_get_nano() < until)
                __builtin_ia32_pause();
        }
    }
    return -1;
}
#endif

'''
edit(RT, [
    ("static int runtime_gpu_present_is_cpu;\n",
     "static int runtime_gpu_present_is_cpu;\nstatic int runtime_gpu_present_fresh; /* flip queued by this swap, not yet announced by present */\nstatic uint64_t runtime_flip_prev_marker;\n"),
    ("static int runtime_video_wait_idle(void);\n\n#ifdef PS5_GPU_PRESENT_BATCH\nint ps5_agc_gate2_wait_present(void);\n",
     "static int runtime_video_wait_idle(void);\n\n" + "@@WAIT@@" + "#ifdef PS5_GPU_PRESENT_BATCH\nint ps5_agc_gate2_wait_present(void);\n"),
    # batch_present guards and bookkeeping
    ("""    if (ps5_agc_gate2_wait_present() != 0 ||
        buffer_index > 1 || runtime_gpu_present_buffer >= 0 ||
        !runtime_video_registered || runtime_video_handle < 0 ||
        !runtime_batch_active || !runtime_batch_count || runtime_batch_faulted ||
        !runtime_batch_api.set_flip || !runtime_batch_api.release_mem ||
        !runtime_video_api.get_flip_status || runtime_video_wait_idle() != 0)
        return -1;""",
     """    const int triple = ps5_agc_gate2_scanout_buffers() == 3;
    if ((triple ? (runtime_gpu_present_deferred ? runtime_present_wait(1) : 0)
                : ps5_agc_gate2_wait_present()) != 0 ||
        buffer_index >= (unsigned)ps5_agc_gate2_scanout_buffers() ||
        (!triple && runtime_gpu_present_buffer >= 0) ||
        !runtime_video_registered || runtime_video_handle < 0 ||
        !runtime_batch_active || !runtime_batch_count || runtime_batch_faulted ||
        !runtime_batch_api.set_flip || !runtime_batch_api.release_mem ||
        !runtime_video_api.get_flip_status || (!triple && runtime_video_wait_idle() != 0))
        return -1;"""),
    ("""    runtime_gpu_present_buffer = (int)buffer_index;
    runtime_gpu_present_marker = marker;
    runtime_gpu_present_is_cpu = 0;
    return 0;""",
     """    if (triple && runtime_gpu_present_buffer >= 0)
        runtime_flip_prev_marker = runtime_gpu_present_marker; /* wait(1) left at most this one */
    runtime_gpu_present_buffer = (int)buffer_index;
    runtime_gpu_present_marker = marker;
    runtime_gpu_present_is_cpu = 0;
    runtime_gpu_present_fresh = 1;
    return 0;"""),
    # strict wait
    ("""    return runtime_gpu_present_deferred
        ? runtime_gpu_present_finish((unsigned)runtime_gpu_present_buffer) : 0;""",
     """    if (!runtime_gpu_present_deferred)
        return 0;
    return ps5_agc_gate2_scanout_buffers() == 3
        ? runtime_present_wait(0)
        : runtime_gpu_present_finish((unsigned)runtime_gpu_present_buffer);"""),
    # three registered buffers
    ("""    video_buffer_t buffers[2] = {
        {framebuffer, NULL, NULL, NULL},
        {framebuffer + (framebuffer_size >= FRAMEBUFFER_POOL_BYTES
                            ? FRAMEBUFFER_BYTES : 0),
         NULL, NULL, NULL}
    };""",
     """    const int buffer_count = ps5_agc_gate2_scanout_buffers();
    const int pooled = framebuffer_size >= FRAMEBUFFER_POOL_BYTES;
    video_buffer_t buffers[3] = {
        {framebuffer, NULL, NULL, NULL},
        {framebuffer + (pooled ? FRAMEBUFFER_BYTES : 0), NULL, NULL, NULL},
        {framebuffer + (pooled ? 2u * FRAMEBUFFER_BYTES : 0), NULL, NULL, NULL}
    };"""),
    ("    if (runtime_video_registered &&\n        runtime_video_framebuffer == framebuffer &&\n        runtime_video_framebuffer_size >= framebuffer_size)\n        return 0;\n    if (runtime_video_handle >= 0 && ps5_agc_gate2_shutdown_present() != 0)",
     "    if (buffer_count == 3 && !pooled)\n        return -1;\n    if (runtime_video_registered &&\n        runtime_video_framebuffer == framebuffer &&\n        runtime_video_framebuffer_size >= framebuffer_size)\n        return 0;\n    if (runtime_video_handle >= 0 && ps5_agc_gate2_shutdown_present() != 0)"),
    ("register_buffers2(runtime_video_handle, 0, 0, buffers, 2,", "register_buffers2(runtime_video_handle, 0, 0, buffers, buffer_count,"),
    ("""           " framebuffer=%p/%zu buffers=2 alias=%u\\n",
           (uint32_t)runtime_video_handle, framebuffer,
           framebuffer_size,""",
     """           " framebuffer=%p/%zu buffers=%d alias=%u\\n",
           (uint32_t)runtime_video_handle, framebuffer,
           framebuffer_size, buffer_count,"""),
    # scanout writes: relaxed wait
    ("        const int wr = ps5_agc_gate2_wait_present();\n",
     "        const int wr = ps5_agc_gate2_scanout_buffers() == 3\n"
     "            ? (runtime_gpu_present_deferred ? runtime_present_wait(1) : 0)\n"
     "            : ps5_agc_gate2_wait_present();\n"),
    # present
    ("""    /* An empty next frame may reach swap without touching its back buffer. */
    if (ps5_agc_gate2_wait_present() != 0)
        return -1;""",
     """    /* An empty next frame may reach swap without touching its back buffer. */
    if (!(ps5_agc_gate2_scanout_buffers() == 3 && runtime_gpu_present_fresh) &&
        ps5_agc_gate2_wait_present() != 0)
        return -1;"""),
    ("    if (buffer_index > 1 || swap_interval > 1 || !runtime_video_registered ||",
     "    if (buffer_index >= (unsigned)ps5_agc_gate2_scanout_buffers() || swap_interval > 1 || !runtime_video_registered ||"),
    ("        if (runtime_gpu_present_buffer != (int)buffer_index)\n            return -1;\n        if (swap_interval == 0 ||",
     "        if (runtime_gpu_present_buffer != (int)buffer_index)\n            return -1;\n        runtime_gpu_present_fresh = 0;\n        if (swap_interval == 0 ||"),
])
p = os.path.join(ROOT, RT)
s = open(p, encoding="utf-8").read().replace("@@WAIT@@", WAIT_BLOCK)
open(p, "w", encoding="utf-8").write(s)
print("ok")
