// SPDX-License-Identifier: GPL-3.0-or-later
// Payload: setup agent. Console-side half of the one-command setup: a tiny HTTP/1.1 server on TCP 9099 that lets the PC copy the game files
// into the two allowed folders, read logs, launch and kill the app. Send it to the ELF loader (port 9021) like the other payloads.
//
// Token: the 32 bytes after the 14-byte marker in `og_token_blob` are the access token. The PC script patches them in the ELF before sending
// (see payloads/README.md). The agent refuses to start while they are still the filler. Every request needs `X-OG-Token: <token>`.
//
// The same file builds for the host (gcc -DOG_HOST) with the platform calls in the "platform layer" replaced by stubs, so tests/test_ogagent_host.py
// can exercise the HTTP and file code without a console. Rules: no thread_local, no statvfs, no static objects with destructors.
#ifdef OG_HOST
#define _GNU_SOURCE
#endif
#include <arpa/inet.h>
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#ifdef OG_HOST
#include <sys/statfs.h>
#endif
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#ifndef OG_HOST
#include <sys/sysctl.h>
#include <sys/user.h>
#endif

#define OG_VERSION "1"
#ifndef OG_PORT
#define OG_PORT 9099
#endif
#ifndef OG_LIFETIME_SEC
#define OG_LIFETIME_SEC 3600         // the agent ends this long after start
#endif
#ifndef OG_IDLE_AFTER_LAUNCH_SEC
#define OG_IDLE_AFTER_LAUNCH_SEC 600 // ... or this long after the last request once a launch succeeded
#endif
#define OG_TITLE "LAPY77001"
#define OG_HDR_MAX 8192              // request line plus headers
#define OG_MAX_FILE (8LL << 30)      // PUT body limit
#define OG_MAX_SMALL_BODY 65536      // body limit of every other endpoint
#define OG_GET_MAX (64LL << 20)      // bytes returned by one GET /v1/file
#define OG_MAX_CONNS 16
#define OG_PATH_CAP 1024
#define OG_RING_LINES 256
#define OG_RING_W 224
#define OG_MAX_PARTS 64
#define OG_MAX_PROCS 1024
#define OG_MAX_MOUNTS 48

// ---- token blob: marker + 32 filler bytes. Non-const, non-static, `used`, read through volatile: it stays in .data and is never folded away.
#define OG_X8 "xx" "xx" "xx" "xx"
#define OG_MARK_LEN 14
#define OG_TOKEN_LEN 32
__attribute__((used, aligned(16))) char og_token_blob[] = "OGAGENT_TOKEN:" OG_X8 OG_X8 OG_X8 OG_X8;
_Static_assert(sizeof og_token_blob == OG_MARK_LEN + OG_TOKEN_LEN + 1, "token blob layout");
#define OG_TOKEN ((const volatile char*)(og_token_blob + OG_MARK_LEN))

// ---- state
static const char* g_root_list[2];   // read/write/get allowlist (with trailing slash)
static const char* g_rm_list[2];     // rm allowlist
#ifdef OG_HOST
static char g_hostroot[3][OG_PATH_CAP];
#endif
static pthread_mutex_t g_logmu, g_partmu, g_lncmu;
static char g_ring[OG_RING_LINES][OG_RING_W];
static unsigned g_ring_n;
static char g_parts[OG_MAX_PARTS][OG_PATH_CAP + 8];
static volatile int g_stop, g_launched, g_conns, g_active_req;
static volatile long g_last_act;
static long g_start_s;
static long g_lifetime = OG_LIFETIME_SEC, g_idle = OG_IDLE_AFTER_LAUNCH_SEC;
static int g_port = OG_PORT;

static long mono_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (long)t.tv_sec; }

static void lg(const char* fmt, ...) {
  char line[OG_RING_W];
  int off = snprintf(line, sizeof line, "[%5ld] ", mono_s() - g_start_s);
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(line + off, sizeof line - off, fmt, ap);
  va_end(ap);
  for (char* p = line; *p; p++)
    if ((unsigned char)*p < 0x20 || (unsigned char)*p > 0x7e) *p = '?';
  pthread_mutex_lock(&g_logmu);
  memcpy(g_ring[g_ring_n % OG_RING_LINES], line, sizeof line);
  g_ring_n++;
  pthread_mutex_unlock(&g_logmu);
#ifdef OG_HOST
  fprintf(stderr, "ogagent %s\n", line);
#endif
}

// =================================================================================================== platform layer
typedef struct { int pid; char name[40]; char title[16]; } ProcInfo;
typedef struct { char path[96]; char type[24]; uint64_t free_b, total_b; } MountInfo;

#ifdef OG_HOST
static volatile int g_fake_running;
static void plat_notify(const char* m) { lg("notify: %s", m); }
static void plat_kernel(char* ver, size_t vn, char* fw, size_t fn, unsigned* sdk) {
  snprintf(ver, vn, "host test kernel"); snprintf(fw, fn, "host"); *sdk = 0;
}
static long plat_uptime(void) { double u = 0; FILE* f = fopen("/proc/uptime", "r"); if (f) { if (fscanf(f, "%lf", &u) != 1) u = 0; fclose(f); } return (long)u; }
static int plat_procs(ProcInfo* o, int max) {
  int n = 0;
  DIR* d = opendir("/proc");
  struct dirent* e;
  while (d && (e = readdir(d)) && n < max - 1) {
    int pid = atoi(e->d_name);
    if (pid <= 0) continue;
    char p[64], nm[40] = "";
    snprintf(p, sizeof p, "/proc/%d/comm", pid);
    FILE* f = fopen(p, "r");
    if (f) { if (fgets(nm, sizeof nm, f)) nm[strcspn(nm, "\n")] = 0; fclose(f); }
    o[n].pid = pid; snprintf(o[n].name, sizeof o[n].name, "%s", nm); o[n].title[0] = 0; n++;
  }
  if (d) closedir(d);
  if (g_fake_running) { o[n].pid = 4242; snprintf(o[n].name, sizeof o[n].name, "eboot.bin"); snprintf(o[n].title, sizeof o[n].title, OG_TITLE); n++; }
  return n;
}
static int plat_mounts(MountInfo* o, int max) {
  int n = 0;
  const char* ps[3] = {"/", g_root_list[0], g_root_list[1]};
  for (int i = 0; i < 3 && n < max; i++) {
    struct statfs s;
    if (statfs(ps[i], &s)) continue;
    snprintf(o[n].path, sizeof o[n].path, "%s", ps[i]); snprintf(o[n].type, sizeof o[n].type, "host");
    o[n].free_b = (uint64_t)s.f_bavail * s.f_bsize; o[n].total_b = (uint64_t)s.f_blocks * s.f_bsize; n++;
  }
  return n;
}
static int plat_can_launch(void) { return 1; }
static int plat_app_id(const char* t) { (void)t; return g_fake_running ? 0x1234 : -1; }
static int plat_launch(const char* t) { (void)t; g_fake_running = 1; return 0; }
static void plat_kill(const char* t, int* app, int* r1, int* r2) { (void)t; *app = g_fake_running ? 0x1234 : -1; *r1 = *r2 = 0; g_fake_running = 0; }
#else
// Documented (not run here) calls of libkernel / libkernel_sys / the launcher service; see payloads/README.md.
typedef struct { char useless1[45]; char message[3075]; } notify_request_t;
int sceKernelSendNotificationRequest(int, notify_request_t*, size_t, int);
int sceKernelGetAppInfo(int pid, void* info);
int sceKernelGetSystemSwVersion(void* info);
typedef struct { uint32_t size; int32_t user_id; int32_t app_attr; int32_t enable_crash_report; uint64_t check_flag; } LncAppParam;
int sceLncUtilInitialize(void);
int sceLncUtilGetAppId(const char* title_id);
int sceLncUtilKillApp(int app_id);
int sceLncUtilForceKillApp(int app_id);
int sceLncUtilLaunchApp(const char* title_id, const char* const* args, LncAppParam* param);
int sceUserServiceInitialize(void*);
int sceUserServiceGetForegroundUser(int* user_id);

