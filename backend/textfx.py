"""文字图层：字幕 / 段落标题 / 关键词大字 / 标题卡 / 自由文字。
预览（前端请求 PNG）和最终渲染共用这里的排版，保证所见即所得。坐标以 1080 宽为基准，按画幅宽度缩放。"""
import io

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config import FONT_DIR, FONTS, FONT_FALLBACK

_fc = {}


def _load(key, size):
    k = (key, size)
    if k not in _fc:
        try:
            _fc[k] = ImageFont.truetype(str(FONT_DIR / FONTS.get(key, key)), size)
        except Exception:
            _fc[k] = ImageFont.truetype(str(FONT_DIR / FONT_FALLBACK), size)
    return _fc[k]


def is_cjk(ch):
    o = ord(ch)
    return 0x2E80 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF or 0x3000 <= o <= 0x303F


class MixFont:
    """英文字体 + 中文回退（英文字体里没有中文字形）。"""

    def __init__(self, key, size):
        self.size = size
        self.en = _load(key, size)
        self.zh = _load("zh_bold" if "bold" in key else "zh_medium", int(round(size * 0.94)))

    def pick(self, ch):
        return self.zh if is_cjk(ch) else self.en

    def getlength(self, t):
        return sum(self.pick(c).getlength(c) for c in t)


def font(key, size):
    size = max(8, int(round(size)))
    if key.startswith("en_"):
        return MixFont(key, size)
    return _load(key, size)


def hex_rgba(h, a=255):
    h = (h or "#ffffff").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a)


def text_w(t, f, tr=0):
    if tr == 0 and not isinstance(f, MixFont):
        return f.getlength(t)
    return sum(f.getlength(c) for c in t) + tr * (len(t) - 1)


def draw_text(d, x, y, t, f, fill, tr=0):
    if isinstance(f, MixFont):
        for c in t:
            ff = f.pick(c)
            d.text((x, y + (f.size * 0.04 if ff is f.zh else 0)), c, font=ff, fill=fill)
            x += ff.getlength(c) + tr
        return
    if tr == 0:
        d.text((x, y), t, font=f, fill=fill)
        return
    for c in t:
        d.text((x, y), c, font=f, fill=fill)
        x += f.getlength(c) + tr


def fit_font(key, size, text, maxw, tr=0):
    while size > 18 and text_w(text, font(key, size), tr) > maxw:
        size -= 1
    return font(key, size)


