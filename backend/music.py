"""程序合成的无版权 BGM（企业宣传风格）和转场音效。结构跟着剪辑段落走：开场→主标题→主体律动→间奏→片尾。"""
import numpy as np
import scipy.signal as sg
from scipy.io import wavfile

SR = 48000


def midi(m):
    return 440 * 2 ** ((m - 69) / 12)


def synth_bgm(out_path, total, bpm=100, title_t=None, groove_t=None, end_t=None, mood="inspiring", seed=7):
    BEAT = 60 / bpm
    BAR = 4 * BEAT
    NB = int(np.ceil(total / BAR)) + 1
    DUR = NB * BAR + 4.0
    N = int(DUR * SR)
    L = np.zeros(N)
    R = np.zeros(N)
    rng = np.random.default_rng(seed)
    bar_of = lambda t, d: int(round(t / BAR)) if t is not None else d
    b_title = bar_of(title_t, 2)
    b_groove = max(b_title + 1, bar_of(groove_t, b_title + 3))
    b_end = bar_of(end_t, NB - 3)
    drums = mood != "calm"

    def add(sig, t, pan=0.0, g=1.0):
        i = int(t * SR)
        n = min(len(sig), N - i)
        if n <= 0 or i < 0:
            return
        L[i:i + n] += sig[:n] * g * np.cos((pan + 1) * np.pi / 4) * 1.414
        R[i:i + n] += sig[:n] * g * np.sin((pan + 1) * np.pi / 4) * 1.414

    def env(a, d, s_level, r, total_n):
        e = np.ones(total_n) * s_level
        na = int(a * SR)
        if na:
            e[:na] = np.linspace(0, 1, na)
        nd = int(d * SR)
        e[na:na + nd] = np.linspace(1, s_level, len(e[na:na + nd]))
        nr = int(r * SR)
        if nr:
            e[-nr:] *= np.linspace(1, 0, nr)
        return e

    CH = [[62, 66, 69], [61, 64, 69], [59, 62, 66], [59, 62, 67]]  # D A Bm G
    ROOT = [38, 33, 35, 31]

    def pad(notes, dur, g=0.06):
        n = int(dur * SR)
        t = np.arange(n) / SR
        s = np.zeros(n)
        for m in notes + [notes[0] + 12]:
            f = midi(m)
            for det in (-0.08, 0.0, 0.07):
                ff = f * 2 ** (det / 12)
                ph = rng.random() * 6.28
                for h in range(1, 9):
                    if ff * h > 5000:
                        break
                    s += np.sin(2 * np.pi * ff * h * t + ph * h) / h ** 1.6
        return s * env(0.8, 0.5, 0.85, 1.2, n) * g / len(notes)

    def pluck(m, g=0.18, dec=1.6):
        f = midi(m)
        n = int(1.8 * SR)
        t = np.arange(n) / SR
        s = sum(np.sin(2 * np.pi * f * h * t) * np.exp(-t * (dec * h ** 0.9)) / h ** 1.2 for h in range(1, 10))
        return s * np.minimum(1, t / 0.003) * g

    def piano(m, g=0.22):
        f = midi(m)
        n = int(3.5 * SR)
        t = np.arange(n) / SR
        s = sum(np.sin(2 * np.pi * f * h * np.sqrt(1 + 0.0004 * h * h) * t) * np.exp(-t * (0.9 + 0.55 * h)) / h ** 1.1
                for h in range(1, 12))
        return s * np.minimum(1, t / 0.004) * g

    def bass(m, dur, g=0.32):
        f = midi(m)
        n = int(dur * SR)
        t = np.arange(n) / SR
        s = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(4 * np.pi * f * t) + 0.08 * np.sin(6 * np.pi * f * t)
        return np.tanh(1.3 * s) * env(0.01, 0.2, 0.75, 0.08, n) * g

    def kick(g=0.9):
        n = int(0.45 * SR)
        t = np.arange(n) / SR
        f = 45 + 85 * np.exp(-t * 28)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5) + 0.15 * rng.standard_normal(n) * np.exp(-t * 300)
        return np.tanh(1.5 * s) * g

    def noise_burst(dur, hp, lp, dec, g):
        n = int(dur * SR)
        t = np.arange(n) / SR
        b, a = sg.butter(2, [hp / (SR / 2), min(lp / (SR / 2), 0.99)], "band")
        return sg.lfilter(b, a, rng.standard_normal(n)) * np.exp(-t * dec) * g

    def clap(g=0.35):
        s = np.zeros(int(0.35 * SR))
        for k, o in enumerate((0, 0.011, 0.022)):
            nb = noise_burst(0.3, 900, 6000, 22 if k == 2 else 120, 1.0)
            i = int(o * SR)
            s[i:i + len(nb)][:len(s) - i] += nb[:len(s) - i]
        return s * g / 2

    hat = lambda g=0.06: noise_burst(0.08, 7000, 16000, 60, g)

    def boom(g=0.8):
        n = int(3.0 * SR)
        t = np.arange(n) / SR
        f = 30 + 50 * np.exp(-t * 6)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 1.6) + noise_burst(3.0, 60, 800, 2.2, 0.5)
        return np.tanh(s) * g

    def riser(dur, g=0.12):
        n = int(dur * SR)
        t = np.arange(n) / SR
        x = rng.standard_normal(n)
        out = np.zeros(n)
        seg = 2048
        for i in range(0, n, seg):
            fc = 300 + 6000 * (i / n) ** 2
            b, a = sg.butter(2, [fc * 0.7 / (SR / 2), min(fc * 1.4 / (SR / 2), 0.99)], "band")
            out[i:i + seg] = sg.lfilter(b, a, x[i:i + seg])
        return out * (t / dur) ** 2 * g

    bt = lambda b: b * BEAT
    for bar in range(NB):
        t0 = bar * BAR
        ci = bar % 4
        ch = CH[ci]
        intro = bar < b_title
        title = b_title <= bar < b_groove
        brk = b_end - 2 <= bar < b_end
        groove = b_groove <= bar < b_end - 2
        end = bar >= b_end
        if end:
            if bar == b_end:
                add(pad([62, 66, 69, 74], 7.5, 0.09), t0)
                add(pad([62, 66, 69, 74], 7.5, 0.05), t0 + 0.01, 0.5)
                for k, m in enumerate([62, 66, 69, 74, 78]):
                    add(piano(m, 0.2), t0 + k * 0.09, (k - 2) * 0.2)
                add(bass(26, 6.0, 0.3), t0)
                add(boom(0.55), t0)
            continue
        add(pad(ch, BAR + 1.0, 0.05 if intro else 0.07), t0, -0.4)
        add(pad(ch, BAR + 1.0, 0.05), t0 + 0.013, 0.4)
        arp = [ch[0] + 12, ch[1] + 12, ch[2] + 12, ch[1] + 12, ch[0] + 24, ch[2] + 12, ch[1] + 12, ch[2] + 12]
        if not title:
            for k in range(8):
                add(pluck(arp[k], 0.10 if (intro or brk or not drums) else 0.12), t0 + k * BEAT / 2, 0.35 if k % 2 else -0.35)
        if title or brk or (groove and bar % 2 == 0):
            add(piano(ch[0] + 12, 0.18 if groove else 0.24), t0, -0.1)
            add(piano(ch[2] + 12, 0.12), t0 + bt(1.5), 0.15)
            if not groove:
                add(piano(ch[1] + 24, 0.10), t0 + bt(3), 0.2)
        if drums and (groove or intro):
            for b in range(4):
                add(kick(0.75 if groove else 0.6), t0 + bt(b))
        if groove:
            add(bass(ROOT[ci], bt(1.9), 0.30), t0)
            add(bass(ROOT[ci], bt(1.9), 0.26), t0 + bt(2))
            if drums:
                add(bass(ROOT[ci] + 12, bt(0.45), 0.12), t0 + bt(1.5))
                add(bass(ROOT[ci] + 12, bt(0.45), 0.12), t0 + bt(3.5))
                for b in (1, 3):
                    add(clap(0.30), t0 + bt(b), 0.05)
                for k in range(8):
                    add(hat(0.05 if k % 2 else 0.03), t0 + k * BEAT / 2, 0.3)
                if bar % 8 == 4:
                    for k in range(4):
                        add(clap(0.12), t0 + bt(3) + k * BEAT / 4, -0.1)
    if b_title > 0:
        add(riser(BAR, 0.10), b_title * BAR - BAR)
        add(boom(0.75), b_title * BAR)
    add(riser(BAR, 0.08), b_groove * BAR - BAR)
    add(riser(BAR, 0.08), b_end * BAR - BAR)

    def ir(sec=2.2, s=1):
        r = np.random.default_rng(s)
        n = int(sec * SR)
        t = np.arange(n) / SR
        b, a = sg.butter(1, 5000 / (SR / 2))
        return sg.lfilter(b, a, r.standard_normal(n) * np.exp(-t * 3.2)) * 0.03

    L = L + 0.35 * sg.fftconvolve(L, ir(s=1))[:N]
    R = R + 0.35 * sg.fftconvolve(R, ir(s=2))[:N]
    mix = np.stack([L, R], 1)
    b, a = sg.butter(2, 30 / (SR / 2), "high")
    mix = sg.lfilter(b, a, mix, axis=0)
    mix /= np.percentile(np.abs(mix), 99.95) + 1e-9
    mix = np.tanh(mix * 0.9) * 0.85
    n_out = int((total + 0.5) * SR)
    mix = mix[:n_out]
    fade = int(1.5 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    wavfile.write(out_path, SR, (mix * 32767).astype(np.int16))
    return len(mix) / SR


def whoosh(out_path, dur=0.7, seed=3):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    x = rng.standard_normal(n)
    out = np.zeros(n)
    seg = 1024
    for i in range(0, n, seg):
        p = i / n
        fc = 400 + 3500 * np.sin(np.pi * p) ** 2
        b, a = sg.butter(2, [fc * 0.6 / (SR / 2), fc * 1.6 / (SR / 2)], "band")
        out[i:i + seg] = sg.lfilter(b, a, x[i:i + seg])
    s = out * np.sin(np.pi * np.linspace(0, 1, n)) ** 2
    s /= np.abs(s).max()
    st = np.stack([s * np.linspace(1.2, 0.6, n), s * np.linspace(0.6, 1.2, n)], 1) * 0.5
    wavfile.write(out_path, SR, (st * 32767).astype(np.int16))
    return dur