static int g_lnc_init = 0x7fffffff; // result of sceLncUtilInitialize, 0x7fffffff = not tried yet
static int lnc_init(void) {
  pthread_mutex_lock(&g_lncmu);
  if (g_lnc_init == 0x7fffffff) { g_lnc_init = sceLncUtilInitialize(); sceUserServiceInitialize(0); }
  int r = g_lnc_init;
  pthread_mutex_unlock(&g_lncmu);
  return r;
}
static void plat_notify(const char* m) {
  notify_request_t req;
  memset(&req, 0, sizeof req);
  snprintf(req.message, sizeof req.message, "%s", m);
  sceKernelSendNotificationRequest(0, &req, sizeof req, 0);
}
static void first_line(char* s, size_t cap) { for (size_t i = 0; i < cap && s[i]; i++) if (s[i] == '\n' || s[i] == '\r') { s[i] = 0; break; } }
static void plat_kernel(char* ver, size_t vn, char* fw, size_t fn, unsigned* sdk) {
  size_t l = vn - 1;
  ver[0] = 0;
  if (sysctlbyname("kern.version", ver, &l, NULL, 0) == 0) ver[l < vn ? l : vn - 1] = 0; else ver[0] = 0;
  first_line(ver, vn);
  unsigned char sw[128];                       // SceKernelSwVersion: u32 size, char version_string[0x1c], u32 version
  memset(sw, 0, sizeof sw);
  *(uint32_t*)sw = 0x24;
  fw[0] = 0;
  if (sceKernelGetSystemSwVersion(sw) == 0) { snprintf(fw, fn, "%.27s", (const char*)(sw + 4)); }
  unsigned v = 0; size_t vl = sizeof v;
  *sdk = (sysctlbyname("kern.sdk_version", &v, &vl, NULL, 0) == 0 && vl == sizeof v) ? v : 0;
}
static long plat_uptime(void) { struct timespec t; clock_gettime(CLOCK_UPTIME, &t); return (long)t.tv_sec; }
static int title_ok(const char* t) {  // XXXX00000 shape
  for (int i = 0; i < 4; i++) if (t[i] < 'A' || t[i] > 'Z') return 0;
  for (int i = 4; i < 9; i++) if (t[i] < '0' || t[i] > '9') return 0;
  return t[9] == 0;
}
static int plat_procs(ProcInfo* o, int max) {
  int mib[3] = {CTL_KERN, KERN_PROC, KERN_PROC_ALL};
  size_t len = 0;
  if (sysctl(mib, 3, NULL, &len, NULL, 0) || len == 0) return 0;
  len += len / 4 + 8192;
  char* buf = malloc(len);
  if (!buf) return 0;
  int n = 0;
  if (sysctl(mib, 3, buf, &len, NULL, 0) == 0) {
    for (size_t off = 0; off + sizeof(int) <= len && n < max;) {
      struct kinfo_proc* kp = (struct kinfo_proc*)(buf + off);
      if (kp->ki_structsize < (int)sizeof(int) || off + (size_t)kp->ki_structsize > len) break;
      o[n].pid = kp->ki_pid;
      snprintf(o[n].name, sizeof o[n].name, "%.30s", kp->ki_comm);
      o[n].title[0] = 0;
      unsigned char ai[512];                   // SceAppInfo: u32 app_id, u32 unknown, u32 app_type, char title_id[10], ...
      memset(ai, 0, sizeof ai);
      if (sceKernelGetAppInfo(kp->ki_pid, ai) == 0 && title_ok((const char*)(ai + 12))) snprintf(o[n].title, sizeof o[n].title, "%s", (const char*)(ai + 12));
      n++;
      off += (size_t)kp->ki_structsize;
    }
  }
  free(buf);
  return n;
}
static int plat_mounts(MountInfo* o, int max) {
  int cnt = getfsstat(NULL, 0, MNT_NOWAIT);
  if (cnt <= 0) return 0;
  if (cnt > max) cnt = max;
  struct statfs* b = malloc(sizeof *b * cnt);
  if (!b) return 0;
  int n = getfsstat(b, (long)(sizeof *b * cnt), MNT_NOWAIT);
  if (n < 0) n = 0;
  for (int i = 0; i < n; i++) {
    snprintf(o[i].path, sizeof o[i].path, "%s", b[i].f_mntonname);
    snprintf(o[i].type, sizeof o[i].type, "%s", b[i].f_fstypename);
    o[i].free_b = (uint64_t)b[i].f_bavail * b[i].f_bsize;
    o[i].total_b = (uint64_t)b[i].f_blocks * b[i].f_bsize;
  }
  free(b);
  return n;
}
static int plat_can_launch(void) { return lnc_init() == 0; }
static int plat_app_id(const char* t) { lnc_init(); return sceLncUtilGetAppId(t); }
static int plat_launch(const char* t) {  // same steps as launchapp.c
  lnc_init();
  int user = -1;
  sceUserServiceGetForegroundUser(&user);
  LncAppParam p = {sizeof p, user, 0, 0, 0};
  pthread_mutex_lock(&g_lncmu);
  int r = sceLncUtilLaunchApp(t, 0, &p);
  pthread_mutex_unlock(&g_lncmu);
  return r;
}
static void plat_kill(const char* t, int* app, int* r1, int* r2) {  // same steps as killapp.c
  lnc_init();
  *app = sceLncUtilGetAppId(t);
  *r1 = sceLncUtilKillApp(*app);
  usleep(1500000);
  *r2 = sceLncUtilForceKillApp(*app);
}
#endif

