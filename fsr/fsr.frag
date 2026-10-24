#version 410 core
// FSR 1.0 style spatial upscaler: EASU (edge adaptive upscale) and RCAS (robust contrast adaptive sharpen).
// Written from the public algorithm description of AMD FidelityFX FSR 1.0 (MIT licensed). Two passes from one source:
// the host prepends "#define FSR_EASU 1" or "#define FSR_RCAS 1" after the #version line.
// Plain fragment shader: sampler2D + texelFetch (LOD 0), no gather, no compute, no image load/store.
#if !defined(FSR_EASU) && !defined(FSR_RCAS)
#define FSR_EASU 1
#endif

out vec4 color;
uniform sampler2D src;
// Only vec4 uniforms (glUniform4f is the call the engine itself relies on).
uniform vec4 dims;         // xy = source size in texels, zw = destination size in pixels (from the CPU, not textureSize)
uniform vec4 misc;         // xy = pixel position of the destination rectangle in the bound framebuffer, z = RCAS exp2(-stops)
uniform vec4 color_mult;   // same final brightness/contrast as the engine's post_processing shader
uniform vec4 color_add;

vec3 fetch(ivec2 p, ivec2 hi) { return texelFetch(src, clamp(p, ivec2(0), hi), 0).rgb; }
float luma(vec3 c) { return c.b * 0.5 + (c.r * 0.5 + c.g); }  // FSR "luma * 2" approximation

#ifdef FSR_EASU
// Accumulates gradient direction and edge length for one of the four bilinear quadrants. a=top b=left c=center d=right e=bottom.
void easu_set(inout vec2 dir, inout float len, vec2 pp, bool s, bool t, bool u, bool v,
              float la, float lb, float lc, float ld, float le) {
  float w = 0.0;
  if (s) w = (1.0 - pp.x) * (1.0 - pp.y);
  if (t) w = pp.x * (1.0 - pp.y);
  if (u) w = (1.0 - pp.x) * pp.y;
  if (v) w = pp.x * pp.y;
  float dc = ld - lc, cb = lc - lb;
  float lenX = 1.0 / max(max(abs(dc), abs(cb)), 1.0 / 32768.0);
  float dirX = ld - lb;
  dir.x += dirX * w;
  lenX = clamp(abs(dirX) * lenX, 0.0, 1.0);
  len += lenX * lenX * w;
  float ec = le - lc, ca = lc - la;
  float lenY = 1.0 / max(max(abs(ec), abs(ca)), 1.0 / 32768.0);
  float dirY = le - la;
  dir.y += dirY * w;
  lenY = clamp(abs(dirY) * lenY, 0.0, 1.0);
  len += lenY * lenY * w;
}

// Windowed, direction-stretched approximation of Lanczos2 without sin/rcp.
void easu_tap(inout vec3 aC, inout float aW, vec2 off, vec2 dir, vec2 len, float lob, float clp, vec3 c) {
  vec2 v = vec2(off.x * dir.x + off.y * dir.y, off.x * -dir.y + off.y * dir.x);
  v *= len;
  float d2 = min(v.x * v.x + v.y * v.y, clp);
  float wB = 2.0 / 5.0 * d2 - 1.0;
  float wA = lob * d2 - 1.0;
  wB *= wB;
  wA *= wA;
  wB = 25.0 / 16.0 * wB - (25.0 / 16.0 - 1.0);
  float w = wB * wA;
  aC += c * w;
  aW += w;
}

