#!/bin/bash
# Build the driver the way the project always did: shader cache on (build id changes whenever the driver changes) and GPU mip blits for small levels (patch 33). Plain drv_cc.sh builds WITHOUT both and is slower.
export EXTRA='-DPS5_GPU_BLIT_MIN_PIXELS=1 -DPS5_SHADER_CACHE_BUILD_ID="opengoal-ps5-shadercache-1"'" ${PS5_EXTRA_DEFS:-}"
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/drv_cc.sh"