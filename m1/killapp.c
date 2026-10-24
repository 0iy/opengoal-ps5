// Payload: close an application through the system's own launcher service (works for suspended apps).
// Reads the title id from /data/kill_app.txt, resolves its app id, and kills it. Reports via UDP broadcast.
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int sceLncUtilInitialize(void);
int sceLncUtilGetAppId(const char* title_id);
int sceLncUtilKillApp(int app_id);
int sceLncUtilForceKillApp(int app_id);

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
  char title[32] = {0};
  FILE* f = fopen("/data/kill_app.txt", "r");
  if (!f || fscanf(f, "%31s", title) != 1) {
    udp("killapp: no /data/kill_app.txt");
    return 1;
  }
  fclose(f);
  char line[200];
  int init = sceLncUtilInitialize();
  int app = sceLncUtilGetAppId(title);
  snprintf(line, sizeof line, "killapp: title=%s init=0x%x appid=0x%x", title, init, app);
  udp(line);
  int r1 = sceLncUtilKillApp(app);
  snprintf(line, sizeof line, "killapp: KillApp=0x%x", r1);
  udp(line);
  usleep(1500000);
  int r2 = sceLncUtilForceKillApp(app);
  snprintf(line, sizeof line, "killapp: ForceKillApp=0x%x", r2);
  udp(line);
  return 0;
}
