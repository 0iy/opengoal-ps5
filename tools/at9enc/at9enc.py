#!/usr/bin/env python3
"""Minimal ATRAC9 encoder (stereo CPE block, 48 kHz, 256-sample frames).

Bitstream = inverse of FFmpeg libavcodec/atrac9dec.c; tables are parsed from
atrac9tab.h (FFmpeg, LGPL-2.1) that sits next to this script.

Simplifications: no intensity stereo, no band extension, no gain control,
no parameter reuse. Bit allocation uses a two-level gradient (G / G+1 split at
unit R) searched per frame against the frame's bit budget; frames inside a
superframe are packed sequentially (as the decoder reads them) and the
superframe is zero-padded to block_align.

Header (fmt/fact/smpl chunk layout, codec config word) is copied from a
template .at9 and only the size/sample-count fields are patched.

usage: at9enc.py template.at9 input.wav output.at9 [--bands N] [--exact]
--exact: output header is byte-identical to the template (input padded/truncated to fit).
input.wav: 16-bit PCM or float32, same rate/channels as template (48k stereo).
"""
import re
import struct
import sys
import os
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- tables
def _parse_braces(body):
    toks = re.findall(r'\{|\}|[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?f?', body)
    stack = [[]]
    for t in toks:
        if t == '{':
            stack.append([])
        elif t == '}':
            v = stack.pop()
            stack[-1].append(v)
        else:
            t = t.rstrip('f')
            stack[-1].append(float(t) if ('.' in t or 'e' in t or 'E' in t) else int(t))
    return stack[0][0]


def load_tables(path):
    src = open(path).read()
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    want = ['at9_tab_band_q_unit_map', 'at9_q_unit_to_coeff_cnt', 'at9_q_unit_to_coeff_idx',
            'at9_q_unit_to_codebookidx', 'at9_tab_sri_max_bands', 'at9_quant_step_coarse',
            'at9_quant_step_fine', 'at9_scalefactor_c', 'at9_tab_sf_weights', 'at9_sfb_a_tab',
            'at9_sfb_b_tab', 'at9_coeffs_tab', 'at9_huffman_coeffs', 'at9_huffman_sf_unsigned',
            'at9_huffman_sf_signed', 'at9_tab_sri_frame_log2', 'at9_tab_samplerates']
    T = {}
    for m in re.finditer(r'static const \w+ (\w+)(?:\[\w*\])+\s*=\s*\{', src):
        name = m.group(1)
        if name not in want:
            continue
        i = m.end() - 1
        depth = 0
        for j in range(i, len(src)):
            if src[j] == '{':
                depth += 1
            elif src[j] == '}':
                depth -= 1
                if depth == 0:
                    break
        T[name] = _parse_braces(src[i:j + 1])
    missing = set(want) - set(T)
    assert not missing, missing
    return T


def canon_codes(entries, offset=0):
    """ff_vlc_init_from_lengths: codes assigned in table order."""
    code = 0
    out = {}
    for sym, ln in entries:
        out[sym + offset] = (code >> (32 - ln), ln)
        code += 1 << (32 - ln)
    assert code == 1 << 32, 'incomplete VLC'
    return out


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


class Tables:
    def __init__(self, path):
        T = load_tables(path)
        self.qmap = T['at9_tab_band_q_unit_map']
        self.ccnt = T['at9_q_unit_to_coeff_cnt']
        self.cidx = T['at9_q_unit_to_coeff_idx']
        self.cbidx = T['at9_q_unit_to_codebookidx']
        self.max_bands = T['at9_tab_sri_max_bands']
        self.cstep = np.array(T['at9_quant_step_coarse'], dtype=np.float64)
        self.sfc = np.array(T['at9_scalefactor_c'], dtype=np.float64)
        self.sfw = T['at9_tab_sf_weights']
        self.frame_log2 = T['at9_tab_sri_frame_log2']
        self.rates = T['at9_tab_samplerates']
        # unsigned sf VLCs, len 1..6
        a = T['at9_sfb_a_tab']
        hu = T['at9_huffman_sf_unsigned']
        self.sf_u = {}
        p = 0
        for ln in range(1, 7):
            n = hu[ln][0]
            self.sf_u[ln] = canon_codes(a[p:p + n])
            p += n
        # signed sf VLCs, len 2..5 (symbols offset -16)
        b = T['at9_sfb_b_tab']
        hs = T['at9_huffman_sf_signed']
        self.sf_s = {}
        p = 0
        for ln in range(2, 6):
            n = hs[ln][0]
            self.sf_s[ln] = canon_codes(b[p:p + n], -16)
            p += n
        # coefficient VLCs [cb][prec][cbi] -> (V values SxK, L lens, C codes)
        ct = T['at9_coeffs_tab']
        hc = T['at9_huffman_coeffs']
        self.cvlc = {}
        p = 0
        for i in range(2):
            for j in range(2, 8):
                for k in range(i, 4):
                    size, vcnt, vpow, vbits = (hc[i][j][k] + [0, 0, 0, 0])[:4]
                    codes = canon_codes(ct[p:p + size])
                    p += size
                    syms = sorted(codes)
                    V = np.array([[sext(s >> (q * vbits), vbits) for q in range(vcnt)] for s in syms],
                                 dtype=np.float64)
                    L = np.array([codes[s][1] for s in syms])
                    C = np.array([codes[s][0] for s in syms])
                    assert 1 << vpow == vcnt and vbits == j
                    self.cvlc[(i, j, k)] = (V, L, C, vcnt)


