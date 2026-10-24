#!/usr/bin/env python3
"""PS5 in-game options: grey out / skip the desktop-only graphics options in the Jak 1/2/3 progress menus, force the
display settings to the fixed PS5 values at settings load, and add 'Upscaling (FSR)' / 'FSR sharpness' entries.
Details: docs/INGAME_SETTINGS.md.

usage: python3 patch_ps5_ingame_settings.py [--emit-manifest]
  JAK_ROOT       jak-project root (default ~/jak; sync_upstream.py sets it to its private copy)
  SYNC_FILE_MAP  JSON {old relative path: new relative path} when upstream moved a file
Idempotent: an edit whose new text is already present is skipped. A failing anchor is reported (with the closest line
in the file) and nothing is written for that edit; the exit code is 1 if any edit failed.
Every patched site carries `__ps5__` (C++/GOAL comment) so `grep __ps5__` finds it.
"""
import difflib
import glob
import json
import os
import re
import sys

JAK = os.environ.get("JAK_ROOT") or os.path.expanduser("~/jak")
FILE_MAP = json.loads(os.environ.get("SYNC_FILE_MAP") or "{}")


def rp(rel):
    return FILE_MAP.get(rel, rel)


EDITS = []  # (id, file, old, new)


def edit(eid, path, old, new):
    EDITS.append((eid, path, old, new))


# ---- C++: kernel functions pc-ps5-get-setting / pc-ps5-set-setting!, fixed display mode ----------------------
KM = "game/kernel/common/kmachine.cpp"
edit("kern.fn", KM, "void pc_set_vsync(u32 sym_val) {\n  Gfx::g_global_settings.vsync = symbol_to_bool(sym_val);\n}",
     """// __ps5__ ingame settings: id 0 = FSR upscale mode (0 off, 1 quality, 2 balanced, 3 performance, 4 auto), id 1 = FSR sharpness 0..10.
// The shim (ps5shim) defines ps5_ingame_get/ps5_ingame_set on top of ps5.cfg; weak, so the engine links and the menu shows 0 without them.
#if defined(__ps5__)
extern "C" int ps5_ingame_get(int id) __attribute__((weak));
extern "C" void ps5_ingame_set(int id, int value) __attribute__((weak));
#endif
u64 pc_ps5_get_setting(int id) {
#if defined(__ps5__)
  if (ps5_ingame_get) {
    int v = ps5_ingame_get(id);
    return v < 0 ? 0 : (u64)v;
  }
#endif
  return 0;
}

void pc_ps5_set_setting(int id, int value) {
#if defined(__ps5__)
  if (ps5_ingame_set) {
    ps5_ingame_set(id, value);
  }
#endif
}

void pc_set_vsync(u32 sym_val) {
#if defined(__ps5__)
  Gfx::g_global_settings.vsync = true;  // __ps5__ fixed output, always vsynced
#else
  Gfx::g_global_settings.vsync = symbol_to_bool(sym_val);
#endif
}""")
edit("kern.reg", KM, '  make_func_symbol_func("pc-set-vsync", (void*)pc_set_vsync);\n',
     '  make_func_symbol_func("pc-set-vsync", (void*)pc_set_vsync);\n'
     '  make_func_symbol_func("pc-ps5-get-setting", (void*)pc_ps5_get_setting);  // __ps5__\n'
     '  make_func_symbol_func("pc-ps5-set-setting!", (void*)pc_ps5_set_setting);  // __ps5__\n')
edit("kern.fps", KM, "void pc_set_frame_rate(int rate) {\n  Gfx::g_global_settings.target_fps = rate;\n}",
     "void pc_set_frame_rate(int rate) {\n#if defined(__ps5__)\n  rate = 60;  // __ps5__ fixed 60 fps\n#endif\n  Gfx::g_global_settings.target_fps = rate;\n}")
edit("kern.dispmode", KM, "void pc_set_display_mode(u32 symptr, u64 window_width, u64 window_height) {\n  if (!Display::GetMainDisplay()) {",
     "void pc_set_display_mode(u32 symptr, u64 window_width, u64 window_height) {\n#if defined(__ps5__)\n  return;  // __ps5__ fixed fullscreen output\n#endif\n  if (!Display::GetMainDisplay()) {")
