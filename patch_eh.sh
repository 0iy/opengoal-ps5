#!/usr/bin/env bash
# Create a linker script variant exporting the __eh_frame* bounds libunwind needs, point build-cxx.sh at it.
set -euo pipefail
cd "$HOME/ps5app"
python3 - <<'PY'
p = "tooling/native/ps5-pie.ld"
s = open(p).read()
old_hdr = "KEEP(*(.eh_frame_hdr))"
old_eh = "KEEP(*(.eh_frame))"
assert old_hdr in s and old_eh in s
s = s.replace(old_hdr, "PROVIDE_HIDDEN(__eh_frame_hdr_start = .); KEEP(*(.eh_frame_hdr)) PROVIDE_HIDDEN(__eh_frame_hdr_end = .);")
s = s.replace(old_eh, "PROVIDE_HIDDEN(__eh_frame_start = .); KEEP(*(.eh_frame)) PROVIDE_HIDDEN(__eh_frame_end = .);")
open("tooling/native/ps5-pie-eh.ld", "w").write(s)
PY
sed -i 's#\$native/ps5-pie.ld#$native/ps5-pie-eh.ld#g' tools/build-cxx.sh
grep -c 'ps5-pie-eh.ld' tools/build-cxx.sh
cat > cxxtest/src/rt_shim.cpp <<'CPP'
// Runtime shims libc++/libunwind expect on top of the system libc.
#include <cstdio>
#include <cstdlib>
extern "C" void __assert(const char *func, const char *file, int line, const char *expr)
{
    std::fprintf(stderr, "assert: %s %s:%d %s\n", func, file, line, expr);
    std::abort();
}
CPP
