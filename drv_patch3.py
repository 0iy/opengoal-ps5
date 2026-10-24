import os
p = os.path.expanduser('~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c')
s = open(p, encoding='utf-8').read()
def rep(old, new):
    global s
    assert s.count(old) == 1, old
    s = s.replace(old, new, 1)
# checkpoints
rep('   tessellation_active = context->tcs || context->tes;\n   if (!context->vs || !context->fs || !context->framebuffer_valid ||',
    '   ps5_ck[1] = ps5_my_tsc();\n   tessellation_active = context->tcs || context->tes;\n   if (!context->vs || !context->fs || !context->framebuffer_valid ||')
rep('   if (!ps5_encode_graphics_state(context, &graphics)) {\n      context->last_draw_status = -18;',
    '   ps5_ck[2] = ps5_my_tsc();\n   if (!ps5_encode_graphics_state(context, &graphics)) {\n      context->last_draw_status = -18;')
rep('   if (!tessellation_active && !ps5_prepare_constant(context, context->vs, 0, input_user_data,',
    '   ps5_ck[3] = ps5_my_tsc();\n   if (!tessellation_active && !ps5_prepare_constant(context, context->vs, 0, input_user_data,')
rep('   if (ps5_agc_gate2_set_packages(vertex_package,', '   ps5_ck[4] = ps5_my_tsc();\n   if (ps5_agc_gate2_set_packages(vertex_package,')
rep('   context->last_draw_status = ps5_agc_gate2_run();',
    '   ps5_ck[5] = ps5_my_tsc();\n   context->last_draw_status = ps5_agc_gate2_run();\n   ps5_ck[6] = ps5_my_tsc();\n   for (int i = 1; i < 7; ++i) ps5_sec[i - 1] += ps5_ck[i] - ps5_ck[i - 1];')
rep('   if (submitted)\n      *submitted = false;\n\n   if (!info || !draws || !num_draws) {',
    '   uint64_t ps5_ck[8] = {0};\n   ps5_ck[0] = ps5_my_tsc();\n   if (submitted)\n      *submitted = false;\n\n   if (!info || !draws || !num_draws) {')
# globals + helper move: ps5_my_tsc must precede draw_vbo_locked -> define near top
rep('#include "ps5_screen.h"', '#include "ps5_screen.h"\nstatic uint64_t ps5_sec[8];\nstatic inline uint64_t ps5_my_tsc(void)\n{\n   uint32_t lo, hi;\n   __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));\n   return ((uint64_t)hi << 32) | lo;\n}')
# remove the later duplicate ps5_my_tsc definition
dup = '''static inline uint64_t ps5_my_tsc(void)
{
   uint32_t lo, hi;
   __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
   return ((uint64_t)hi << 32) | lo;
}
#define PS5_MY_BEGIN'''
rep(dup, '#define PS5_MY_BEGIN')
# report secs
rep('   ps5_my_last_print = now;', '   printf("[ps5-driver-sec] bounds=%llu variant=%llu layout=%llu prepare=%llu agcset=%llu run=%llu\n", (unsigned long long)ps5_sec[0], (unsigned long long)ps5_sec[1], (unsigned long long)ps5_sec[2], (unsigned long long)ps5_sec[3], (unsigned long long)ps5_sec[4], (unsigned long long)ps5_sec[5]);\n   memset(ps5_sec, 0, sizeof ps5_sec);\n   ps5_my_last_print = now;')
open(p, 'w', encoding='utf-8').write(s)
print('ok')
