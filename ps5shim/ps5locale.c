// C-locale-only implementations of the BSD xlocale entry points libc++ links against.
// The PS5 system libc does not export them; OpenGOAL only ever needs the "C" locale.

#include <ctype.h>
#include <locale.h>
#include <runetype.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <wchar.h>
#include <wctype.h>

static _RuneLocale g_runes;
static int g_runes_ready;

static void build_runes(void) {
  if (g_runes_ready) return;
  for (int c = 0; c < _CACHED_RUNES; ++c) {
    unsigned long f = 0;
    if (c < 128) {
      if (isalpha(c)) f |= _CTYPE_A;
      if (iscntrl(c)) f |= _CTYPE_C;
      if (isdigit(c)) f |= _CTYPE_D | _CTYPE_N;
      if (isgraph(c)) f |= _CTYPE_G;
      if (islower(c)) f |= _CTYPE_L;
      if (ispunct(c)) f |= _CTYPE_P;
      if (isspace(c)) f |= _CTYPE_S;
      if (isupper(c)) f |= _CTYPE_U;
      if (isxdigit(c)) f |= _CTYPE_X;
      if (c == ' ' || c == '\t') f |= _CTYPE_B;
      if (isprint(c)) f |= _CTYPE_R;
      f |= _CTYPE_SW1;
    }
    g_runes.__runetype[c] = f;
    g_runes.__maplower[c] = (c < 128) ? tolower(c) : c;
    g_runes.__mapupper[c] = (c < 128) ? toupper(c) : c;
  }
  g_runes_ready = 1;
}

_RuneLocale* __runes_for_locale(locale_t l, int* limit) {
  (void)l;
  build_runes();
  if (limit) *limit = _CACHED_RUNES;
  return &g_runes;
}
unsigned long ___runetype_l(__ct_rune_t c, locale_t l) {
  (void)l;
  build_runes();
  return (c < 0 || c >= _CACHED_RUNES) ? 0 : g_runes.__runetype[c];
}
__ct_rune_t ___tolower_l(__ct_rune_t c, locale_t l) {
  (void)l;
  return (c >= 0 && c < 128) ? tolower(c) : c;
}
__ct_rune_t ___toupper_l(__ct_rune_t c, locale_t l) {
  (void)l;
  return (c >= 0 && c < 128) ? toupper(c) : c;
}
int ___mb_cur_max_l(locale_t l) {
  (void)l;
  return 1;
}

const _RuneLocale* __getCurrentRuneLocale(void) {
  build_runes();
  return &g_runes;
}
unsigned long ___runetype(__ct_rune_t c) { return ___runetype_l(c, 0); }

// The system libc lacks the restartable "n" conversions; the "C" locale is byte == code point.
size_t mbsnrtowcs(wchar_t* dst, const char** src, size_t nms, size_t len, mbstate_t* ps) {
  (void)ps;
  const unsigned char* s = (const unsigned char*)*src;
  size_t n = 0;
  while (n < len || !dst) {
    if (nms == 0) break;
    if (dst) dst[n] = (wchar_t)*s;
    if (*s == 0) {
      if (dst) *src = 0;
      return n;
    }
    ++s;
    --nms;
    ++n;
  }
  if (dst) *src = (const char*)s;
  return n;
}
size_t wcsnrtombs(char* dst, const wchar_t** src, size_t nwc, size_t len, mbstate_t* ps) {
  (void)ps;
  const wchar_t* s = *src;
  size_t n = 0;
  while (n < len || !dst) {
    if (nwc == 0) break;
    wchar_t c = *s;
    if (c > 0xff) return (size_t)-1;
    if (dst) dst[n] = (char)c;
    if (c == 0) {
      if (dst) *src = 0;
      return n;
    }
    ++s;
    --nwc;
    ++n;
  }
  if (dst) *src = s;
  return n;
}

static int g_locale_token;
locale_t newlocale(int mask, const char* name, locale_t base) {
  (void)mask;
  (void)name;
  (void)base;
  return (locale_t)&g_locale_token;
}
int freelocale(locale_t l) {
  (void)l;
  return 0;
}

