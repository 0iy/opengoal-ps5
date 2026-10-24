#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <signal.h>
#include <unistd.h>
#include <sys/mman.h>
extern int* __error(void);
#define errn (*__error())

#ifndef VAR
#define VAR 'A'
#endif
#define EE_MAP 0x2123000000ULL
#define EE_SIZE (128u << 20)
static FILE* lg;

static void on_sig(int sig, siginfo_t* si, void* uc) {
  (void)uc;
  fprintf(lg, "SIGNAL %d code=%d addr=%p\n", sig, si->si_code, si->si_addr);
  fclose(lg);
  _exit(2);
}

int main() {
  char path[64]; snprintf(path, sizeof path, "/data/homebrew/m1_%c.log", VAR);
  lg = fopen(path, "w");
  if (!lg) return 1;
  struct sigaction sa; memset(&sa, 0, sizeof sa);
  sa.sa_sigaction = on_sig; sa.sa_flags = SA_SIGINFO;
  sigaction(SIGSEGV, &sa, 0); sigaction(SIGBUS, &sa, 0); sigaction(SIGILL, &sa, 0);

  static const unsigned char code[] = {0xB8, 0x2A, 0x00, 0x00, 0x00, 0xC3};
  void* p = MAP_FAILED;
  if (VAR == 'A') p = mmap((void*)EE_MAP, EE_SIZE, PROT_READ|PROT_WRITE|PROT_EXEC, MAP_ANON|MAP_PRIVATE, -1, 0);
  if (VAR == 'B') { /* RW, then mprotect RX after write */
    p = mmap((void*)EE_MAP, EE_SIZE, PROT_READ|PROT_WRITE, MAP_ANON|MAP_PRIVATE, -1, 0);
    if (p != MAP_FAILED) { memcpy(p, code, sizeof code);
      int r = mprotect(p, 4096, PROT_READ|PROT_EXEC);
      fprintf(lg, "mprotect RX r=%d errno=%d\n", r, r ? errn : 0); } }
  if (VAR == 'D') { /* RW map, then mprotect whole region RWX */
    p = mmap((void*)EE_MAP, EE_SIZE, PROT_READ|PROT_WRITE, MAP_ANON|MAP_PRIVATE, -1, 0);
    if (p != MAP_FAILED) { int r = mprotect(p, EE_SIZE, PROT_READ|PROT_WRITE|PROT_EXEC);
      fprintf(lg, "mprotect RWX whole r=%d errno=%d\n", r, r ? errn : 0); } }
  if (VAR == 'E') { /* RW map, write code, RX first page, then write data to later page, call */
    p = mmap((void*)EE_MAP, EE_SIZE, PROT_READ|PROT_WRITE, MAP_ANON|MAP_PRIVATE, -1, 0);
    if (p != MAP_FAILED) { memcpy(p, code, sizeof code);
      int r = mprotect(p, 4096, PROT_READ|PROT_EXEC);
      ((unsigned char*)p)[4096*4] = 7;
      fprintf(lg, "RX first page r=%d, write to other RW page ok\n", r); } }
  if (VAR == 'C') p = mmap(0, 4096, PROT_READ|PROT_WRITE|PROT_EXEC, MAP_ANON|MAP_PRIVATE, -1, 0);
  fprintf(lg, "var %c: map=%p errno=%d\n", VAR, p, p == MAP_FAILED ? errn : 0);
  fflush(lg);
  if (p == MAP_FAILED) { fclose(lg); return 3; }
  if (VAR != 'B' && VAR != 'E') memcpy(p, code, sizeof code);
  fprintf(lg, "write ok, calling\n"); fflush(lg);
  int rv = ((int(*)(void))p)();
  fprintf(lg, "EXEC OK rv=%d\n", rv);
  fclose(lg);
  return 0;
}
