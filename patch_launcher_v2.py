#!/usr/bin/env python3
"""One-shot, idempotent patch of ps5shim/launcher.cpp: settings rows (locked + custom), clearer main-screen navigation,
forced onboarding until one game is installed, guide for locked games."""
import os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps5shim", "launcher.cpp")
s = open(p, encoding="utf-8").read()
if "build_rows" in s:
    print("already patched")
    raise SystemExit

NL = chr(10)


def rep(old, new, count=1):
    global s
    assert s.count(old) >= 1, old[:60]
    s = s.replace(old, new, count)


# ---- helpers: L(), setting rows
rep("const char* tr(Str s) { return kText[g_settings.lang ? 1 : 0][s]; }", NL.join([
    "const char* tr(Str s) { return kText[g_settings.lang ? 1 : 0][s]; }",
    "const char* L(const char* en, const char* de) { return g_settings.lang ? de : en; }",
    "",
    "// Settings rows. Locked rows are shown greyed out: Windows concepts or values fixed by the PS5 output.",
    "enum SettingId { SET_WINDOW, SET_RES, SET_FPS, SET_VSYNC, SET_MERGE, SET_ASYNC, SET_LAZYMIPS, SET_FSR, SET_LANG, SET_ADD, SET_COUNT };",
    "struct SettingRow {",
    "  const char* name;",
    "  std::string value;",
    "  bool enabled;",
    "  const char* hint;",
    "};",
    "void build_rows(SettingRow* r) {",
    "  auto onoff = [](int v) { return std::string(v ? L(\"On\", \"An\") : L(\"Off\", \"Aus\")); };",
    "  r[SET_WINDOW] = {L(\"Window mode\", \"Fenstermodus\"), L(\"Fullscreen (fixed)\", \"Vollbild (fest)\"), false,",
    "                   L(\"Locked: a PS5 always runs fullscreen.\", \"Gesperrt: eine PS5 l\\xc3\\xa4uft immer im Vollbild.\")};",
    "  r[SET_RES] = {L(\"Output resolution\", \"Ausgabeaufl\\xc3\\xb6sung\"), kResolutions[g_settings.resolution].label, true,",
    "                L(\"The game renders at this size. 4K needs far more GPU time. Applies at the next start.\",",
    "                  \"Das Spiel rendert in dieser Gr\\xc3\\xb6\\xc3\\x9f\\x65. 4K braucht viel mehr GPU-Zeit. Gilt ab dem n\\xc3\\xa4\\x63hsten Start.\")};",
    "  r[SET_FPS] = {L(\"Frame rate\", \"Bildrate\"), \"60 fps\", false,",
    "                L(\"Locked: the game logic runs at 60 fps.\", \"Gesperrt: die Spiellogik l\\xc3\\xa4uft mit 60 fps.\")};",
    "  r[SET_VSYNC] = {\"V-Sync\", L(\"On (fixed)\", \"An (fest)\"), false,",
    "                  L(\"Locked: the PS5 output is always synchronised.\", \"Gesperrt: die PS5-Ausgabe ist immer synchronisiert.\")};",
    "  r[SET_MERGE] = {L(\"Draw merging\", \"Draw-Zusammenfassung\"), onoff(g_settings.merge), true,",
    "                  L(\"Fewer GPU draw calls (about +10 fps in Jak 2). Turn off if you see broken geometry.\",",
    "                    \"Weniger GPU-Aufrufe (ca. +10 fps in Jak 2). Bei kaputter Geometrie ausschalten.\")};",
    "  r[SET_ASYNC] = {L(\"Async GPU submit\", \"Asynchrones GPU-Senden\"), onoff(g_settings.async_md), true,",
    "                  L(\"Prepares draws on worker threads. Turn off to look for visual glitches.\",",
    "                    \"Bereitet Draws in Arbeitsthreads vor. Zur Fehlersuche ausschalten.\")};",
    "  r[SET_LAZYMIPS] = {L(\"Lazy mipmaps (experimental)\", \"Faule Mipmaps (experimentell)\"), onoff(g_settings.lazy_mips), true,",
    "                     L(\"Skips unused mipmap work (about +2 fps in Jak 2). Distant surfaces may flicker.\",",
    "                       \"\\xc3\\x9c\\x62\\x65rspringt unn\\xc3\\xb6tige Mipmap-Arbeit (ca. +2 fps in Jak 2). Ferne Fl\\xc3\\xa4\\x63hen k\\xc3\\xb6nnen flackern.\")};",
    "  r[SET_FSR] = {L(\"Upscaling (FSR)\", \"Hochskalierung (FSR)\"), L(\"Not available yet\", \"Noch nicht verf\\xc3\\xbcgbar\"), false,",
    "                L(\"Planned: render below the output size and upscale with FSR 1.0.\",",
    "                  \"Geplant: unter Ausgabegr\\xc3\\xb6\\xc3\\x9f\\x65 rendern und mit FSR 1.0 hochskalieren.\")};",
    "  r[SET_LANG] = {L(\"Language\", \"Sprache\"), g_settings.lang ? \"Deutsch\" : \"English\", true, L(\"Launcher language.\", \"Sprache des Launchers.\")};",
    "  r[SET_ADD] = {tr(S_ADD_ROW), \">\", true, L(\"Open the page to add or re-add a game.\", \"Seite zum Hinzuf\\xc3\\xbc\\x67\\x65n eines Spiels \\xc3\\xb6\\x66\\x66nen.\")};",
    "}",
]))

