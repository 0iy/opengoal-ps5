#!/usr/bin/env python3
"""Upstream patch (run in WSL, idempotent): real progress + cancel + faster extraction for the on-console ISO import.
Root of the jak-project tree: $JAK_ROOT (default ~/jak). Companion code: app/shim/importer.cpp (defines the two hooks).

  1. common/log/log.cpp          every lg::info/lg::print line is offered to ps5_import_log(level, msg) (weak symbol, so
                                 non-PS5 targets still link). The importer parses "Extracting ..." / "[Mem] After ..." /
                                 "stats for ..." lines for progress and may silence stdout (less console I/O, no fflush per line).
  2. goalc/make/MakeSystem.cpp   the build loop calls ps5_import_progress(4, done, total) -> real compile percent (and a cancel point).
  3. decompiler/extractor/main.cpp  after unpacking, the temporary iso_data/_temp is renamed into place instead of copied
                                 recursively (saves a full copy of the extracted disc, GBs of writes); falls back to the copy.
"""
import json
import os

ROOT = os.environ.get("JAK_ROOT") or os.path.expanduser("~/jak")
MAP = json.loads(os.environ.get("SYNC_FILE_MAP") or "{}")  # SYNC_FILE_MAP: see sync_upstream.py
MARK = "__ps5__ import progress"


def edit(rel, pairs):
    p = os.path.join(ROOT, MAP.get(rel, rel))
    s = open(p, encoding="utf-8").read()
    if MARK in s:
        print("already patched:", rel)
        return
    for old, new in pairs:
        assert s.count(old) == 1, (rel, old)
        s = s.replace(old, new)
    open(p, "w", encoding="utf-8").write(s)
    print("patched:", rel)


edit("common/log/log.cpp", [
    ('#include "log.h"\n',
     '#include "log.h"\n\n'
     'extern "C" int ps5_import_log(int level, const char* msg) __attribute__((weak));  // ' + MARK + '\n'),
    ("void log_message(level log_level, LogTime& now, const char* message) {\n",
     "void log_message(level log_level, LogTime& now, const char* message) {\n"
     "  const bool ps5_quiet = ps5_import_log && ps5_import_log(int(log_level), message);  // " + MARK + "\n"),
    ("    if (log_level >= gLogger.stdout_log_level ||\n"
     "        (log_level == level::die && gLogger.stdout_log_level == level::off_unless_die)) {\n",
     "    if (!ps5_quiet && (log_level >= gLogger.stdout_log_level ||\n"
     "        (log_level == level::die && gLogger.stdout_log_level == level::off_unless_die))) {\n"),
    ("void log_print(const char* message) {\n",
     "void log_print(const char* message) {\n"
     "  if (ps5_import_log && ps5_import_log(-1, message)) {\n    return;  // " + MARK + "\n  }\n"),
])

edit("goalc/make/MakeSystem.cpp", [
    ('#include "MakeSystem.h"\n',
     '#include "MakeSystem.h"\n\n'
     'extern "C" void ps5_import_progress(int stage, long long done, long long total) __attribute__((weak));  // ' + MARK + '\n'),
    ("    int percent = (100.0 * (1 + (i++)) / (deps.size())) + 0.5;\n",
     "    int percent = (100.0 * (1 + (i++)) / (deps.size())) + 0.5;\n"
     "    if (ps5_import_progress) {\n      ps5_import_progress(4, i - 1, (long long)deps.size());  // " + MARK + "\n    }\n"),
])

edit("decompiler/extractor/main.cpp", [
    ("        if (!file_util::is_dir_in_dir(iso_data_path, temp_iso_extract_location)) {\n"
     "          fs::copy(temp_iso_extract_location, iso_data_path, fs::copy_options::recursive);\n"
     "        }\n",
     "        if (!file_util::is_dir_in_dir(iso_data_path, temp_iso_extract_location)) {\n"
     "          std::error_code ps5_ec;  // " + MARK + ": rename instead of copying the whole disc\n"
     "          fs::rename(temp_iso_extract_location, iso_data_path, ps5_ec);\n"
     "          if (ps5_ec) {\n"
     "            fs::copy(temp_iso_extract_location, iso_data_path, fs::copy_options::recursive);\n"
     "          }\n"
     "        }\n"),
])