DM = "game/system/hid/display_manager.cpp"
edit("disp.force", DM, "    m_display_settings.load_settings();\n",
     "    m_display_settings.load_settings();\n#if defined(__ps5__)\n"
     "    // __ps5__ a copied PC display-settings file must not select windowed/borderless or another monitor\n"
     "    m_display_settings.display_mode = game_settings::DisplaySettings::DisplayMode::Fullscreen;\n"
     "    m_display_settings.display_id = 0;\n#endif\n")

# ---- GOAL: kernel externs, text ids ----------------------------------------------------------------------------
EXTERN_NEW = ("(define-extern pc-set-vsync (function symbol none))\n"
              ";; __ps5__ ingame settings (kmachine.cpp)\n"
              "(define-extern pc-ps5-get-setting (function int int))\n"
              "(define-extern pc-ps5-set-setting! (function int int none))\n")
for g in ("jak1", "jak2", "jak3"):
    edit(f"{g}.extern", f"goal_src/{g}/kernel-defs.gc", "(define-extern pc-set-vsync (function symbol none))\n", EXTERN_NEW)
edit("jak1.textid", "goal_src/jak1/engine/ui/text-h.gc", "  (vsync #x103b)\n",
     "  (vsync #x103b)\n  (ps5-upscale #x1f10)\n  (ps5-sharpness #x1f11)\n")
edit("jak2.textid", "goal_src/jak2/engine/ui/text-id-h.gc", "  (progress-vsync #x120d)\n",
     "  (progress-vsync #x120d)\n  (progress-ps5-upscale #x1f10)\n  (progress-ps5-sharpness #x1f11)\n")
edit("jak3.textid", "goal_src/jak3/engine/ui/text-h.gc", "  (progress-vsync #x120d)\n",
     "  (progress-vsync #x120d)\n  (progress-ps5-upscale #x1f10)\n  (progress-ps5-sharpness #x1f11)\n")

# text JSON (appended to every game_custom_text_*.json of the game; English everywhere, no per-language translation)
JSON_TEXT = {
    "jak1": {"1f10": "UPSCALING (FSR)", "1f11": "FSR SHARPNESS"},
    "jak2": {"1f10": "Upscaling (FSR)", "1f11": "FSR Sharpness"},
    "jak3": {"1f10": "Upscaling (FSR)", "1f11": "FSR Sharpness"},
}

# ---- GOAL: shared pckernel-common.gc (used by all three games; jak2/jak3 build it from the jak1 folder) -------
PK = "goal_src/jak1/pc/pckernel-common.gc"
edit("pk.load", PK, "     (commit-to-file obj)))\n  0)",
     "     (commit-to-file obj)))\n"
     "  ;; __ps5__ fixed output: a copied PC pc-settings.gc must not turn vsync off or raise the frame rate\n"
     "  (set-frame-rate! obj 60 #t)\n  (true! (-> obj vsync?))\n  0)")
edit("pk.fps", PK, '    (("fps") (set-frame-rate! obj (file-stream-read-int file) #t))',
     '    (("fps") (file-stream-read-int file) (set-frame-rate! obj 60 #t)) ;; __ps5__ ignore the saved value')
edit("pk.vsync", PK, '    (("vsync") (set! (-> obj vsync?) (file-stream-read-symbol file)))',
     '    (("vsync") (file-stream-read-symbol file) (true! (-> obj vsync?))) ;; __ps5__ always on')
edit("pk.tos", PK,
     "  (pc-set-vsync (and (-> obj vsync?)\n                     (or (= 'fullscreen (pc-get-display-mode)) (>= (pc-get-active-display-refresh-rate) (-> obj target-fps)))))\n"
     "  (when (!= 'fullscreen (pc-get-display-mode))\n    (pc-set-frame-rate (-> obj target-fps)))\n",
     "  ;; __ps5__ fixed vsync + 60 fps (the display mode is forced fullscreen in the C++ display manager)\n"
     "  (true! (-> obj vsync?))\n  (pc-set-vsync #t)\n  (pc-set-frame-rate 60)\n")

