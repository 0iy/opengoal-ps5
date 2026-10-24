import os
p = os.path.expanduser('~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c')
s = open(p, encoding='utf-8').read()
def rep(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new, 1)
rep('   struct pipe_resource *descriptor_cache[3][PS5_MULTIDRAW_BATCH_CAPACITY];', '   struct pipe_resource *descriptor_cache[3][2048];')
rep('          context->descriptor_cache_count[stage] == PS5_MULTIDRAW_BATCH_CAPACITY)', '          context->descriptor_cache_count[stage] == 2048)')
open(p, 'w', encoding='utf-8').write(s)
print('ok')
