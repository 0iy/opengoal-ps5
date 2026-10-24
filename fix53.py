#!/usr/bin/env python3
"""One-off: make drv_patch53.py apply after drv_patch52.py (52 prefixes the deferred-draw condition with !ps5_sync_dbg)."""
p = "drv_patch53.py"
s = open(p, encoding="utf-8").read()
if "fix53" in s:
    print("already fixed")
    raise SystemExit
NL = chr(10)
marker = 'assert s.count(old) == 1, s.count(old)' + NL + 's = s.replace(old, new)'
i = s.index(marker)
inject = NL.join([
    "# fix53: after drv_patch52 the deferred-draw condition carries a !ps5_sync_dbg prefix",
    "if s.count(old) != 1 and 'ps5_sync_dbg' in s:",
    "    a = '   if (!context->legacy_primitive_conversion &&' + chr(10) + '       ps5_try_deferred_draw(base, info, drawid_offset, indirect, draws, num_draws))'",
    "    b = '   if (!ps5_sync_dbg && !context->legacy_primitive_conversion &&' + chr(10) + '       ps5_try_deferred_draw(base, info, drawid_offset, indirect, draws, num_draws))'",
    "    old = old.replace(a, b)",
    "    new = new.replace(a, b)",
    "    new = new.replace('if (async_multidraw && num_draws > 1', 'if (async_multidraw && !ps5_sync_dbg && num_draws > 1')",
    ""])
s = s[:i] + inject + s[i:]
open(p, "w", encoding="utf-8").write(s)
print("fixed")
