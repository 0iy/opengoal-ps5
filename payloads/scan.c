// SPDX-License-Identifier: GPL-3.0-or-later
// Payload: ask ShadowMountPlus (loopback API) for an immediate scan so newly deployed titles register.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
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
}

int main(void) {
  int s = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in a = {0};
  a.sin_family = AF_INET;
  a.sin_port = htons(10101);
  inet_pton(AF_INET, "127.0.0.1", &a.sin_addr);
  if (connect(s, (struct sockaddr*)&a, sizeof a) != 0) {
    udp("scan: connect failed");
    return 1;
  }
  const char* body = "{\"reset_attempts\":true}";
  char req[512];
  int n = snprintf(req, sizeof req,
                   "POST /api/v1/scan HTTP/1.1\r\nHost: 127.0.0.1:10101\r\nContent-Type: application/json\r\n"
                   "Content-Length: %d\r\nConnection: close\r\n\r\n%s",
                   (int)strlen(body), body);
  send(s, req, n, 0);
  char resp[1024];
  int r = recv(s, resp, sizeof resp - 1, 0);
  if (r < 0) r = 0;
  resp[r] = 0;
  char line[1200];
  snprintf(line, sizeof line, "scan: response: %.600s", resp);
  udp(line);
  close(s);
  return 0;
}
