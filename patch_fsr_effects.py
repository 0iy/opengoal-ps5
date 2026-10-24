#!/usr/bin/env python3
"""Screen-space effects at a render size below the output size (docs/FSR_EFFECTS_AUDIT.md). Apply AFTER patch_fsr.py v2.

usage: FSR_SRC=<jak-project root> python3 patch_fsr_effects.py [--emit-manifest]
  FSR_SRC / JAK_ROOT  jak-project root (FSR_SRC wins; sync_upstream.py sets JAK_ROOT). One of them is required: no default, so the
                      live tree is never patched by accident.
  SYNC_FILE_MAP       JSON {old relative path: new relative path} when upstream moved a file
Idempotent (an edit whose new text is present is skipped). A failing anchor is reported with the closest line and that edit is not
written; the exit code is 1 if any edit failed. Every patched site carries `__ps5__ fsr fx`.

Run-time switch: PS5_FSR_FX=0 restores the old behaviour of the one changed code path (no scaled copy-back).

What it fixes (the audit found only one real break; everything else already follows render_fb_w/h):
  BlitDisplays (Jak 2/3 pause/progress menu): the screen copy taken when the menu opens is copied back every frame while the menu is
  open, but only if its size equals the render size. When AUTO changes the percent while the menu is open (a menu frame is cheap, so
  AUTO steps UP), the copy-back is skipped and the menu background stays black. Now the copy is blitted back with scaling (linear).
"""
import difflib
import json
import os
import sys

ROOT = os.environ.get("FSR_SRC") or os.environ.get("JAK_ROOT")
FILE_MAP = json.loads(os.environ.get("SYNC_FILE_MAP") or "{}")
D = "game/graphics/opengl_renderer/"
GL = D + "OpenGLRenderer.cpp"
BD_H, BD_CPP, UT_CPP = D + "BlitDisplays.h", D + "BlitDisplays.cpp", D + "opengl_utils.cpp"
MARK = "__ps5__ fsr fx"


def rp(rel):
    return FILE_MAP.get(rel, rel)


EDITS = []  # (id, file, old, new)


def edit(eid, path, old, new):
    EDITS.append((eid, path, old, new))


edit("bd.h", BD_H, "  bool m_copy_back_pending = false;\n",
     "  bool m_copy_back_pending = false;\n  bool m_fx_have_copy = false;  // " + MARK + ": m_copier holds a screen copy (set at pc-port 0x10)\n")

edit("bd.copy", BD_CPP,
     """          m_copier->copy_now(render_state->render_fb_w, render_state->render_fb_h,
                             render_state->render_fb);
          m_gpu_tex->w = render_state->render_fb_w;
""",
     """          m_copier->copy_now(render_state->render_fb_w, render_state->render_fb_h,
                             render_state->render_fb);
          m_fx_have_copy = true;  // """ + MARK + """
          m_gpu_tex->w = render_state->render_fb_w;
""")

edit("bd.back", BD_CPP,
     """    if (render_state->render_fb_w == m_copier->width() &&
        render_state->render_fb_h == m_copier->height()) {
      m_copier->copy_back_now(""",
     """    // """ + MARK + """: the copy was taken at an earlier render size when the menu opened; if the dynamic resolution changed since,
    // copy_back_now scales it (linear). PS5_FSR_FX=0 = old behaviour (skip the copy-back on a size mismatch).
    const char* fx_env = std::getenv("PS5_FSR_FX");
    const bool fx_scaled_back = m_fx_have_copy && !(fx_env && fx_env[0] == '0');
    if ((render_state->render_fb_w == m_copier->width() && render_state->render_fb_h == m_copier->height()) ||
        fx_scaled_back) {
      m_copier->copy_back_now(""")

edit("ut.filter", UT_CPP,
     """                    render_fb_h,          // dstY1
                    GL_COLOR_BUFFER_BIT,  // mask
                    GL_NEAREST            // filter
""",
     """                    render_fb_h,          // dstY1
                    GL_COLOR_BUFFER_BIT,  // mask
                    (m_fbo_width == render_fb_w && m_fbo_height == render_fb_h) ? GL_NEAREST
                                                                                : GL_LINEAR  // filter, """ + MARK + """
""")


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def anchor_report(text, old):
    first = old.strip("\n").split("\n")[0].strip()
    lines = [l.strip() for l in text.split("\n")]
    best = difflib.get_close_matches(first, lines, n=1, cutoff=0.5)
    if not best:
        return f"no line similar to {first!r}"
    i = lines.index(best[0])
    return f"closest line {i + 1}: {lines[i]!r} (looked for {first!r})"


def emit_manifest():
    files = sorted({rp(f) for _, f, _, _ in EDITS})
    step = {
        "id": "fsr-effects", "kind": "script", "path": "patch_fsr_effects.py",
        "description": "Dynamic-resolution (FSR) follow-up: Jak 2/3 pause-menu screen copy is copied back with scaling when the render size changed while the menu was open. Must run after patch_fsr.py v2 (FSR_SRC or JAK_ROOT).",
        "required": False,
        "touches": files,
        "markers": [{"file": BD_CPP, "text": MARK}],
        "anchors": [{"id": f"fsr-effects.{eid}", "file": f, "kind": "text", "text": old, "count": 1} for eid, f, old, _ in EDITS],
    }
    print(json.dumps(step, indent=1))


def main():
    if "--emit-manifest" in sys.argv:
        return emit_manifest()
    if not ROOT:
        sys.exit("set FSR_SRC (or JAK_ROOT) to the jak-project root to patch")
    root = os.path.expanduser(ROOT)
    gl = os.path.join(root, rp(GL))
    if not os.path.exists(gl) or "ps5_fsr_v2" not in read(gl):
        sys.exit("PATCH FAILED: OpenGLRenderer.cpp is not patched by patch_fsr.py v2 (marker ps5_fsr_v2 missing); run patch_fsr.py first")
    changed, failed = 0, []
    by_file = {}
    for eid, f, old, new in EDITS:
        by_file.setdefault(f, []).append((eid, old, new))
    for f, items in by_file.items():
        path = os.path.join(root, rp(f))
        if not os.path.exists(path):
            print(f"PATCH FAILED {f}: file missing")
            failed.extend(e for e, _, _ in items)
            continue
        text = orig = read(path)
        for eid, old, new in items:
            if new in text:
                continue
            if text.count(old) != 1:
                print(f"PATCH FAILED {eid} in {f}: expected 1 match, found {text.count(old)}; {anchor_report(text, old)}")
                failed.append(eid)
                continue
            text = text.replace(old, new)
            changed += 1
            print(f"patched {eid} ({f})")
        if text != orig:
            write(path, text)
    print(f"{changed} change(s) applied, {len(EDITS)} edits total, {len(failed)} failed" if changed or failed else "already patched")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