# ---- GOAL: Jak 1 progress menu (old game-option system) ---------------------------------------------------------
J1 = "goal_src/jak1/pc/progress-pc.gc"
DIS = "(lambda () #t)"
edit("j1.res", J1, "            :name (text-id game-resolution)\n            :scale #t\n            :param3 (game-option-menu resolution))",
     f"            :name (text-id game-resolution)\n            :scale #t\n            :param3 (game-option-menu resolution)\n            :option-disabled-func {DIS}) ;; __ps5__")
edit("j1.dmode", J1, "(new 'static 'game-option :option-type (game-option-type display-mode) :name (text-id display-mode) :scale #t)",
     f"(new 'static 'game-option :option-type (game-option-type display-mode) :name (text-id display-mode) :scale #t :option-disabled-func {DIS}) ;; __ps5__")
edit("j1.monitor", J1, "            :option-disabled-func\n            (lambda ()\n              (= (pc-get-display-mode) 'windowed)))",
     f"            :option-disabled-func\n            {DIS}) ;; __ps5__")
edit("j1.vsync", J1, "(new 'static 'game-option :option-type (game-option-type on-off) :name (text-id vsync) :scale #t)",
     f"(new 'static 'game-option :option-type (game-option-type on-off) :name (text-id vsync) :scale #t :option-disabled-func {DIS}) ;; __ps5__")
edit("j1.fps", J1,
     "            :option-disabled-func\n            (lambda ()\n              (or (-> *pc-settings* speedrunner-mode?) (<= (pc-get-active-display-refresh-rate) 60))))",
     f"            :option-disabled-func\n            {DIS}) ;; __ps5__ fixed 60 fps")
J1_FSR_ENTRIES = """       ;; __ps5__ FSR entries: sliders (the old menu has no carousel type for custom entries). values live in *ps5-fsr*
       (new 'static
            'game-option
            :option-type (game-option-type slider)
            :name (text-id ps5-upscale)
            :scale #t
            :param1 0.0
            :param2 4.0
            :slider-step-size 1.0
            :slider-show-decimal? #f
            :on-change
            (lambda ((val object))
              (pc-ps5-set-setting! 0 (the int (the-as float val)))
              (none)))
       (new 'static
            'game-option
            :option-type (game-option-type slider)
            :name (text-id ps5-sharpness)
            :scale #t
            :param1 0.0
            :param2 10.0
            :slider-step-size 1.0
            :slider-show-decimal? #f
            :on-change
            (lambda ((val object))
              (pc-ps5-set-setting! 1 (the int (the-as float val)))
              (none)))
"""
PS2_ENTRY = "       (new 'static\n            'game-option\n            :option-type (game-option-type menu)\n            :name (text-id ps2-options)"
edit("j1.fsr", J1, PS2_ENTRY, J1_FSR_ENTRIES + PS2_ENTRY)
edit("j1.state", J1, "(define *graphic-options-pc*\n",
     """;; __ps5__ storage for the two FSR sliders (floats, the slider code needs a float pointer)
(deftype ps5-fsr-state (structure)
  ((upscale   float)
   (sharpness float)))
(define *ps5-fsr* (new 'static 'ps5-fsr-state))

(define *graphic-options-pc*
""")
edit("j1.ptr", J1, "  (set! (-> *graphic-options-pc* 6 value-to-modify) (&-> *progress-carousell* int-backup))\n",
     "  (set! (-> *graphic-options-pc* 6 value-to-modify) (&-> *progress-carousell* int-backup))\n"
     "  ;; __ps5__ FSR sliders (entries 7 and 8 of *graphic-options-pc*), read from ps5.cfg every time the menu is built\n"
     "  (set! (-> *ps5-fsr* upscale) (the float (pc-ps5-get-setting 0)))\n"
     "  (set! (-> *ps5-fsr* sharpness) (the float (pc-ps5-get-setting 1)))\n"
     "  (set! (-> *graphic-options-pc* 7 value-to-modify) (&-> *ps5-fsr* upscale))\n"
     "  (set! (-> *graphic-options-pc* 8 value-to-modify) (&-> *ps5-fsr* sharpness))\n")