vec3 easu(vec2 ip) {
  ivec2 hi = ivec2(dims.xy) - 1;
  vec2 scale = dims.xy / dims.zw;
  vec2 pp = ip * scale + (0.5 * scale - 0.5);  // position in source texel space, texel centers at integers
  vec2 fp = floor(pp);
  pp -= fp;
  ivec2 f0 = ivec2(fp);
  //    b c
  //  e f g h
  //  i j k l
  //    n o
  vec3 bC = fetch(f0 + ivec2( 0,-1), hi), cC = fetch(f0 + ivec2( 1,-1), hi);
  vec3 eC = fetch(f0 + ivec2(-1, 0), hi), fC = fetch(f0 + ivec2( 0, 0), hi);
  vec3 gC = fetch(f0 + ivec2( 1, 0), hi), hC = fetch(f0 + ivec2( 2, 0), hi);
  vec3 iC = fetch(f0 + ivec2(-1, 1), hi), jC = fetch(f0 + ivec2( 0, 1), hi);
  vec3 kC = fetch(f0 + ivec2( 1, 1), hi), lC = fetch(f0 + ivec2( 2, 1), hi);
  vec3 nC = fetch(f0 + ivec2( 0, 2), hi), oC = fetch(f0 + ivec2( 1, 2), hi);
  float bL = luma(bC), cL = luma(cC), eL = luma(eC), fL = luma(fC), gL = luma(gC), hL = luma(hC);
  float iL = luma(iC), jL = luma(jC), kL = luma(kC), lL = luma(lC), nL = luma(nC), oL = luma(oC);

  vec2 dir = vec2(0.0);
  float len = 0.0;
  easu_set(dir, len, pp, true,  false, false, false, bL, eL, fL, gL, jL);
  easu_set(dir, len, pp, false, true,  false, false, cL, fL, gL, hL, kL);
  easu_set(dir, len, pp, false, false, true,  false, fL, iL, jL, kL, nL);
  easu_set(dir, len, pp, false, false, false, true,  gL, jL, kL, lL, oL);

  vec2 dir2 = dir * dir;
  float dirR = dir2.x + dir2.y;
  bool zro = dirR < 1.0 / 32768.0;
  dirR = zro ? 1.0 : inversesqrt(dirR);
  dir.x = zro ? 1.0 : dir.x;
  dir *= dirR;
  len = len * 0.5;
  len *= len;
  float stretch = (dir.x * dir.x + dir.y * dir.y) / max(abs(dir.x), abs(dir.y));
  vec2 len2 = vec2(1.0 + (stretch - 1.0) * len, 1.0 - 0.5 * len);
  float lob = 0.5 + ((1.0 / 4.0 - 0.04) - 0.5) * len;
  float clp = 1.0 / lob;

  vec3 aC = vec3(0.0);
  float aW = 0.0;
  easu_tap(aC, aW, vec2( 0.0,-1.0) - pp, dir, len2, lob, clp, bC);
  easu_tap(aC, aW, vec2( 1.0,-1.0) - pp, dir, len2, lob, clp, cC);
  easu_tap(aC, aW, vec2(-1.0, 0.0) - pp, dir, len2, lob, clp, eC);
  easu_tap(aC, aW, vec2( 0.0, 0.0) - pp, dir, len2, lob, clp, fC);
  easu_tap(aC, aW, vec2( 1.0, 0.0) - pp, dir, len2, lob, clp, gC);
  easu_tap(aC, aW, vec2( 2.0, 0.0) - pp, dir, len2, lob, clp, hC);
  easu_tap(aC, aW, vec2(-1.0, 1.0) - pp, dir, len2, lob, clp, iC);
  easu_tap(aC, aW, vec2( 0.0, 1.0) - pp, dir, len2, lob, clp, jC);
  easu_tap(aC, aW, vec2( 1.0, 1.0) - pp, dir, len2, lob, clp, kC);
  easu_tap(aC, aW, vec2( 2.0, 1.0) - pp, dir, len2, lob, clp, lC);
  easu_tap(aC, aW, vec2( 0.0, 2.0) - pp, dir, len2, lob, clp, nC);
  easu_tap(aC, aW, vec2( 1.0, 2.0) - pp, dir, len2, lob, clp, oC);
  // normalize and de-ring against the 4 center texels
  vec3 mn = min(min(fC, gC), min(jC, kC));
  vec3 mx = max(max(fC, gC), max(jC, kC));
  return min(mx, max(mn, aC / aW));
}
#endif

#ifdef FSR_RCAS
const float RCAS_LIMIT = 0.25 - 1.0 / 16.0;
vec3 rcas(ivec2 ip) {
  ivec2 hi = ivec2(dims.xy) - 1;
  //  b
  // d e f
  //  h
  vec3 b = fetch(ip + ivec2(0, -1), hi), d = fetch(ip + ivec2(-1, 0), hi);
  vec3 e = fetch(ip, hi);
  vec3 f = fetch(ip + ivec2(1, 0), hi), h = fetch(ip + ivec2(0, 1), hi);
  float bL = luma(b), dL = luma(d), eL = luma(e), fL = luma(f), hL = luma(h);
  // noise detection: attenuate sharpening on noisy pixels
  float nz = 0.25 * (bL + dL + fL + hL) - eL;
  float rng = max(max(max(bL, dL), max(eL, fL)), hL) - min(min(min(bL, dL), min(eL, fL)), hL);
  nz = clamp(abs(nz) / max(rng, 1.0 / 65536.0), 0.0, 1.0);
  nz = -0.5 * nz + 1.0;
  vec3 mn4 = min(min(b, d), min(f, h));
  vec3 mx4 = max(max(b, d), max(f, h));
  // limiters: how far the lobe may go before the ring clips below 0 or above 1
  vec3 hitMin = mn4 / (4.0 * max(mx4, vec3(1.0 / 65536.0)));
  vec3 hitMax = (1.0 - mx4) / min(4.0 * mn4 - 4.0, vec3(-1.0 / 65536.0));
  vec3 lobeRGB = max(-hitMin, hitMax);
  float lobe = max(-RCAS_LIMIT, min(max(lobeRGB.r, max(lobeRGB.g, lobeRGB.b)), 0.0)) * misc.z;
  lobe *= nz;
  float rcpL = 1.0 / (4.0 * lobe + 1.0);
  return (lobe * (b + d + h + f) + e) * rcpL;
}
#endif

void main() {
#ifdef FSR_EASU
  vec3 pix = easu(floor(gl_FragCoord.xy - misc.xy));
#else
  vec3 pix = rcas(ivec2(floor(gl_FragCoord.xy - misc.xy)));
#endif
  color = vec4(pix * color_mult.rgb * color_mult.a, 1.0) + color_add;
}
