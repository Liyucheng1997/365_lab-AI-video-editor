"""最终渲染：按时间线逐帧合成（防抖 / 慢放补帧 / 调色 / 转场 / 文字动画），多进程分段编码，混音并统一响度。

也可作为子进程运行：python render.py worker <project.json> <project_dir> <frame0> <frame1> <out.mp4> <quality>
"""
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import scipy.signal as sg
from scipy.io import wavfile
from scipy.ndimage import gaussian_filter1d

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FFMPEG  # noqa: E402
from media import NOWIN, TONEMAP, decode_audio  # noqa: E402
from textfx import Sprite, hex_rgba, layers  # noqa: E402

FILTER_PRESETS = {
    "none": dict(exposure=1.0, contrast=0.0, saturation=1.0, temperature=0.0, sharpen=0.0, splitTone=0.0),
    "cinematic": dict(exposure=1.05, contrast=0.28, saturation=1.10, temperature=0.0, sharpen=0.45, splitTone=1.0),
    "bright": dict(exposure=1.12, contrast=0.15, saturation=1.08, temperature=0.05, sharpen=0.3, splitTone=0.3),
    "warm": dict(exposure=1.05, contrast=0.22, saturation=1.05, temperature=0.35, sharpen=0.35, splitTone=0.5),
    "cool": dict(exposure=1.03, contrast=0.25, saturation=1.0, temperature=-0.35, sharpen=0.35, splitTone=0.8),
    "bw": dict(exposure=1.05, contrast=0.35, saturation=0.0, temperature=0.0, sharpen=0.4, splitTone=0.0),
}


def filt(c):
    f = dict(FILTER_PRESETS.get((c.get("filter") or {}).get("preset", "cinematic"), FILTER_PRESETS["cinematic"]))
    f.update({k: v for k, v in (c.get("filter") or {}).items() if k != "preset" and v is not None})
    f.setdefault("blur", 0.0)
    f.setdefault("brightness", 1.0)
    return f


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return 1 - (1 - x) ** 3


def clamp01(x):
    return min(max(x, 0.0), 1.0)


def smooth(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def tracks(proj, typ):
    return [t for t in proj["timeline"]["tracks"] if t["type"] == typ and not t.get("hidden")]


def timeline_end(proj):
    end = 0.0
    for t in proj["timeline"]["tracks"]:
        for c in t["clips"]:
            end = max(end, c["start"] + c["duration"])
    return end


# --------------------------------------------------------------------------- 画面
class Ctx:
    def __init__(self, proj, pdir):
        s = proj["settings"]
        self.W, self.H, self.FPS = int(s["width"]), int(s["height"]), int(s.get("fps", 30))
        self.k = self.W / 1080
        self.proj, self.pdir = proj, Path(pdir)
        W, H = self.W, self.H
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        self.xx, self.yy = xx, yy
        look = s.get("look", {})
        st = np.ones((H, W), np.float32)
        if look.get("vignette", True):
            r = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.47) / (H * 0.6)) ** 2)
            st *= 1 - 0.30 * np.clip(r, 0, 1.4) ** 2.4
        if look.get("gradients", True):
            bot = np.clip((yy - H * 0.667) / (H * 0.333), 0, 1) ** 1.4
            top = np.clip((H * 0.29 - yy) / (H * 0.29), 0, 1) ** 1.6
            st *= (1 - 0.58 * bot) * (1 - 0.30 * top)
        self.STATIC = st[..., None]
        self.HDRMASK = (np.clip((640 * self.k - yy) / (640 * self.k), 0, 1) ** 1.3 * np.clip(1.25 - xx / W, 0, 1))[..., None]
        self.fade_io = look.get("fadeInOut", True)
        self.total = timeline_end(proj)
        self.assets = {a["id"]: a for a in proj["assets"]}

    def path(self, p):
        p = Path(p)
        return p if p.is_absolute() else self.pdir / p

    def tband(self, yc):
        return np.exp(-((self.yy - yc) / (300 * self.k)) ** 4)[..., None]


