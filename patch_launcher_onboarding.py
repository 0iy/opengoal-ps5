#!/usr/bin/env python3
"""Idempotent: replace the launcher's Import screen with the live onboarding view (per-game cards with real progress).
Needs ps5shim/include/ps5import.h (Ps5GameStatus, ps5_game_status, ps5_import_queue_text)."""
import os

p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ps5shim", "launcher.cpp")
s = open(p, encoding="utf-8").read()
if "ps5_game_status" in s:
    print("already patched")
    raise SystemExit
NL = chr(10)

s = s.replace('#include "ps5launcher.h"', '#include "ps5import.h"' + NL + '#include "ps5launcher.h"', 1)

helpers = r'''
// ---- onboarding view helpers
std::string fmt_bytes(unsigned long long b) {
  char t[32];
  if (b >= (1ull << 30)) std::snprintf(t, sizeof t, "%.1f GB", double(b) / double(1ull << 30));
  else if (b >= (1ull << 20)) std::snprintf(t, sizeof t, "%.0f MB", double(b) / double(1ull << 20));
  else std::snprintf(t, sizeof t, "%.0f KB", double(b) / 1024.0);
  return t;
}
std::string fmt_eta(int s) {
  char t[32];
  if (s < 0) return "";
  if (s >= 120) std::snprintf(t, sizeof t, "%d min", (s + 30) / 60);
  else std::snprintf(t, sizeof t, "%d s", s);
  return t;
}
const char* stage_label(const Ps5GameStatus& st) {
  switch (st.phase) {
    case 1: return L("Uploading", "Hochladen");
    case 2: return L("Checking", "Pr\xc3\xbc\x66\x65n");
    case 3: return L("Queued", "In Warteschlange");
    case 4:
      switch (st.stage) {
        case 1: return L("Preparing", "Vorbereiten");
        case 2: return L("Unpacking", "Entpacken");
        case 3: return L("Decompiling", "Dekompilieren");
        case 4: return L("Building", "Bauen");
        default: return L("Installing", "Einrichten");
      }
    case 5: return L("Ready", "Bereit");
    case 6: return L("Failed", "Fehlgeschlagen");
    default: return st.installed ? L("Ready", "Bereit") : L("Waiting for ISO", "Warte auf ISO");
  }
}
const char* reason_text(const char* r) {
  struct R { const char* key; const char* en; const char* de; };
  static const R t[] = {
      {"notiso", "Not an .iso file", "Keine .iso-Datei"},
      {"tiny", "File too small to be a disc", "Datei zu klein f\xc3\xbcr eine Disc"},
      {"raw", "Raw .bin image: use an .iso", "Rohes .bin-Abbild: nutze eine .iso"},
      {"truncated", "Upload incomplete or file cut off", "Datei unvollst\xc3\xa4ndig"},
      {"nosys", "No game found on this disc", "Kein Spiel auf dieser Disc"},
      {"unknown", "Unknown disc", "Unbekannte Disc"},
      {"wrong_game", "This is a different game", "Das ist ein anderes Spiel"},
      {"toolchain", "Tools missing, reinstall the app", "Werkzeuge fehlen, App neu installieren"},
      {"unknown_disc", "Unknown or modified disc", "Unbekannte oder ver\xc3\xa4nderte Disc"},
      {"bad_contents", "Disc contents damaged", "Disc-Inhalt besch\xc3\xa4\x64igt"},
      {"bad_iso", "Damaged .iso", "Besch\xc3\xa4\x64igte .iso"},
      {"extract", "Unpacking failed", "Entpacken fehlgeschlagen"},
      {"decompile", "Decompiling failed", "Dekompilieren fehlgeschlagen"},
      {"compile", "Building failed", "Bauen fehlgeschlagen"},
  };
  for (const R& e : t) if (std::strcmp(e.key, r) == 0) return L(e.en, e.de);
  return L("Import failed", "Import fehlgeschlagen");
}
'''
anchor = "enum Str {"
assert anchor in s
# helpers need L() and Ps5GameStatus: put them after the SettingRow builder block (end of build_rows)
marker = "void build_rows(SettingRow* r) {"
i = s.index(marker)
j = s.index(NL + "}" + NL, i) + 3
s = s[:j] + helpers + s[j:]