# ---------------------------------------------------------------- bit writer
class BitWriter:
    def __init__(self):
        self.acc = 0
        self.n = 0

    def w(self, nbits, val):
        if nbits == 0:
            return
        assert 0 <= val < (1 << nbits), (nbits, val)
        self.acc = (self.acc << nbits) | val
        self.n += nbits

    def align(self):
        pad = (-self.n) & 7
        self.w(pad, 0) if pad else None

    def bytes(self):
        assert self.n % 8 == 0
        return self.acc.to_bytes(self.n // 8, 'big') if self.n else b''


# ---------------------------------------------------------------- encoder
class Encoder:
    def __init__(self, tab, frame_bytes, frames_per_sf, sr_idx, bands):
        self.t = tab
        self.N = 1 << tab.frame_log2[sr_idx]
        self.sr_idx = sr_idx
        self.frame_nbits = frame_bytes * 8
        self.fps = frames_per_sf
        self.sf_bytes = frame_bytes * frames_per_sf
        self.bands = min(bands, tab.max_bands[sr_idx])
        self.min_band = 3 if sr_idx <= 7 else 1
        self.max_prec = 7 if sr_idx <= 7 else 1
        N = self.N
        n = np.arange(2 * N)
        k = np.arange(N)
        self.cos = np.cos(np.pi / N * (n[:, None] + 0.5 + N / 2) * (k[None, :] + 0.5))
        i = np.arange(N)
        s_c = np.sin((i + 0.5) / N * np.pi - np.pi / 2) * 0.5 + 0.5
        self.awin = np.concatenate([s_c, s_c[::-1]])  # analysis window (decoder normalizes)
        # decoder: y = -IMDCT(X)/32768 (lavu tx sign convention, verified against ffmpeg),
        # window s_c/(s_c^2+e_c^2); PR needs X = -MDCT*32768*2/N
        self.gain = -32768.0 * 2.0 / N

    def mdct(self, x):
        """x: (samples,) already padded; returns (frames, N)."""
        N = self.N
        F = (len(x) - N) // N
        idx = np.arange(F)[:, None] * N + np.arange(2 * N)[None, :]
        return (x[idx] * self.awin) @ self.cos * self.gain

    # -- scalefactors
    def choose_sf(self, X, q):
        t = self.t
        sf = np.zeros(31, dtype=int)
        for u in range(q):
            m = np.max(np.abs(X[t.cidx[u]:t.cidx[u + 1]]))
            s = int(np.searchsorted(t.sfc, m * 0.999999))
            sf[u] = min(s, 31)
        return sf

    def sf_mode0(self, sf, q):
        """VLC delta offset. returns (bits, writer-fn)."""
        t = self.t
        best = None
        for wi in range(8):
            w = np.array(t.sfw[wi][:q])
            v = sf[:q] + w
            base = int(min(v.min(), 31))
            raw = v - base
            for ln in range(3, 7):
                if raw.max() >= (1 << ln) or raw.min() < 0:
                    continue
                tab = t.sf_u[ln]
                d = (raw[1:] - raw[:-1]) & ((1 << ln) - 1)
                bits = 2 + 3 + 5 + 2 + ln + sum(tab[int(x)][1] for x in d)
                if best is None or bits < best[0]:
                    best = (bits, wi, base, ln, raw.copy(), d.copy())
        if best is None:
            return None
        bits, wi, base, ln, raw, d = best

        def wr(bw, idx_code=0):
            bw.w(2, idx_code)
            bw.w(3, wi)
            bw.w(5, base)
            bw.w(2, ln - 3)
            bw.w(ln, int(raw[0]))
            for x in d:
                c, l = t.sf_u[ln][int(x)]
                bw.w(l, c)
        return bits, wr

    def sf_mode1(self, sf, q):
        """CLC offset (channel 0 only)."""
        v = sf[:q]
        best = None
        for ln in range(2, 6):
            base = int(v.min()) if ln < 5 else 0
            if v.max() - base >= (1 << ln) or base > 31:
                continue
            bits = 2 + 2 + (5 if ln < 5 else 0) + ln * q
            if best is None or bits < best[0]:
                best = (bits, ln, base)
        bits, ln, base = best

        def wr(bw):
            bw.w(2, 1)
            bw.w(2, ln - 2)
            if ln < 5:
                bw.w(5, base)
            for x in v:
                bw.w(ln, int(x) - base)
        return bits, wr

    def sf_mode2(self, sf, ref, q):
        """VLC distance to channel-0 scalefactors (channel 1 only)."""
        t = self.t
        d = sf[:q] - ref[:q]
        best = None
        for ln in range(2, 6):
            tab = t.sf_s[ln]
            if any(int(x) not in tab for x in d):
                continue
            bits = 2 + 2 + sum(tab[int(x)][1] for x in d)
            if best is None or bits < best[0]:
                best = (bits, ln)
        if best is None:
            return None
        bits, ln = best

        def wr(bw):
            bw.w(2, 1)
            bw.w(2, ln - 2)
            for x in d:
                c, l = t.sf_s[ln][int(x)]
                bw.w(l, c)
        return bits, wr

    def codebookset(self, sf, q):
        t = self.t
        cbs = [0] * 30
        if q <= 1:
            return cbs
        s = list(int(x) for x in sf)
        s[q] = s[q - 1]
        avg = 0
        if q > 12:
            avg = (sum(s[:12]) + 6) // 12
        for i in range(8, q):
            prev, cur, nxt = s[i - 1], s[i], s[i + 1]
            if cur - min(prev, nxt) >= 3 or 2 * cur - prev - nxt >= 3:
                cbs[i] = 1
        for i in range(12, q):
            if cbs[i]:
                continue
            cnd = 1 if t.ccnt[i] == 16 else 0
            mn = min(s[i + 1], s[i - 1])
            cbs[i] = 1 if (s[i] - mn >= 2 and s[i] >= avg - cnd) else 0
        return cbs

    # -- coefficient quantization (cached per unit/precision)
    def quant_unit(self, xn, pc, cb, cbi):
        prec = pc + 1
        tv = xn / self.t.cstep[pc]
        if prec <= self.max_prec:
            V, L, C, k = self.t.cvlc[(cb, prec, cbi)]
            g = tv.reshape(-1, k)
            err = ((g[:, None, :] - V[None, :, :]) ** 2).sum(-1) + 1e-6 * L[None, :]
            idx = np.argmin(err, axis=1)
            return int(L[idx].sum()), ('v', idx, V[idx].ravel())
        lim = 1 << (prec - 1)
        qv = np.clip(np.rint(tv), -lim, lim - 1).astype(int)
        return prec * len(qv), ('r', prec, qv)

    def frame_bits(self, ch, G, R, q):
        """total coefficient bits for one channel and the quantized data."""
        t = self.t
        tot = 0
        data = []
        for u in range(q):
            grad = G if u < R else G + 1
            pc = max(int(ch['sf'][u]) - grad, 1)
            key = (u, pc)
            if key not in ch['cache']:
                xn = ch['X'][t.cidx[u]:t.cidx[u + 1]] / t.sfc[ch['sf'][u]]
                ch['cache'][key] = self.quant_unit(xn, pc, ch['cbs'][u], t.cbidx[u])
            b, d = ch['cache'][key]
            tot += b
            data.append((u, pc, d))
        return tot, data

    def encode_frame(self, bw, X2, first, budget):
        t = self.t
        HDR = 42
        for band_count in range(self.bands, self.min_band - 1, -1):
            q = t.qmap[band_count]
            chans = []
            for c in range(2):
                X = X2[c]
                sf = self.choose_sf(X, q)
                chans.append({'X': X, 'sf': sf, 'cbs': self.codebookset(sf, q), 'cache': {}})
            s0 = min(x for x in (self.sf_mode0(chans[0]['sf'], q), self.sf_mode1(chans[0]['sf'], q))
                     if x is not None)
            c1 = [self.sf_mode0(chans[1]['sf'], q), self.sf_mode2(chans[1]['sf'], chans[0]['sf'], q)]
            c1 = [x for x in c1 if x is not None]
            s1 = min(c1, key=lambda x: x[0])
            # mode2 for channel 1 must be written with index 1, mode0 with index 0
            fixed = HDR + s0[0] + s1[0]
            Gmin = max(0, int(max(chans[0]['sf'][:q].max(), chans[1]['sf'][:q].max())) - 15)

            def params(tt):
                return 30 - tt // q, tt % q

            def cost(tt):
                G, R = params(tt)
                return fixed + self.frame_bits(chans[0], G, R, q)[0] + self.frame_bits(chans[1], G, R, q)[0]

            tmax = (30 - Gmin) * q + (q - 1)
            if cost(0) > budget:
                continue
            lo, hi = 0, tmax
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if cost(mid) <= budget:
                    lo = mid
                else:
                    hi = mid - 1
            G, R = params(lo)
            start = bw.n
            # ---- write block
            bw.w(1, 0 if first else 1)      # !first_in_pkt
            bw.w(1, 0)                       # reuse_params
            bw.w(4, band_count - self.min_band)
            bw.w(4, band_count - self.min_band)  # stereo band = band count (no IS)
            bw.w(1, 0)                       # has_band_ext
            bw.w(2, 0)                       # grad_mode
            bw.w(6, R)                       # grad_range[0]
            bw.w(6, 30)                      # grad_range[1]-1
            bw.w(5, G)                       # grad_value[0]
            bw.w(5, G + 1)                   # grad_value[1]
            bw.w(4, 0)                       # grad_boundary
            bw.w(1, 0)                       # cpe_base_channel
            bw.w(1, 0)                       # no IS signs
            bw.w(1, 0)                       # has_band_ext_data
            for c in range(2):
                ch = chans[c]
                if c == 0:
                    s0[1](bw)
                else:
                    s1[1](bw)
                _, data = self.frame_bits(ch, G, R, q)
                for u, pc, d in data:
                    if d[0] == 'v':
                        V, L, C, k = t.cvlc[(ch['cbs'][u], pc + 1, t.cbidx[u])]
                        for i in d[1]:
                            bw.w(int(L[i]), int(C[i]))
                    else:
                        prec = d[1]
                        for v in d[2]:
                            bw.w(prec, int(v) & ((1 << prec) - 1))
            used = bw.n - start
            assert used == cost(lo), (used, cost(lo))
            bw.align()
            # reconstruction (for stats)
            rec = np.zeros((2, self.N))
            for c in range(2):
                _, data = self.frame_bits(chans[c], G, R, q)
                for u, pc, d in data:
                    vals = d[2]
                    rec[c, t.cidx[u]:t.cidx[u + 1]] = vals * t.cstep[pc] * t.sfc[chans[c]['sf'][u]]
            return G, R, band_count, rec
        raise RuntimeError('frame does not fit')

    def encode(self, pcm):
        """pcm: (samples, 2) float in [-1,1]. returns (data bytes, n_frames)."""
        N = self.N
        ns = len(pcm)
        F = -(-(ns + N) // N)
        F = -(-F // self.fps) * self.fps
        xp = np.zeros((F * N + N, 2))
        xp[N:N + ns] = pcm
        X = [self.mdct(xp[:, c]) for c in range(2)]
        out = bytearray()
        stats = []
        for s in range(F // self.fps):
            bw = BitWriter()
            for f in range(self.fps):
                fi = s * self.fps + f
                budget = self.frame_nbits * (f + 1) - bw.n
                G, R, bc, rec = self.encode_frame(bw, [X[0][fi], X[1][fi]], f == 0, budget)
                stats.append((G, R, bc))
            b = bw.bytes()
            assert len(b) <= self.sf_bytes
            out += b + bytes(self.sf_bytes - len(b))
            if s % 100 == 0:
                print('superframe %d/%d  G=%d R=%d bands=%d  used=%d/%d bytes' %
                      (s, F // self.fps, G, R, bc, len(b), self.sf_bytes), file=sys.stderr)
        return bytes(out), F, stats


# ---------------------------------------------------------------- container
def read_chunks(buf):
    assert buf[:4] == b'RIFF' and buf[8:12] == b'WAVE'
    p = 12
    ch = []
    while p + 8 <= len(buf):
        cid = buf[p:p + 4]
        sz = struct.unpack_from('<I', buf, p + 4)[0]
        ch.append((cid, p, sz))
        p += 8 + sz + (sz & 1)
    return ch


def parse_template(path):
    buf = open(path, 'rb').read()
    chunks = read_chunks(buf)
    d = {c[0]: c for c in chunks}
    _, fp, fsz = d[b'fmt ']
    fmt = buf[fp + 8:fp + 8 + fsz]
    tag, nch, rate, brate, balign, bps, cbsize = struct.unpack_from('<HHIIHHH', fmt, 0)
    ext = fmt[18:18 + cbsize]
    ver = struct.unpack_from('<I', ext, 22)[0]
    cfg = ext[26:30]
    assert cfg[0] == 0xFE
    bits = int.from_bytes(cfg, 'big')
    sr_idx = (bits >> 20) & 15
    chcfg = (bits >> 17) & 7
    fbytes = ((bits >> 5) & 0x7FF) + 1
    sfi = (bits >> 3) & 3
    info = dict(tag=tag, nch=nch, rate=rate, brate=brate, balign=balign, ver=ver,
                cfg=cfg.hex(), sr_idx=sr_idx, chcfg=chcfg, frame_bytes=fbytes, fps=1 << sfi)
    return buf, chunks, info


def build_file(tbuf, chunks, data, nsamples, delay):
    out = bytearray(b'RIFF\0\0\0\0WAVE')
    for cid, p, sz in chunks:
        body = bytearray(tbuf[p + 8:p + 8 + sz])
        if cid == b'data':
            body = bytearray(data)
        elif cid == b'fact':
            struct.pack_into('<I', body, 0, nsamples)
        elif cid == b'smpl':
            nl = struct.unpack_from('<I', body, 28)[0]
            for i in range(nl):
                o = 36 + 24 * i
                struct.pack_into('<I', body, o + 8, delay)                  # loop start
                struct.pack_into('<I', body, o + 12, delay + nsamples - 1)  # loop end
        out += cid + struct.pack('<I', len(body)) + body
        if len(body) & 1:
            out += b'\0'
    struct.pack_into('<I', out, 4, len(out) - 8)
    return bytes(out)


def read_wav(path):
    buf = open(path, 'rb').read()
    ch = {c[0]: c for c in read_chunks(buf)}
    _, fp, fsz = ch[b'fmt ']
    tag, nch, rate, brate, balign, bps = struct.unpack_from('<HHIIHH', buf, fp + 8)
    if tag == 0xFFFE:
        tag = struct.unpack_from('<H', buf, fp + 8 + 24)[0]
    _, dp, dsz = ch[b'data']
    raw = buf[dp + 8:dp + 8 + dsz]
    if tag == 1 and bps == 16:
        x = np.frombuffer(raw, '<i2').astype(np.float64) / 32768.0
    elif tag == 3 and bps == 32:
        x = np.frombuffer(raw, '<f4').astype(np.float64)
    else:
        raise ValueError('need s16 or f32 wav')
    return x.reshape(-1, nch), rate


def main():
    args = sys.argv[1:]
    bands = 16
    if '--bands' in args:
        i = args.index('--bands')
        bands = int(args[i + 1])
        del args[i:i + 2]
    exact = '--exact' in args   # keep every template header byte; only replace data payload
    if exact:
        args.remove('--exact')
    tpl, inp, outp = args
    tbuf, chunks, info = parse_template(tpl)
    print('template:', info, file=sys.stderr)
    assert info['chcfg'] == 2 and info['nch'] == 2, 'only stereo (single CPE block) supported'
    tab = Tables(os.path.join(HERE, 'atrac9tab.h'))
    assert info['frame_bytes'] * info['fps'] == info['balign']
    pcm, rate = read_wav(inp)
    assert rate == info['rate'] == tab.rates[info['sr_idx']] and pcm.shape[1] == 2, 'resample input first'
    enc = Encoder(tab, info['frame_bytes'], info['fps'], info['sr_idx'], bands)
    if exact:
        _, dp, dsz = [c for c in chunks if c[0] == b'data'][0]
        n_in = dsz // info['frame_bytes'] * enc.N - enc.N   # max input that fits the template data size
        pcm = np.concatenate([pcm, np.zeros((max(0, n_in - len(pcm)), 2))])[:n_in]
    data, F, stats = enc.encode(pcm)
    if exact:
        assert len(data) == dsz, (len(data), dsz)
        out = tbuf[:dp + 8] + data + tbuf[dp + 8 + dsz:]
        assert len(out) == len(tbuf)
    else:
        out = build_file(tbuf, chunks, data, len(pcm), enc.N)
    open(outp, 'wb').write(out)
    G = np.array([s[0] for s in stats])
    print('wrote %s: %d bytes, %d samples, %d frames, mean G=%.2f, min bands=%d' %
          (outp, len(out), len(pcm), F, G.mean(), min(s[2] for s in stats)), file=sys.stderr)


if __name__ == '__main__':
    main()