def build_lut(f):
    x = np.arange(256) / 255.0
    temp = float(f["temperature"])
    gains = (1 - 0.10 * temp, 1.0, 1 + 0.10 * temp)  # B G R
    con, split = float(f["contrast"]), float(f["splitTone"])
    luts = []
    for ch, g in zip((0, 1, 2), gains):
        y = np.clip(x * f["exposure"] * g, 0, 1.2)
        y = np.where(y > 0.8, 0.8 + (y - 0.8) / (1 + (y - 0.8) * 2.2), y)
        y = np.clip(y, 0, 1)
        y = (1 - con) * y + con * (3 * y ** 2 - 2 * y ** 3)
        if con > 0:
            y = 0.012 + 0.975 * y
        sh, hi = (1 - y) ** 3, y ** 3
        if ch == 0:
            y = y + split * (0.030 * sh - 0.018 * hi)
        if ch == 1:
            y = y + split * (0.010 * sh - 0.002 * hi)
        if ch == 2:
            y = y + split * (-0.012 * sh + 0.016 * hi)
        luts.append(np.clip(y * 255, 0, 255))
    return np.stack(luts, -1).astype(np.uint8).reshape(1, 256, 3)


def grade(img, f, lut):
    img = cv2.LUT(img, lut)
    if f["sharpen"] > 0:
        bl = cv2.GaussianBlur(img, (0, 0), 1.3)
        img = cv2.addWeighted(img, 1 + f["sharpen"], bl, -f["sharpen"], 0)
    out = img.astype(np.float32) * (1 / 255)
    if abs(f["saturation"] - 1) > 1e-3:
        Y = out[..., 0:1] * 0.114 + out[..., 1:2] * 0.587 + out[..., 2:3] * 0.299
        out = Y + f["saturation"] * (out - Y)
    if f["blur"] > 0.2:
        out = cv2.GaussianBlur(out, (0, 0), f["blur"])
    if abs(f["brightness"] - 1) > 1e-3:
        out *= f["brightness"]
    return out


def vf_chain(w, h, rotate, hdr):
    vf = []
    r = int(rotate or 0) % 360
    if r == 90:
        vf.append("transpose=1")
    elif r == 270:
        vf.append("transpose=2")
    elif r == 180:
        vf.append("transpose=1,transpose=1")
    vf.append(f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=bicubic,crop={w}:{h}")
    if hdr:
        vf.append(TONEMAP)
    return ",".join(vf)


class FramePipe:
    """顺序读取 ffmpeg 解码帧，只保留很小的缓冲，避免整段素材进内存。"""

    def __init__(self, src, ss, dur, w, h, fps, rotate, hdr, gray=False):
        self.args = (src, ss, dur, w, h, fps, rotate, hdr, gray)
        self.w, self.h, self.gray = w, h, gray
        self._open()

    def _open(self):
        src, ss, dur, w, h, fps, rotate, hdr, gray = self.args
        cmd = [FFMPEG, "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-an",
               "-vf", vf_chain(w, h, rotate, hdr) + f",fps={fps}", "-f", "rawvideo", "-pix_fmt", "gray" if gray else "bgr24", "-"]
        self.p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWIN, bufsize=10 ** 7)
        self.buf, self.next, self.eof = {}, 0, False
        self.n = w * h * (1 if gray else 3)

    def get(self, i):
        i = max(0, int(i))
        if self.buf and i < min(self.buf):
            self.close()
            self._open()
        while self.next <= i and not self.eof:
            raw = self.p.stdout.read(self.n)
            if len(raw) < self.n:
                self.eof = True
                break
            self.buf[self.next] = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, *(() if self.gray else (3,)))
            self.next += 1
        for k in [k for k in self.buf if k < i - 1]:
            del self.buf[k]
        if not self.buf:
            return None
        return self.buf[min(i, max(self.buf))]

    def read_all(self):
        out = []
        while True:
            raw = self.p.stdout.read(self.n)
            if len(raw) < self.n:
                break
            out.append(np.frombuffer(raw, np.uint8).reshape(self.h, self.w))
        self.close()
        return out

    def close(self):
        try:
            self.p.stdout.close()
            self.p.kill()
            self.p.wait(2)
        except Exception:
            pass


