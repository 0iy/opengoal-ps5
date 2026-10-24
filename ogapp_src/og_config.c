// Larger application heap than the 128 MiB default (the engine stages level data in malloc memory).
#include <stddef.h>
const size_t ps5_opengl_heap_size = 1024ull * 1024ull * 1024ull;
