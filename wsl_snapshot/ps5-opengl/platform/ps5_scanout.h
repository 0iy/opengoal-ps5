// PS5 OpenGL - OpenGL implementation for PlayStation 5.
// Copyright (C) 2026 BlackBearReloaded
// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef PS5_SCANOUT_H
#define PS5_SCANOUT_H

/* One build-time native window mode, shared by EGL, Gallium and presentation.
 * No output-mode request is implied by choosing a render-buffer resolution. */
#ifndef PS5_SCANOUT_HEIGHT
#ifdef AGC_4K
#define PS5_SCANOUT_HEIGHT 2160
#else
#define PS5_SCANOUT_HEIGHT 1080
#endif
#endif

#if PS5_SCANOUT_HEIGHT == 1080
#define PS5_SCANOUT_WIDTH 1920u
#define PS5_SCANOUT_BYTES 0xa00000u
#elif PS5_SCANOUT_HEIGHT == 1440
#define PS5_SCANOUT_WIDTH 2560u
#define PS5_SCANOUT_BYTES 0x1000000u
#elif PS5_SCANOUT_HEIGHT == 2160
#define PS5_SCANOUT_WIDTH 3840u
#define PS5_SCANOUT_BYTES 0x2000000u
#else
#error Unsupported PS5 scanout resolution
#endif

#if defined(AGC_4K) && PS5_SCANOUT_HEIGHT != 2160
#error AGC_4K conflicts with the selected PS5 scanout resolution
#endif

/* Bounded GPU work retained across asynchronous flushes. */
#define PS5_INFLIGHT_BATCH_CAPACITY 8u

#define PS5_SCANOUT_ALIGNMENT 0x200000u
#define PS5_SCANOUT_POOL_BYTES (2u * PS5_SCANOUT_BYTES)
#ifndef PS5_SCANOUT_FPS
#define PS5_SCANOUT_FPS 60
#endif
#if PS5_SCANOUT_FPS != 60 && PS5_SCANOUT_FPS != 120
#error Unsupported PS5 presentation rate
#endif
#define PS5_SCANOUT_TILED_BYTES \
   (((PS5_SCANOUT_WIDTH + 127u) / 128u) * \
    ((PS5_SCANOUT_HEIGHT + 127u) / 128u) * 0x10000u)
#if PS5_SCANOUT_BYTES < PS5_SCANOUT_TILED_BYTES || \
    PS5_SCANOUT_BYTES % PS5_SCANOUT_ALIGNMENT != 0
#error Invalid tiled display buffer size or alignment
#endif

/* Runtime display modes: one SDK presents 1080p, 1440p or 2160p at 60 or
 * 120 Hz, chosen with eglSetDisplayModePS5/eglSetDisplayRefreshPS5 while EGL
 * is terminated. The build profile only sizes capacity: display slots and
 * arena offsets stay at the 2160p size in every mode, and the high-refresh
 * output path is compiled in and used when requested. */
#ifdef PS5_DYNAMIC_SCANOUT
#if PS5_SCANOUT_HEIGHT != 2160 || PS5_SCANOUT_FPS != 120
#error Runtime display modes require the 2160p120 capacity profile
#endif
enum { PS5_SCANOUT_DEFAULT_WIDTH = 1920, PS5_SCANOUT_DEFAULT_HEIGHT = 1080,
       PS5_SCANOUT_DEFAULT_FPS = 60 };
/* Requested mode, and the refresh rate the output actually accepted. */
extern unsigned ps5_scanout_width, ps5_scanout_height;
extern unsigned ps5_scanout_fps, ps5_scanout_active_fps;
#undef PS5_SCANOUT_WIDTH
#undef PS5_SCANOUT_HEIGHT
#define PS5_SCANOUT_WIDTH ps5_scanout_width
#define PS5_SCANOUT_HEIGHT ps5_scanout_height
#define PS5_SCANOUT_HFR_REQUESTED (ps5_scanout_fps > 60u)
#else
#define PS5_SCANOUT_HFR_REQUESTED (PS5_SCANOUT_FPS > 60)
#endif

#endif