class VClip:
    def __init__(self, c, ctx: Ctx, nxt, idx, quality):
        self.c, self.ctx, self.idx, self.quality = c, ctx, idx, quality
        self.asset = ctx.assets.get(c["assetId"])
        self.start, self.dur = float(c["start"]), float(c["duration"])
        self.end = self.start + self.dur
        self.freeze = bool(c.get("freeze")) or (self.asset and self.asset["kind"] == "image")
        self.speed = 0.0 if self.freeze else (c["out"] - c["in"]) / max(1e-3, self.dur)
        tr = c.get("transition") or {}
        self.tr_type, self.tr_d = tr.get("type", "none"), float(tr.get("duration", 0.4) or 0)
        ntr = (nxt.get("transition") or {}) if nxt else {}
        touching = nxt is not None and abs(nxt["start"] - self.end) < 0.05
        self.xin = self.tr_d / 2 if self.tr_type == "fade" else 0.0
        self.xout = float(ntr.get("duration", 0.4)) / 2 if (touching and ntr.get("type") == "fade") else 0.0
        self.a0, self.a1 = self.start - self.xin, self.end + self.xout
        self.f = filt(c)
        self.lut = build_lut(self.f)
        tf = c.get("transform") or {}
        self.zoom = float(tf.get("zoom", 1.07))
        self.kb = float(tf.get("kenburns", 0.045 if idx % 2 == 0 else -0.04))
        self.ox, self.oy = float(tf.get("x", 0)) * ctx.k, float(tf.get("y", 0)) * ctx.k
        self.rot = float(tf.get("rotate", 0))
        self.pipe = None
        self.still = None
        self.flowcache = {}

    def src_time(self, t):
        return self.c["in"] + (t - self.start) * self.speed

    def load(self):
        ctx, a, c = self.ctx, self.asset, self.c
        W, H, FPS = ctx.W, ctx.H, ctx.FPS
        if a is None:
            self.still = np.zeros((H, W, 3), np.uint8)
            return
        if a["kind"] == "image":
            im = cv2.imdecode(np.fromfile(str(ctx.path(a["path"])), np.uint8), cv2.IMREAD_COLOR)
            s = max(W / im.shape[1], H / im.shape[0])
            im = cv2.resize(im, (math.ceil(im.shape[1] * s), math.ceil(im.shape[0] * s)), interpolation=cv2.INTER_AREA)
            y0, x0 = (im.shape[0] - H) // 2, (im.shape[1] - W) // 2
            self.still = np.ascontiguousarray(im[y0:y0 + H, x0:x0 + W])
            self.corr = np.zeros((1, 3))
            return
        src = ctx.path(a["path"])
        if self.freeze:
            p = FramePipe(src, max(0, c["in"]), 0.2, W, H, FPS, self.rot, a.get("hdr"))
            self.still = p.get(0)
            p.close()
            if self.still is None:
                self.still = np.zeros((H, W, 3), np.uint8)
            self.corr = np.zeros((1, 3))
            return
        dur_src = a.get("duration") or 1e9
        self.ss = max(0.0, self.src_time(self.a0) - 0.1 * max(self.speed, 0.2))
        until = min(dur_src, self.src_time(self.a1) + 0.15)
        self.span = max(0.1, until - self.ss)
        self.pipe = FramePipe(src, self.ss, self.span, W, H, FPS, self.rot, a.get("hdr"))
        # 防抖轨迹：用低分辨率预览代理估计（与全分辨率解码同样的几何变换）
        self.corr = None
        if c.get("stabilize", True) and a.get("proxy"):
            q = 4
            frames = FramePipe(ctx.path(a["proxy"]), self.ss, self.span, W // q, H // q, FPS, self.rot, False, gray=True).read_all()
            if len(frames) > 5:
                tr = [[0, 0, 0]]
                for prev, g in zip(frames, frames[1:]):
                    m = None
                    p0 = cv2.goodFeaturesToTrack(prev, 300, 0.01, 8)
                    if p0 is not None and len(p0) > 10:
                        p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, g, p0, None)
                        if st is not None and st.sum() > 6:
                            m, _ = cv2.estimateAffinePartial2D(p0[st == 1], p1[st == 1])
                    tr.append([m[0, 2] * q, m[1, 2] * q, math.atan2(m[1, 0], m[0, 0])] if m is not None else [0, 0, 0])
                traj = np.cumsum(np.array(tr), 0)
                sig = float(c.get("stabilizeStrength", 9.0))
                sm = np.stack([gaussian_filter1d(traj[:, i], sig, mode="nearest") for i in range(3)], 1)
                corr = sm - traj
                corr[:, 0] = np.clip(corr[:, 0], -30 * ctx.k, 30 * ctx.k)
                corr[:, 1] = np.clip(corr[:, 1], -52 * ctx.k, 52 * ctx.k)
                corr[:, 2] = np.clip(corr[:, 2], -0.02, 0.02)
                self.corr = corr

    def free(self):
        if self.pipe:
            self.pipe.close()
        self.pipe = None
        self.still = None
        self.flowcache = {}

    @property
    def loaded(self):
        return self.pipe is not None or self.still is not None

    def flow(self, i, j, a, b):
        k = (i, j)
        if k not in self.flowcache:
            W, H = self.ctx.W, self.ctx.H
            ga = cv2.cvtColor(cv2.resize(a, (W // 2, H // 2)), cv2.COLOR_BGR2GRAY)
            gb = cv2.cvtColor(cv2.resize(b, (W // 2, H // 2)), cv2.COLOR_BGR2GRAY)
            f = DIS().calc(ga, gb, None)
            self.flowcache = {k: cv2.resize(f, (W, H)) * 2}
        return self.flowcache[k]

    def raw(self, p):
        if self.still is not None:
            return self.still, 0.0
        i = int(math.floor(p))
        a = p - i
        f0 = self.pipe.get(i)
        if f0 is None:
            return np.zeros((self.ctx.H, self.ctx.W, 3), np.uint8), 0.0
        interp = self.quality == "high" and self.c.get("smoothSlowmo", True) and self.speed < 0.97 and 0.12 < a < 0.88
        if not interp:
            if a > 0.5:
                f1 = self.pipe.get(i + 1)
                return (f1 if f1 is not None else f0), p
            return f0, p
        f1 = self.pipe.get(i + 1)
        if f1 is None or f1 is f0:
            return f0, p
        xx, yy = self.ctx.xx, self.ctx.yy
        f01 = self.flow(i, i + 1, f0, f1)
        f10 = self.flow(i + 1, i, f1, f0)
        I0 = cv2.remap(f0, xx - a * f01[..., 0], yy - a * f01[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        I1 = cv2.remap(f1, xx - (1 - a) * f10[..., 0], yy - (1 - a) * f10[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return cv2.addWeighted(I0, 1 - a, I1, a, 0), p

    def render(self, t):
        if not self.loaded:
            self.load()
        W, H, FPS = self.ctx.W, self.ctx.H, self.ctx.FPS
        p = 0.0 if self.still is not None else (self.src_time(t) - self.ss) * FPS
        im, p = self.raw(max(0.0, p))
        dx = dy = da = 0.0
        if self.corr is not None and len(self.corr) > 1:
            i = min(int(p), len(self.corr) - 1)
            j = min(i + 1, len(self.corr) - 1)
            a = p - int(p)
            dx, dy, da = self.corr[i] * (1 - a) + self.corr[j] * a
        u = clamp01((t - self.a0) / max(1e-3, self.a1 - self.a0))
        z = self.zoom * (1 + (self.kb * u if self.kb > 0 else -self.kb * (1 - u)))
        M = cv2.getRotationMatrix2D((W / 2, H / 2), math.degrees(da), z)
        M[0, 2] += dx * z + self.ox
        M[1, 2] += dy * z + self.oy
        out = cv2.warpAffine(im, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        return grade(out, self.f, self.lut)


_dis = None


def DIS():
    global _dis
    if _dis is None:
        _dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    return _dis


def blit(frame, sp: Sprite, x, y, alpha=1.0, wipe=None, scale=1.0):
    if alpha <= 0.003:
        return
    H, W = frame.shape[:2]
    rgb, a = sp.rgb, sp.a
    if scale != 1.0:
        nw, nh = max(1, int(sp.w * scale)), max(1, int(sp.h * scale))
        rgb = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_LINEAR)
        a = cv2.resize(a, (nw, nh), interpolation=cv2.INTER_LINEAR)[..., None]
        x -= (nw - sp.w) / 2
        y -= (nh - sp.h) / 2
    x, y = int(round(x)), int(round(y))
    h, w = a.shape[:2]
    a = a * alpha
    if wipe is not None:
        ww = w * clamp01(wipe)
        a = a * np.clip((ww - np.arange(w)) / 40.0, 0, 1)[None, :, None]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 <= x0 or y1 <= y0:
        return
    sa = a[y0 - y:y1 - y, x0 - x:x1 - x]
    sr = rgb[y0 - y:y1 - y, x0 - x:x1 - x]
    reg = frame[y0:y1, x0:x1]
    reg *= 1 - sa
    reg += sr * sa


class TClip:
    def __init__(self, c, ctx: Ctx):
        self.c, self.ctx = c, ctx
        self.start, self.dur = float(c["start"]), float(c["duration"])
        self.end = self.start + self.dur
        self.preset = c.get("preset", "caption")
        self.els = None

    def load(self):
        self.els = [(Sprite(im), x, y, d, role) for im, x, y, d, role in layers(dict(self.c, _H=self.ctx.H), self.ctx.W)]

    def draw(self, f, t):
        if self.els is None:
            self.load()
        ctx, c, p = self.ctx, self.c, self.preset
        u = t - self.start
        tail = self.end - t
        bd = c.get("backdrop", True)
        if p == "subtitle":
            al = clamp01(u / 0.12) * clamp01(tail / 0.12)
            for sp, x, y, *_ in self.els:
                blit(f, sp, x, y + 8 * ctx.k * (1 - ease(u / 0.25)), al)
        elif p == "heading":
            inn = ease(u / 0.7)
            al = inn * clamp01(tail / 0.45)
            if bd:
                f *= 1 - 0.5 * al * ctx.HDRMASK
            for sp, x, y, *_ in self.els:
                blit(f, sp, x, y - 18 * ctx.k * (1 - inn), al, wipe=ease(u / 0.9) * 1.05)
        elif p == "word":
            al = ease(u / 0.18) * clamp01(tail / 0.15)
            sc = 1.10 - 0.10 * ease(u / 0.5) + 0.02 * u
            if bd:
                f *= 1 - 0.28 * al
            for sp, x, y, *_ in self.els:
                blit(f, sp, x, y, al, scale=sc)
        elif p == "title":
            out = clamp01(tail / 0.6) if self.end < ctx.total - 0.05 else 1.0
            line = next((e for e in self.els if e[4] == "line"), None)
            if bd:
                k = ease(u / 0.8) * out
                if k > 0.01:
                    yc = (line[2] if line else 833 * ctx.k) - 43 * ctx.k
                    m = ctx.tband(yc) * k
                    bl = cv2.GaussianBlur(f, (0, 0), 7)
                    f[:] = f * (1 - m) + bl * m
                    f *= 1 - 0.5 * m
            for sp, x, y, d, role in self.els:
                if role == "line":
                    lw = int(sp.w / 2 * ease((u - d) / 0.8))
                    if lw > 2 and out > 0:
                        cx, yy = int(x + sp.w / 2), int(y)
                        col = np.array(hex_rgba(c.get("accent") or "#d4b47a")[2::-1], np.float32) / 255
                        x0, x1 = max(0, cx - lw), min(ctx.W, cx + lw)
                        f[yy:yy + max(2, sp.h - 1), x0:x1] = f[yy:yy + max(2, sp.h - 1), x0:x1] * (1 - out) + col * out
                    continue
                al = ease((u - d) / 0.7) * out
                blit(f, sp, x, y + 22 * ctx.k * (1 - ease((u - d) / 0.9)), al)
        else:
            al = clamp01(u / 0.3) * clamp01(tail / 0.3)
            for sp, x, y, *_ in self.els:
                blit(f, sp, x, y + 12 * ctx.k * (1 - ease(u / 0.4)), al)
        return f


class Compositor:
    def __init__(self, proj, pdir, quality="high"):
        self.ctx = ctx = Ctx(proj, pdir)
        self.vclips = []
        for tr in tracks(proj, "video"):
            cl = sorted(tr["clips"], key=lambda c: c["start"])
            for i, c in enumerate(cl):
                self.vclips.append(VClip(c, ctx, cl[i + 1] if i + 1 < len(cl) else None, len(self.vclips), quality))
        self.tclips = [TClip(c, ctx) for tr in tracks(proj, "text") for c in sorted(tr["clips"], key=lambda c: c["start"])]

    def frame(self, t):
        ctx = self.ctx
        for v in self.vclips:
            if v.loaded and (t >= v.a1 + 0.05 or t < v.a0 - 0.5):
                v.free()
        for tc in self.tclips:
            if tc.els is not None and t >= tc.end + 0.05:
                tc.els = None
        act = [v for v in self.vclips if v.a0 <= t < v.a1]
        f = None
        if len(act) >= 2:
            a, b = act[-2], act[-1]
            if b.tr_type == "fade" and b.xin > 0:
                w = smooth((t - b.a0) / max(1e-3, a.a1 - b.a0))
                f = a.render(t) * (1 - w) + b.render(t) * w
            else:
                f = b.render(t)
        elif act:
            f = act[0].render(t)
        if f is None:
            f = np.zeros((ctx.H, ctx.W, 3), np.float32)
        # 黑场 / 白场 / 闪白
        for v in act:
            if v.tr_type in ("black", "white") and v.tr_d > 0:
                h = v.tr_d / 2
                k = clamp01((t - v.start) / h) if t >= v.start else 1.0
                if k < 1:
                    f = f * smooth(k) + (0 if v.tr_type == "black" else 1) * (1 - smooth(k))
            if v.tr_type == "flash" and v.start <= t < v.start + max(0.05, v.tr_d):
                f = f * (1 + 0.35 * (1 - (t - v.start) / max(0.05, v.tr_d)))
        # 下一段是黑/白场：本段尾部渐隐
        nxt = [v for v in self.vclips if v.tr_type in ("black", "white") and v.start - v.tr_d / 2 <= t < v.start]
        for v in nxt:
            k = clamp01((v.start - t) / (v.tr_d / 2))
            f = f * smooth(k) + (0 if v.tr_type == "black" else 1) * (1 - smooth(k))
        f = f * ctx.STATIC
        for tc in self.tclips:
            if tc.start <= t < tc.end:
                f = tc.draw(f, t)
        if ctx.fade_io:
            if t < 0.3:
                f = f * (t / 0.3)
            if t > ctx.total - 1.4:
                f = f * clamp01((ctx.total - t) / 1.4)
        return (np.clip(f, 0, 1) * 255 + 0.5).astype(np.uint8)


def x264_args(quality):
    if quality == "high":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "16"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def render_range(proj, pdir, n0, n1, out, quality, progress=None):
    comp = Compositor(proj, pdir, quality)
    ctx = comp.ctx
    p = subprocess.Popen([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{ctx.W}x{ctx.H}",
                          "-r", str(ctx.FPS), "-i", "-", *x264_args(quality), "-pix_fmt", "yuv420p",
                          "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                          str(out)], stdin=subprocess.PIPE, creationflags=NOWIN)
    for n in range(n0, n1):
        p.stdin.write(comp.frame(n / ctx.FPS).tobytes())
        if progress and (n - n0) % 10 == 0:
            progress(n - n0)
    p.stdin.close()
    p.wait()
    if p.returncode != 0:
        raise RuntimeError("视频编码失败")


def preview_frame(proj, pdir, t, quality="fast"):
    return Compositor(proj, pdir, quality).frame(t)


# --------------------------------------------------------------------------- 声音
SR = 48000


def _fit_len(x, n):
    if len(x) == n:
        return x
    if len(x) < 2:
        return np.zeros((n, 2))
    src = np.linspace(0, len(x) - 1, n)
    return np.stack([np.interp(src, np.arange(len(x)), x[:, c]) for c in range(2)], 1)


def mix_audio(proj, pdir, out_wav, total):
    ctx_dir = Path(pdir)
    assets = {a["id"]: a for a in proj["assets"]}
    N = int(total * SR) + 1

    def path(a, key="path"):
        p = Path(a[key])
        return p if p.is_absolute() else ctx_dir / p

    def place(buf, sig, t):
        i = int(round(t * SR))
        if i < 0:
            sig = sig[-i:]
            i = 0
        n = min(len(sig), N - i)
        if n > 0:
            buf[i:i + n] += sig[:n]

    def fades(x, fi, fo):
        n = len(x)
        if n == 0:
            return x
        e = np.ones(n)
        a, b = min(n, int(fi * SR)), min(n, int(fo * SR))
        if a > 0:
            e[:a] = np.linspace(0, 1, a)
        if b > 0:
            e[n - b:] *= np.linspace(1, 0, b)
        return x * e[:, None]

    buses = {"voice": np.zeros((N, 2)), "music": np.zeros((N, 2)), "sfx": np.zeros((N, 2)), "amb": np.zeros((N, 2))}
    duck_cfg = []
    for tr in tracks(proj, "audio"):
        if tr.get("muted"):
            continue
        role = tr.get("role", "sfx")
        for c in tr["clips"]:
            a = assets.get(c["assetId"])
            if not a or float(c.get("volume", 1)) <= 0:
                continue
            x = decode_audio(str(path(a)), SR, 2, float(c.get("in", 0)), float(c["duration"]))
            x = fades(x, float(c.get("fadeIn", 0.02)), float(c.get("fadeOut", 0.05))) * float(c.get("volume", 1))
            bus = role if role in buses else "sfx"
            if bus == "music" and c.get("duck", True):
                tmp = np.zeros((N, 2))
                place(tmp, x, c["start"])
                duck_cfg.append((tmp, float(c.get("duckAmount", 0.55))))
            else:
                place(buses[bus], x, c["start"])
    bh, ah = sg.butter(2, [140 / (SR / 2), 7000 / (SR / 2)], "band")
    for tr in tracks(proj, "video"):
        if tr.get("muted"):
            continue
        for c in tr["clips"]:
            a = assets.get(c["assetId"])
            vol = float(c.get("volume", 0))
            if not a or vol <= 0 or not a.get("hasAudio") or c.get("freeze"):
                continue
            x = decode_audio(str(path(a)), SR, 2, float(c["in"]), float(c["out"] - c["in"]))
            if len(x) < 100:
                continue
            x = _fit_len(x, int(c["duration"] * SR))
            if c.get("ambience", False):
                x = sg.lfilter(bh, ah, x, axis=0)
            place(buses["amb"], fades(x, 0.06, 0.06) * vol, c["start"])
    vo = buses["voice"]
    if duck_cfg:
        env = (np.abs(vo).max(1) > 0.01).astype(np.float64)
        from scipy.ndimage import uniform_filter1d
        env = np.clip(uniform_filter1d(env, int(0.35 * SR), mode="nearest") * 3, 0, 1)
        for m, amt in duck_cfg:
            buses["music"] += m * (1 - amt * env)[:, None]
    mix = sum(buses.values())
    if proj["settings"].get("look", {}).get("fadeInOut", True):
        n = min(N, int(1.2 * SR))
        mix[-n:] *= np.linspace(1, 0, n)[:, None] ** 1.5
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    wavfile.write(str(out_wav), SR, (mix * 32767).astype(np.int16))


# --------------------------------------------------------------------------- 导出
def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(proj, out):
    subs = sorted([c for tr in tracks(proj, "text") for c in tr["clips"] if c.get("preset") == "subtitle"], key=lambda c: c["start"])
    with open(out, "w", encoding="utf-8-sig") as f:
        for i, c in enumerate(subs, 1):
            body = c.get("text", "") + (("\n" + c["sub"]) if c.get("sub") else "")
            f.write(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['start'] + c['duration'])}\n{body}\n\n")
    return len(subs)


def export(job, proj, pdir, quality="high", workers=None):
    pdir = Path(pdir)
    total = timeline_end(proj)
    if total <= 0.1:
        raise RuntimeError("时间线是空的")
    fps = int(proj["settings"].get("fps", 30))
    nf = int(round(total * fps))
    work = pdir / "exports" / f"_work_{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)
    snap = work / "project.json"
    snap.write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
    workers = workers or max(1, min(4, (os.cpu_count() or 4) // 4, nf // (fps * 4) or 1))
    bounds = [round(nf * i / workers) for i in range(workers + 1)]
    procs = []
    for i in range(workers):
        seg = work / f"seg{i}.mp4"
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker", str(snap), str(pdir), str(bounds[i]),
                              str(bounds[i + 1]), str(seg), quality], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             creationflags=NOWIN, text=True, encoding="utf-8", errors="replace")
        procs.append((p, seg, bounds[i + 1] - bounds[i]))
    job.progress(0.02, f"渲染画面（{workers} 个进程并行）")
    done = [0] * workers
    import threading

    def reader(i, p):
        for line in p.stdout:
            if line.startswith("P "):
                done[i] = int(line.split()[1])

    ths = [threading.Thread(target=reader, args=(i, p), daemon=True) for i, (p, _, _) in enumerate(procs)]
    for t in ths:
        t.start()
    audio_done = {"ok": False, "err": None}

    def audio():
        try:
            mix_audio(proj, pdir, work / "mix.wav", total)
            audio_done["ok"] = True
        except Exception as e:  # noqa
            audio_done["err"] = e

    at = threading.Thread(target=audio, daemon=True)
    at.start()
    t0 = time.time()
    while any(p.poll() is None for p, _, _ in procs):
        if job.cancelled:
            for p, _, _ in procs:
                p.kill()
            raise RuntimeError("已取消")
        frac = sum(done) / nf
        el = time.time() - t0
        eta = f"，预计还需 {int(el / frac * (1 - frac))} 秒" if frac > 0.03 else ""
        job.progress(0.02 + 0.88 * frac, f"渲染画面 {sum(done)}/{nf} 帧{eta}")
        time.sleep(1.0)
    for p, seg, _ in procs:
        if p.returncode != 0:
            raise RuntimeError("渲染进程出错：" + (p.stderr.read() or "")[-1500:])
    if at.is_alive():
        job.progress(0.9, "混音中")
    at.join()
    if audio_done["err"]:
        raise audio_done["err"]
    job.progress(0.92, "合成音视频并统一响度")
    (work / "list.txt").write_text("".join(f"file '{seg.as_posix()}'\n" for _, seg, _ in procs), encoding="utf-8")
    name = "".join(ch for ch in proj["name"] if ch not in '\\/:*?"<>|').strip() or "video"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = pdir / "exports" / f"{name}_{stamp}.mp4"
    r = subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "list.txt"),
                        "-i", str(work / "mix.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-af", "alimiter=limit=0.6:level=false:attack=3:release=60,loudnorm=I=-14:TP=-1.5:LRA=9",
                        "-ar", "48000", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(out)],
                       capture_output=True, creationflags=NOWIN)
    if r.returncode != 0:
        raise RuntimeError("合成失败：" + r.stderr.decode("utf-8", "replace")[-800:])
    srt = out.with_suffix(".srt")
    write_srt(proj, srt)
    import shutil
    shutil.rmtree(work, ignore_errors=True)
    return {"file": f"exports/{out.name}", "srt": f"exports/{srt.name}", "duration": total, "seconds": round(time.time() - t0)}


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "worker":
    _, _, snap, pdir, n0, n1, out, quality = sys.argv
    proj = json.loads(Path(snap).read_text(encoding="utf-8"))
    cv2.setNumThreads(4)
    render_range(proj, pdir, int(n0), int(n1), out, quality, progress=lambda k: print(f"P {k}", flush=True))
    print(f"P {int(n1) - int(n0)}", flush=True)
