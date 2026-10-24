#!/bin/bash
# Host-side test of the PC install path (WSL/Linux): builds ps5shim/webserver.cpp with a stubbed importer and /data/opengoal redirected
# to a temp dir, starts it, then drives it with the real pc_import.py upload code (tests_install_e2e.py).
set -e
R=$(cd "$(dirname "$0")" && pwd); T=$(mktemp -d); cd "$T"
sed "s#/data/opengoal#$T/og#g" "$R/ps5shim/webserver.cpp" > ws.cpp
cat > stub.cpp <<'EOF'
#include <cstdarg>
#include <cstring>
#include <unistd.h>
void ps5_log(const char*, ...) {}
const char* ps5_web_page() { return "<html>ok</html>"; }
extern "C" bool ps5_import_start(const char*, const char*, const char*) { return true; }
extern "C" int ps5_import_state() { return 0; }
extern "C" int ps5_import_rc() { return 0; }
extern "C" const char* ps5_import_stage() { return "idle"; }
extern "C" int ps5_import_stage_id() { return 0; }
extern "C" int ps5_import_stage_percent() { return -1; }
extern "C" void ps5_import_cancel() {}
extern "C" const char* ps5_import_reason() { return ""; }
extern "C" const char* ps5_iso_probe(const char*, char*, char*, char*) { return "notiso"; }
extern "C" void ps5_web_start(int, const char*);
int main() { ps5_web_start(18091, "127.0.0.1"); for (;;) sleep(1); }
EOF
g++ -std=c++17 -O2 -Wall -Wextra -I "$R/ps5shim" ws.cpp stub.cpp -o ws -lpthread
g++ -std=c++17 -O2 -Wall -Wextra -I "$R/ps5shim" "$R/tests_install.cpp" -o rx
mkdir -p og
./ws & PID=$!; trap "kill $PID 2>/dev/null; rm -rf $T" EXIT; sleep 1
WS_PORT=18091 WS_ROOT="$T/og" RX_BIN="$T/rx" python3 "$R/tests_install_e2e.py"