J1_NAV_FNS = """;; __ps5__ cursor navigation that skips options whose option-disabled-func says so
(defun ps5-opt-disabled? ((opt game-option))
  (and (nonzero? (-> opt option-disabled-func))
       (!= (-> opt option-disabled-func) #f)
       ((-> opt option-disabled-func))))

(defun ps5-nav-step! ((obj progress) (options (array game-option)) (dir int))
  "one cursor step (dir -1 up, 1 down) with the same wrap and scroll handling as respond-common"
  (cond
    ((< dir 0)
     (cond
       ((> (-> obj option-index) 0)
        (1-! (-> obj option-index))
        (when (and (> (length options) PROGRESS_PC_PAGE_HEIGHT) (< (-> obj option-index) *progress-scroll-start*))
          (progress-scroll-up!)))
       (else
        (set! (-> obj option-index) (1- (length options)))
        (set! (-> *progress-scroll* start-index) (max 0 (- (length options) PROGRESS_PC_PAGE_HEIGHT -1))))))
    (else
     (cond
       ((< (-> obj option-index) (1- (length options)))
        (1+! (-> obj option-index))
        (when (and (> (length options) PROGRESS_PC_PAGE_HEIGHT) (>= (-> obj option-index) *progress-scroll-end*))
          (progress-scroll-down!)))
       (else (set! (-> obj option-index) 0) (set! (-> *progress-scroll* start-index) 0)))))
  0)

(defun ps5-nav-skip! ((obj progress) (options (array game-option)) (dir int))
  "step until the cursor rests on an enabled option (at most one lap, so an all-disabled list cannot hang)"
  (let ((tries (length options)))
    (while (> tries 0)
      (ps5-nav-step! obj options dir)
      (1-! tries)
      (if (not (ps5-opt-disabled? (-> options (-> obj option-index))))
          (set! tries 0))))
  0)

(defmethod respond-common ((obj progress))"""
edit("j1.navfns", J1, "(defmethod respond-common ((obj progress))", J1_NAV_FNS)
J1_UP_OLD = """           (cond
             ((> (-> obj option-index) 0)
              (1-! (-> obj option-index))
              (when (and (> (length options) PROGRESS_PC_PAGE_HEIGHT) (< (-> obj option-index) *progress-scroll-start*))
                (progress-scroll-up!)))
             (else
              (set! (-> obj option-index) (1- (length options)))
              (set! (-> *progress-scroll* start-index) (max 0 (- (length options) PROGRESS_PC_PAGE_HEIGHT -1)))))"""
edit("j1.up", J1, J1_UP_OLD, "           ;; __ps5__ skip disabled options\n           (ps5-nav-skip! obj options -1)")
J1_DOWN_OLD = """           (cond
             ((< (-> obj option-index) (1- (length options)))
              (1+! (-> obj option-index))
              (when (and (> (length options) PROGRESS_PC_PAGE_HEIGHT) (>= (-> obj option-index) *progress-scroll-end*))
                (progress-scroll-down!)))
             (else (set! (-> obj option-index) 0) (set! (-> *progress-scroll* start-index) 0)))"""
# the helper function above also contains this text with other indentation, so the anchor keeps the 11-space indent
edit("j1.down", J1, J1_DOWN_OLD, "           ;; __ps5__ skip disabled options\n           (ps5-nav-skip! obj options 1)")
edit("j1.snap", J1,
     "      ;; only respond to inputs when transition is done (and also there's options at all)\n      (cond\n",
     "      ;; only respond to inputs when transition is done (and also there's options at all)\n"
     "      ;; __ps5__ never rest on a disabled option (e.g. the page opens on index 0)\n"
     "      (when (and (not (-> obj selected-option)) (ps5-opt-disabled? (-> options (-> obj option-index))))\n"
     "        (ps5-nav-skip! obj options 1))\n      (cond\n")