// =================================================================================================== small helpers
typedef struct { char* p; size_t n, cap; int oom; } SB;
#define SB_MAX (4u << 20)
static void sb_put(SB* b, const char* s, size_t n) {
  if (b->oom) return;
  if (b->n + n + 1 > b->cap) {
    size_t nc = b->cap ? b->cap * 2 : 1024;
    while (nc < b->n + n + 1) nc *= 2;
    if (nc > SB_MAX) { b->oom = 1; return; }
    char* q = realloc(b->p, nc);
    if (!q) { b->oom = 1; return; }
    b->p = q; b->cap = nc;
  }
  memcpy(b->p + b->n, s, n);
  b->n += n;
  b->p[b->n] = 0;
}
static void sb_s(SB* b, const char* s) { sb_put(b, s, strlen(s)); }
static void sb_f(SB* b, const char* fmt, ...) {
  char t[512];
  va_list ap;
  va_start(ap, fmt);
  int n = vsnprintf(t, sizeof t, fmt, ap);
  va_end(ap);
  if (n > 0) sb_put(b, t, (size_t)(n < (int)sizeof t ? n : (int)sizeof t - 1));
}
static void sb_str(SB* b, const char* s) {  // JSON string; anything outside printable ASCII becomes '?'
  sb_put(b, "\"", 1);
  for (; *s; s++) {
    unsigned char c = (unsigned char)*s;
    if (c == '"' || c == '\\') { char e[2] = {'\\', (char)c}; sb_put(b, e, 2); }
    else if (c < 0x20 || c > 0x7e) sb_put(b, "?", 1);
    else sb_put(b, (const char*)&c, 1);
  }
  sb_put(b, "\"", 1);
}

static int hexv(int c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1; }
// percent-decode s[0..n) into out; -1 on bad escape, NUL or overflow. '+' stays '+'.
static int pct_decode(const char* s, size_t n, char* out, size_t cap) {
  size_t o = 0;
  for (size_t i = 0; i < n; i++) {
    int c = (unsigned char)s[i];
    if (c == '%') {
      if (i + 2 >= n) return -1;
      int h = hexv(s[i + 1]), l = hexv(s[i + 2]);
      if (h < 0 || l < 0) return -1;
      c = h * 16 + l; i += 2;
    }
    if (c == 0 || o + 1 >= cap) return -1;
    out[o++] = (char)c;
  }
  out[o] = 0;
  return (int)o;
}
// find key in "a=b&c=d"; 1 found, 0 absent, -1 malformed/too long
static int form_get(const char* q, const char* key, char* out, size_t cap) {
  size_t kl = strlen(key);
  while (q && *q) {
    const char* e = strchr(q, '&');
    size_t l = e ? (size_t)(e - q) : strlen(q);
    if (l > kl && !strncmp(q, key, kl) && q[kl] == '=') return pct_decode(q + kl + 1, l - kl - 1, out, cap) < 0 ? -1 : 1;
    q = e ? e + 1 : NULL;
  }
  return 0;
}
// minimal {"key":"value"} reader: \" \\ \/ escapes only
static int json_get(const char* j, const char* key, char* out, size_t cap) {
  char pat[48];
  snprintf(pat, sizeof pat, "\"%s\"", key);
  const char* p = strstr(j, pat);
  if (!p) return 0;
  p += strlen(pat);
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
  if (*p++ != ':') return -1;
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
  if (*p++ != '"') return -1;
  size_t o = 0;
  for (; *p && *p != '"'; p++) {
    char c = *p;
    if (c == '\\') { c = *++p; if (c != '"' && c != '\\' && c != '/') return -1; }
    if (o + 1 >= cap) return -1;
    out[o++] = c;
  }
  if (*p != '"') return -1;
  out[o] = 0;
  return 1;
}

// =================================================================================================== path policy
static const char* find_root(const char* p, const char* const* list, int allow_equal, int* is_equal) {
  *is_equal = 0;
  for (int i = 0; i < 2; i++) {
    size_t rl = strlen(list[i]);
    if (!strncmp(p, list[i], rl) && p[rl]) return list[i];
    if (allow_equal && strlen(p) == rl - 1 && !strncmp(p, list[i], rl - 1)) { *is_equal = 1; return list[i]; }
  }
  return NULL;
}
static int shape_ok(const char* p) {  // absolute, no control chars, no backslash, no empty / "." / ".." component, no trailing slash
  size_t n = strlen(p);
  if (n < 2 || n > OG_PATH_CAP - 16 || p[0] != '/') return 0;
  for (size_t i = 0; i < n; i++) if ((unsigned char)p[i] < 0x20 || p[i] == 0x7f || p[i] == '\\') return 0;
  const char* s = p + 1;
  for (;;) {
    const char* e = strchr(s, '/');
    size_t l = e ? (size_t)(e - s) : strlen(s);
    if (l == 0 || (l == 1 && s[0] == '.') || (l == 2 && s[0] == '.' && s[1] == '.')) return 0;
    if (!e) return 1;
    s = e + 1;
  }
}
// 1 when p is allowed: shaped, under a root of `list` (or equal to it when allow_equal), and no existing component below the root is a symlink.
static int path_ok(const char* p, const char* const* list, int allow_equal) {
  int eq;
  if (!shape_ok(p)) return 0;
  const char* root = find_root(p, list, allow_equal, &eq);
  if (!root) return 0;
  if (eq) return 1;
  char t[OG_PATH_CAP];
  size_t pos = strlen(root), n = strlen(p);
  while (pos <= n) {
    const char* sl = strchr(p + pos, '/');
    size_t end = sl ? (size_t)(sl - p) : n;
    memcpy(t, p, end); t[end] = 0;
    struct stat st;
    if (lstat(t, &st)) { if (errno == ENOENT || errno == ENOTDIR) return 1; return 0; }
    if (S_ISLNK(st.st_mode)) return 0;
    pos = end + 1;
  }
  return 1;
}
static int mkdir_p(const char* path, mode_t mode) {
  char t[OG_PATH_CAP];
  size_t n = strlen(path);
  if (n >= sizeof t) { errno = ENAMETOOLONG; return -1; }
  memcpy(t, path, n + 1);
  for (size_t i = 1; i <= n; i++) {
    if (t[i] != '/' && t[i] != 0) continue;
    char c = t[i]; t[i] = 0;
    if (mkdir(t, mode) && errno != EEXIST) return -1;
    t[i] = c;
  }
  struct stat st;
  if (stat(path, &st)) return -1;
  if (!S_ISDIR(st.st_mode)) { errno = ENOTDIR; return -1; }
  return 0;
}
static int rm_tree(char* path, size_t cap, int depth, long* count) {  // never follows symlinks
  struct stat st;
  if (lstat(path, &st)) return errno == ENOENT ? 0 : -1;
  if (S_ISDIR(st.st_mode)) {
    if (depth > 32) { errno = ELOOP; return -1; }
    DIR* d = opendir(path);
    if (!d) return -1;
    size_t pl = strlen(path);
    struct dirent* e;
    int rc = 0;
    while ((e = readdir(d))) {
      if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
      if (pl + 1 + strlen(e->d_name) >= cap) { errno = ENAMETOOLONG; rc = -1; break; }
      path[pl] = '/'; strcpy(path + pl + 1, e->d_name);
      if (rm_tree(path, cap, depth + 1, count)) rc = -1;
      path[pl] = 0;
    }
    closedir(d);
    if (rc || rmdir(path)) return -1;
    (*count)++;
    return 0;
  }
  if (unlink(path)) return -1;
  (*count)++;
  return 0;
}
static int part_claim(const char* p) {  // one writer per .part path inside this process
  int ok = 1, free_i = -1;
  pthread_mutex_lock(&g_partmu);
  for (int i = 0; i < OG_MAX_PARTS; i++) {
    if (!g_parts[i][0]) { if (free_i < 0) free_i = i; }
    else if (!strcmp(g_parts[i], p)) ok = 0;
  }
  if (ok && free_i >= 0) snprintf(g_parts[free_i], OG_PATH_CAP + 8, "%s", p); else ok = 0;
  pthread_mutex_unlock(&g_partmu);
  return ok;
}
static void part_release(const char* p) {
  pthread_mutex_lock(&g_partmu);
  for (int i = 0; i < OG_MAX_PARTS; i++) if (!strcmp(g_parts[i], p)) g_parts[i][0] = 0;
  pthread_mutex_unlock(&g_partmu);
}

