// Payload: report logged-in users and the launcher service view of running apps (UDP broadcast).
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

int sceUserServiceInitialize(void*);
int sceUserServiceGetLoginUserIdList(int* list /* 4 ints */);
int sceUserServiceGetInitialUser(int*);
int sceLncUtilInitialize(void);
int sceLncUtilGetAppId(const char* title_id);
int sceSystemServiceGetAppIdOfRunningBigApp(void);

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
  char line[256];
  int rc = sceUserServiceInitialize(0);
  int users[4] = {-1, -1, -1, -1};
  int r2 = sceUserServiceGetLoginUserIdList(users);
  int init_user = -1;
  int r3 = sceUserServiceGetInitialUser(&init_user);
  snprintf(line, sizeof line, "userinfo: init=0x%x loginlist rc=0x%x ids=[%d %d %d %d] initialUser rc=0x%x id=%d", rc, r2,
           users[0], users[1], users[2], users[3], r3, init_user);
  udp(line);
  sceLncUtilInitialize();
  int big = sceSystemServiceGetAppIdOfRunningBigApp();
  snprintf(line, sizeof line, "userinfo: running big app id=0x%x (negative/0x8094... = none)", big);
  udp(line);
  return 0;
}
