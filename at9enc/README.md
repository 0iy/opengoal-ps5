# at9enc - minimal ATRAC9 encoder

Pure Python + numpy. Writes the inverse of FFmpeg's `libavcodec/atrac9dec.c` bitstream.
The tables are parsed at runtime from `atrac9tab.h` (FFmpeg, LGPL-2.1).

The RIFF header (fmt/ATRAC9 extradata, fact, smpl) is copied from a template .at9. Only
these fields are changed: RIFF size, fact sample count, smpl loop end, and data size.
The codec config is taken from the template: 48 kHz stereo, 128-byte frames, 4 frames
per 512-byte superframe, 192 kbps.

Encoder features: one stereo (CPE) block per frame. Bandwidth is fixed (`--bands 16` = 26
quant units, about 18 kHz). Scalefactor coding uses mode 0, 1 or 2, whichever is cheapest.
A per-frame bit-allocation search (gradient G/G+1 split) fits each frame into the
superframe budget. Frames are packed sequentially, and each superframe is zero-padded.
Not implemented: intensity stereo, band extension, parameter reuse, and fine (>15 bit)
precision.

## Build snd0_new.at9 (WSL; static ffmpeg in ~/at9work/ffbin)

    FF=~/at9work/ffbin/ffmpeg-master-latest-linux64-gpl/bin
    $FF/ffmpeg -ss 0.15 -t 45 -i "Sandover Village - Jak and Daxter OST - BoomerStreams.mp3" \
      -af "aresample=48000:resampler=soxr,afade=t=in:d=0.01,afade=t=out:st=44:d=1" \
      -ac 2 -c:a pcm_s16le seg.wav
    python3 at9enc.py ../snd0_original.at9 seg.wav snd0_new.at9     # ~100 s
    $FF/ffmpeg -xerror -i snd0_new.at9 check.wav
    python3 verify.py seg.wav check.wav                               # lag/corr/SNR

## snd0_15s.at9 (header byte-identical to the template, only the data payload differs)

    $FF/ffmpeg -ss 0.15 -t 15 -i "<mp3>" \
      -af "aresample=48000:resampler=soxr,afade=t=in:d=0.02,afade=t=out:st=14.5:d=0.5" \
      -ac 2 -c:a pcm_s16le seg15.wav
    python3 at9enc.py --exact ../snd0_original.at9 seg15.wav snd0_15s.at9

With `--exact`, the input is padded or truncated to fit the template's data size: 704
superframes, which is 720640 input samples plus the 256-sample delay.

Note: ffmpeg's ATRAC9 IMDCT output is the negative of the textbook IMDCT. The encoder
negates its MDCT gain to compensate. This was checked against ffmpeg's decoder.
