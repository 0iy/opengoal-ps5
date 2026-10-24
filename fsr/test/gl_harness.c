// Host test: runs fsr.frag (EASU, then RCAS) on a raw RGBA8 image through EGL surfaceless + Mesa llvmpipe.
// build: gcc gl_harness.c -o gl_harness -lEGL -lGL -lm
// run:   ./gl_harness in.raw inW inH outW outH sharpStops easu.raw rcas.raw    (cwd = fsr/test)
#define GL_GLEXT_PROTOTYPES 1
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GL/gl.h>
#include <GL/glext.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char* slurp(const char* p, size_t* n) {
  FILE* f = fopen(p, "rb");
  if (!f) { perror(p); exit(1); }
  fseek(f, 0, SEEK_END);
  long l = ftell(f);
  fseek(f, 0, SEEK_SET);
  char* b = malloc(l + 2);
  fread(b, 1, l, f);
  fclose(f);
  b[l] = 0;
  if (n) *n = l;
  return b;
}

static GLuint prog(const char* vs, const char* fs, const char* def) {
  // splice the define after the #version line, like the engine patch does
  const char* nl = strchr(fs, '\n');
  size_t head = nl - fs + 1;
  char* full = malloc(strlen(fs) + strlen(def) + 8);
  memcpy(full, fs, head);
  full[head] = 0;
  strcat(full, def);
  strcat(full, nl + 1);
  GLuint v = glCreateShader(GL_VERTEX_SHADER), f = glCreateShader(GL_FRAGMENT_SHADER), p = glCreateProgram();
  glShaderSource(v, 1, &vs, 0);
  glCompileShader(v);
  const char* fp = full;
  glShaderSource(f, 1, &fp, 0);
  glCompileShader(f);
  char log[4096];
  GLint ok;
  glGetShaderiv(v, GL_COMPILE_STATUS, &ok);
  if (!ok) { glGetShaderInfoLog(v, 4096, 0, log); printf("vs: %s\n", log); exit(2); }
  glGetShaderiv(f, GL_COMPILE_STATUS, &ok);
  if (!ok) { glGetShaderInfoLog(f, 4096, 0, log); printf("fs: %s\n", log); exit(2); }
  glAttachShader(p, v);
  glAttachShader(p, f);
  glLinkProgram(p);
  glGetProgramiv(p, GL_LINK_STATUS, &ok);
  if (!ok) { glGetProgramInfoLog(p, 4096, 0, log); printf("link: %s\n", log); exit(2); }
  return p;
}

static GLuint mktex(int w, int h, const void* px) {
  GLuint t;
  glGenTextures(1, &t);
  glBindTexture(GL_TEXTURE_2D, t);
  glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
  glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
  return t;
}

static void dump(const char* path, int w, int h) {
  unsigned char* buf = malloc((size_t)w * h * 4);
  glReadPixels(0, 0, w, h, GL_RGBA, GL_UNSIGNED_BYTE, buf);
  FILE* f = fopen(path, "wb");
  fwrite(buf, 1, (size_t)w * h * 4, f);
  fclose(f);
  free(buf);
}

int main(int argc, char** argv) {
  if (argc < 9) return 1;
  int iw = atoi(argv[2]), ih = atoi(argv[3]), ow = atoi(argv[4]), oh = atoi(argv[5]);
  float stops = atof(argv[6]);
  PFNEGLGETPLATFORMDISPLAYEXTPROC gpd = (void*)eglGetProcAddress("eglGetPlatformDisplayEXT");
  EGLDisplay d = gpd(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, 0);
  EGLint maj, min;
  if (!eglInitialize(d, &maj, &min)) { puts("egl init fail"); return 3; }
  eglBindAPI(EGL_OPENGL_API);
  EGLint ca[] = {EGL_CONTEXT_MAJOR_VERSION, 4, EGL_CONTEXT_MINOR_VERSION, 1,
                 EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
  EGLContext c = eglCreateContext(d, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, ca);
  if (!c || !eglMakeCurrent(d, EGL_NO_SURFACE, EGL_NO_SURFACE, c)) { puts("ctx fail"); return 3; }
  printf("GL %s | %s\n", glGetString(GL_VERSION), glGetString(GL_RENDERER));
  char* vs = slurp("../fsr.vert", 0);
  char* fs = slurp("../fsr.frag", 0);
  GLuint pe = prog(vs, fs, "#define FSR_EASU 1\n"), pr = prog(vs, fs, "#define FSR_RCAS 1\n");
  size_t n;
  void* in = slurp(argv[1], &n);
  GLuint tin = mktex(iw, ih, in), tmid = mktex(ow, oh, 0), tout = mktex(ow, oh, 0);
  GLuint fb[2];
  glGenFramebuffers(2, fb);
  glBindFramebuffer(GL_FRAMEBUFFER, fb[0]);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tmid, 0);
  glBindFramebuffer(GL_FRAMEBUFFER, fb[1]);
  glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tout, 0);
  float quad[8] = {-1, -1, -1, 1, 1, -1, 1, 1};
  GLuint vao, vbo;
  glGenVertexArrays(1, &vao);
  glBindVertexArray(vao);
  glGenBuffers(1, &vbo);
  glBindBuffer(GL_ARRAY_BUFFER, vbo);
  glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
  glEnableVertexAttribArray(0);
  glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 8, 0);
  glDisable(GL_DEPTH_TEST);
  glDisable(GL_BLEND);
  glActiveTexture(GL_TEXTURE0);

  glBindFramebuffer(GL_FRAMEBUFFER, fb[0]);
  glViewport(0, 0, ow, oh);
  glUseProgram(pe);
  glBindTexture(GL_TEXTURE_2D, tin);
  glUniform1i(glGetUniformLocation(pe, "src"), 0);
  glUniform4f(glGetUniformLocation(pe, "dims"), iw, ih, ow, oh);
  glUniform4f(glGetUniformLocation(pe, "misc"), 0, 0, 0, 0);
  glUniform4f(glGetUniformLocation(pe, "color_mult"), 1, 1, 1, 1);
  glUniform4f(glGetUniformLocation(pe, "color_add"), 0, 0, 0, 0);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  glReadBuffer(GL_COLOR_ATTACHMENT0);
  dump(argv[7], ow, oh);

  glBindFramebuffer(GL_FRAMEBUFFER, fb[1]);
  glViewport(0, 0, ow, oh);
  glUseProgram(pr);
  glBindTexture(GL_TEXTURE_2D, tmid);
  glUniform1i(glGetUniformLocation(pr, "src"), 0);
  glUniform4f(glGetUniformLocation(pr, "dims"), ow, oh, ow, oh);
  glUniform4f(glGetUniformLocation(pr, "misc"), 0, 0, exp2f(-stops), 0);
  glUniform4f(glGetUniformLocation(pr, "color_mult"), 1, 1, 1, 1);
  glUniform4f(glGetUniformLocation(pr, "color_add"), 0, 0, 0, 0);
  glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
  dump(argv[8], ow, oh);
  printf("glerror 0x%x\n", glGetError());
  return 0;
}
