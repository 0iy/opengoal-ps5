#!/usr/bin/env python3
"""One-off helper: fill `anchors` of ports/manifest.json from the anchor tables inside apply_ps5_patches.py (exec'd with
main() removed) plus the hand-listed ones for patch_gfxprof.py / patch_proftree.py. After this, the manifest is the
source of truth for pre-flight; keep it in sync by hand when you change a script's anchor text."""
import json, re, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent
src = (R / "apply_ps5_patches.py").read_text()
src = src[:src.rindex("\nmain()")]
ns = {"__name__": "gen"}
exec(compile(src, "apply_ps5_patches.py", "exec"), ns)
man = json.loads((R / "ports/manifest.json").read_text())
core = [s for s in man["steps"] if s["id"] == "core"][0]
A = []
def add(file, text, count=1, kind="text", name=None, note=None):
    a = {"id": f"core.{len(A) + 1}", "file": file, "kind": kind, "text": text, "count": count}
    if name: a["name"] = name
    if note: a["note"] = note
    A.append(a)
for f in ns["LINUX_ABI_FILES"]:
    for t in ("#ifdef __linux__", "#elif __linux__"):
        add(f, t, "any", note="global replace by patch_linux_abi (any count; absent is fine only if the other form exists)")
for f in ns["_RGB_FILES"]:
    add(f, "glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB,", "any", note="regex patch_rgb_textures")
for rel, old, new, count in ns["PATCHES"]:
    add(rel, old, count)
add("game/system/SystemThread.cpp", "void* bootstrap_thread_func(void* x) {", 1, "function", "bootstrap_thread_func")
add("decompiler/extractor/main.cpp", "ExtractorErrorCode decompile(const fs::path& in_folder,", 1, "function", "decompile")
add("decompiler/extractor/main.cpp", "ExtractorErrorCode compile(const fs::path& iso_data_path, const std::string& data_subfolder) {", 1, "function", "compile")
add("decompiler/extractor/main.cpp", "int main(int argc, char** argv) {", 1, "function", "main")
core["anchors"] = A
OGL = "game/graphics/pipelines/opengl.cpp"
def mk(prefix, items):
    return [{"id": f"{prefix}.{i + 1}", "file": f, "kind": "text", "text": t, "count": 1} for i, (f, t) in enumerate(items)]
for s in man["steps"]:
    if s["id"] == "gfxprof":
        s["anchors"] = mk("gfxprof", [(OGL, t) for t in [
            "#include <condition_variable>\n",
            "  // wait for a copied chain.\n  bool got_chain = false;\n  {",
            "                                            [=] { return g_gfx_data->has_data_to_render; });\n  }\n",
            "  // render debug\n  if (is_imgui_visible()) {",
            "  // actual vsync\n  g_gfx_data->debug_gui.finish_frame();",
            "  {\n    auto p = scoped_prof(\"swap-buffers\");\n    SDL_GL_SwapWindow(m_window);\n  }\n"]])
    if s["id"] == "proftree":
        f = "game/graphics/opengl_renderer/OpenGLRenderer.cpp"
        s["anchors"] = mk("proftree", [(f, "  m_profiler.finish();\n"), (f, '#include "OpenGLRenderer.h"\n')])
(R / "ports/manifest.json").write_text(json.dumps(man, indent=1) + "\n")
print(len(A), "core anchors")
