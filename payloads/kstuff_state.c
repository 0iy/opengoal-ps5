// SPDX-License-Identifier: GPL-3.0-or-later
// Payload: read kstuff's enable flags in kernel memory (firmware 13.60 offsets from kstuff-lite prosper0gdb/offsets/13_60.h).
// 0xdeb7 = enabled, 0xffff = disabled. Read-only; set KSTUFF_ENABLE=1 at build time to write 0xdeb7 where it reads 0xffff.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include <ps5/kernel.h>

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
  usleep(20000);
}

int main(void) {
  char l[200];
  unsigned fw = kernel_get_fw_version();
  snprintf(l, sizeof l, "kstate: fw=0x%x", fw);
  udp(l);
  if ((fw & 0xffff0000) != 0x13600000) {
    udp("kstate: not 13.60, abort");
    return 1;
  }
  intptr_t native = KERNEL_ADDRESS_DATA_BASE + 0xDDD8F8 + 14;
  intptr_t ps4 = KERNEL_ADDRESS_DATA_BASE + 0xDDDA70 + 14;
  unsigned short a = kernel_getshort(native), b = kernel_getshort(ps4);
  snprintf(l, sizeof l, "kstate: native=0x%04x ps4=0x%04x (deb7=on ffff=off)", a, b);
  udp(l);
#ifdef KSTUFF_ENABLE
  if (a == 0xffff) kernel_setshort(native, 0xdeb7);
  if (b == 0xffff) kernel_setshort(ps4, 0xdeb7);
  snprintf(l, sizeof l, "kstate: after native=0x%04x ps4=0x%04x", kernel_getshort(native), kernel_getshort(ps4));
  udp(l);
#endif
  udp("kstate: done");
  return 0;
}
