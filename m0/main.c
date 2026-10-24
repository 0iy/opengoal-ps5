#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
#include <unistd.h>

#define LOG "/data/homebrew/m0.log"
#define W 1920
#define H 1080
#define NBUF 2
#define MB2 (2u << 20)

typedef struct { uint8_t pad[64]; } vo_attr_t;

int sceUserServiceInitialize(void*);
int sceUserServiceGetInitialUser(int*);
int sceVideoOutOpen(int user, int type, int idx, const void* param);
int sceVideoOutClose(int h);
void sceVideoOutSetBufferAttribute(vo_attr_t*, unsigned fmt, unsigned tiling, unsigned aspect,
                                   unsigned w, unsigned h, unsigned pitch);
int sceVideoOutRegisterBuffers(int h, int start, void* const* addrs, int n, const vo_attr_t* a);
int sceVideoOutSetFlipRate(int h, int rate);
int sceVideoOutSubmitFlip(int h, int idx, unsigned mode, int64_t arg);
int sceKernelAllocateDirectMemory(int64_t s, int64_t e, size_t len, size_t align, int type, int64_t* phys);
int sceKernelMapDirectMemory(void** addr, size_t len, int prot, int flags, int64_t phys, size_t align);
int64_t sceKernelGetDirectMemorySize(void);
int scePadInit(void);
int scePadOpen(int user, int type, int idx, const void* param);
int scePadReadState(int h, void* state);
int sceKernelUsleep(unsigned us);

static FILE* lg;
static void L(const char* what, int rc) { fprintf(lg, "%-28s rc=0x%08x\n", what, (unsigned)rc); fflush(lg); }

int main() {
  lg = fopen(LOG, "w");
  if (!lg) return 1;
  int rc;
  rc = sceUserServiceInitialize(0); L("UserServiceInitialize", rc);
  int user = 0; rc = sceUserServiceGetInitialUser(&user); L("GetInitialUser", rc);
  fprintf(lg, "user=%d\n", user); fflush(lg);

  int vo = sceVideoOutOpen(255 /*system*/, 0, 0, 0); L("VideoOutOpen(255)", vo);
  if (vo < 0) { vo = sceVideoOutOpen(user, 0, 0, 0); L("VideoOutOpen(user)", vo); }

  int64_t dmem = sceKernelGetDirectMemorySize();
  fprintf(lg, "direct mem size=%lld\n", (long long)dmem); fflush(lg);
  size_t fb = ((size_t)W * H * 4 + MB2 - 1) & ~(size_t)(MB2 - 1);
  void* addr[NBUF]; int ok = 1;
  for (int i = 0; i < NBUF; i++) {
    int64_t phys = 0;
    rc = sceKernelAllocateDirectMemory(0, dmem, fb, MB2, 3, &phys); L("AllocDirectMem", rc);
    if (rc) { ok = 0; break; }
    addr[i] = 0;
    rc = sceKernelMapDirectMemory(&addr[i], fb, 0x33, 0, phys, MB2); L("MapDirectMem", rc);
    if (rc) { ok = 0; break; }
    fprintf(lg, "fb%d=%p\n", i, addr[i]); fflush(lg);
  }

  if (vo >= 0 && ok) {
    vo_attr_t at; memset(&at, 0, sizeof at);
    sceVideoOutSetBufferAttribute(&at, 0x80000000u /*A8R8G8B8_SRGB*/, 1 /*linear*/, 0, W, H, W);
    rc = sceVideoOutRegisterBuffers(vo, 0, addr, NBUF, &at); L("RegisterBuffers", rc);
    rc = sceVideoOutSetFlipRate(vo, 0); L("SetFlipRate", rc);
  }

  scePadInit();
  int pad = scePadOpen(user, 0, 0, 0); L("PadOpen", pad);

  uint32_t last = 0xFFFFFFFFu;
  for (int f = 0; f < 60 * 15; f++) {
    if (vo >= 0 && ok) {
      uint32_t c = 0xFF000000u | ((f * 3) & 0xFF) << 16 | ((255 - (f * 3 & 0xFF)) << 8) | 0x40;
      uint32_t* p = (uint32_t*)addr[f & 1];
      for (size_t i = 0; i < (size_t)W * H; i++) p[i] = c;
      rc = sceVideoOutSubmitFlip(vo, f & 1, 1, f);
      if (f < 3) L("SubmitFlip", rc);
    }
    if (pad >= 0) {
      uint8_t st[512]; memset(st, 0, sizeof st);
      rc = scePadReadState(pad, st);
      uint32_t btn; memcpy(&btn, st, 4);
      if (btn != last) { fprintf(lg, "f=%d pad rc=0x%x buttons=0x%08x\n", f, (unsigned)rc, btn); fflush(lg); last = btn; }
    }
    sceKernelUsleep(16000);
  }
  if (vo >= 0) sceVideoOutClose(vo);
  fprintf(lg, "DONE\n"); fclose(lg);
  return 0;
}