def canvas(w, h):
    im = Image.new("RGBA", (max(1, int(w)), max(1, int(h))), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def with_shadow(img, shadow=0.55, blur=7, dy=3):
    if not shadow:
        return img
    a = img.split()[3].filter(ImageFilter.GaussianBlur(blur))
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh.putalpha(a.point(lambda v: int(v * shadow)))
    base = Image.new("RGBA", img.size, (0, 0, 0, 0))
    base.alpha_composite(sh, (0, dy))
    base.alpha_composite(img)
    return base


class Sprite:
    def __init__(self, img: Image.Image):
        arr = np.asarray(img.convert("RGBA")).astype(np.float32) / 255
        self.img = img
        self.rgb = arr[..., 2::-1].copy()  # BGR
        self.a = arr[..., 3:4].copy()
        self.h, self.w = self.a.shape[:2]


# --------------------------------------------------------------------------- 预设
DEFAULTS = {
    "subtitle": {"color": "#ffffff", "accent": "#ece4d4"},
    "heading": {"color": "#ffffff", "accent": "#d4b47a"},
    "word": {"color": "#ffffff", "accent": "#d4b47a"},
    "title": {"color": "#ffffff", "accent": "#d4b47a"},
    "caption": {"color": "#ffffff", "accent": "#d4b47a"},
}


def layers(clip: dict, W: int):
    """返回 [(PIL 图像, x, y, 入场延迟秒, 角色)]，坐标为画面像素（左上角）。"""
    s = W / 1080 * float(clip.get("scale", 1.0) or 1.0)
    k = W / 1080
    p = clip.get("preset", "caption")
    col = clip.get("color") or DEFAULTS.get(p, {}).get("color", "#ffffff")
    acc = clip.get("accent") or DEFAULTS.get(p, {}).get("accent", "#d4b47a")
    dx, dy = float(clip.get("dx", 0)) * k, float(clip.get("dy", 0)) * k
    text, sub = clip.get("text", "") or "", clip.get("sub", "") or ""
    out = []
    if p == "subtitle":
        fz = fit_font("zh_medium", 50 * s, text, 960 * k)
        fe = fit_font("en_semilight", 32 * s, sub, 980 * k)
        wz, we = text_w(text, fz), text_w(sub, fe)
        cw = int(max(wz, we) + 40 * s)
        im, d = canvas(cw, 130 * s)
        draw_text(d, (cw - wz) / 2, 6 * s, text, fz, hex_rgba(col))
        if sub:
            draw_text(d, (cw - we) / 2, 76 * s, sub, fe, hex_rgba(acc, 235))
        im = with_shadow(im, 0.85, 6 * s)
        out.append((im, (W - im.width) / 2 + dx, 1560 * k + dy, 0, "main"))
    elif p == "heading":
        num = clip.get("num", "") or ""
        fn, fz, fe = font("en_light", 104 * s), font("zh_bold", 62 * s), font("en_semibold", 24 * s)
        nw = text_w(num, fn) if num else -34 * s
        x2 = nw + 34 * s
        w = x2 + max(text_w(text, fz), text_w(sub, fe, 5 * s)) + 30 * s
        im, d = canvas(w, 150 * s)
        if num:
            draw_text(d, 0, -8 * s, num, fn, hex_rgba(acc))
            d.rectangle([nw + 16 * s, 22 * s, nw + 18 * s, 128 * s], fill=hex_rgba(acc))
        draw_text(d, x2, 14 * s, text, fz, hex_rgba(col))
        draw_text(d, x2 + 2 * s, 100 * s, sub, fe, hex_rgba(col, 205), 5 * s)
        out.append((with_shadow(im, 0.85, 10 * s), 72 * k + dx, 240 * k + dy, 0, "main"))
    elif p == "word":
        fz, fe = font("serif", 210 * s), font("en_semibold", 34 * s)
        wz, we = text_w(text, fz, 30 * s), text_w(sub, fe, 14 * s)
        cw = int(max(wz, we) + 60 * s)
        im, d = canvas(cw, 360 * s)
        draw_text(d, (cw - wz) / 2, 10 * s, text, fz, hex_rgba(col), 30 * s)
        lw = 70 * s
        d.rectangle([(cw - lw) / 2, 278 * s, (cw + lw) / 2, 281 * s], fill=hex_rgba(acc))
        if sub:
            draw_text(d, (cw - we) / 2, 300 * s, sub, fe, hex_rgba(col, 230), 14 * s)
        im = with_shadow(im, 0.6, 12 * s)
        out.append((im, (W - im.width) / 2 + dx, 760 * k + dy, 0, "main"))
    elif p == "title":
        cy = 833 * k + dy  # 金线位置
        kicker, extra = clip.get("kicker", "") or "", clip.get("extra", "") or ""

        def line(t, f, fill, tr, sh, bl, y, delay, role):
            im, d = canvas(text_w(t, f, tr) + 20 * s, f.size * 1.5)
            draw_text(d, 0, 2 * s, t, f, fill, tr)
            im = with_shadow(im, sh, bl)
            out.append((im, (W - im.width) / 2 + dx, y, delay, role))

        if kicker:
            line(kicker, font("en_semibold", 26 * s), hex_rgba(acc), 10 * s, 0.5, 6 * s, cy - 233 * s, 0.0, "kicker")
        if text:
            f2 = fit_font("serif", 115 * s, text, 1000 * k, 8 * s)
            line(text, f2, hex_rgba(col), 8 * s, 0.65, 12 * s, cy - 183 * s, 0.25, "text")
        if sub:
            f3 = fit_font("en_semibold", 30 * s, sub, 1000 * k, 7 * s)
            line(sub, f3, hex_rgba(col, 235), 7 * s, 0.6, 8 * s, cy + 17 * s, 0.7, "sub")
        for i, ex in enumerate([e for e in extra.split("\n") if e.strip()]):
            if i == 0:
                f4 = fit_font("zh_medium", 41 * s, ex, 1000 * k, 5 * s)
                line(ex, f4, hex_rgba("#ece4d4", 245), 5 * s, 0.6, 8 * s, cy + 97 * s, 1.1, "extra")
            else:
                f5 = fit_font("en_semilight", 28 * s, ex, 1000 * k, 1 * s)
                line(ex, f5, hex_rgba("#dcd6c8", 225), 1 * s, 0.5, 8 * s, cy + 97 * s + (i * 78 + 8) * s, 1.1 + 0.2 * i, "extra")
        lw = 145 * s
        im, d = canvas(2 * lw, 3 * s + 1)
        d.rectangle([0, 0, 2 * lw, 3 * s], fill=hex_rgba(acc))
        out.append((im, W / 2 - lw + dx, cy, 0.5, "line"))
    else:  # caption 自由文字
        size = float(clip.get("fontSize", 64)) * s
        fk = clip.get("font", "zh_bold")
        lines = [l for l in text.split("\n")] or [""]
        f = font(fk, size)
        lh = size * 1.35
        wmax = max(text_w(l, f) for l in lines) if lines else 10
        pad = 24 * s
        im, d = canvas(wmax + 2 * pad, lh * len(lines) + 2 * pad)
        if clip.get("box"):
            d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=16 * s, fill=hex_rgba(clip.get("boxColor", "#000000"), 150))
        for i, l in enumerate(lines):
            draw_text(d, (im.width - text_w(l, f)) / 2, pad + i * lh, l, f, hex_rgba(col))
        im = with_shadow(im, 0.7, 8 * s)
        cx = float(clip.get("x", 0.5)) * W
        cy = float(clip.get("y", 0.5)) * clip.get("_H", W * 16 / 9)
        out.append((im, cx - im.width / 2 + dx, cy - im.height / 2, 0, "main"))
    return out


def render_png(clip: dict, W: int, H: int) -> bytes:
    """整帧透明 PNG（预览用，位置精确）。"""
    clip = dict(clip, _H=H)
    full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for im, x, y, _, _ in layers(clip, W):
        x, y = int(round(x)), int(round(y))
        cx, cy = max(0, -x), max(0, -y)
        if cx >= im.width or cy >= im.height:
            continue
        full.alpha_composite(im.crop((cx, cy, im.width, im.height)), (x + cx, y + cy))
    bio = io.BytesIO()
    full.save(bio, "PNG", optimize=False, compress_level=3)
    return bio.getvalue()
