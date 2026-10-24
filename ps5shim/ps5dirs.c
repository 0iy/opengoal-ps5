// Directory enumeration for sandboxed PS5 titles.
//
// libc's opendir() fails with EPERM for a title running inside the shell sandbox, although plain
// open()/stat() on the same paths work. The kernel itself allows the operation, so this issues the
// getdirentries system call directly through libkernel's own syscall stub (the technique Playden
// uses for openat/mkdirat). opendir/readdir/closedir are then reimplemented on top of it.

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

extern int sceKernelDlsym(int module, const char* name, void** symbol);

struct sys_result {
  long value;
  long failed;
};

// rdi=entry, rsi=number, rdx,rcx,r8,r9 = four syscall arguments. Calls the syscall stub inside
// libkernel (the `syscall` instruction lives there, not in the title) and reports the carry flag.
__attribute__((naked, noinline)) static struct sys_result gateway_call(void* entry, long number, long a, long b,
                                                                          long c, long d) {
  __asm__ volatile(
      "movq %rdi, %r11\n"
      "movq %rsi, %rax\n"
      "movq %rdx, %rdi\n"
      "movq %rcx, %rsi\n"
      "movq %r8, %rdx\n"
      "movq %r9, %r10\n"
      "subq $8, %rsp\n"
      "call *%r11\n"
      "setc %dl\n"
      "movzbl %dl, %edx\n"
      "addq $8, %rsp\n"
      "ret\n");
}

static _Atomic(uintptr_t) g_gateway;

static int gateway_ready(void) {
  if (atomic_load_explicit(&g_gateway, memory_order_acquire)) return 1;
  // getpid is an import: its address is libkernel's own stub (`mov eax,20 ; syscall ; ret`).
  void* getpid_entry = (void*)&getpid;
  if (!getpid_entry) return 0;
  void* gateway = (void*)((uintptr_t)getpid_entry + 0xa);
  struct sys_result probe = gateway_call(gateway, SYS_getpid, 0, 0, 0, 0);
  if (probe.failed || probe.value != getpid()) return 0;
  atomic_store_explicit(&g_gateway, (uintptr_t)gateway, memory_order_release);
  return 1;
}

void ps5_log_c(const char* fmt, ...) __asm__("_Z7ps5_logPKcz");
long ps5_syscall4(long number, long a, long b, long c, long d);
#define ps5_syscall4_pre ps5_syscall4

void ps5_dir_debug(const char* path) {
  long fd = ps5_syscall4_pre(SYS_open, (long)path, O_RDONLY | O_DIRECTORY, 0, 0);
  ps5_log_c("dirdbg: open(%s)=%ld errno=%d SYS_getdirentries=%d SYS_getdents=%d", path, fd, errno, SYS_getdirentries,
            272);
  if (fd < 0) return;
  static char buf[65536];
  long base = 0;
  long n = ps5_syscall4_pre(SYS_getdirentries, fd, (long)buf, sizeof buf, (long)&base);
  ps5_log_c("dirdbg: getdirentries=%ld errno=%d base=%ld", n, errno, base);
  if (n > 0) {
    ps5_log_c("dirdbg: first reclen=%u fileno=%u type=%u namlen=%u name=%s", ((unsigned char)buf[4]) | (((unsigned char)buf[5]) << 8),
              *(unsigned*)buf, (unsigned char)buf[6], (unsigned char)buf[7], buf + 8);
  }
  ps5_syscall4_pre(SYS_close, fd, 0, 0, 0);
}

void ps5_gateway_debug(void) {
  void* entry = (void*)&getpid;
  int rc = 0;
  ps5_log_c("gateway: &getpid=%p", entry);
  ps5_log_c("gateway: getpid()=%d", (int)getpid());
}

long ps5_syscall4(long number, long a, long b, long c, long d) {
  if (!gateway_ready()) {
    errno = ENOSYS;
    return -1;
  }
  struct sys_result r = gateway_call((void*)atomic_load_explicit(&g_gateway, memory_order_acquire), number, a, b, c, d);
  if (r.failed) {
    errno = (int)r.value;
    return -1;
  }
  return r.value;
}

struct ps5_dir {
  int fd;
  long base;
  size_t pos, len;
  char* buf;
  size_t bufsize;
  struct dirent ent;
};

DIR* opendir(const char* path) {
  long fd = ps5_syscall4(SYS_open, (long)path, O_RDONLY | O_DIRECTORY | O_CLOEXEC, 0, 0);
  if (fd < 0) return 0;
  struct ps5_dir* d = (struct ps5_dir*)calloc(1, sizeof *d);
  if (!d) {
    ps5_syscall4(SYS_close, fd, 0, 0, 0);
    errno = ENOMEM;
    return 0;
  }
  d->bufsize = 65536;  // getdirentries needs at least the filesystem block size
  d->buf = (char*)malloc(d->bufsize);
  if (!d->buf) {
    ps5_syscall4(SYS_close, fd, 0, 0, 0);
    free(d);
    errno = ENOMEM;
    return 0;
  }
  d->fd = (int)fd;
  return (DIR*)d;
}

struct dirent* readdir(DIR* dir) {
  struct ps5_dir* d = (struct ps5_dir*)dir;
  for (;;) {
    if (d->pos >= d->len) {
      long n = ps5_syscall4(SYS_getdirentries, d->fd, (long)d->buf, (long)d->bufsize, (long)&d->base);
      if (n <= 0) return 0;
      d->len = (size_t)n;
      d->pos = 0;
    }
    struct dirent* e = (struct dirent*)(d->buf + d->pos);
    if (e->d_reclen == 0) return 0;
    d->pos += e->d_reclen;
    if (e->d_fileno == 0) continue;  // deleted entry
    memcpy(&d->ent, e, e->d_reclen < sizeof d->ent ? e->d_reclen : sizeof d->ent);
    return &d->ent;
  }
}

int readdir_r(DIR* dir, struct dirent* entry, struct dirent** result) {
  struct dirent* e = readdir(dir);
  if (!e) {
    *result = 0;
    return 0;
  }
  memcpy(entry, e, sizeof *entry);
  *result = entry;
  return 0;
}

int closedir(DIR* dir) {
  struct ps5_dir* d = (struct ps5_dir*)dir;
  if (!d) return 0;
  ps5_syscall4(SYS_close, d->fd, 0, 0, 0);
  free(d->buf);
  free(d);
  return 0;
}

void rewinddir(DIR* dir) {
  struct ps5_dir* d = (struct ps5_dir*)dir;
  ps5_syscall4(SYS_lseek, d->fd, 0, SEEK_SET, 0);
  d->pos = d->len = 0;
  d->base = 0;
}

int dirfd(DIR* dir) { return ((struct ps5_dir*)dir)->fd; }
