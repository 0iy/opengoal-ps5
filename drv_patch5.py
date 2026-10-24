import os
p = os.path.expanduser('~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c')
s = open(p, encoding='utf-8').read()
old = '         templ.width0 = MAX2(PS5_DIRECT_ALIGNMENT, live_bytes);'
new = '         templ.width0 = (live_bytes + PS5_DIRECT_ALIGNMENT - 1u) / PS5_DIRECT_ALIGNMENT * PS5_DIRECT_ALIGNMENT;'
assert s.count(old) == 1
s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(s)
print('ok')