a = s.index("    } else if (scr.id == Screen::Import) {" + NL + "      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 240));")
b = s.index("    } else {" + NL + "      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 235));" + NL + '      text(dl, 60 * S, ImVec2(sbw + 96 * S, 200 * S), IM_COL32(255, 255, 255, 255), "Controls");')

new_view = r'''    } else if (scr.id == Screen::Import) {
      dl->AddRectFilled(ImVec2(sbw, 0), ImVec2(w, h), IM_COL32(8, 8, 10, 245));
      const float lx = sbw + 64 * S, rx = w - 64 * S;
      text(dl, 54 * S, ImVec2(lx, 50 * S), IM_COL32(255, 255, 255, 255), tr(S_TITLE));
      text(dl, 26 * S, ImVec2(lx, 118 * S), IM_COL32(170, 180, 210, 255),
           any_ready ? L("Add more games any time: drop the .iso files on the page below.",
                         "Weitere Spiele jederzeit hinzuf\xc3\xbc\x67\x65n: .iso-Dateien auf die Seite unten ziehen.")
                     : L("Add at least one game to start playing: drop your .iso on the page below.",
                         "F\xc3\xbc\x67\x65 mindestens ein Spiel hinzu: ziehe deine .iso auf die Seite unten."));
      // one live card per game
      const float gap = 22 * S, cw = (rx - lx - 2 * gap) / 3, cy = 172 * S, ch = 330 * S;
      for (int i = 0; i < kGameCount; ++i) {
        Ps5GameStatus st;
        std::memset(&st, 0, sizeof st);
        ps5_game_status(kGames[i].id, &st);
        const bool installed = st.installed || ready[i];
        const bool busy = st.phase >= 1 && st.phase <= 4;
        const bool failed = st.phase == 6;
        const bool done = !busy && !failed && installed;
        const float cx = lx + i * (cw + gap);
        const ImVec2 a0(cx, cy), b0(cx + cw, cy + ch);
        dl->AddRectFilled(a0, b0, IM_COL32(18, 20, 30, 255), 14 * S);
        if (tex.bg[i]) dl->AddImage(static_cast<ImTextureID>(tex.bg[i]), a0, ImVec2(b0.x, cy + 150 * S), ImVec2(0.2f, 0.2f), ImVec2(0.8f, 0.8f),
                                    done ? IM_COL32(255, 255, 255, 255) : IM_COL32(120, 120, 120, 255), 14 * S, ImDrawFlags_RoundCornersTop);
        const ImU32 edge = failed ? IM_COL32(248, 113, 113, 255) : done ? IM_COL32(74, 222, 128, 255) : busy ? kOrange : IM_COL32(50, 54, 70, 255);
        dl->AddRect(a0, b0, edge, 14 * S, 0, (busy ? 4 : 2) * S);
        const Tex& lg = tex.logo[i];
        if (lg.id) {
          const float lw = 150 * S, lh = lw * lg.h / lg.w;
          dl->AddImage(static_cast<ImTextureID>(lg.id), ImVec2(cx + 20 * S, cy + 20 * S), ImVec2(cx + 20 * S + lw, cy + 20 * S + lh));
        }
        // status line
        int pct = st.percent;
        if (pct < 0 && st.phase == 1 && st.total > 0) pct = int(100.0 * double(st.bytes) / double(st.total));
        char big[96];
        const char* label = stage_label(st);
        if (busy && pct >= 0) std::snprintf(big, sizeof big, "%s  %d%%", label, std::min(pct, 100));
        else std::snprintf(big, sizeof big, "%s", label);
        const ImU32 bigcol = failed ? IM_COL32(248, 113, 113, 255) : done ? IM_COL32(74, 222, 128, 255) : busy ? IM_COL32(255, 200, 120, 255) : IM_COL32(150, 156, 180, 255);
        text(dl, 34 * S, ImVec2(cx + 20 * S, cy + 168 * S), bigcol, big);
        // progress bar
        const float by = cy + 222 * S, bh = 14 * S, bx0 = cx + 20 * S, bx1 = cx + cw - 20 * S;
        dl->AddRectFilled(ImVec2(bx0, by), ImVec2(bx1, by + bh), IM_COL32(40, 44, 60, 255), bh * 0.5f);
        if (busy || done) {
          if (pct >= 0 || done) {
            const float fr = done ? 1.0f : std::min(1.0f, pct / 100.0f);
            dl->AddRectFilled(ImVec2(bx0, by), ImVec2(bx0 + (bx1 - bx0) * fr, by + bh), done ? IM_COL32(74, 222, 128, 255) : kOrange, bh * 0.5f);
          } else {  // unknown percent: moving segment
            const float seg = (bx1 - bx0) * 0.25f, t = std::fmod(float(now) * 0.9f, 1.0f) * ((bx1 - bx0) - seg);
            dl->AddRectFilled(ImVec2(bx0 + t, by), ImVec2(bx0 + t + seg, by + bh), kOrange, bh * 0.5f);
          }
        }
        // detail line
        char det[160] = "";
        if (failed) {
          std::snprintf(det, sizeof det, "%s", reason_text(st.reason));
        } else if (st.phase == 1 && st.total > 0) {
          std::snprintf(det, sizeof det, "%s / %s", fmt_bytes(st.bytes).c_str(), fmt_bytes(st.total).c_str());
        } else if (busy && st.stage_percent >= 0) {
          std::snprintf(det, sizeof det, "%s %d%%", label, st.stage_percent);
        } else if (!installed && !busy) {
          std::snprintf(det, sizeof det, "%s", L("Drop the .iso on the web page", ".iso auf die Webseite ziehen"));
        } else if (done) {
          std::snprintf(det, sizeof det, "%s", st.serial[0] ? st.serial : L("Installed", "Installiert"));
        }
        text(dl, 22 * S, ImVec2(cx + 20 * S, cy + 250 * S), IM_COL32(190, 198, 220, 255), det);
        if (busy) {
          char sp[96] = "";
          if (st.speed_bps > 0 && st.eta_s >= 0) std::snprintf(sp, sizeof sp, "%s/s  -  %s %s", fmt_bytes(st.speed_bps).c_str(), fmt_eta(st.eta_s).c_str(), L("left", "\xc3\xbc\x62rig"));
          else if (st.speed_bps > 0) std::snprintf(sp, sizeof sp, "%s/s", fmt_bytes(st.speed_bps).c_str());
          else if (st.elapsed_s > 0) std::snprintf(sp, sizeof sp, "%d s", st.elapsed_s);
          text(dl, 22 * S, ImVec2(cx + 20 * S, cy + 282 * S), IM_COL32(140, 148, 172, 255), sp);
        }
      }
      // how to + QR
      const float hy = cy + ch + 40 * S;
      const Str steps[3] = {S_STEP1, S_STEP2, S_STEP3};
      for (int i = 0; i < 3; ++i) text(dl, 28 * S, ImVec2(lx, hy + i * 54 * S), IM_COL32(220, 226, 246, 255), tr(steps[i]));
      text(dl, 30 * S, ImVec2(lx, hy + 3 * 54 * S + 8 * S), IM_COL32(255, 200, 120, 255), import_url.c_str());
      if (qr_n > 0) {
        const float mod = 8 * S, qz = 3 * mod, side = qr_n * mod + 2 * qz;
        const float qx = rx - side, qy = hy - 6 * S;
        dl->AddRectFilled(ImVec2(qx, qy), ImVec2(qx + side, qy + side), IM_COL32(255, 255, 255, 255), 8 * S);
        for (int y = 0; y < qr_n; ++y)
          for (int x = 0; x < qr_n; ++x)
            if (qr[size_t(y) * qr_n + x])
              dl->AddRectFilled(ImVec2(qx + qz + x * mod, qy + qz + y * mod), ImVec2(qx + qz + (x + 1) * mod, qy + qz + (y + 1) * mod), IM_COL32(0, 0, 0, 255));
      }
      const char* qt = ps5_import_queue_text();
      if (qt && qt[0]) text(dl, 28 * S, ImVec2(lx, h - 116 * S), kAmber, qt);
      if (ps5_import_state() == 1) text(dl, 24 * S, ImVec2(lx, h - 160 * S), IM_COL32(170, 180, 210, 255), tr(S_KEEPON));
      text(dl, 28 * S, ImVec2(lx, h - 66 * S), IM_COL32(170, 180, 210, 255),
           any_ready ? tr(S_HINT) : L("Square: language     Add at least one game to continue", "Quadrat: Sprache     F\xc3\xbc\x67\x65 mindestens ein Spiel hinzu, um fortzufahren"));
'''
s = s[:a] + new_view + s[b:]
open(p, "w", encoding="utf-8").write(s)
print("patched")
