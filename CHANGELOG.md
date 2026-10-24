# Changelog

## 0.1.0 (unreleased, first public version)

Based on OpenGOAL (jak-project `553a713`, v0.3.x). Tested on firmware 13.60 only.

### Added
- Native Jak 1/2/3 port: PS5 shim (SDL replacement over EGL), controller launcher (English/German), keep-awake, quit-to-launcher flow
- On-console ISO import with web page on port 8080, QR code, pre-checks and queue ([`docs/ONBOARDING_WEB.md`](docs/ONBOARDING_WEB.md))
- Installer for Windows/Linux/macOS (`release_template/install.py`)
- Draw merging (`glfix.cpp`) and asynchronous multi-draw submit; patched Mesa-to-AGC driver (`drv_patch1` to `drv_patch60`)
- Experimental: FSR 1.0 upscaling with dynamic resolution, lazy mipmaps ([`docs/FSR.md`](docs/FSR.md))
- Upstream sync tooling (`sync_upstream.py`, `ports/`) and offline QA pipeline (`qa_pipeline.py`)
- Frame tracer and analysis tools (`trace2json.py`, `perfround.py`)

### Performance (1080p, from [`docs/PERF_JOURNAL.md`](docs/PERF_JOURNAL.md))
- Jak 3 gameplay: 39-43 fps -> 59-60 fps (async multi-draw + merge)
- Jak 2 city: 21-22 fps -> about 50-58 fps (async multi-draw, merge, GPU mip fix)
- Jak 3 spawn scene 27-30 -> about 40 fps in the earlier work of 2026-10-19/20

### Fixed
- Glow sprites visible through solid objects (depth blit format, `glTexImage2D` fix)
- Mip generation falling back to the CPU path (missing `PS5_GPU_BLIT_MIN_PIXELS` build flag)
- Earlier rendering issues: merc, logo, crates, Jak, TM purple (shader), UI

### Known issues
- Visual glitches in places; occasional frame-time spikes; Jak 1 import re-test pending; XMB tile name still shows "OpenGOAL"

### History
- 2026-10-22: first commits (development state, performance fixes, handoff docs)