// =================================================================================================== HTTP
#define IOBUF 16384
typedef struct {
  int fd;
  char peer[48];
  unsigned char buf[IOBUF];
  size_t n;                 // buffered bytes
  char method[12], target[2048], path[2048];
  const char* query;
  int http11, keepalive, expect100, has_te, has_token, close_after, code;
  long long clen, body_left;
  char token[96];
  unsigned char* pre;       // buffered body bytes
  size_t prelen;
  char sbody[OG_MAX_SMALL_BODY + 1];
  size_t sbody_n;
} Conn;

static const char* status_text(int c) {
  switch (c) {
    case 200: return "OK"; case 400: return "Bad Request"; case 401: return "Unauthorized"; case 403: return "Forbidden"; case 404: return "Not Found";
    case 405: return "Method Not Allowed"; case 409: return "Conflict"; case 411: return "Length Required"; case 413: return "Payload Too Large";
    case 431: return "Request Header Fields Too Large"; case 500: return "Internal Server Error"; case 501: return "Not Implemented";
    case 503: return "Service Unavailable"; case 507: return "Insufficient Storage"; default: return "Error";
  }
}
static int send_all(int fd, const void* d, size_t n) {
  const char* p = d;
  while (n) {
#ifdef MSG_NOSIGNAL
    ssize_t r = send(fd, p, n, MSG_NOSIGNAL);
#else
    ssize_t r = send(fd, p, n, 0);
#endif
    if (r < 0 && errno == EINTR) continue;
    if (r <= 0) return -1;
    p += r; n -= (size_t)r;
  }
  return 0;
}
static int respond_head(Conn* c, int code, const char* ctype, long long len, const char* extra) {
  char h[512];
  int close = c->close_after || !c->keepalive || c->body_left > 0;
  c->code = code;
  int n = snprintf(h, sizeof h, "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %lld\r\nConnection: %s\r\nCache-Control: no-store\r\n%s\r\n", code,
                   status_text(code), ctype, len, close ? "close" : "keep-alive", extra ? extra : "");
  if (close) c->close_after = 1;
  return send_all(c->fd, h, (size_t)n);
}
static int respond_json(Conn* c, int code, SB* b) {
  if (b->oom) { b->n = 0; if (b->p) b->p[0] = 0; sb_s(b, "{\"ok\":false,\"error\":\"response too large\"}"); code = 500; }
  int r = respond_head(c, code, "application/json", (long long)b->n, NULL) || send_all(c->fd, b->p ? b->p : "", b->n);
  return r ? -1 : 0;
}
static int respond_err(Conn* c, int code, const char* msg) {
  SB b = {0};
  sb_s(&b, "{\"ok\":false,\"error\":");
  sb_str(&b, msg);
  sb_s(&b, "}");
  int r = respond_json(c, code, &b);
  free(b.p);
  return r;
}
static ssize_t body_read(Conn* c, void* dst, size_t max) {
  if (c->body_left <= 0) return 0;
  if ((long long)max > c->body_left) max = (size_t)c->body_left;
  if (c->prelen) {
    size_t m = max < c->prelen ? max : c->prelen;
    memcpy(dst, c->pre, m); c->pre += m; c->prelen -= m; c->body_left -= (long long)m;
    return (ssize_t)m;
  }
  for (;;) {
    ssize_t r = recv(c->fd, dst, max, 0);
    if (r < 0 && errno == EINTR) continue;
    if (r <= 0) return -1;
    c->body_left -= r;
    return r;
  }
}

static int tok_ok(const Conn* c) {  // constant time over the 32 token bytes
  unsigned diff = (unsigned)(strlen(c->token) != OG_TOKEN_LEN);
  for (int i = 0; i < OG_TOKEN_LEN; i++) diff |= (unsigned)((unsigned char)c->token[i] ^ (unsigned char)OG_TOKEN[i]);
  return c->has_token && diff == 0;
}

static int port_open(int port) {
  int s = socket(AF_INET, SOCK_STREAM, 0);
  if (s < 0) return 0;
  fcntl(s, F_SETFL, fcntl(s, F_GETFL, 0) | O_NONBLOCK);
  struct sockaddr_in a;
  memset(&a, 0, sizeof a);
  a.sin_family = AF_INET; a.sin_port = htons((uint16_t)port); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  int ok = 0;
  int r = connect(s, (struct sockaddr*)&a, sizeof a);
  if (r == 0) ok = 1;
  else if (errno == EINPROGRESS) {
    struct pollfd pf = {s, POLLOUT, 0};
    int e = 0; socklen_t el = sizeof e;
    if (poll(&pf, 1, 150) > 0 && getsockopt(s, SOL_SOCKET, SO_ERROR, &e, &el) == 0 && e == 0) ok = 1;
  }
  close(s);
  return ok;
}
static int dir_exists(const char* rootslash) {
  char t[OG_PATH_CAP];
  snprintf(t, sizeof t, "%s", rootslash);
  t[strlen(t) - 1] = 0;
  struct stat st;
  return stat(t, &st) == 0 && S_ISDIR(st.st_mode);
}

