#!/bin/bash
# Host-side smoke test of app/shim/webserver.cpp (WSL/Linux): status, info, cancel, the removed upload endpoints; /data/opengoal -> temp dir.
set -e
R=$(cd "$(dirname "$0")/../.." && pwd); T=$(mktemp -d); cd "$T"   # R = repository root
sed "s#/data/opengoal#$T/og#g" "$R/app/shim/webserver.cpp" > ws.cpp
cat > stub.cpp <<'EOF'
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <atomic>
#include <unistd.h>
void ps5_log(const char*, ...) {}
const char* ps5_web_page() { return "<html>ok</html>"; }
extern "C" bool ps5sdl_game_active() { return false; }
extern "C" unsigned ps5sdl_slow_frames() { return 0; }
extern "C" void ps5_web_start(int, const char*);
#include "include/ps5import.h"
int main() { ps5_web_start(18080, "127.0.0.1"); for (;;) { sleep(1); } }
EOF
g++ -std=c++17 -O1 -I "$R/app/shim" ws.cpp stub.cpp -o ws -lpthread
./ws & PID=$!; trap "kill $PID 2>/dev/null; rm -rf $T" EXIT; sleep 1
U=http://127.0.0.1:18080
curl -s "$U/" -o /dev/null -w "page %{http_code}\n"
curl -s "$U/api/info" | python3 -c "import sys,json;j=json.load(sys.stdin);print('info', j['install_api'], j['busy'])"
curl -s "$U/api/status" | python3 -c "import sys,json;j=json.load(sys.stdin);g=j['games']['jak2'];print('status', j['version'], g['phase'], g['installed'], j['overall'])"
curl -s -m 1 "$U/api/events" | head -c 40; echo
curl -s -XPOST "$U/api/cancel?game=jak2" -w "cancel %{http_code}\n" -o /dev/null
for e in begin chunk start settings; do curl -s -XPOST "$U/api/$e?game=jak2" -o /dev/null -w "$e %{http_code}\n"; done   # the upload is gone
