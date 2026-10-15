"""素材导入与预处理：登记 → 探测 → 预览代理 → 缩略图/胶片条 → 波形 → 抖动分析 → AI 帧拼图。"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import media
import store


def register(proj, path: str, origin="import", name=None, rel=None) -> dict:
    kind = media.kind_of(path)
    if not kind:
        raise ValueError(f"不支持的文件类型：{path}")
    ids = {a["id"] for a in proj["assets"]}
    n = len(proj["assets"]) + 1
    while f"a{n:02d}" in ids:
        n += 1
    a = {"id": f"a{n:02d}", "name": name or Path(path).name, "path": rel or str(Path(path).resolve()).replace("\\", "/"),
         "kind": kind, "origin": origin, "status": "pending", "duration": 0, "width": 0, "height": 0}
    proj["assets"].append(a)
    return a


def abspath(pid, p):
    p = Path(p)
    return p if p.is_absolute() else store.pdir(pid) / p


def process(pid: str, aid: str, sheets=True):
    proj = store.load(pid)
    a = store.asset(proj, aid)
    src = str(abspath(pid, a["path"]))
    d = store.pdir(pid)
    upd = {"status": "ready"}
    try:
        info = media.probe(src)
        upd.update({k: info[k] for k in ("duration", "width", "height", "fps", "hasAudio", "hdr", "rotation")})
        if a["kind"] == "video":
            if not info["hasVideo"]:
                raise RuntimeError("文件里没有视频流")
            proxy = f"cache/{aid}_proxy.mp4"
            media.make_proxy(src, str(d / proxy), info["hdr"])
            upd["proxy"] = proxy
            fs = media.make_thumbs(str(d / proxy), info["duration"], str(d / f"cache/{aid}_thumb.jpg"), str(d / f"cache/{aid}_strip.jpg"))
            upd.update({"thumb": f"cache/{aid}_thumb.jpg", "strip": f"cache/{aid}_strip.jpg", "stripInfo": fs})
            if sheets:
                media.contact_sheet(str(d / proxy), info["duration"], str(d / f"cache/{aid}_sheet.jpg"),
                                    label=f"{aid}  {a['name']}  {info['duration']:.1f}s")
                upd["sheet"] = f"cache/{aid}_sheet.jpg"
            upd["motion"] = media.motion_stats(str(d / proxy))
            if info["hasAudio"]:
                upd["audio"] = media.audio_stats(src, str(d / f"cache/{aid}_peaks.json"))
                upd["peaks"] = f"cache/{aid}_peaks.json"
        elif a["kind"] == "audio":
            upd["proxy"] = a["path"]
            upd["audio"] = media.audio_stats(src, str(d / f"cache/{aid}_peaks.json"))
            upd["peaks"] = f"cache/{aid}_peaks.json"
            upd["hasAudio"] = True
        elif a["kind"] == "image":
            import cv2
            import numpy as np
            im = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                raise RuntimeError("图片无法读取")
            upd.update({"width": im.shape[1], "height": im.shape[0], "duration": 5.0, "hasAudio": False})
            s = 960 / max(im.shape[:2])
            pr = cv2.resize(im, (int(im.shape[1] * s), int(im.shape[0] * s)), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(d / f"cache/{aid}_proxy.jpg"), pr, [cv2.IMWRITE_JPEG_QUALITY, 88])
            s2 = 320 / max(im.shape[:2])
            cv2.imwrite(str(d / f"cache/{aid}_thumb.jpg"), cv2.resize(im, (int(im.shape[1] * s2), int(im.shape[0] * s2))))
            upd.update({"proxy": f"cache/{aid}_proxy.jpg", "thumb": f"cache/{aid}_thumb.jpg", "strip": f"cache/{aid}_thumb.jpg",
                        "sheet": f"cache/{aid}_proxy.jpg"})
    except Exception as e:
        upd = {"status": "error", "error": str(e)[:300]}

    def apply(p):
        x = store.asset(p, aid)
        if x:
            x.update(upd)
    store.mutate(pid, apply)
    return upd


def process_job(job, pid, aids, workers=4):
    n = len(aids)
    if not n:
        return {"count": 0}
    done = {"n": 0}

    def one(aid):
        r = process(pid, aid)
        done["n"] += 1
        job.progress(done["n"] / n, f"已处理 {done['n']}/{n} 个素材")
        return r

    with ThreadPoolExecutor(workers) as ex:
        res = list(ex.map(one, aids))
    errs = sum(1 for r in res if r.get("status") == "error")
    return {"count": n, "errors": errs}
