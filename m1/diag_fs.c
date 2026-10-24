// Payload: probe file access to the homebrew app dir the way ShadowMountPlus does, report over UDP broadcast 9999.
#include <arpa/inet.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/socket.h>
#include <sys/stat.h>
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
  usleep(30000);
}

static void probe(const char* path) {
  char l[400];
  struct stat st;
  int rs = stat(path, &st);
  int e1 = errno;
  snprintf(l, sizeof l, "diag: stat %s rc=%d errno=%d mode=%o size=%lld", path, rs, rs ? e1 : 0, rs ? 0 : (unsigned)st.st_mode, rs ? 0LL : (long long)st.st_size);
  udp(l);
  errno = 0;
  FILE* f = fopen(path, "rb");
  int e2 = errno;
  size_t n = 0;
  char buf[64];
  if (f) {
    n = fread(buf, 1, sizeof buf, f);
    fclose(f);
  }
  snprintf(l, sizeof l, "diag: fopen %s -> %s errno=%d read=%zu", path, f ? "OK" : "FAIL", f ? 0 : e2, n);
  udp(l);
}

int main(void) {
  char l[400];
  snprintf(l, sizeof l, "diag: uid=%d gid=%d", (int)getuid(), (int)getgid());
  udp(l);
  probe("/data/homebrew/LAPY77001/sce_sys/param.json");
  probe("/data/homebrew/LAPY77001/eboot.bin");
  probe("/data/homebrew/LAPY77001/sce_sys/icon0.png");
  probe("/data/opengoal/config/ps5.cfg");
  probe("/user/app/LAPY77001/sce_sys/param.json");
  DIR* d = opendir("/data/homebrew/LAPY77001");
  snprintf(l, sizeof l, "diag: opendir homebrew/LAPY77001 -> %s errno=%d", d ? "OK" : "FAIL", d ? 0 : errno);
  udp(l);
  if (d) {
    struct dirent* e;
    while ((e = readdir(d))) {
      snprintf(l, sizeof l, "diag:   entry %s", e->d_name);
      udp(l);
    }
    closedir(d);
  }
  struct statfs fs[64];
  int n = getfsstat(fs, sizeof fs, MNT_NOWAIT);
  for (int i = 0; i < n && i < 64; i++) {
    if (strstr(fs[i].f_mntonname, "homebrew") || strstr(fs[i].f_mntonname, "LAPY") || !strcmp(fs[i].f_mntonname, "/data") || strstr(fs[i].f_mntonname, "system_ex/app")) {
      snprintf(l, sizeof l, "diag: mount %s from %s type %s flags=0x%x", fs[i].f_mntonname, fs[i].f_mntfromname, fs[i].f_fstypename, (unsigned)fs[i].f_flags);
      udp(l);
    }
  }
  udp("diag: done");
  return 0;
}