static int h_status(Conn* c) {
  SB b = {0};
  char ver[256], fw[64];
  unsigned sdk = 0;
  plat_kernel(ver, sizeof ver, fw, sizeof fw, &sdk);
  sb_f(&b, "{\"ok\":true,\"agent\":{\"version\":\"%s\",\"uptime_s\":%ld,\"lifetime_left_s\":%ld,\"launched\":%s},", OG_VERSION, mono_s() - g_start_s,
       g_lifetime - (mono_s() - g_start_s), g_launched ? "true" : "false");
  sb_s(&b, "\"system\":{\"kernel\":"); sb_str(&b, ver);
  sb_s(&b, ",\"firmware\":"); sb_str(&b, fw);
  sb_f(&b, ",\"sdk_version\":\"0x%08x\",\"uptime_s\":%ld},", sdk, plat_uptime());
  ProcInfo* pr = malloc(sizeof *pr * OG_MAX_PROCS);
  int np = pr ? plat_procs(pr, OG_MAX_PROCS) : 0;
  int running = 0, titles = 0;
  sb_s(&b, "\"processes\":[");
  for (int i = 0; i < np; i++) {
    sb_f(&b, "%s{\"pid\":%d,\"name\":", i ? "," : "", pr[i].pid); sb_str(&b, pr[i].name);
    sb_s(&b, ",\"title\":"); sb_str(&b, pr[i].title);
    sb_s(&b, "}");
    if (pr[i].title[0]) titles = 1;
    if (!strcmp(pr[i].title, OG_TITLE)) running = 1;
  }
  sb_s(&b, "],\"tcp_ports_open\":[");
  static const int ports[] = {744, 2121, 2323, 9020, 9021, 9099};  // loopback probe of the ports this setup uses
  for (size_t i = 0, first = 1; i < sizeof ports / sizeof *ports; i++)
    if (ports[i] == g_port || port_open(ports[i])) { sb_f(&b, "%s%d", first ? "" : ",", ports[i]); first = 0; }
  sb_s(&b, "],\"mounts\":[");
  MountInfo* mi = malloc(sizeof *mi * OG_MAX_MOUNTS);
  int nm = mi ? plat_mounts(mi, OG_MAX_MOUNTS) : 0;
  for (int i = 0; i < nm; i++) {
    sb_s(&b, i ? ",{\"path\":" : "{\"path\":"); sb_str(&b, mi[i].path);
    sb_s(&b, ",\"type\":"); sb_str(&b, mi[i].type);
    sb_f(&b, ",\"free_bytes\":%llu,\"total_bytes\":%llu}", (unsigned long long)mi[i].free_b, (unsigned long long)mi[i].total_b);
  }
  char ep[OG_PATH_CAP];
  snprintf(ep, sizeof ep, "%seboot.bin", g_root_list[0]);
  struct stat st;
  long long eboot = stat(ep, &st) == 0 && S_ISREG(st.st_mode) ? (long long)st.st_size : -1;
  int app = plat_app_id(OG_TITLE);
  if (!titles && app > 0) running = 1;  // no process reported a title id: fall back to the launcher's answer
  int wd = 0;
  char probe[OG_PATH_CAP];
  snprintf(probe, sizeof probe, "%s", g_root_list[1]);
  probe[strlen(probe) - 1] = 0;
  wd = access(probe, W_OK) == 0;
  if (!wd) { char* sl = strrchr(probe, '/'); if (sl && sl != probe) { *sl = 0; wd = access(probe, W_OK) == 0; } }
  sb_f(&b, "],\"paths\":{\"app_dir_exists\":%s,\"data_dir_exists\":%s,\"eboot_size\":%lld},", dir_exists(g_root_list[0]) ? "true" : "false",
       dir_exists(g_root_list[1]) ? "true" : "false", eboot);
  sb_f(&b, "\"app\":{\"title\":\"%s\",\"running\":%s,\"app_id\":%d},\"caps\":{\"write_data\":%s,\"launch\":%s}}", OG_TITLE, running ? "true" : "false", app,
       wd ? "true" : "false", plat_can_launch() ? "true" : "false");
  free(pr); free(mi);
  int r = respond_json(c, 200, &b);
  free(b.p);
  return r;
}

static int get_param(Conn* c, const char* key, char* out, size_t cap) {  // query first, then a small form or JSON body
  int r = form_get(c->query, key, out, cap);
  if (r) return r;
  if (c->sbody_n == 0) return 0;
  return c->sbody[0] == '{' ? json_get(c->sbody, key, out, cap) : form_get(c->sbody, key, out, cap);
}

static int h_put(Conn* c) {
  char path[OG_PATH_CAP], num[32];
  long long size = -1;
  unsigned mode = 0644;
  c->close_after = 1;  // every early answer leaves the body unread
  if (get_param(c, "path", path, sizeof path) != 1) return respond_err(c, 400, "path missing or malformed");
  if (!path_ok(path, g_root_list, 0)) return respond_err(c, 403, "path not allowed");
  size_t pl = strlen(path);
  if (pl > 5 && !strcmp(path + pl - 5, ".part")) return respond_err(c, 400, "name ends with .part");
  int gp = get_param(c, "size", num, sizeof num);
  if (gp < 0) return respond_err(c, 400, "bad size");
  if (gp == 1) {
    char* e; errno = 0; size = strtoll(num, &e, 10);
    if (*e || errno || size < 0 || !isdigit((unsigned char)num[0])) return respond_err(c, 400, "bad size");
  }
  gp = get_param(c, "mode", num, sizeof num);
  if (gp < 0) return respond_err(c, 400, "bad mode");
  if (gp == 1) {
    char* e; errno = 0; unsigned long m = strtoul(num, &e, 8);
    if (*e || errno || !num[0] || m > 0777) return respond_err(c, 400, "bad mode");
    mode = (unsigned)m;
  }
  if (c->clen < 0) return respond_err(c, 411, "Content-Length required");
  if (size < 0) size = c->clen;
  if (size != c->clen) return respond_err(c, 400, "size differs from Content-Length");
  if (size > OG_MAX_FILE) return respond_err(c, 413, "file too large");
  struct stat st;
  if (lstat(path, &st) == 0 && !S_ISREG(st.st_mode)) return respond_err(c, 409, "target exists and is not a regular file");
  char dir[OG_PATH_CAP];
  snprintf(dir, sizeof dir, "%s", path);
  *strrchr(dir, '/') = 0;
  if (mkdir_p(dir, 0755)) return respond_err(c, 500, strerror(errno));
  char part[OG_PATH_CAP + 8];
  snprintf(part, sizeof part, "%s.part", path);
  if (!part_claim(part)) return respond_err(c, 409, "another upload of this path is running");
  int fd = open(part, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0600);
  if (fd < 0) { int e = errno; part_release(part); return respond_err(c, 500, strerror(e)); }
  if (c->expect100) send_all(c->fd, "HTTP/1.1 100 Continue\r\n\r\n", 25);
  unsigned char* io = malloc(256 * 1024);
  int fail = !io, werr = 0;
  while (!fail && c->body_left > 0) {
    ssize_t r = body_read(c, io, 256 * 1024);
    if (r <= 0) { fail = 1; break; }
    for (ssize_t o = 0; o < r;) {
      ssize_t w = write(fd, io + o, (size_t)(r - o));
      if (w < 0 && errno == EINTR) continue;
      if (w <= 0) { werr = errno; fail = 1; break; }
      o += w;
    }
  }
  free(io);
  int bad = fail || c->body_left != 0 || chmod(part, (mode_t)mode) != 0;
  if (close(fd) && !werr) werr = errno;
  if (bad || werr || rename(part, path)) {
    int e = werr ? werr : errno;
    unlink(part);
    part_release(part);
    if (c->body_left > 0 && !werr) return -1;  // peer went away mid-upload: nothing to answer
    return respond_err(c, e == ENOSPC || e == EDQUOT ? 507 : 500, strerror(e));
  }
  part_release(part);
  c->close_after = 0;
  SB b = {0};
  sb_s(&b, "{\"ok\":true,\"path\":"); sb_str(&b, path);
  sb_f(&b, ",\"size\":%lld,\"mode\":\"%03o\"}", size, mode);
  int r = respond_json(c, 200, &b);
  free(b.p);
  return r;
}

