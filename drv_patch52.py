#!/usr/bin/env python3
"""Driver patch 52: PS5_SYNC_DEBUG=1 'sync-debug' mode, for classifying visual glitches (race/coherency vs translation bug).
Every draw takes the pre-batching synchronous path (ps5_screen_submit_lock = flush + retire everything in flight, then
ps5_draw_vbo_locked -> ps5_agc_gate2_run with no batch active = ps5_agc_gate2_run_sync, no async prep workers, GPU wait per draw),
buffer renaming is off, and the 'no flush' experiments (PS5_NO_BUFFER_FLUSH, PS5_NO_DESC_FLUSH) are ignored while whole-bank descriptor
flushes (PS5_FULL_DESC_FLUSH) are forced. Without the variable nothing changes. Root: env PS5_SRC (default ~/gl/src/ps5-opengl/src)."""
import os

R = os.environ.get("PS5_SRC", os.path.expanduser("~/gl/src/ps5-opengl/src"))
P = os.path.join(R, "gallium/ps5/ps5_screen.c")
s = open(P, encoding="utf-8").read()
if "ps5_sync_dbg" in s:
    print("already patched")
    raise SystemExit


def rep(old, new, n=1):
    global s
    assert s.count(old) == n, (old, s.count(old))
    s = s.replace(old, new)


# 1. no deferred / multi-draw batches
rep("""#ifdef PS5_DEFERRED_DRAW_BATCH
   if (!context->legacy_primitive_conversion &&
       ps5_try_deferred_draw(""", """   static int ps5_sync_dbg = -1; /* PS5_SYNC_DEBUG: skip the deferred and multi-draw batches below */
   if (ps5_sync_dbg < 0)
      ps5_sync_dbg = getenv("PS5_SYNC_DEBUG") != NULL;
#ifdef PS5_DEFERRED_DRAW_BATCH
   if (!ps5_sync_dbg && !context->legacy_primitive_conversion &&
       ps5_try_deferred_draw(""")
rep("""   if (num_draws > 1 && ps5_try_multi_draw_batch(""", """   if (!ps5_sync_dbg && num_draws > 1 && ps5_try_multi_draw_batch(""")
# 2. no buffer renaming
rep("""enabled = getenv("PS5_NO_BUFFER_RENAME") == NULL;""",
    """enabled = getenv("PS5_NO_BUFFER_RENAME") == NULL && getenv("PS5_SYNC_DEBUG") == NULL;""")
# 3. flush experiments ignored, full descriptor flush forced
rep("""skip = getenv("PS5_NO_BUFFER_FLUSH") != NULL;""",
    """skip = getenv("PS5_NO_BUFFER_FLUSH") != NULL && getenv("PS5_SYNC_DEBUG") == NULL;""", 3)
rep("""skip = getenv("PS5_NO_DESC_FLUSH") != NULL;""",
    """skip = getenv("PS5_NO_DESC_FLUSH") != NULL && getenv("PS5_SYNC_DEBUG") == NULL;""")
rep("""full = getenv("PS5_FULL_DESC_FLUSH") != NULL;""",
    """full = getenv("PS5_FULL_DESC_FLUSH") != NULL || getenv("PS5_SYNC_DEBUG") != NULL;""")
open(P, "w", encoding="utf-8").write(s)
print("ok")
