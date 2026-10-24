#include <stdio.h>
#include <string.h>
extern int* __error(void);
#define errno (*__error())
#include <stdint.h>
#include <sys/mman.h>

#define LOG "/data/homebrew/m1.log"
#define EE_MAP 0x2123000000ULL
#define EE_SIZE (128u << 20)

typedef struct notify_request {
  char useless1[45];
  char message[3075];
} notify_request_t;
int sceKernelSendNotificationRequest(int, notify_request_t*, size_t, int);

static FILE* lg;
static void say(const char* m) {
  notify_request_t r; memset(&r, 0, sizeof r);
  strncpy(r.message, m, sizeof r.message - 1);
  sceKernelSendNotificationRequest(0, &r, sizeof r, 0);
}

static int try_exec(const char* name, void* p) {
  /* mov eax,42 ; ret */
  static const unsigned char code[] = {0xB8, 0x2A, 0x00, 0x00, 0x00, 0xC3};
  memcpy(p, code, sizeof code);
  int rv = ((int (*)(void))p)();
  fprintf(lg, "%s: exec returned %d\n", name, rv);
  fflush(lg);
  return rv == 42;
}

int main() {
  lg = fopen(LOG, "w");
  if (!lg) { say("M1: cannot open log"); return 1; }
  int ok = 0;

  /* A: RWX, address hint only (what jak-project does) */
  void* a = mmap((void*)EE_MAP, EE_SIZE, PROT_READ | PROT_WRITE | PROT_EXEC,
                 MAP_ANON | MAP_PRIVATE, -1, 0);
  fprintf(lg, "A rwx hint: ret=%p errno=%d want=%p\n", a, a == MAP_FAILED ? errno : 0, (void*)EE_MAP);
  fflush(lg);
  if (a != MAP_FAILED) {
    ok += try_exec("A", a);
    if (a != (void*)EE_MAP) fprintf(lg, "A: address differs from request\n");
    munmap(a, EE_SIZE);
  }

  /* B: RW at fixed address then mprotect to RWX */
  void* b = mmap((void*)EE_MAP, EE_SIZE, PROT_READ | PROT_WRITE,
                 MAP_ANON | MAP_PRIVATE | MAP_FIXED, -1, 0);
  fprintf(lg, "B rw fixed: ret=%p errno=%d\n", b, b == MAP_FAILED ? errno : 0);
  fflush(lg);
  if (b != MAP_FAILED) {
    int pr = mprotect(b, EE_SIZE, PROT_READ | PROT_WRITE | PROT_EXEC);
    fprintf(lg, "B mprotect rwx: %d errno=%d\n", pr, pr ? errno : 0);
    fflush(lg);
    if (pr == 0) ok += try_exec("B", b);
    munmap(b, EE_SIZE);
  }

  /* C: small RWX anywhere (baseline JIT test) */
  void* c = mmap(0, 4096, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_ANON | MAP_PRIVATE, -1, 0);
  fprintf(lg, "C rwx 4k any: ret=%p errno=%d\n", c, c == MAP_FAILED ? errno : 0);
  fflush(lg);
  if (c != MAP_FAILED) { ok += try_exec("C", c); munmap(c, 4096); }

  fprintf(lg, "RESULT ok=%d/3\n", ok);
  fclose(lg);
  char m[64]; snprintf(m, sizeof m, "M1 done: %d/3 exec tests passed", ok);
  say(m);
  return 0;
}