static int h_get_file(Conn* c) {
  char path[OG_PATH_CAP], num[32];
  if (get_param(c, "path", path, sizeof path) != 1) return respond_err(c, 400, "path missing or malformed");
  if (!path_ok(path, g_root_list, 0)) return respond_err(c, 403, "path not allowed");
  int fd = open(path, O_RDONLY | O_NOFOLLOW);
  struct stat st;
  if (fd < 0) return respond_err(c, errno == ENOENT ? 404 : 500, strerror(errno));
  if (fstat(fd, &st) || !S_ISREG(st.st_mode)) { close(fd); return respond_err(c, 409, "not a regular file"); }
  long long fsz = st.st_size, off = 0, len;
  if (get_param(c, "tail", num, sizeof num) == 1) { long long t = atoll(num); if (t < 0) t = 0; off = t < fsz ? fsz - t : 0; }
  else if (get_param(c, "offset", num, sizeof num) == 1) { off = atoll(num); if (off < 0 || off > fsz) off = fsz; }
  len = fsz - off;
  if (get_param(c, "len", num, sizeof num) == 1) { long long l = atoll(num); if (l >= 0 && l < len) len = l; }
  if (len > OG_GET_MAX) len = OG_GET_MAX;
  char extra[64];
  snprintf(extra, sizeof extra, "X-OG-File-Size: %lld\r\n", fsz);
  if (lseek(fd, (off_t)off, SEEK_SET) < 0 || respond_head(c, 200, "application/octet-stream", len, extra)) { close(fd); return -1; }
  char* io = malloc(65536);
  int rc = io ? 0 : -1;
  while (rc == 0 && len > 0) {
    ssize_t r = read(fd, io, len < 65536 ? (size_t)len : 65536);
    if (r <= 0 || send_all(c->fd, io, (size_t)r)) rc = -1;  // the length is already promised, so the connection has to end
    else len -= r;
  }
  free(io);
  close(fd);
  return rc;
}

static int h_mkdir(Conn* c) {
  char path[OG_PATH_CAP];
  if (get_param(c, "path", path, sizeof path) != 1) return respond_err(c, 400, "path missing or malformed");
  if (!path_ok(path, g_root_list, 1)) return respond_err(c, 403, "path not allowed");
  if (mkdir_p(path, 0755)) return respond_err(c, 500, strerror(errno));
  SB b = {0};
  sb_s(&b, "{\"ok\":true,\"path\":"); sb_str(&b, path); sb_s(&b, "}");
  int r = respond_json(c, 200, &b);
  free(b.p);
  return r;
}

static int h_rm(Conn* c) {
  char path[OG_PATH_CAP], num[16];
  if (get_param(c, "path", path, sizeof path) != 1) return respond_err(c, 400, "path missing or malformed");
  if (!path_ok(path, g_rm_list, 0)) return respond_err(c, 403, "path not allowed");  // the root folders themselves are never removed
  int rec = get_param(c, "recursive", num, sizeof num) == 1 && (!strcmp(num, "1") || !strcmp(num, "true"));
  struct stat st;
  long removed = 0;
  if (lstat(path, &st)) {
    if (errno != ENOENT) return respond_err(c, 500, strerror(errno));
  } else if (S_ISDIR(st.st_mode) && !rec) {
    if (rmdir(path)) return respond_err(c, errno == ENOTEMPTY ? 409 : 500, errno == ENOTEMPTY ? "directory not empty (use recursive=1)" : strerror(errno));
    removed = 1;
  } else {
    char t[OG_PATH_CAP];
    snprintf(t, sizeof t, "%s", path);
    if (rm_tree(t, sizeof t, 0, &removed)) return respond_err(c, 500, strerror(errno));
  }
  SB b = {0};
  sb_s(&b, "{\"ok\":true,\"path\":"); sb_str(&b, path); sb_f(&b, ",\"removed\":%ld}", removed);
  int r = respond_json(c, 200, &b);
  free(b.p);
  return r;
}

static int title_param(Conn* c, char* title, size_t cap) {  // 0 ok, else HTTP code sent
  strcpy(title, OG_TITLE);
  int r = get_param(c, "title", title, cap);
  if (r < 0) return respond_err(c, 400, "bad title"), 400;
  if (strcmp(title, OG_TITLE)) return respond_err(c, 403, "title not allowed"), 403;
  return 0;
}
static int h_launch(Conn* c) {
  char title[32];
  if (title_param(c, title, sizeof title)) return 0;
  int r = plat_launch(title);
  if (r == 0) { g_launched = 1; g_last_act = mono_s(); }
  lg("launch %s -> 0x%x", title, (unsigned)r);
  SB b = {0};
  sb_f(&b, "{\"ok\":%s,\"title\":\"%s\",\"launch\":%d}", r == 0 ? "true" : "false", title, r);
  int rc = respond_json(c, r == 0 ? 200 : 500, &b);
  free(b.p);
  return rc;
}
static int h_kill(Conn* c) {
  char title[32];
  int app, r1, r2;
  if (title_param(c, title, sizeof title)) return 0;
  plat_kill(title, &app, &r1, &r2);
  lg("kill %s app=0x%x kill=0x%x force=0x%x", title, (unsigned)app, (unsigned)r1, (unsigned)r2);
  SB b = {0};
  sb_f(&b, "{\"ok\":true,\"title\":\"%s\",\"app_id\":%d,\"kill\":%d,\"force_kill\":%d}", title, app, r1, r2);
  int rc = respond_json(c, 200, &b);
  free(b.p);
  return rc;
}
static int h_log(Conn* c) {
  char num[16];
  int want = 100;
  if (get_param(c, "tail", num, sizeof num) == 1) want = atoi(num);
  if (want < 1) want = 1;
  if (want > OG_RING_LINES) want = OG_RING_LINES;
  SB b = {0};
  sb_s(&b, "{\"ok\":true,\"lines\":[");
  pthread_mutex_lock(&g_logmu);
  unsigned total = g_ring_n, have = total < OG_RING_LINES ? total : OG_RING_LINES;
  unsigned cnt = (unsigned)want < have ? (unsigned)want : have;
  for (unsigned i = 0; i < cnt; i++) {
    if (i) sb_s(&b, ",");
    sb_str(&b, g_ring[(total - cnt + i) % OG_RING_LINES]);
  }
  pthread_mutex_unlock(&g_logmu);
  sb_s(&b, "]}");
  int r = respond_json(c, 200, &b);
  free(b.p);
  return r;
}
static int h_shutdown(Conn* c) {
  SB b = {0};
  sb_s(&b, "{\"ok\":true,\"shutdown\":true}");
  c->close_after = 1;
  int r = respond_json(c, 200, &b);
  free(b.p);
  g_stop = 1;
  return r;
}

