import os
p = os.path.expanduser('~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c')
s = open(p, encoding='utf-8').read()
old = '''      if (!r || r->reference.count != 1 || r->target != PIPE_BUFFER ||
          r->width0 != PS5_DIRECT_ALIGNMENT ||
          context->descriptor_cache_count[stage] == PS5_MULTIDRAW_BATCH_CAPACITY)'''
new = '''      if (!r || r->reference.count != 1 || r->target != PIPE_BUFFER ||
          context->descriptor_cache_count[stage] == PS5_MULTIDRAW_BATCH_CAPACITY)'''
assert old in s
s = s.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(s)
print("ok")
