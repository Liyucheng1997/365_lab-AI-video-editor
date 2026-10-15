"""媒体处理：探测、HDR→SDR 预览代理、缩略图/胶片条、AI 帧拼图、抖动与音量分析、波形。"""
import json
import math
import re
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import FFMPEG, MEDIA_EXT, FONT_DIR, FONTS

NOWIN = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
TONEMAP = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"


def run(args, **kw):
    return subprocess.run([FFMPEG, "-hide_banner", *args], capture_output=True, creationflags=NOWIN, **kw)


def kind_of(path: str):
    ext = Path(path).suffix.lower()
    for k, s in MEDIA_EXT.items():
        if ext in s:
            return k
    return None


def probe(path: str) -> dict:
    """解析 ffmpeg -i 输出（环境里不一定有 ffprobe）。宽高为旋转后的显示尺寸。"""
    err = run(["-i", path]).stderr.decode("utf-8", "replace")
    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 30.0, "hasAudio": False, "hasVideo": False, "hdr": False, "rotation": 0}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    for line in err.splitlines():
        if "Stream #" in line and "Video:" in line and not info["hasVideo"]:
            if "attached pic" in line:
                continue
            info["hasVideo"] = True
            m = re.search(r", (\d{2,5})x(\d{2,5})", line)
            if m:
                info["width"], info["height"] = int(m[1]), int(m[2])
            m = re.search(r"([\d.]+) fps", line)
            if m:
                info["fps"] = float(m[1])
            if "arib-std-b67" in line or "smpte2084" in line:
                info["hdr"] = True
            info["codec"] = line.split("Video:")[1].strip().split(" ")[0]
        elif "Stream #" in line and "Audio:" in line:
            info["hasAudio"] = True
        m = re.search(r"rotation of (-?[\d.]+) degrees", line)
        if m:
            info["rotation"] = float(m[1])
    if abs(info["rotation"]) % 180 == 90:
        info["width"], info["height"] = info["height"], info["width"]
    return info


def _scale_expr(longest):
    return f"scale='if(gt(iw,ih),{longest},-2)':'if(gt(iw,ih),-2,{longest})'"


def make_proxy(src: str, dst: str, hdr: bool, longest=960):
    vf = _scale_expr(longest) + ":flags=bicubic"
    if hdr:
        vf += "," + TONEMAP
    else:
        vf += ",format=yuv420p"
    vf += ",fps=30"
    r = run(["-v", "error", "-y", "-i", src, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-g", "15", "-c:a", "aac", "-b:a", "128k", "-ac", "2", "-movflags", "+faststart", dst])
    if r.returncode != 0:
        raise RuntimeError("生成预览代理失败: " + r.stderr.decode("utf-8", "replace")[-400:])


def read_frames_at(video: str, times, size=None):
    cap = cv2.VideoCapture(video)
    out = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0, t) * 1000)
        ok, im = cap.read()
        if not ok:
            out.append(None)
            continue
        if size:
            im = cv2.resize(im, size, interpolation=cv2.INTER_AREA)
        out.append(im)
    cap.release()
    return out