# ---- state: any game ready
rep("  double rescan = 0;" + NL, "  double rescan = 0;" + NL + "  bool any_ready = false;" + NL)
rep("  {" + NL + "    bool any = false;" + NL + "    for (int i = 0; i < kGameCount; ++i) any = any || ready[i];" + NL + "    if (!any) scr.id = Screen::Import;  // first start: guide the player through adding a game" + NL + "  }" + NL,
    "  for (int i = 0; i < kGameCount; ++i) any_ready = any_ready || ready[i];" + NL +
    "  if (!any_ready) scr.id = Screen::Import;  // onboarding: forced until at least one game is installed" + NL)
rep("      for (int i = 0; i < kGameCount; ++i) ready[i] = game_ready(kGames[i].id);" + NL + "    }" + NL,
    "      any_ready = false;" + NL + "      for (int i = 0; i < kGameCount; ++i) { ready[i] = game_ready(kGames[i].id); any_ready = any_ready || ready[i]; }" + NL +
    "    }" + NL)

# ---- input: main, settings, import
a = s.index("    } else if (scr.id == Screen::Main) {" + NL + "      if (in.pressed(PAD_L1)")
b = s.index("    } else if (scr.id == Screen::Import) {" + NL + "      if (in.pressed(PAD_SQUARE))")
new_in = NL.join([
    "    } else if (!any_ready && scr.id != Screen::Import) {",
    "      scr.id = Screen::Import;  // onboarding is mandatory",
    "    } else if (scr.id == Screen::Main) {",
    "      // Left/Right (or L1/R1) always pick the game. Up/Down move between Play and the two buttons below it;",
    "      // on the lower row Left/Right switch between Settings and Controls.",
    "      if (in.pressed(PAD_L1) || (focus == 0 && f_left)) sel = (sel + kGameCount - 1) % kGameCount;",
    "      if (in.pressed(PAD_R1) || (focus == 0 && f_right)) sel = (sel + 1) % kGameCount;",
    "      if (f_down && focus == 0) focus = 1;",
    "      else if (f_up && focus != 0) focus = 0;",
    "      else if (focus != 0 && f_left) focus = 1;",
    "      else if (focus != 0 && f_right) focus = 2;",
    "      if (in.pressed(PAD_TRIANGLE) || in.pressed(PAD_OPTIONS)) { scr.id = Screen::Settings; settings_sel = SET_RES; }",
    "      if (in.pressed(PAD_SQUARE)) scr.id = Screen::Controls;",
    "      if (confirm && focus == 1) { scr.id = Screen::Settings; settings_sel = SET_RES; }",
    "      else if (confirm && focus == 2) scr.id = Screen::Controls;",
    "      else if (confirm) {",
    "        if (ready[sel] && ps5_import_state() == 1) {  // the extractor and the engine share process-wide state, so no Play while importing",
    "          toast = tr(S_BUSY);",
    "          toast_until = now + 4.0;",
    "        } else if (ready[sel]) {",
    "          g_settings.last_game = sel;",
    "          ps5_settings_save();",
    "          out->game = kGames[sel].id;",
    "          out->project_path = game_dir(kGames[sel].id);",
    "          start_game = true;",
    "          if (out->on_start) {",
    "            launching = true;  // animate, then boot the engine while the loading screen keeps running",
    "            launch_t0 = now;",
    "          } else {",
    "            done = true;",
    "          }",
    "        } else {",
    "          scr.id = Screen::Import;",
    "        }",
    "      }",
    "    } else if (scr.id == Screen::Settings) {",
    "      SettingRow rows[SET_COUNT];",
    "      build_rows(rows);",
    "      if (!rows[settings_sel].enabled) settings_sel = SET_RES;",
    "      const int step = f_down ? 1 : (f_up ? SET_COUNT - 1 : 0);",
    "      if (step) {",
    "        do settings_sel = (settings_sel + step) % SET_COUNT;",
    "        while (!rows[settings_sel].enabled);  // greyed rows are skipped",
    "      }",
    "      const int dir = f_left ? -1 : (f_right || confirm ? 1 : 0);",
    "      if (dir != 0) {",
    "        bool changed = true;",
    "        switch (settings_sel) {",
    "          case SET_RES: g_settings.resolution = (g_settings.resolution + 3 + dir) % 3; break;",
    "          case SET_MERGE: g_settings.merge = 1 - g_settings.merge; break;",
    "          case SET_ASYNC: g_settings.async_md = 1 - g_settings.async_md; break;",
    "          case SET_LAZYMIPS: g_settings.lazy_mips = 1 - g_settings.lazy_mips; break;",
    "          case SET_LANG: g_settings.lang = 1 - g_settings.lang; changed = false; break;",
    "          case SET_ADD: scr.id = Screen::Import; changed = false; break;",
    "          default: changed = false; break;",
    "        }",
    "        ps5_settings_save();",
    "        if (changed) {",
    "          toast = L(\"Changes apply the next time OpenGOAL is opened\", \"\\xc3\\x84nderungen gelten ab dem n\\xc3\\xa4\\x63hsten Start von OpenGOAL\");",
    "          toast_until = now + 3.0;",
    "        }",
    "      }",
    "      if (back) scr.id = Screen::Main;",
])
s = s[:a] + new_in + NL + s[b:]
rep("      if (back) scr.id = Screen::Main;" + NL + "    } else {" + NL + "      if (back || confirm) scr.id = Screen::Main;",
    "      if (back && any_ready) scr.id = Screen::Main;  // forced onboarding: no way out before one game is installed" + NL + "    } else {" + NL + "      if (back || confirm) scr.id = Screen::Main;")

