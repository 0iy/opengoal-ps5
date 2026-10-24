// Decode an .at9 (RIFF) with the reference LibAtrac9 decoder; print codec info, per-superframe status, write s16 stereo wav.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "C/src/libatrac9.h"

int main(int argc, char **argv) {
  FILE *f = fopen(argv[1], "rb");
  fseek(f, 0, SEEK_END);
  long n = ftell(f);
  fseek(f, 0, SEEK_SET);
  unsigned char *b = malloc(n);
  fread(b, 1, n, f);
  fclose(f);
  // find fmt and data chunks
  long p = 12, dataoff = 0, datalen = 0;
  unsigned char cfg[4] = {0};
  while (p + 8 <= n) {
    unsigned sz = b[p + 4] | b[p + 5] << 8 | b[p + 6] << 16 | (unsigned)b[p + 7] << 24;
    if (!memcmp(b + p, "fmt ", 4)) {
      // extradata after the 16-byte GUID: u32 version, u8[4] config
      long e = p + 8 + 24 + 16;  // WAVEFORMATEXTENSIBLE: 18 + 22 -> subformat GUID at +24
      printf("fmt size=%u guid-end-bytes: ", sz);
      for (int i = 0; i < 12; i++) printf("%02x ", b[e + i]);
      printf("\n");
      memcpy(cfg, b + e + 4, 4);
    } else if (!memcmp(b + p, "data", 4)) {
      dataoff = p + 8;
      datalen = sz;
      break;
    }
    p += 8 + sz + (sz & 1);
  }
  printf("config %02x %02x %02x %02x data off=%ld len=%ld\n", cfg[0], cfg[1], cfg[2], cfg[3], dataoff, datalen);
  void *h = Atrac9GetHandle();
  int r = Atrac9InitDecoder(h, cfg);
  printf("init=%d\n", r);
  Atrac9CodecInfo ci;
  Atrac9GetCodecInfo(h, &ci);
  printf("channels=%d rate=%d superframeSize=%d framesInSuperframe=%d frameSamples=%d wlength=%d configData=%02x%02x%02x%02x\n", ci.channels, ci.samplingRate, ci.superframeSize, ci.framesInSuperframe, ci.frameSamples, ci.wlength, ci.configData[0], ci.configData[1], ci.configData[2], ci.configData[3]);
  int sfs = ci.superframeSize, spsf = ci.frameSamples * ci.framesInSuperframe;
  long nsf = datalen / sfs;
  short *pcm = calloc(nsf * spsf * ci.channels, 2);
  int bad = 0;
  for (long i = 0; i < nsf; i++) {
    int off = 0;
    for (int fr = 0; fr < ci.framesInSuperframe; fr++) {
      int used = 0;
      int e = Atrac9Decode(h, b + dataoff + i * sfs + off, pcm + (i * spsf + fr * ci.frameSamples) * ci.channels, &used);
      if (i < 3) printf("sf %ld frame %d err=%d used=%d\n", i, fr, e, used);
      if (e != 0) { if (bad++ < 10) printf("superframe %ld frame %d: err=%d used=%d\n", i, fr, e, used); break; }
      off += used;
    }
  }
  printf("superframes=%ld bad=%d samples/ch=%ld\n", nsf, bad, nsf * spsf);
  FILE *o = fopen(argv[2], "wb");
  unsigned dl = nsf * spsf * ci.channels * 2, rl = 36 + dl, sr = ci.samplingRate, br = sr * ci.channels * 2;
  unsigned short ch = ci.channels, ba = ci.channels * 2, bits = 16, one = 1;
  unsigned sixteen = 16;
  fwrite("RIFF", 1, 4, o); fwrite(&rl, 4, 1, o); fwrite("WAVEfmt ", 1, 8, o); fwrite(&sixteen, 4, 1, o);
  fwrite(&one, 2, 1, o); fwrite(&ch, 2, 1, o); fwrite(&sr, 4, 1, o); fwrite(&br, 4, 1, o); fwrite(&ba, 2, 1, o); fwrite(&bits, 2, 1, o);
  fwrite("data", 1, 4, o); fwrite(&dl, 4, 1, o); fwrite(pcm, 1, dl, o);
  fclose(o);
  return 0;
}
