#!/bin/bash
# Host-side smoke test of app/shim/webserver.cpp (WSL/Linux): stubs the importer, redirects /data/opengoal to a temp dir.
set -e
R=$(cd "$(dirname "$0")/../.." && pwd); T=$(mktemp -d); cd "$T"   # R = repository root
sed "s#/data/opengoal#$T/og#g" "$R/app/shim/webserver.cpp" > ws.cpp
cat > stub.cpp <<'EOF'
#include <cstdarg>
#include <cstring>
#include <atomic>
#include <unistd.h>
void ps5_log(const char*, ...) {}
const char* ps5_web_page() { return "<html>ok</html>"; }
std::atomic<int> st{0}; std::atomic<bool> cx{false}; int prog = 0;
extern "C" bool ps5_import_start(const char*, const char*, const char*) { st = 1; prog = 0; return true; }
extern "C" int ps5_import_state() { if (st == 1 && cx) st = 3; return st; }
extern "C" int ps5_import_rc() { return 0; }
extern "C" const char* ps5_import_stage() { return "decompile"; }
extern "C" int ps5_import_stage_id() { return 3; }
extern "C" int ps5_import_stage_percent() { return 50; }
extern "C" void ps5_import_cancel() { cx = true; }
extern "C" const char* ps5_import_reason() { return cx ? "cancelled" : ""; }
extern "C" const char* ps5_iso_probe(const char*, char* s, char* g, char* r) { strcpy(s, "SCUS-97265"); strcpy(g, "jak2"); strcpy(r, "NTSC-U"); return nullptr; }
extern "C" void ps5_web_start(int, const char*);
#include "include/ps5import.h"
int main() { ps5_web_start(18080, "127.0.0.1"); for (;;) { sleep(1); } }
EOF
g++ -std=c++17 -O1 -I "$R/app/shim" ws.cpp stub.cpp -o ws -lpthread
./ws & PID=$!; trap "kill $PID 2>/dev/null; rm -rf $T" EXIT; sleep 1
U=http://127.0.0.1:18080
head -c 3145728 /dev/urandom > body; head -c 1048576 body > c1; tail -c 2097152 body > c2   # total 3 MB, chunk 1 MB
curl -s -XPOST "$U/api/begin?game=jak2&total=3145728&chunk=1048576&fp=abc" | head -c 60; echo
curl -s -XPUT --data-binary @c1 "$U/api/chunk?game=jak2&off=0&total=3145728" -o /dev/null -w "chunk0 %{http_code}\n"
# interrupted: a second begin with same fp resumes and reports offset 0
curl -s -XPOST "$U/api/begin?game=jak2&total=3145728&chunk=1048576&fp=abc" | head -c 40; echo
curl -s -XPOST "$U/api/start?game=jak2" -w " start-incomplete %{http_code}\n"
head -c 1048576 body | tail -c 0 >/dev/null; dd if=body bs=1048576 skip=1 count=1 2>/dev/null > c1b; dd if=body bs=1048576 skip=2 count=1 2>/dev/null > c2b
curl -s -XPUT --data-binary @c1b "$U/api/chunk?game=jak2&off=1048576&total=3145728" -o /dev/null -w "chunk1 %{http_code}\n"
curl -s -XPUT --data-binary @c2b "$U/api/chunk?game=jak2&off=2097152&total=3145728" -o /dev/null -w "chunk2 %{http_code}\n"
curl -s -XPOST "$U/api/start?game=jak2" -o /dev/null -w "start %{http_code}\n"
sleep 1
curl -s "$U/api/status" | python3 -c "import sys,json;j=json.load(sys.stdin);g=j['games']['jak2'];print(j['version'],g['phase'],g['stage'],g['stage_percent'],g['percent'],j['overall'],j['settings'])"
curl -s -m 1 "$U/api/events" | head -c 80; echo
curl -s -XPOST "$U/api/cancel?game=jak2" -o /dev/null; sleep 1
curl -s "$U/api/status" | python3 -c "import sys,json;g=json.load(sys.stdin)['games']['jak2'];print(g['phase'],g['reason'])"
curl -s -XPOST "$U/api/settings?delete_iso=0" | python3 -c "import sys,json;print(json.load(sys.stdin)['settings'])"
ls "$T/og/import" | tr '\n' ' '; echo