def make_thumbs(proxy: str, duration: float, thumb: str, strip: str):
    """封面图 + 胶片条（时间线上显示）。返回胶片条参数。"""
    cap = cv2.VideoCapture(proxy)
    w, h = int(cap.get(3)), int(cap.get(4))
    cap.release()
    th = 96
    tw = max(1, int(round(w * th / h)))
    n = int(min(60, max(1, math.ceil(duration / 1.0))))
    step = duration / n
    frames = read_frames_at(proxy, [min(duration - 0.05, (i + 0.5) * step) for i in range(n)], (tw, th))
    last = None
    tiles = []
    for f in frames:
        if f is None:
            f = last if last is not None else np.zeros((th, tw, 3), np.uint8)
        tiles.append(f)
        last = f
    cv2.imwrite(strip, np.hstack(tiles), [cv2.IMWRITE_JPEG_QUALITY, 80])
    mid = read_frames_at(proxy, [min(duration * 0.4, max(0, duration - 0.1))])[0]
    if mid is None:
        mid = tiles[0]
    s = 320 / max(mid.shape[:2])
    cv2.imwrite(thumb, cv2.resize(mid, (int(mid.shape[1] * s), int(mid.shape[0] * s)), interpolation=cv2.INTER_AREA),
                [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {"tileW": tw, "tileH": th, "count": n, "step": step}


def _font(size):
    for name in (FONTS["zh_medium"], "msyh.ttc", "arial.ttf"):
        try:
            return ImageFont.truetype(str(FONT_DIR / name), size)
        except Exception:
            continue
    return ImageFont.load_default()


def contact_sheet(proxy: str, duration: float, dst: str, n=8, label=""):
    """给 AI 看的帧拼图：n 帧均匀采样，带时间戳。返回采样时间。"""
    times = [round(duration * (i + 0.5) / n, 2) for i in range(n)]
    frames = read_frames_at(proxy, times)
    ok = [f for f in frames if f is not None]
    if not ok:
        raise RuntimeError("无法读取视频帧")
    h0, w0 = ok[0].shape[:2]
    s = 300 / max(h0, w0)
    tw, th = int(w0 * s), int(h0 * s)
    cols = 4
    rows = math.ceil(n / cols)
    head = 34
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 6, head + rows * (th + 6) + 6), (24, 24, 24))
    d = ImageDraw.Draw(sheet)
    d.text((8, 6), label, font=_font(20), fill=(255, 220, 140))
    f = _font(18)
    for i, (t, fr) in enumerate(zip(times, frames)):
        if fr is None:
            continue
        im = Image.fromarray(cv2.cvtColor(cv2.resize(fr, (tw, th), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB))
        x = 6 + (i % cols) * (tw + 6)
        y = head + (i // cols) * (th + 6)
        sheet.paste(im, (x, y))
        tag = f"{t:.1f}s"
        d.rectangle([x, y, x + 12 + f.getlength(tag), y + 26], fill=(0, 0, 0))
        d.text((x + 6, y + 2), tag, font=f, fill=(255, 255, 255))
    sheet.save(dst, quality=85)
    return times


def motion_stats(proxy: str):
    """手持抖动（高频残差）与运镜速度（平滑轨迹速度），单位：1080 宽画面下的像素。"""
    cap = cv2.VideoCapture(proxy)
    w = int(cap.get(3))
    k = 1080 / max(1, w) * 2
    prev = None
    tr = []
    while True:
        ok, im = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(im, (im.shape[1] // 2, im.shape[0] // 2)), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            m = None
            p0 = cv2.goodFeaturesToTrack(prev, 200, 0.01, 6)
            if p0 is not None and len(p0) > 10:
                p1, st, _ = cv2.calcOpticalFlowPyrLK(prev, g, p0, None)
                if st is not None and st.sum() > 6:
                    m, _ = cv2.estimateAffinePartial2D(p0[st == 1], p1[st == 1])
            tr.append([m[0, 2] * k, m[1, 2] * k] if m is not None else [0, 0])
        prev = g
    cap.release()
    if len(tr) < 5:
        return {"jitter": 0.0, "pan": 0.0}
    from scipy.ndimage import gaussian_filter1d
    traj = np.cumsum(np.array(tr), 0)
    sm = np.stack([gaussian_filter1d(traj[:, i], 8, mode="nearest") for i in range(2)], 1)
    jit = float(np.sqrt(((traj - sm) ** 2).sum(1)).mean())
    vel = np.linalg.norm(np.diff(sm, axis=0), axis=1)
    return {"jitter": round(jit, 2), "pan": round(float(vel.mean()), 2)}


def decode_audio(path: str, sr=48000, ch=2, start=None, dur=None):
    args = ["-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", path]
    if dur is not None:
        args += ["-t", f"{dur:.3f}"]
    args += ["-vn", "-f", "f32le", "-ac", str(ch), "-ar", str(sr), "-"]
    raw = run(args).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch).astype(np.float64)


def audio_stats(path: str, peaks_dst: str):
    x = decode_audio(path, 16000, 1)[:, 0]
    if len(x) == 0:
        return None
    rms = float(np.sqrt(np.mean(x ** 2) + 1e-12))
    hop = 16000 // 50  # 50 peaks / 秒
    n = len(x) // hop
    pk = np.abs(x[: n * hop]).reshape(n, hop).max(1) if n else np.zeros(0)
    top = max(1e-6, float(np.percentile(pk, 99.5))) if n else 1
    Path(peaks_dst).write_text(json.dumps({"rate": 50, "peaks": [round(min(1.0, v / top), 3) for v in pk]}))
    return {"rmsDb": round(20 * math.log10(rms), 1), "peakDb": round(20 * math.log10(float(np.abs(x).max()) + 1e-12), 1)}


def audio_duration(path: str) -> float:
    return probe(path)["duration"]
