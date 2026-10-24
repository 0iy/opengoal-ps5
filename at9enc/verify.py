#!/usr/bin/env python3
"""verify.py source.wav decoded.wav [delay]  -> lag, correlation, SNR (per channel)."""
import sys, numpy as np
sys.path.insert(0, __import__('os').path.dirname(__file__))
from at9enc import read_wav
src, _ = read_wav(sys.argv[1]); dec, _ = read_wav(sys.argv[2])
delay = int(sys.argv[3]) if len(sys.argv) > 3 else 256
# search lag around nominal delay
a = src[:, 0]; best = None
for lag in range(delay - 300, delay + 300):
    if lag < 0: continue
    b = dec[lag:lag + len(a), 0]
    c = np.dot(a[:len(b)], b)
    if best is None or c > best[0]: best = (c, lag)
lag = best[1]
print('decoded samples %d (%.3f s), source %d (%.3f s), best lag %d' %
      (len(dec), len(dec) / 48000, len(src), len(src) / 48000, lag))
for c in range(src.shape[1]):
    s = src[:, c]; d = dec[lag:lag + len(s), c]; s = s[:len(d)]
    corr = np.corrcoef(s, d)[0, 1]
    snr = 10 * np.log10(np.sum(s ** 2) / np.sum((s - d) ** 2))
    print('ch%d: corr %.5f  SNR %.2f dB  rms src %.4f dec %.4f' % (c, corr, snr, s.std(), d.std()))
