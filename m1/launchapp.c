// Payload: launch an application through the system's launcher service. Title id from /data/launch_app.txt.
// Reports via UDP broadcast on port 9999 (same channel as killapp).
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

typedef struct { uint32_t size; int32_t user_id; int32_t app_attr; int32_t enable_crash_report; uint64_t check_flag; } LncAppParam;
int sceLncUtilInitialize(void);
int sceLncUtilLaunchApp(const char* title_id, const char* const* args, LncAppParam* param);
int sceUserServiceInitialize(void*);
int sceUserServiceGetForegroundUser(int* user_id);

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
  char title[32] = {0}, line[200];
  FILE* f = fopen("/data/launch_app.txt", "r");
  if (!f || fscanf(f, "%31s", title) != 1) {
    udp("launchapp: no /data/launch_app.txt");
    return 1;
  }
  fclose(f);
  int init = sceLncUtilInitialize();
  int usr_init = sceUserServiceInitialize(0);
  int user = -1;
  int ur = sceUserServiceGetForegroundUser(&user);
  LncAppParam p = {sizeof p, user, 0, 0, 0};
  int r = sceLncUtilLaunchApp(title, 0, &p);
  snprintf(line, sizeof line, "launchapp: title=%s init=0x%x userinit=0x%x user=0x%x(%d) launch=0x%x", title, init, usr_init, ur, user, r);
  udp(line);
  return 0;
}
