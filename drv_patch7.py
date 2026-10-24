import os
p = os.path.expanduser('~/gl/src/ps5-opengl/src/platform/ps5_agc_native_runtime.c')
s = open(p, encoding='utf-8').read()
old = '    unsigned cpu = 10u + worker * 2u;'
new = '''    const char *eb = getenv("PS5_PREP_BASE"), *es = getenv("PS5_PREP_STEP");
    unsigned cpu = (eb ? (unsigned)atoi(eb) : 10u) + worker * (es ? (unsigned)atoi(es) : 2u);'''
assert old in s
s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