static int dispatch(Conn* c) {
  const char* p = c->path;
  int get = !strcmp(c->method, "GET"), put = !strcmp(c->method, "PUT"), post = !strcmp(c->method, "POST");
  if (!strcmp(p, "/v1/status")) return get ? h_status(c) : respond_err(c, 405, "use GET");
  if (!strcmp(p, "/v1/file")) return put ? h_put(c) : get ? h_get_file(c) : respond_err(c, 405, "use GET or PUT");
  if (!strcmp(p, "/v1/log")) return get ? h_log(c) : respond_err(c, 405, "use GET");
  if (!strcmp(p, "/v1/mkdir")) return post ? h_mkdir(c) : respond_err(c, 405, "use POST");
  if (!strcmp(p, "/v1/rm")) return post ? h_rm(c) : respond_err(c, 405, "use POST");
  if (!strcmp(p, "/v1/launch")) return post ? h_launch(c) : respond_err(c, 405, "use POST");
  if (!strcmp(p, "/v1/kill")) return post ? h_kill(c) : respond_err(c, 405, "use POST");
  if (!strcmp(p, "/v1/shutdown")) return post ? h_shutdown(c) : respond_err(c, 405, "use POST");
  return respond_err(c, 404, "unknown endpoint");
}

// ---- request parsing. Returns 1 request ready, 0 connection ended quietly, -1 protocol error (answer sent, close).
static int bad(Conn* c, int code, const char* msg) { c->close_after = 1; respond_err(c, code, msg); return -1; }
static int ieq(const char* a, const char* b) { for (; *a && *b; a++, b++) if (tolower((unsigned char)*a) != tolower((unsigned char)*b)) return 0; return *a == *b; }
static int read_request(Conn* c) {
  size_t scan = 0, hend = 0;
  int found = 0;
  for (;;) {
    for (; scan + 3 < c->n; scan++)
      if (c->buf[scan] == '\r' && c->buf[scan + 1] == '\n' && c->buf[scan + 2] == '\r' && c->buf[scan + 3] == '\n') { hend = scan; found = 1; break; }
    if (found) break;
    if (c->n >= OG_HDR_MAX) { c->keepalive = 0; return bad(c, 431, "headers too large"); }
    ssize_t r = recv(c->fd, c->buf + c->n, IOBUF - c->n, 0);
    if (r < 0 && errno == EINTR) continue;
    if (r <= 0) return 0;
    c->n += (size_t)r;
  }
  if (hend > OG_HDR_MAX) { c->keepalive = 0; return bad(c, 431, "headers too large"); }
  c->keepalive = 0;
  c->clen = -1; c->has_te = c->has_token = c->expect100 = 0; c->token[0] = 0; c->close_after = 0; c->code = 0;
  c->sbody_n = 0; c->sbody[0] = 0;
  for (size_t i = 0; i < hend; i++) if (c->buf[i] == 0 || (c->buf[i] < 0x20 && c->buf[i] != '\r' && c->buf[i] != '\n' && c->buf[i] != '\t')) return bad(c, 400, "control character in header");
  char* h = (char*)c->buf;
  h[hend] = 0;
  char* eol = strstr(h, "\r\n");
  if (eol) *eol = 0;
  // request line
  char* sp1 = strchr(h, ' ');
  char* sp2 = sp1 ? strchr(sp1 + 1, ' ') : NULL;
  if (!sp1 || !sp2 || sp1 == h) return bad(c, 400, "bad request line");
  *sp1 = 0; *sp2 = 0;
  if (strlen(h) >= sizeof c->method || strlen(sp1 + 1) >= sizeof c->target || sp1[1] != '/') return bad(c, 400, "bad request line");
  for (char* m = h; *m; m++) if (!isupper((unsigned char)*m)) return bad(c, 400, "bad method");
  snprintf(c->method, sizeof c->method, "%.11s", h);
  snprintf(c->target, sizeof c->target, "%s", sp1 + 1);
  if (!strcmp(sp2 + 1, "HTTP/1.1")) c->http11 = 1; else if (!strcmp(sp2 + 1, "HTTP/1.0")) c->http11 = 0; else return bad(c, 400, "unsupported HTTP version");
  c->keepalive = c->http11;
  snprintf(c->path, sizeof c->path, "%s", c->target);
  char* q = strchr(c->path, '?');
  if (q) { *q = 0; c->query = c->target + (q - c->path) + 1; } else c->query = "";
  // headers
  int nh = 0;
  char* line = eol ? eol + 2 : h + hend;
  while (eol && *line) {
    char* nx = strstr(line, "\r\n");
    if (nx) *nx = 0;
    if (++nh > 64) return bad(c, 431, "too many headers");
    if (*line == ' ' || *line == '\t') return bad(c, 400, "folded header");
    char* colon = strchr(line, ':');
    if (!colon || colon == line) return bad(c, 400, "bad header");
    *colon = 0;
    for (char* t = line; *t; t++) if (*t == ' ' || *t == '\t') return bad(c, 400, "bad header name");
    char* v = colon + 1;
    while (*v == ' ' || *v == '\t') v++;
    size_t vl = strlen(v);
    while (vl && (v[vl - 1] == ' ' || v[vl - 1] == '\t')) v[--vl] = 0;
    if (ieq(line, "content-length")) {
      if (!vl || vl > 19) return bad(c, 400, "bad Content-Length");
      long long x = 0;
      for (size_t i = 0; i < vl; i++) { if (!isdigit((unsigned char)v[i])) return bad(c, 400, "bad Content-Length"); x = x * 10 + (v[i] - '0'); }
      if (c->clen >= 0 && c->clen != x) return bad(c, 400, "conflicting Content-Length");
      c->clen = x;
    } else if (ieq(line, "x-og-token")) {
      c->has_token = 1;
      snprintf(c->token, sizeof c->token, "%s", v);
    } else if (ieq(line, "transfer-encoding")) c->has_te = 1;
    else if (ieq(line, "connection")) {
      char lo[64]; size_t i = 0;
      for (; v[i] && i < sizeof lo - 1; i++) lo[i] = (char)tolower((unsigned char)v[i]);
      lo[i] = 0;
      if (strstr(lo, "close")) c->keepalive = 0; else if (strstr(lo, "keep-alive")) c->keepalive = 1;
    } else if (ieq(line, "expect") && ieq(v, "100-continue")) c->expect100 = 1;
    if (!nx) break;
    line = nx + 2;
  }
  size_t used = hend + 4;
  c->pre = c->buf + used;
  c->prelen = c->n - used;
  c->body_left = c->clen > 0 ? c->clen : 0;
  return 1;
}
static void log_request(Conn* c) {
  char t[200];
  snprintf(t, sizeof t, "%.190s", c->target);
  lg("%s %s %s -> %d", c->peer, c->method, t, c->code);
}

