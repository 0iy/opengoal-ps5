// Payload: list running processes (pid, ppid, name) over UDP broadcast 9999.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/sysctl.h>
#include <unistd.h>

static void udp(const char* m) {
  int s = socket(AF_INET, SOCK_DGRAM, 0);
  int yes = 1;
  setsockopt(s, SOL_SOCKET, SO_BROADCAST, &yes, sizeof yes);
  struct sockaddr_in d = {0};
  d.sin_family = AF_INET;
  d.sin_port = htons(9999);
  inet_pton(AF_INET, "255.255.255.255", &d.sin_addr);
  sendto(s, m, strlen(m), 0, (struct sockaddr*)&d, sizeof d);
  close(s);
  usleep(8000);
}

// struct kinfo_proc layout on FreeBSD 11 (PS5): ki_structsize first, ki_pid at 0x48, ki_ppid at 0x4c, ki_comm at 0x1bf
int main(void) {
  int mib[3] = {1 /*CTL_KERN*/, 14 /*KERN_PROC*/, 0 /*KERN_PROC_ALL*/};
  size_t len = 0;
  if (sysctl(mib, 3, NULL, &len, NULL, 0) != 0) {
    udp("ps: sysctl size failed");
    return 1;
  }
  char* buf = malloc(len * 2);
  len *= 2;
  if (sysctl(mib, 3, buf, &len, NULL, 0) != 0) {
    udp("ps: sysctl read failed");
    return 1;
  }
  size_t off = 0;
  char l[200];
  while (off + 8 < len) {
    int sz = *(int*)(buf + off);
    if (sz <= 0x200 || off + sz > len) break;
    int pid = *(int*)(buf + off + 0x48);
    int ppid = *(int*)(buf + off + 0x4c);
    const char* comm = buf + off + 0x1bf;
    snprintf(l, sizeof l, "ps: %d %d %.19s", pid, ppid, comm);
    udp(l);
    off += sz;
  }
  udp("ps: done");
  return 0;
}