# ---- draw: main buttons labels + hint + guide, settings screen
rep('f ? IM_COL32(255, 255, 255, 255) : IM_COL32(200, 200, 200, 255), k == 0 ? "Display" : "Controls");',
    'f ? IM_COL32(255, 255, 255, 255) : IM_COL32(200, 200, 200, 255), k == 0 ? L("Settings", "Einstellungen") : L("Controls", "Steuerung"));')
a = s.index('      text(dl, 26 * S, ImVec2(sbw + 40 * S, h - 62 * S), IM_COL32(210, 214, 224, 200),' + NL + '           "L1 / R1: game')
b = s.index("    } else if (scr.id == Screen::Settings) {" + NL + "      dl->AddRectFilled(ImVec2(sbw, 0)")
new_hint = NL.join([
    "      // guide for a game that is not installed yet",
    "      if (!ready[sel]) {",
    "        char guide[200];",
    "        std::snprintf(guide, sizeof guide, \"%s %s\", L(\"Locked. Open\", \"Gesperrt. \\xc3\\x96\\x66\\x66ne\"), import_url.c_str());",
    "        text(dl, 30 * S, ImVec2(sbw + 40 * S, h - 150 * S), IM_COL32(255, 200, 120, 255), guide);",
    "        text(dl, 28 * S, ImVec2(sbw + 40 * S, h - 108 * S), IM_COL32(210, 214, 224, 220),",
    "             L(\"on your phone or PC and drop your .iso of this game there.\", \"auf Handy oder PC und ziehe deine .iso dieses Spiels dorthin.\"));",
    "      }",
    "      // arrows around the title show that Left/Right change the game while Play is selected",
    "      if (focus == 0) {",
    "        const float ay = h - 70 * S - 70 * S - 16 * S - 90 * S - 20 * S - 62 * S - (kGames[sel].subtitle[0] ? 46 * S : 0) + 22 * S;",
    "        text(dl, 40 * S, ImVec2(bx - 54 * S, ay), IM_COL32(255, 255, 255, 170), \"<\");",
    "        text(dl, 40 * S, ImVec2(w - 70 * S + 14 * S, ay), IM_COL32(255, 255, 255, 170), \">\");",
    "      }",
    "      text(dl, 26 * S, ImVec2(sbw + 40 * S, h - 62 * S), IM_COL32(210, 214, 224, 200),",
    "           L(\"Left / Right or L1 / R1: game     Cross: select     Triangle: settings     Square: controls\",",
    "             \"Links / Rechts oder L1 / R1: Spiel     Kreuz: ausw\\xc3\\xa4hlen     Dreieck: Einstellungen     Quadrat: Steuerung\"));",
])
s = s[:a] + new_hint + NL + s[b:]

