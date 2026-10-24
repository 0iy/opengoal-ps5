// POSIX functions the PS5 libc/libkernel does not export (the loader leaves them NULL).
// Found with the runtime import probe; each is a small, honest implementation or a clean failure.

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#ifndef AT_FDCWD
#define AT_FDCWD (-100)
#endif

// lstat() is refused (EPERM) in the title sandbox while stat() works; there are no symlinks to preserve.
int lstat(const char* path, struct stat* st) { return stat(path, st); }

long pathconf(const char* path, int name) {
  (void)path;
  switch (name) {
    case _PC_PATH_MAX: return 1024;
    case _PC_NAME_MAX: return 255;
    case _PC_LINK_MAX: return 32767;
    case _PC_PIPE_BUF: return 512;
    default: errno = EINVAL; return -1;
  }
}

ssize_t readlink(const char* path, char* buf, size_t size) {
  (void)path; (void)buf; (void)size;
  errno = EINVAL;  // nothing is a symbolic link here
  return -1;
}

// The console's getcwd jumps to garbage for sandboxed titles; the working directory is always /app0.
char* getcwd(char* buf, size_t size) {
  static const char cwd[] = "/app0";
  if (!buf) {
    size = sizeof cwd;
    buf = (char*)malloc(size);
    if (!buf) return 0;
  }
  if (size < sizeof cwd) {
    errno = ERANGE;
    return 0;
  }
  memcpy(buf, cwd, sizeof cwd);
  return buf;
}

int fchown(int fd, uid_t owner, gid_t group) {
  (void)fd; (void)owner; (void)group;
  return 0;  // ownership is not meaningful in the title sandbox
}

int symlink(const char* target, const char* linkpath) {
  (void)target; (void)linkpath;
  errno = ENOSYS;
  return -1;
}

int link(const char* from, const char* to) {
  (void)from; (void)to;
  errno = ENOSYS;
  return -1;
}

int isatty(int fd) {
  (void)fd;
  errno = ENOTTY;
  return 0;
}

pid_t fork(void) {
  errno = ENOSYS;
  return -1;
}

static uint64_t g_rng = 0;
static uint64_t next_rand(void) {
  if (!g_rng) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    g_rng = (uint64_t)ts.tv_nsec * 6364136223846793005ull + (uint64_t)ts.tv_sec + 0x9e3779b97f4a7c15ull;
  }
  g_rng ^= g_rng << 13;
  g_rng ^= g_rng >> 7;
  g_rng ^= g_rng << 17;
  return g_rng;
}

uint32_t arc4random(void) { return (uint32_t)(next_rand() >> 16); }

int mkstemp(char* tmpl) {
  size_t n = strlen(tmpl);
  if (n < 6 || strcmp(tmpl + n - 6, "XXXXXX") != 0) {
    errno = EINVAL;
    return -1;
  }
  static const char chars[] = "abcdefghijklmnopqrstuvwxyz0123456789";
  for (int attempt = 0; attempt < 100; ++attempt) {
    for (int i = 0; i < 6; ++i) tmpl[n - 6 + i] = chars[next_rand() % (sizeof chars - 1)];
    int fd = open(tmpl, O_RDWR | O_CREAT | O_EXCL, 0600);
    if (fd >= 0 || errno != EEXIST) return fd;
  }
  return -1;
}

int openat(int dirfd, const char* path, int flags, ...) {
  mode_t mode = 0;
  if (flags & O_CREAT) {
    __builtin_va_list ap;
    __builtin_va_start(ap, flags);
    mode = (mode_t)__builtin_va_arg(ap, int);
    __builtin_va_end(ap);
  }
  if (dirfd == AT_FDCWD || (path && path[0] == '/')) return open(path, flags, mode);
  errno = ENOSYS;
  return -1;
}

int fchmodat(int dirfd, const char* path, mode_t mode, int flag) {
  (void)flag;
  if (dirfd == AT_FDCWD || (path && path[0] == '/')) return chmod(path, mode);
  errno = ENOSYS;
  return -1;
}

int unlinkat(int dirfd, const char* path, int flag) {
  if (dirfd == AT_FDCWD || (path && path[0] == '/')) return (flag & AT_REMOVEDIR) ? rmdir(path) : unlink(path);
  errno = ENOSYS;
  return -1;
}

/* ---- missing from the console libc ------------------------------------------------------------------ */
#include <time.h>
#include <string.h>
struct tm* localtime_r(const time_t* t, struct tm* out) {
  struct tm* r = localtime(t);
  if (!r) return 0;
  memcpy(out, r, sizeof *out);
  return out;
}
/* wordexp is only used to expand '~' in glTF file paths; report failure so callers use the path as given. */
typedef struct { unsigned long we_wordc; char** we_wordv; unsigned long we_offs; } ps5_wordexp_t;
int wordexp(const char* words, ps5_wordexp_t* p, int flags) { (void)words; (void)flags; if (p) { p->we_wordc = 0; p->we_wordv = 0; } return 1; }
void wordfree(ps5_wordexp_t* p) { (void)p; }