# ---- GOAL: Jak 2 and Jak 3 progress menus (generic menu system, identical text in both games) -------------------
GEN_FNS = """;; __ps5__ the hover cursor skips options whose should-disable? says so
(defun ps5-menu-option-disabled? ((opt menu-option))
  (and (type? opt menu-generic-option)
       (nonzero? (-> (the-as menu-generic-option opt) should-disable?))
       (!= (-> (the-as menu-generic-option opt) should-disable?) #f)
       ((-> (the-as menu-generic-option opt) should-disable?))))

(defun ps5-menu-skip-disabled! ((page menu-generic-scrolling-page) (dir int))
  "move the hover cursor in direction dir (1 or -1, wrapping) to the next enabled option; unchanged if all are disabled"
  (let ((n (-> page menu-options length))
        (start (-> *progress-pc-generic-store* current-menu-hover-index)))
    (when (and (>= start 0) (< start n))
      (dotimes (i n)
        (if (not (ps5-menu-option-disabled? (-> page menu-options (-> *progress-pc-generic-store* current-menu-hover-index))))
            (return 0))
        (let ((next (+ (-> *progress-pc-generic-store* current-menu-hover-index) dir)))
          (cond
            ((< next 0) (set! next (+ n -1)))
            ((>= next n) (set! next 0)))
          (set! (-> *progress-pc-generic-store* current-menu-hover-index) next)))
      (set! (-> *progress-pc-generic-store* current-menu-hover-index) start)))
  0)

"""
GP = "goal_src/{g}/pc/progress/progress-generic-pc.gc"
GS = "goal_src/{g}/pc/progress/progress-static-pc.gc"
GEN_FSR = """    ;; __ps5__ FSR entries. The launcher (ps5.cfg upscale=/sharpness=) and this menu share ps5_ingame_get/set; applied at the next game start
    (new 'static 'menu-generic-carousel-option
      :name (text-id progress-ps5-upscale)
      :get-item-index-fn (lambda () (min 4 (max 0 (pc-ps5-get-setting 0))))
      :get-max-size-fn (lambda () 5)
      :get-item-label-fn (lambda ((index int))
        (case index
          ((1) "Quality (83%)")
          ((2) "Balanced (67%)")
          ((3) "Performance (50%)")
          ((4) "Auto")
          (else "Off")))
      :on-confirm (lambda ((index int) (the-progress progress))
        (pc-ps5-set-setting! 0 index)))
    (new 'static 'menu-generic-carousel-option
      :name (text-id progress-ps5-sharpness)
      :should-disable? (lambda () (zero? (pc-ps5-get-setting 0)))
      :get-item-index-fn (lambda () (min 10 (max 0 (pc-ps5-get-setting 1))))
      :get-max-size-fn (lambda () 11)
      :get-item-label-fn (lambda ((index int)) (string-format "~D" index))
      :on-confirm (lambda ((index int) (the-progress progress))
        (pc-ps5-set-setting! 1 index)))
"""
GEN_LINK = "    (progress-new-generic-link-to-scrolling-page (text-id progress-graphics-ps2)"
SCROLL_HEAD = ('(defmethod respond-progress ((this menu-generic-scrolling-page) (progress progress) (selected? symbol))\n'
               '  "Handle progress menu navigation logic."\n  (let ((selected-item? #f))\n')
for g in ("jak2", "jak3"):
    p, s = GP.format(g=g), GS.format(g=g)
    edit(f"{g}.navfns", p, SCROLL_HEAD, GEN_FNS + SCROLL_HEAD + "    (if (= (-> this selected-option-index) -1) (ps5-menu-skip-disabled! this 1)) ;; __ps5__ never rest on a disabled option\n")
    edit(f"{g}.down", p,
         '            (else\n              (set! (-> *progress-pc-generic-store* current-menu-hover-index) 0)\n              (sound-play "roll-over"))))\n',
         '            (else\n              (set! (-> *progress-pc-generic-store* current-menu-hover-index) 0)\n              (sound-play "roll-over")))\n'
         '          (ps5-menu-skip-disabled! this 1)) ;; __ps5__\n')
    edit(f"{g}.up", p,
         "          (set! (-> *progress-pc-generic-store* current-menu-hover-index) (dec (-> this menu-options length)))))\n",
         "          (set! (-> *progress-pc-generic-store* current-menu-hover-index) (dec (-> this menu-options length))))\n"
         "          (ps5-menu-skip-disabled! this -1)) ;; __ps5__\n")
    edit(f"{g}.res", s, "      :name (text-id progress-window-size)\n", f"      :name (text-id progress-window-size)\n      :should-disable? {DIS} ;; __ps5__\n")
    edit(f"{g}.monitor", s, "      :should-disable? (lambda () (or (= (pc-get-display-mode) 'windowed) (<= (pc-get-display-count) 1))))",
         f"      :should-disable? {DIS}) ;; __ps5__")
    edit(f"{g}.dmode", s, "      :name (text-id progress-display-mode)\n", f"      :name (text-id progress-display-mode)\n      :should-disable? {DIS} ;; __ps5__\n")
    edit(f"{g}.fps", s, "      :name (text-id progress-frame-rate)\n      :should-disable? (lambda () (-> *pc-settings* speedrunner-mode?))\n",
         f"      :name (text-id progress-frame-rate)\n      :should-disable? {DIS} ;; __ps5__\n")
    edit(f"{g}.vsync", s, "      :name (text-id progress-vsync)\n", f"      :name (text-id progress-vsync)\n      :should-disable? {DIS} ;; __ps5__\n")
    edit(f"{g}.fsr", s, GEN_LINK, GEN_FSR + GEN_LINK)


