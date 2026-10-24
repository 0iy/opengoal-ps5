// SPDX-License-Identifier: GPL-3.0-or-later
// Payload: read /dev/klog for ~20 s, send lines matching remote-play/NP keywords (or all with -DALL) over UDP broadcast 9999.
#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static int sock;
static struct sockaddr_in d;
static void udp(const char* m) {
  sendto(sock, m, strlen(m), 0, (struct sockaddr*)&d, sizeof d);
  usleep(3000);
}

int main(void) {
  sock = socket(AF_INET, SOCK_DGRAM, 0);
  int yes = 1;
  setsockopt(sock, SOL_SOCKET, SO_BROADCAST, &yes, sizeof yes);
  d.sin_family = AF_INET;
  d.sin_port = htons(9999);
  inet_pton(AF_INET, "255.255.255.255", &d.sin_addr);
  int fd = open("/dev/klog", O_RDONLY | O_NONBLOCK);
  char l[600];
  snprintf(l, sizeof l, "klog: open fd=%d", fd);
  udp(l);
  if (fd < 0) return 1;
  char buf[4096], line[1024];
  size_t ll = 0;
  time_t t0 = time(0);
  int total = 0, sent = 0;
  while (time(0) - t0 < 20) {
    ssize_t n = read(fd, buf, sizeof buf);
    if (n <= 0) { usleep(20000); continue; }
    total += n;
    for (ssize_t i = 0; i < n; i++) {
      if (buf[i] == '\n' || ll >= sizeof line - 1) {
        line[ll] = 0;
        ll = 0;
        if (!line[0]) continue;
#ifndef ALL
        if (!(strcasestr(line, "remote") || strcasestr(line, "rplay") || strcasestr(line, "8b12") || strcasestr(line, "np") || strcasestr(line, "session") || strcasestr(line, "regist"))) continue;
#endif
        snprintf(l, sizeof l, "klog: %.560s", line);
        udp(l);
        sent++;
      } else line[ll++] = buf[i];
    }
  }
  snprintf(l, sizeof l, "klog: done bytes=%d sent=%d", total, sent);
  udp(l);
  return 0;
}
