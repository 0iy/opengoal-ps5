#!/usr/bin/env python3
"""Idempotent source patches that make jak-project (v0.3.6) build and run on the PS5.

Run from anywhere; patches ~/jak in place. Each patch is a (file, old, new) replacement and is
skipped when `new` is already present. Mark every patched site with `__ps5__`.
"""
import os
import sys

JAK = os.environ.get("JAK_ROOT") or os.path.expanduser("~/jak")  # JAK_ROOT: private copy (sync_upstream.py)

import json
FILE_MAP = json.loads(os.environ.get("SYNC_FILE_MAP") or "{}")  # sync_upstream.py: upstream moved/renamed a file


def rp(rel):
    return FILE_MAP.get(rel, rel)


PATCHES = []


def patch(path, old, new, count=1):
    PATCHES.append((path, old, new, count))


# --- threads: no Win32 fallback, skip thread naming -------------------------------------------
patch(
    "game/system/SystemThread.cpp",
    "#ifdef __linux\n  pthread_setname_np(pthread_self(), thd->name.c_str());\n#elif __APPLE__",
    "#if defined(__ps5__)\n  // no thread naming on the PS5\n#elif defined(__linux)\n  pthread_setname_np(pthread_self(), thd->name.c_str());\n#elif __APPLE__",
)

# --- per-thread CPU report: every SystemThread registers its name with the shim (app/shim/ps5sdl.cpp, 'threads:' log line)
patch(
    "game/system/SystemThread.cpp",
    "void* bootstrap_thread_func(void* x) {\n  SystemThread* thd = (SystemThread*)x;\n",
    "#if defined(__ps5__)\nextern \"C\" void ps5_thread_register(const char*);  // __ps5__\n#endif\nvoid* bootstrap_thread_func(void* x) {\n  SystemThread* thd = (SystemThread*)x;\n#if defined(__ps5__)\n  ps5_thread_register(thd->name.c_str());  // __ps5__\n#endif\n",
)

# --- file layout: config under /data/opengoal, executable path inside /app0 -------------------------
patch(
    "common/util/FileUtil.cpp",
    "#elif __linux\n  // Docs - https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html",
    "#elif defined(__ps5__)\n  config_base_path = fs::path(\"/data/opengoal/config\");\n#elif __linux\n  // Docs - https://specifications.freedesktop.org/basedir-spec/basedir-spec-latest.html",
)
patch(
    "common/util/FileUtil.cpp",
    "#elif __linux\n  char buffer[FILENAME_MAX + 1];",
    "#elif defined(__ps5__)\n  return std::string(\"/app0/eboot.bin\");\n#elif __linux\n  char buffer[FILENAME_MAX + 1];",
)


# --- OpenGL loading: gladLoadGL() dlopens libGL, which does not exist; use the SDL/EGL proc-address loader
patch(
    "game/graphics/pipelines/opengl.cpp",
    "      gladLoadGLLoader((GLADloadproc)SDL_GL_GetProcAddress);\n      if (!gladLoadGL()) {",
    "      if (!gladLoadGLLoader((GLADloadproc)SDL_GL_GetProcAddress)) {",
)

# --- ImGui's own GL loader dlopens libGL; point it at the PS5 GL entry point table instead ---------------
patch(
    "third-party/imgui/imgui_impl_opengl3_loader.h",
    "#elif defined(__APPLE__)\n#include <dlfcn.h>\n\nstatic void *libgl = NULL;",
    "#elif defined(__ps5__)\n#ifdef __cplusplus\nextern \"C\" {\n#endif\nextern const void* ps5_gl_lookup(const char*);\n#ifdef __cplusplus\n}\n#endif\nstatic int open_libgl(void) { return GL3W_OK; }\nstatic void close_libgl(void) {}\nstatic GL3WglProc get_proc(const char *proc) { return (GL3WglProc)ps5_gl_lookup(proc); }\n#elif defined(__APPLE__)\n#include <dlfcn.h>\n\nstatic void *libgl = NULL;",
)

# --- GOAL main memory: the PS5 refuses RWX in mmap (SEGV on execute), but accepts RW + mprotect(RWX) ----
patch(
    "game/runtime.cpp",
    """    g_ee_main_mem =
        (u8*)mmap((void*)EE_MAIN_MEM_MAP, EE_MAIN_MEM_SIZE, PROT_EXEC | PROT_READ | PROT_WRITE,
                  MAP_ANONYMOUS | MAP_PRIVATE, 0, 0);
  }
""",
    """#ifdef __ps5__
    // PS5: map read/write first (fd must be -1 for anonymous memory), then make it executable.
    g_ee_main_mem = (u8*)mmap((void*)EE_MAIN_MEM_MAP, EE_MAIN_MEM_SIZE, PROT_READ | PROT_WRITE,
                              MAP_ANONYMOUS | MAP_PRIVATE, -1, 0);
    if (g_ee_main_mem != (u8*)(-1) &&
        mprotect(g_ee_main_mem, EE_MAIN_MEM_SIZE, PROT_READ | PROT_WRITE | PROT_EXEC) != 0) {
      lg::error("mprotect(RWX) of the main memory failed: {}", strerror(errno));
      munmap(g_ee_main_mem, EE_MAIN_MEM_SIZE);
      g_ee_main_mem = (u8*)(-1);
    }
#else
    g_ee_main_mem =
        (u8*)mmap((void*)EE_MAIN_MEM_MAP, EE_MAIN_MEM_SIZE, PROT_EXEC | PROT_READ | PROT_WRITE,
                  MAP_ANONYMOUS | MAP_PRIVATE, 0, 0);
#endif
  }
""",
)