# ---- helpers ----------------------------------------------------------------------------------------------------
def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def anchor_report(text, old):
    first = old.strip("\n").split("\n")[0].strip()
    lines = text.split("\n")
    best = difflib.get_close_matches(first, [l.strip() for l in lines], n=1, cutoff=0.5)
    if not best:
        return f"no line similar to {first!r}"
    i = [l.strip() for l in lines].index(best[0])
    return f"closest line {i + 1}: {lines[i].strip()!r} (looked for {first!r})"


def balance(text):
    """Paren balance of a GOAL file, ignoring strings, ; comments and #| |# blocks. Returns the final depth (0 = balanced) or -1 on underflow."""
    depth, i, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == ";":
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("#|", i):
            i = text.find("|#", i) + 1
            if i == 0:
                return -2
        elif text.startswith("#\\", i):
            i += 2
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth < 0:
                return -1
        i += 1
    return depth


def patch_json(failed):
    changed = 0
    for g, kv in JSON_TEXT.items():
        for path in sorted(glob.glob(os.path.join(JAK, rp(f"game/assets/{g}/text"), "game_custom_text_*.json"))):
            raw = read(path)
            data = json.loads(raw)
            add = {k: v for k, v in kv.items() if k not in data}
            if not add:
                continue
            body = raw.rstrip()
            tail = raw[len(body):]
            if not body.endswith("}"):
                print(f"PATCH FAILED {path}: does not end with }}")
                failed.append(path)
                continue
            body = body[:-1].rstrip()
            items = ",\n".join(f'  "{k}": {json.dumps(v, ensure_ascii=False)}' for k, v in add.items())
            new = body + ("" if body.endswith("{") else ",") + "\n" + items + "\n}" + tail
            json.loads(new)
            write(path, new)
            changed += 1
    return changed


def emit_manifest():
    files = sorted({rp(f) for _, f, _, _ in EDITS})
    anchors = [{"id": f"ingame.{eid}", "file": f, "kind": "text", "text": old, "count": 1} for eid, f, old, _ in EDITS]
    step = {
        "id": "ingame-settings", "kind": "script", "path": "patch_ps5_ingame_settings.py",
        "description": "PS5 in-game options (Jak 1/2/3): grey out and skip window/monitor/display mode/vsync/fps options, force fullscreen+vsync+60 fps at settings load, add Upscaling (FSR) and FSR sharpness entries (kernel fns pc-ps5-get-setting / pc-ps5-set-setting!)",
        "required": False, "requires": ["core"],
        "touches": files + [f"game/assets/{g}/text/game_custom_text_*.json" for g in JSON_TEXT],
        "markers": [{"file": KM, "text": "__ps5__ ingame settings"}],
        "anchors": anchors,
    }
    print(json.dumps(step, indent=1))


def main():
    if "--emit-manifest" in sys.argv:
        return emit_manifest()
    changed, failed = 0, []
    by_file = {}
    for eid, f, old, new in EDITS:
        by_file.setdefault(f, []).append((eid, old, new))
    for f, items in by_file.items():
        path = os.path.join(JAK, rp(f))
        if not os.path.exists(path):
            print(f"PATCH FAILED {f}: file missing")
            failed.extend(e for e, _, _ in items)
            continue
        text = read(path)
        orig = text
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
            if f.endswith(".gc") and balance(text) != 0 and balance(orig) == 0:
                print(f"PATCH FAILED {f}: result is not paren balanced (depth {balance(text)}); file not written")
                failed.append(f)
                continue
            write(path, text)
    changed += patch_json(failed)
    print(f"{changed} change(s) applied, {len(EDITS)} edits total, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
