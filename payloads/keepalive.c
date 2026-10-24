// SPDX-License-Identifier: GPL-3.0-or-later
// Resident payload: keeps the PS5 from entering rest mode / showing the screen saver while we work.
// Every 20 s: reset the auto-power-down timer, turn the screen saver off, extend any shutdown timer.
// Single instance (guarded by a TCP port bind). Heartbeat goes out as UDP broadcast on port 9999.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int sceShellCoreUtilResetAutoPowerDownTimer(void);
int sceShellCoreUtilTurnOffScreenSaver(void);
int sceSystemServiceTurnOffScreenSaver(void);
int sceShellCoreUtilGetAutoPowerDownRemainingSeconds(int* seconds);
int sceSystemStateMgrExtendShutdownTimer(void);

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
  int guard = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in a = {0};
  a.sin_family = AF_INET;
  a.sin_port = htons(9033);
  a.sin_addr.s_addr = htonl(INADDR_ANY);
  int one = 1;
  setsockopt(guard, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  if (bind(guard, (struct sockaddr*)&a, sizeof a) != 0) {
    udp("keepalive: already running");
    return 0;
  }
  listen(guard, 1);
  udp("keepalive: started");
  for (unsigned n = 0;; ++n) {
    int r1 = sceShellCoreUtilResetAutoPowerDownTimer();
    sceShellCoreUtilTurnOffScreenSaver();
    sceSystemServiceTurnOffScreenSaver();
    sceSystemStateMgrExtendShutdownTimer();
    if (n % 15 == 0) {  // every 5 minutes
      int remaining = -1;
      int r2 = sceShellCoreUtilGetAutoPowerDownRemainingSeconds(&remaining);
      char line[128];
      snprintf(line, sizeof line, "keepalive: tick %u reset=0x%x remaining=%d (rc 0x%x)", n, r1, remaining, r2);
      udp(line);
    }
    sleep(20);
  }
}