# --- CPU feature detection: the PS5 is a plain x86-64 (Zen 2) with AVX/AVX2 -------------------------
patch(
    "common/util/os.cpp",
    "#elif defined(__APPLE__)\n  setup_cpu_info_macos(gCpuInfo);\n#elif defined(__linux__)",
    "#elif defined(__APPLE__) || defined(__ps5__)\n  setup_cpu_info_macos(gCpuInfo);  // plain cpuid path, no sysctl\n#elif defined(__linux__)",
)


# --- platform branches: the PS5 is x86-64 System V (same ABI as Linux) ------------------------------
# Files whose `#ifdef __linux__` selects the System V calling convention / assembly entry points. Without
# this, functions such as make_function_from_c() fall off the end (compiled to ud2).
LINUX_ABI_FILES = [
    "game/kernel/jak1/kscheme.cpp",
    "game/kernel/jak2/kscheme.cpp",
    "game/kernel/jak3/kscheme.cpp",
    "game/kernel/jakx/kscheme.cpp",
    "game/kernel/common/kscheme.cpp",
    "game/kernel/common/kmachine.cpp",
    "game/mips2c/mips2c_table.cpp",
    "game/mips2c/mips2c_private.h",
]
ALL_REPLACEMENTS = [
    ("#ifdef __linux__", "#if defined(__linux__) || defined(__ps5__)"),
    ("#elif __linux__", "#elif defined(__linux__) || defined(__ps5__)"),
]


# --- ocean: after the per-level mip drawing, let the driver build the mip chain (render-to-mip-level is not supported)
patch(
    "game/graphics/opengl_renderer/ocean/OceanTexture.cpp",
    "    make_texture_with_mipmaps(render_state, prof);\n  }\n",
    "    make_texture_with_mipmaps(render_state, prof);\n    glBindTexture(GL_TEXTURE_2D, m_result_texture.texture());  // __ps5__\n    glGenerateMipmap(GL_TEXTURE_2D);\n  }\n",
    2,
)


# --- vertex inputs: the driver reads 16-bit integer vertex attributes through a per-draw CPU conversion. glfix.cpp
# re-declares them as 32-bit integers; the shaders unpack the halves.
patch(
    "game/graphics/opengl_renderer/Shader.cpp",
    '  vert_src = std::regex_replace(vert_src, std::regex("SCISSOR_ADJUST"), "(" + scissor_adjust + ")");\n',
    '  vert_src = std::regex_replace(vert_src, std::regex("SCISSOR_ADJUST"), "(" + scissor_adjust + ")");\n'
    '  // __ps5__: u16 integer attributes arrive as u32 (see app/shim/glfix.cpp)\n'
    '  vert_src = std::regex_replace(\n'
    '      vert_src, std::regex("in int time_of_day_index;"),\n'
    '      "in uint time_of_day_index_u32;\\n#define time_of_day_index (int(time_of_day_index_u32 & 0xffffu))");\n'
    '  vert_src = std::regex_replace(\n'
    '      vert_src, std::regex("in uvec2 flags_matrix;"),\n'
    '      "in uint flags_matrix_u32;\\n#define flags_matrix uvec2(flags_matrix_u32 & 0xffffu, flags_matrix_u32 >> 16)");\n'
    '  if (shader_name.find("sprite") != std::string::npos) {  // the direct shaders feed u8 data into tex_info_in\n'
    '    vert_src = std::regex_replace(\n'
    '        vert_src, std::regex("in uvec4 tex_info_in;"),\n'
    '        "in uvec2 tex_info_u32;\\n#define tex_info_in uvec4(tex_info_u32.x & 0xffffu, tex_info_u32.x >> 16, "\n'
    '        "tex_info_u32.y & 0xffffu, tex_info_u32.y >> 16)");\n'
    '  }\n',
)


# --- texture units: the PS5 driver exposes 16 sampler units. The engine binds the direct-renderer / sprite samplers to
# units 20..29 (tex_T20..tex_T29), which the driver silently drops (white quads: text, sprite glints). Remap to 0..9.
patch(
    "game/graphics/opengl_renderer/Shader.cpp",
    "      glUniform1i(texLoc, i);\n",
    "      glUniform1i(texLoc, i >= 20 ? i - 20 : i);  // __ps5__: driver has only 16 texture units\n",
)
patch(
    "game/graphics/opengl_renderer/DirectRenderer.cpp",
    "glActiveTexture(GL_TEXTURE20 + unit);",
    "glActiveTexture(GL_TEXTURE0 + unit);  // __ps5__: was GL_TEXTURE20 + unit",
)


