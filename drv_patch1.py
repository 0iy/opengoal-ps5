import os, re
p = os.path.expanduser('~/gl/src/ps5-opengl/src/gallium/ps5/ps5_screen.c')
s = open(p, encoding='utf-8').read()

# 1. timing helpers before ps5_try_deferred_draw
helper = r'''
static uint64_t ps5_my_t[8], ps5_my_n[8];
static uint64_t ps5_my_last_print;
static inline uint64_t ps5_my_tsc(void)
{
   uint32_t lo, hi;
   __asm__ volatile("rdtsc" : "=a"(lo), "=d"(hi));
   return ((uint64_t)hi << 32) | lo;
}
#define PS5_MY_BEGIN(i) uint64_t ps5_my_s##i = ps5_my_tsc()
#define PS5_MY_END(i) do { ps5_my_t[i] += ps5_my_tsc() - ps5_my_s##i; ++ps5_my_n[i]; } while (0)
static void ps5_my_report(void)
{
   uint64_t now = ps5_my_tsc();
   if (now - ps5_my_last_print < 30000000000ull / 10)
      return;
   if (ps5_my_last_print)
      printf("[ps5-driver-my] total=%llu deferred=%llu/%llu copy=%llu/%llu locked=%llu/%llu immediate=%llu/%llu flush=%llu/%llu elig=%llu/%llu (cycles/count)\n",
             (unsigned long long)(now - ps5_my_last_print), (unsigned long long)ps5_my_t[0], (unsigned long long)ps5_my_n[0],
             (unsigned long long)ps5_my_t[1], (unsigned long long)ps5_my_n[1], (unsigned long long)ps5_my_t[2],
             (unsigned long long)ps5_my_n[2], (unsigned long long)ps5_my_t[3], (unsigned long long)ps5_my_n[3],
             (unsigned long long)ps5_my_t[4], (unsigned long long)ps5_my_n[4], (unsigned long long)ps5_my_t[5],
             (unsigned long long)ps5_my_n[5]);
   ps5_my_last_print = now;
   memset(ps5_my_t, 0, sizeof ps5_my_t);
   memset(ps5_my_n, 0, sizeof ps5_my_n);
}

'''
anchor = 'static bool\nps5_try_deferred_draw(struct pipe_context *base,'
assert anchor in s
s = s.replace(anchor, helper + anchor, 1)

# 2. instrument deferred function body
a = s.index(anchor)
body_start = s.index('{', a)
s = s[:body_start + 1] + '\n   PS5_MY_BEGIN(0);' + s[body_start + 1:]
# copy descriptors
s = s.replace('   if (!ps5_batch_copy_descriptors(base, saved, storage)) {',
              '   PS5_MY_BEGIN(1);\n   bool ps5_my_copy_ok = ps5_batch_copy_descriptors(base, saved, storage);\n   PS5_MY_END(1);\n   if (!ps5_my_copy_ok) {', 1)
s = s.replace('   ps5_draw_vbo_locked(base, info, drawid_offset, indirect, draws, num_draws,\n                       &ps5_deferred.flush_cache, &submitted);',
              '   PS5_MY_BEGIN(2);\n   ps5_draw_vbo_locked(base, info, drawid_offset, indirect, draws, num_draws,\n                       &ps5_deferred.flush_cache, &submitted);\n   PS5_MY_END(2);', 1)
s = s.replace('   if (context->last_draw_status || ps5_deferred.count == PS5_MULTIDRAW_BATCH_CAPACITY)\n      ps5_draw_batch_flush_locked();\nout:',
              '   if (context->last_draw_status || ps5_deferred.count == PS5_MULTIDRAW_BATCH_CAPACITY) {\n      PS5_MY_BEGIN(4);\n      ps5_draw_batch_flush_locked();\n      PS5_MY_END(4);\n   }\nout:', 1)
# end of function: before unlock return handled
s = s.replace('   simple_mtx_unlock(&ps5_deferred_mutex);\n   return handled;\n}\n#endif', '   simple_mtx_unlock(&ps5_deferred_mutex);\n   PS5_MY_END(0);\n   ps5_my_report();\n   return handled;\n}\n#endif', 1)
# eligibility timing
s = s.replace('   if (!ps5_agc_gate2_batch_begin || !ps5_agc_gate2_batch_end || num_draws != 1 ||',
              '   PS5_MY_BEGIN(5);\n   bool ps5_my_elig = ps5_multidraw_eligible(context, info, indirect, draws, num_draws);\n   PS5_MY_END(5);\n   if (!ps5_agc_gate2_batch_begin || !ps5_agc_gate2_batch_end || num_draws != 1 ||', 1)
s = s.replace('       !ps5_multidraw_eligible(context, info, indirect, draws, num_draws)) {\n      ps5_draw_batch_flush_locked();\n      goto out;',
              '       !ps5_my_elig) {\n      ps5_draw_batch_flush_locked();\n      goto out;', 1)

# 3. immediate path timing (last ps5_draw_vbo_locked call in ps5_draw_vbo)
idx = s.rindex('   ps5_draw_vbo_locked(base, info, drawid_offset, indirect, draws, num_draws,')
end = s.index(';', idx) + 1
seg = s[idx:end]
s = s[:idx] + '   PS5_MY_BEGIN(3);\n' + seg + '\n   PS5_MY_END(3);' + s[end:]
open(p, 'w', encoding='utf-8').write(s)
print('patched')
