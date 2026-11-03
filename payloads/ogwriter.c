// SPDX-License-Identifier: GPL-3.0-or-later
// Payload: file writer for the PC import. The console throttles the disk writes of the app process to ~2 MB/s after ~1.3 GB, while
// another process keeps ~250 MB/s (measured 2026-11-02). The app therefore hands the file data of an install to this process.
// The app sends /data/homebrew/LAPY77001/ogwriter.elf to the ELF loader (127.0.0.1:9021) when it needs it, pc_import sends it before every
// upload too; a second copy finds the port taken and exits.
//
// Listens on 127.0.0.1:9098 only (the app on the same console). Writes only below /data/opengoal/. Exits after 120 s without a client.
// Protocol, little endian, one file at a time per connection:
//   'O' u32 len, path   open (create, truncate)    -> i32 errno (0 = ok)
//   'W' u32 len, data   append                     -> no answer; a failure is kept and returned by 'C'
//   'C'                 close                      -> i32 errno (0 = ok)
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define PORT 9098
#define ROOT "/data/opengoal/"
#define MAX_CHUNK (16u << 20)

static volatile long g_last;  // monotonic seconds of the last activity
static volatile int g_conns;

static long mono_s(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec;
}

static int recv_all(int fd, void* p, size_t n) {
  char* c = p;
  while (n) {
    ssize_t r = recv(fd, c, n, 0);
    if (r <= 0) return -1;
    c += r; n -= (size_t)r;
  }
  return 0;
}

static int send_i32(int fd, int32_t v) { return send(fd, &v, 4, 0) == 4 ? 0 : -1; }

static int path_ok(const char* p) {
  return strncmp(p, ROOT, sizeof ROOT - 1) == 0 && !strstr(p, "/../") && !strstr(p, "/./");
}

static void* conn_thread(void* arg) {
  int fd = (int)(intptr_t)arg, out = -1, err = 0;
  char* buf = malloc(MAX_CHUNK);
  for (;;) {
    uint8_t op;
    uint32_t len;
    if (!buf || recv_all(fd, &op, 1)) break;
    g_last = mono_s();
    if (op == 'C') {
      if (out >= 0 && close(out) && !err) err = errno;
      out = -1;
      if (send_i32(fd, err)) break;
      err = 0;
      continue;
    }
    if ((op != 'O' && op != 'W') || recv_all(fd, &len, 4) || len > MAX_CHUNK || recv_all(fd, buf, len)) break;
    if (op == 'O') {
      if (out >= 0) close(out);
      err = 0;
      out = -1;
      if (len == 0 || len >= 1024) err = EINVAL;
      else {
        buf[len] = 0;
        if (!path_ok(buf)) err = EPERM;
        else if ((out = open(buf, O_WRONLY | O_CREAT | O_TRUNC, 0644)) < 0) err = errno;
      }
      if (send_i32(fd, err)) break;
    } else if (out >= 0 && !err) {
      for (char* p = buf; len && !err;) {
        ssize_t w = write(out, p, len);
        if (w <= 0) err = w < 0 ? errno : EIO;
        else { p += w; len -= (uint32_t)w; }
      }
    } else if (!err) {
      err = EBADF;
    }
  }
  if (out >= 0) close(out);
  free(buf);
  close(fd);
  __sync_fetch_and_sub(&g_conns, 1);
  g_last = mono_s();
  return NULL;
}

int main(void) {
  int ls = socket(AF_INET, SOCK_STREAM, 0), yes = 1;
  setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof yes);
  struct sockaddr_in a;
  memset(&a, 0, sizeof a);
  a.sin_family = AF_INET; a.sin_port = htons(PORT); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (ls < 0 || bind(ls, (struct sockaddr*)&a, sizeof a) || listen(ls, 4)) return 0;  // another copy runs
  g_last = mono_s();
  while (g_conns > 0 || mono_s() - g_last < 120) {
    struct pollfd pf = {ls, POLLIN, 0};
    if (poll(&pf, 1, 500) <= 0) continue;
    int fd = accept(ls, NULL, NULL);
    if (fd < 0) continue;
    __sync_fetch_and_add(&g_conns, 1);
    pthread_t t;
    if (pthread_create(&t, NULL, conn_thread, (void*)(intptr_t)fd)) { __sync_fetch_and_sub(&g_conns, 1); close(fd); continue; }
    pthread_detach(t);
  }
  close(ls);
  return 0;
}