# --- frame pacing: "accurate lag" rounds every frame up to a multiple of 1/60 s and sleeps the difference; when the
# renderer needs 33-45 ms that costs a whole extra vblank (20 fps instead of 30). Run the limiter at its plain target.
patch(
    "game/graphics/pipelines/opengl.cpp",
    "Gfx::g_global_settings.target_fps, Gfx::g_global_settings.experimental_accurate_lag,",
    "Gfx::g_global_settings.target_fps, false /* __ps5__: no accurate-lag rounding */,",
)


# --- extractor: report the current step to the on-console import page (see app/shim/importer.cpp) -----------------
patch(
    "decompiler/extractor/main.cpp",
    "ExtractorErrorCode decompile(const fs::path& in_folder,\n                             const std::string& data_subfolder,\n                             const std::string& config_override) {\n",
    "extern \"C\" void ps5_import_stage_set(const char*);  // __ps5__\nExtractorErrorCode decompile(const fs::path& in_folder,\n                             const std::string& data_subfolder,\n                             const std::string& config_override) {\n  ps5_import_stage_set(\"decompile\");  // __ps5__\n",
)
patch(
    "decompiler/extractor/main.cpp",
    "ExtractorErrorCode compile(const fs::path& iso_data_path, const std::string& data_subfolder) {\n",
    "ExtractorErrorCode compile(const fs::path& iso_data_path, const std::string& data_subfolder) {\n  ps5_import_stage_set(\"compile\");  // __ps5__\n",
)
patch(
    "decompiler/extractor/main.cpp",
    "int main(int argc, char** argv) {\n  ArgumentGuard u8_guard(argc, argv);",
    "int main(int argc, char** argv) {\n  ps5_import_stage_set(\"extract\");  // __ps5__\n  ArgumentGuard u8_guard(argc, argv);",
)

# --- textures: a GL_RGB internal format becomes an RGBX surface on Mesa; the PS5 driver only blits RGBA8 on the GPU
# (anything else falls back to a per-pixel CPU copy). All of these are empty render-target textures (no data).
_RGB_FILES = [
    "game/graphics/opengl_renderer/opengl_utils.cpp",
    "game/graphics/opengl_renderer/DepthCue.cpp",
    "game/graphics/opengl_renderer/sprite/Sprite3_Distort.cpp",
]


def patch_rgb_textures():
    import re
    changed = 0
    pat = re.compile(r"glTexImage2D\(GL_TEXTURE_2D, 0, GL_RGB,([^;]*?)GL_RGB,(\s*)GL_UNSIGNED_BYTE,(\s*)NULL\);", re.S)
    for rel in _RGB_FILES:
        path = os.path.join(JAK, rp(rel))
        text = open(path, encoding="utf-8").read()
        new = pat.sub(lambda m: "glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8,%sGL_RGBA,%sGL_UNSIGNED_BYTE,%sNULL);  // __ps5__" % (m.group(1), m.group(2), m.group(3)), text)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            print(f"patched {rel}")
            changed += 1
    return changed


def patch_linux_abi():
    n = 0
    for rel in LINUX_ABI_FILES:
        path = os.path.join(JAK, rp(rel))
        text = open(path, encoding="utf-8").read()
        new = text
        for old, rep in ALL_REPLACEMENTS:
            new = new.replace(old, rep)
        if new != text:
            open(path, "w", encoding="utf-8").write(new)
            print(f"patched {rel} (linux ABI branches)")
            n += 1
    return n


def anchor_report(text, old):
    """Where the first line of an anchor sits in the file (1-based), to find what upstream changed."""
    first = old.split(chr(10), 1)[0].strip()
    hits = [i + 1 for i, ln in enumerate(text.split(chr(10))) if first and first in ln]
    return f"first anchor line {first!r} found at line(s) {hits[:5] if hits else 'NONE (removed/renamed upstream?)'}"


def main():
    changed = patch_linux_abi() + patch_rgb_textures()
    failed = 0
    for rel, old, new, count in PATCHES:
        path = os.path.join(JAK, rp(rel))
        text = open(path, encoding="utf-8").read()
        if new in text:
            continue
        if text.count(old) != count:
            # report every failing anchor (not just the first); nothing is written for it
            print(f"PATCH FAILED {rel}: expected {count} match(es), found {text.count(old)}; {anchor_report(text, old)}")
            failed += 1
            continue
        open(path, "w", encoding="utf-8").write(text.replace(old, new))
        print(f"patched {rel}")
        changed += 1
    print(f"{changed} patch(es) applied, {len(PATCHES)} total, {failed} failed")
    sys.exit(1 if failed else 0)


main()