static void* conn_thread(void* arg) {
  Conn* c = arg;
  struct timeval tv = {60, 0};
  setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
  setsockopt(c->fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
#ifdef SO_NOSIGPIPE
  int one = 1;
  setsockopt(c->fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#endif
  for (int served = 0; served < 100000 && !g_stop; served++) {
    int r = read_request(c);
    if (r <= 0) {
      if (r < 0) log_request(c);
      break;
    }
    __sync_fetch_and_add(&g_active_req, 1);
    int rc = 0;
    if (!tok_ok(c)) {
      usleep(100000);  // slows token guessing
      c->close_after = 1;
      respond_err(c, 401, "bad or missing X-OG-Token");
    } else {
      g_last_act = mono_s();
      int upload = !strcmp(c->method, "PUT") && !strcmp(c->path, "/v1/file");
      if (c->has_te) { c->close_after = 1; rc = respond_err(c, 501, "Transfer-Encoding is not supported"); }
      else if (!upload && c->clen > OG_MAX_SMALL_BODY) { c->close_after = 1; rc = respond_err(c, 413, "body too large"); }
      else {
        if (!upload && c->body_left > 0) {  // small bodies are read up front
          while (c->body_left > 0 && rc == 0) {
            ssize_t n = body_read(c, c->sbody + c->sbody_n, sizeof c->sbody - 1 - c->sbody_n);
            if (n <= 0) rc = -1; else c->sbody_n += (size_t)n;
          }
          c->sbody[c->sbody_n] = 0;
          if (memchr(c->sbody, 0, c->sbody_n)) { c->close_after = 1; rc = respond_err(c, 400, "NUL in body"); }
        }
        if (rc == 0) rc = dispatch(c);
      }
    }
    if (c->code) log_request(c); else lg("%s %s %s -> (aborted)", c->peer, c->method, c->target);
    g_last_act = mono_s();
    __sync_fetch_and_sub(&g_active_req, 1);
    if (rc || c->close_after || !c->keepalive || c->body_left > 0) break;
    // pipelined bytes after the body start the next request
    memmove(c->buf, c->pre, c->prelen);
    c->n = c->prelen;
  }
  close(c->fd);
  __sync_fetch_and_sub(&g_conns, 1);
  free(c);
  return NULL;
}

// =================================================================================================== main
static int token_valid(void) {
  int allx = 1;
  for (int i = 0; i < OG_TOKEN_LEN; i++) {
    char ch = OG_TOKEN[i];
    if (ch < 0x21 || ch > 0x7e) return 0;
    if (ch != 'x') allx = 0;
  }
  return !allx;  // still the filler: nobody patched it
}

#ifdef OG_HOST
static void host_root(int i, const char* d) {
  char rp[4096];
  snprintf(g_hostroot[i], OG_PATH_CAP, "%.900s", realpath(d, rp) ? rp : d);
  size_t l = strlen(g_hostroot[i]);
  if (l && g_hostroot[i][l - 1] != '/') strcat(g_hostroot[i], "/");
}
#endif

int main(int argc, char** argv) {
  signal(SIGPIPE, SIG_IGN);
  pthread_mutex_init(&g_logmu, NULL); pthread_mutex_init(&g_partmu, NULL); pthread_mutex_init(&g_lncmu, NULL);
  g_start_s = mono_s();
  g_last_act = g_start_s;
  g_root_list[0] = "/data/homebrew/" OG_TITLE "/";
  g_root_list[1] = "/data/opengoal/";
  g_rm_list[0] = g_root_list[0];
  g_rm_list[1] = "/data/opengoal/tmp/";
#ifdef OG_HOST
  const char *app = NULL, *data = NULL;
  for (int i = 1; i + 1 < argc; i += 2) {
    if (!strcmp(argv[i], "--port")) g_port = atoi(argv[i + 1]);
    else if (!strcmp(argv[i], "--app")) app = argv[i + 1];
    else if (!strcmp(argv[i], "--data")) data = argv[i + 1];
    else if (!strcmp(argv[i], "--lifetime")) g_lifetime = atol(argv[i + 1]);
    else if (!strcmp(argv[i], "--idle")) g_idle = atol(argv[i + 1]);
    else if (!strcmp(argv[i], "--token") && strlen(argv[i + 1]) == OG_TOKEN_LEN) memcpy(og_token_blob + OG_MARK_LEN, argv[i + 1], OG_TOKEN_LEN);
  }
  if (!app || !data) { fprintf(stderr, "usage: ogagent_host --app DIR --data DIR [--port N] [--token T32] [--lifetime S] [--idle S]\n"); return 2; }
  host_root(0, app); host_root(1, data);
  snprintf(g_hostroot[2], OG_PATH_CAP, "%.1000stmp/", g_hostroot[1]);
  g_root_list[0] = g_hostroot[0]; g_root_list[1] = g_hostroot[1]; g_rm_list[0] = g_hostroot[0]; g_rm_list[1] = g_hostroot[2];
#else
  (void)argc; (void)argv;
#endif
  if (!token_valid()) { plat_notify("OpenGOAL setup agent: token not set, exiting"); return 3; }
  int ls = socket(AF_INET, SOCK_STREAM, 0);
  int yes = 1;
  setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof yes);
  struct sockaddr_in a;
  memset(&a, 0, sizeof a);
  a.sin_family = AF_INET; a.sin_port = htons((uint16_t)g_port); a.sin_addr.s_addr = htonl(INADDR_ANY);
  if (ls < 0 || bind(ls, (struct sockaddr*)&a, sizeof a) || listen(ls, 16)) {
    lg("start: port %d not available (%s), another agent is probably running", g_port, strerror(errno));  // second instance: leave quietly
    return 0;
  }
  lg("agent %s listening on %d", OG_VERSION, g_port);
  plat_notify("OpenGOAL setup agent ready");
  while (!g_stop) {
    long now = mono_s();
    if (now - g_start_s >= g_lifetime) { lg("lifetime over, exiting"); break; }
    if (g_launched && g_active_req == 0 && now - g_last_act >= g_idle) { lg("idle after launch, exiting"); break; }
    struct pollfd pf = {ls, POLLIN, 0};
    if (poll(&pf, 1, 500) <= 0 || !(pf.revents & POLLIN)) continue;
    struct sockaddr_in pa;
    socklen_t pl = sizeof pa;
    int fd = accept(ls, (struct sockaddr*)&pa, &pl);
    if (fd < 0) continue;
    Conn* c = g_conns < OG_MAX_CONNS ? calloc(1, sizeof *c) : NULL;
    if (!c) {
      static const char busy[] = "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n";
      send_all(fd, busy, sizeof busy - 1);
      close(fd);
      continue;
    }
    c->fd = fd;
    inet_ntop(AF_INET, &pa.sin_addr, c->peer, sizeof c->peer);
    __sync_fetch_and_add(&g_conns, 1);
    pthread_t t;
    if (pthread_create(&t, NULL, conn_thread, c)) { __sync_fetch_and_sub(&g_conns, 1); close(fd); free(c); continue; }
    pthread_detach(t);
  }
  usleep(300000);  // let the last answer (shutdown) leave
  close(ls);
  return 0;
}
