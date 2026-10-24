#!/usr/bin/env python3
"""Idempotent: wire FSR / dynamic resolution (docs/FSR.md) into launcher.cpp, ps5launcher.h, appmain.cpp."""
import os

root = os.path.dirname(os.path.abspath(__file__))


def edit(rel, fn):
    p = os.path.join(root, rel)
    s = open(p, encoding="utf-8").read()
    t = fn(s)
    if t != s:
        open(p, "w", encoding="utf-8").write(t)
        print("patched", rel)
    else:
        print("unchanged", rel)


def rep(s, old, new):
    assert old in s, old[:70]
    return s.replace(old, new, 1)


NL = chr(10)


def header(s):
    if "upscale" in s:
        return s
    return rep(s, "  int lazy_mips = 0;", "  int upscale = 0;     // 0 off, 1 quality 83%, 2 balanced 67%, 3 performance 50%, 4 auto (FSR 1.0)" + NL +
               "  int sharpness = 7;   // FSR RCAS strength 0..10" + NL + "  int lazy_mips = 0;")


def launcher(s):
    if "SET_SHARP" in s:
        return s
    s = rep(s, '    else if (std::sscanf(line, "lazymips=%d", &v) == 1) g_settings.lazy_mips = v ? 1 : 0;',
            '    else if (std::sscanf(line, "lazymips=%d", &v) == 1) g_settings.lazy_mips = v ? 1 : 0;' + NL +
            '    else if (std::sscanf(line, "upscale=%d", &v) == 1) g_settings.upscale = std::clamp(v, 0, 4);' + NL +
            '    else if (std::sscanf(line, "sharpness=%d", &v) == 1) g_settings.sharpness = std::clamp(v, 0, 10);')
    s = rep(s, "SET_LAZYMIPS, SET_FSR, SET_LANG", "SET_LAZYMIPS, SET_FSR, SET_SHARP, SET_LANG")
    a = s.index("  r[SET_FSR] = {")
    b = s.index("  r[SET_LANG] = {")
    new = NL.join([
        '  static const char* const kUpEn[] = {"Off", "Quality (83%)", "Balanced (67%)", "Performance (50%)", "Auto"};',
        '  static const char* const kUpDe[] = {"Aus", "Qualit\\xc3\\xa4t (83%)", "Ausgewogen (67%)", "Leistung (50%)", "Auto"};',
        '  r[SET_FSR] = {L("Upscaling (FSR)", "Hochskalierung (FSR)"), g_settings.lang ? kUpDe[g_settings.upscale] : kUpEn[g_settings.upscale], true,',
        '                L("Renders below the output size and upscales with FSR 1.0. Auto lowers the size when the frame rate drops.",',
        '                  "Rendert unter der Ausgabegr\\xc3\\xb6\\xc3\\x9f\\x65 und skaliert mit FSR 1.0 hoch. Auto verkleinert bei niedriger Bildrate.")};',
        '  r[SET_SHARP] = {L("Sharpness", "Sch\\xc3\\xa4rfe"), std::to_string(g_settings.sharpness), g_settings.upscale > 0,',
        '                  L("FSR sharpening, 0 = off.", "FSR-Sch\\xc3\\xa4rfung, 0 = aus.")};',
        "",
    ])
    s = s[:a] + new + s[b:]
    s = rep(s, "          case SET_LAZYMIPS: g_settings.lazy_mips = 1 - g_settings.lazy_mips; break;",
            "          case SET_LAZYMIPS: g_settings.lazy_mips = 1 - g_settings.lazy_mips; break;" + NL +
            "          case SET_FSR: g_settings.upscale = (g_settings.upscale + 5 + dir) % 5; break;" + NL +
            "          case SET_SHARP: g_settings.sharpness = std::clamp(g_settings.sharpness + dir, 0, 10); break;")
    # settings list is now 11 rows: tighten the row pitch so it still fits at 1080p
    s = s.replace("(190 + i * 68 + (i >= SET_MERGE ? 30 : 0)) * S", "(170 + i * 62 + (i >= SET_MERGE ? 26 : 0)) * S")
    s = s.replace("ImVec2(sbw + 96 * S, 190 * S)", "ImVec2(sbw + 96 * S, 170 * S)")
    s = s.replace("(190 + SET_MERGE * 68 + 6) * S", "(170 + SET_MERGE * 62 + 4) * S")
    s = s.replace("b(w - 96 * S, y + 60 * S);", "b(w - 96 * S, y + 54 * S);")
    s = s.replace("ImVec2(a.x + 36 * S, y + 12 * S), nc, rows[i].name);", "ImVec2(a.x + 36 * S, y + 9 * S), nc, rows[i].name);")
    s = s.replace("shown), y + 12 * S), on ?", "shown), y + 9 * S), on ?")
    return s


def appmain(s):
    if "PS5_RENDER_SCALE" in s:
        return s
    anchor = "  const Ps5Settings& cfg = ps5_settings();"
    block = NL.join([
        "  {  // dynamic resolution + FSR (docs/FSR.md). Developer flag files win over ps5.cfg.",
        '    static const char* const kScale[] = {nullptr, "83", "67", "50", "auto"};',
        "    if (cfg.upscale > 0 && cfg.upscale <= 4) {",
        '      setenv("PS5_RENDER_SCALE", kScale[cfg.upscale], 1);',
        '      setenv("PS5_FSR_SHARP", std::to_string(cfg.sharpness).c_str(), 1);',
        '      setenv("PS5_FSR_REFRESH", std::to_string(cfg.refresh).c_str(), 1);',
        "    }",
        "    int rs = 0;",
        '    if (FILE* rf = std::fopen("/data/opengoal/config/renderscale.txt", "r")) {  // content: 33..100 or 0 (= auto)',
        '      if (std::fscanf(rf, "%d", &rs) == 1 && rs >= 0) setenv("PS5_RENDER_SCALE", rs >= 100 ? "100" : (rs == 0 ? "auto" : std::to_string(rs).c_str()), 1);',
        "      std::fclose(rf);",
        "    }",
        "    struct stat nf;",
        '    if (stat("/data/opengoal/config/nofsr.txt", &nf) == 0) setenv("PS5_FSR", "0", 1);  // scaled render, plain bilinear blit',
        '    if (FILE* sf = std::fopen("/data/opengoal/config/fsrsharp.txt", "r")) {            // content: 0..10',
        "      int v = 0;",
        '      if (std::fscanf(sf, "%d", &v) == 1 && v >= 0 && v <= 10) setenv("PS5_FSR_SHARP", std::to_string(v).c_str(), 1);',
        "      std::fclose(sf);",
        "    }",
        "  }",
    ])
    return rep(s, anchor, anchor + NL + block)


edit("ps5shim/include/ps5launcher.h", header)
edit("ps5shim/launcher.cpp", launcher)
edit("ps5shim/appmain.cpp", appmain)
