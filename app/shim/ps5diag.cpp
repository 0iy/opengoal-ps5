// Development diagnostics: exercise the ghc::filesystem calls the engine makes and log which fail.
#include <exception>
#include <string>

#include "common/util/FileUtil.h"

void ps5_log(const char* fmt, ...);

#define TRY(label, expr)                                              \
  try {                                                               \
    expr;                                                             \
    ps5_log("fsdiag %-28s ok", label);                                \
  } catch (const std::exception& e) {                                 \
    ps5_log("fsdiag %-28s EXC: %s", label, e.what());                 \
  }

#include <errno.h>
#include <sys/stat.h>

static void raw_stat(const char* p) {
  struct stat st;
  int r = stat(p, &st);
  ps5_log("fsdiag raw stat  %s -> %d errno=%d mode=%o", p, r, r ? errno : 0, r ? 0 : (unsigned)st.st_mode);
  r = lstat(p, &st);
  ps5_log("fsdiag raw lstat %s -> %d errno=%d mode=%o", p, r, r ? errno : 0, r ? 0 : (unsigned)st.st_mode);
}

void ps5_fs_diag() {
  raw_stat("/data/opengoal/jak1/data/log");
  raw_stat("/data/opengoal/log");
  raw_stat("/data/opengoal/log/ps5.log");
  raw_stat("/data/opengoal/jak1/data/does_not_exist");
  const fs::path dir = "/data/opengoal/jak1/data/log";
  TRY("exists", (void)fs::exists(dir));
  TRY("is_directory", (void)fs::is_directory(dir));
  TRY("create_directories", (void)fs::create_directories(dir));
  TRY("directory_iterator", {
    int n = 0;
    for (auto& e : fs::directory_iterator(dir)) {
      (void)e;
      ++n;
    }
    ps5_log("fsdiag   entries=%d", n);
  });
  TRY("file_size/status", (void)fs::status(dir));
  TRY("find_files_in_dir", (void)file_util::find_files_in_dir(dir, std::regex(".*")));
  TRY("create_dir_if_needed_for_file", (void)file_util::create_dir_if_needed_for_file(dir / "x.log"));
}