a = s.index("    } else if (scr.id == Screen::Settings) {" + NL + "      dl->AddRectFilled(ImVec2(sbw, 0)")
b = s.index("    } else if (scr.id == Screen::Import) {" + NL + "      dl->AddRectFilled(ImVec2(sbw, 0)")
new_set = NL.join([
    "    } else if (scr.id == Screen::Settings) {",
    "      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 235));",
    "      text(dl, 60 * S, ImVec2(sbw + 96 * S, 90 * S), IM_COL32(255, 255, 255, 255), L(\"Settings\", \"Einstellungen\"));",
    "      SettingRow rows[SET_COUNT];",
    "      build_rows(rows);",
    "      for (int i = 0; i < SET_COUNT; ++i) {",
    "        const float y = (190 + i * 68 + (i >= SET_MERGE ? 30 : 0)) * S;  // gap between the fixed and the custom group",
    "        const bool selected = (i == settings_sel), on = rows[i].enabled;",
    "        const ImVec2 a(sbw + 96 * S, y), b(w - 96 * S, y + 60 * S);",
    "        dl->AddRectFilled(a, b, selected ? IM_COL32(40, 52, 98, 255) : (on ? IM_COL32(24, 30, 56, 255) : IM_COL32(18, 18, 22, 255)), 16 * S);",
    "        if (selected) dl->AddRect(a, b, kOrange, 16 * S, 0, 4 * S);",
    "        const ImU32 nc = on ? IM_COL32(255, 255, 255, 255) : IM_COL32(110, 110, 120, 255);",
    "        text(dl, 32 * S, ImVec2(a.x + 36 * S, y + 12 * S), nc, rows[i].name);",
    "        char shown[128];",
    "        if (on) std::snprintf(shown, sizeof shown, \"<  %s  >\", rows[i].value.c_str());",
    "        else std::snprintf(shown, sizeof shown, \"%s\", rows[i].value.c_str());",
    "        text(dl, 32 * S, ImVec2(b.x - 36 * S - text_width(32 * S, shown), y + 12 * S), on ? IM_COL32(255, 200, 120, 255) : IM_COL32(110, 110, 120, 255), shown);",
    "      }",
    "      {",
    "        const float gy = (190 + SET_MERGE * 68 + 6) * S;",
    "        text(dl, 22 * S, ImVec2(sbw + 96 * S, gy - 4 * S), IM_COL32(150, 160, 190, 255), L(\"CUSTOM\", \"ERWEITERT\"));",
    "      }",
    "      text(dl, 28 * S, ImVec2(sbw + 96 * S, h - 120 * S), IM_COL32(200, 210, 240, 255), rows[settings_sel].hint);",
    "      text(dl, 28 * S, ImVec2(sbw + 96 * S, h - 70 * S), IM_COL32(170, 180, 210, 255),",
    "           L(\"Up / Down: choose     Left / Right or Cross: change     Circle: back\", \"Hoch / Runter: w\\xc3\\xa4hlen     Links / Rechts oder Kreuz: \\xc3\\xa4ndern     Kreis: zur\\xc3\\xbc\\x63k\"));",
])
s = s[:a] + new_set + NL + s[b:]
open(p, "w", encoding="utf-8").write(s)
print("patched")