int snprintf_l(char* s, size_t n, locale_t l, const char* fmt, ...) {
  (void)l;
  va_list ap;
  va_start(ap, fmt);
  int r = vsnprintf(s, n, fmt, ap);
  va_end(ap);
  return r;
}
int asprintf_l(char** out, locale_t l, const char* fmt, ...) {
  (void)l;
  va_list ap;
  va_start(ap, fmt);
  int r = vasprintf(out, fmt, ap);
  va_end(ap);
  return r;
}
int sscanf_l(const char* s, locale_t l, const char* fmt, ...) {
  (void)l;
  va_list ap;
  va_start(ap, fmt);
  int r = vsscanf(s, fmt, ap);
  va_end(ap);
  return r;
}

double strtod_l(const char* s, char** e, locale_t l) { (void)l; return strtod(s, e); }
float strtof_l(const char* s, char** e, locale_t l) { (void)l; return strtof(s, e); }
long double strtold_l(const char* s, char** e, locale_t l) { (void)l; return strtold(s, e); }
long long strtoll_l(const char* s, char** e, int b, locale_t l) { (void)l; return strtoll(s, e, b); }
unsigned long long strtoull_l(const char* s, char** e, int b, locale_t l) { (void)l; return strtoull(s, e, b); }
int strcoll_l(const char* a, const char* b, locale_t l) { (void)l; return strcmp(a, b); }
size_t strxfrm_l(char* d, const char* s, size_t n, locale_t l) {
  (void)l;
  size_t len = strlen(s);
  if (n) {
    size_t c = len < n - 1 ? len : n - 1;
    memcpy(d, s, c);
    d[c] = 0;
  }
  return len;
}
size_t strftime_l(char* s, size_t max, const char* fmt, const struct tm* tm, locale_t l) {
  (void)l;
  return strftime(s, max, fmt, tm);
}
int wcscoll_l(const wchar_t* a, const wchar_t* b, locale_t l) { (void)l; return wcscmp(a, b); }
size_t wcsxfrm_l(wchar_t* d, const wchar_t* s, size_t n, locale_t l) {
  (void)l;
  size_t len = wcslen(s);
  if (n) {
    size_t c = len < n - 1 ? len : n - 1;
    wmemcpy(d, s, c);
    d[c] = 0;
  }
  return len;
}

size_t mbrlen_l(const char* s, size_t n, mbstate_t* ps, locale_t l) { (void)l; return mbrlen(s, n, ps); }
size_t mbrtowc_l(wchar_t* pwc, const char* s, size_t n, mbstate_t* ps, locale_t l) { (void)l; return mbrtowc(pwc, s, n, ps); }
int mbtowc_l(wchar_t* pwc, const char* s, size_t n, locale_t l) { (void)l; return mbtowc(pwc, s, n); }
size_t mbsrtowcs_l(wchar_t* d, const char** s, size_t len, mbstate_t* ps, locale_t l) { (void)l; return mbsrtowcs(d, s, len, ps); }
size_t mbsnrtowcs_l(wchar_t* d, const char** s, size_t nms, size_t len, mbstate_t* ps, locale_t l) { (void)l; return mbsnrtowcs(d, s, nms, len, ps); }
size_t wcrtomb_l(char* s, wchar_t wc, mbstate_t* ps, locale_t l) { (void)l; return wcrtomb(s, wc, ps); }
size_t wcsnrtombs_l(char* d, const wchar_t** s, size_t nwc, size_t len, mbstate_t* ps, locale_t l) { (void)l; return wcsnrtombs(d, s, nwc, len, ps); }
wint_t btowc_l(int c, locale_t l) { (void)l; return btowc(c); }
int wctob_l(wint_t c, locale_t l) { (void)l; return wctob(c); }
int iswctype_l(wint_t wc, wctype_t t, locale_t l) { (void)l; return iswctype(wc, t); }
struct lconv* localeconv_l(locale_t l) { (void)l; return localeconv(); }

// message catalogs (libc++ <locale> messages facet): none available
typedef void* nl_catd;
nl_catd catopen(const char* name, int oflag) { (void)name; (void)oflag; return (nl_catd)-1; }
char* catgets(nl_catd cat, int set, int num, const char* def) { (void)cat; (void)set; (void)num; return (char*)def; }
int catclose(nl_catd cat) { (void)cat; return 0; }
