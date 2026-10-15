"""AI 视频剪辑 —— 本地后端（FastAPI）。启动：python app.py  然后打开 http://127.0.0.1:8765"""
import json
import shutil
import time
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import ai
import build as builder
import ingest
import jobs
import media
import render
import store
import textfx
import tts
from config import CLAUDE_MODEL, FRONTEND_DIST, MEDIA_EXT, PROJECTS_DIR, VOICES

app = FastAPI(title="AI 视频剪辑", version="1.0.0")


def P(pid):
    try:
        return store.load(pid)
    except FileNotFoundError:
        raise HTTPException(404, "项目不存在")


# --------------------------------------------------------------------------- 基础
@app.get("/api/config")
def config():
    return {"voices": VOICES, "model": CLAUDE_MODEL, "filters": render.FILTER_PRESETS,
            "mediaExt": {k: sorted(v) for k, v in MEDIA_EXT.items()}}


@app.get("/api/projects")
def projects():
    return store.list_projects()


@app.post("/api/projects")
def create_project(body: dict = Body(...)):
    return store.create(body.get("name") or "未命名项目", int(body.get("width", 1080)), int(body.get("height", 1920)), int(body.get("fps", 30)))


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return P(pid)


@app.patch("/api/projects/{pid}")
def patch_project(pid: str, body: dict = Body(...)):
    allowed = {"name", "settings", "brief", "script", "timeline"}

    def apply(p):
        for k, v in body.items():
            if k in allowed:
                p[k] = v
        return {"updatedAt": time.time()}
    P(pid)
    return store.mutate(pid, apply)


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    src = store.pdir(pid)
    if not (src / "project.json").exists():
        raise HTTPException(404)
    trash = PROJECTS_DIR / "_trash"
    trash.mkdir(exist_ok=True)
    shutil.move(str(src), str(trash / f"{pid}_{int(time.time())}"))
    return {"ok": True}


# --------------------------------------------------------------------------- 素材
def _start_processing(pid, aids):
    return jobs.start("ingest", pid, ingest.process_job, pid, aids)


@app.post("/api/projects/{pid}/upload")
async def upload(pid: str, files: list[UploadFile] = File(...)):
    P(pid)
    d = store.pdir(pid) / "media"
    d.mkdir(exist_ok=True)
    saved = []
    for f in files:
        name = Path(f.filename).name
        if not media.kind_of(name):
            continue
        dst = d / name
        k = 1
        while dst.exists():
            dst = d / f"{Path(name).stem}_{k}{Path(name).suffix}"
            k += 1
        with open(dst, "wb") as out:
            while chunk := await f.read(1 << 22):
                out.write(chunk)
        saved.append((dst, name))
    if not saved:
        raise HTTPException(400, "没有可导入的媒体文件")

    def apply(p):
        return [ingest.register(p, str(dst), name=name, rel=f"media/{dst.name}")["id"] for dst, name in saved]
    aids = store.mutate(pid, apply)
    return {"assetIds": aids, "job": _start_processing(pid, aids)}


@app.post("/api/projects/{pid}/import")
def import_paths(pid: str, body: dict = Body(...)):
    """从本机素材库导入（原地引用，不复制）。body: {paths: [...]} 或 {folder: "..."}"""
    P(pid)
    paths = list(body.get("paths") or [])
    if body.get("folder"):
        folder = Path(body["folder"].strip().strip('"'))
        if not folder.is_dir():
            raise HTTPException(400, f"文件夹不存在：{folder}")
        it = folder.rglob("*") if body.get("recursive") else folder.iterdir()
        paths += sorted(str(x) for x in it if x.is_file() and media.kind_of(str(x)))
    paths = [p for p in paths if Path(p).is_file() and media.kind_of(p)]
    if not paths:
        raise HTTPException(400, "没有找到可导入的视频/音频/图片")

    def apply(p):
        have = {a["path"] for a in p["assets"]}
        out = []
        for x in paths:
            norm = str(Path(x).resolve()).replace("\\", "/")
            if norm in have:
                continue
            out.append(ingest.register(p, x)["id"])
        return out
    aids = store.mutate(pid, apply)
    return {"assetIds": aids, "job": _start_processing(pid, aids) if aids else None}


@app.get("/api/browse")
def browse(path: str = ""):
    """简单的本机目录浏览，用来选择素材库文件夹。"""
    if not path:
        import string
        drives = [f"{c}:/" for c in string.ascii_uppercase if Path(f"{c}:/").exists()]
        return {"path": "", "dirs": drives, "files": []}
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(400, "不是文件夹")
    dirs, files = [], []
    try:
        for x in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if x.name.startswith(("$", ".")):
                continue
            if x.is_dir():
                dirs.append(x.name)
            elif media.kind_of(x.name):
                files.append({"name": x.name, "size": x.stat().st_size, "kind": media.kind_of(x.name)})
    except PermissionError:
        pass
    return {"path": str(p).replace("\\", "/"), "parent": str(p.parent).replace("\\", "/") if p.parent != p else "", "dirs": dirs, "files": files}


@app.delete("/api/projects/{pid}/assets/{aid}")
def delete_asset(pid: str, aid: str):
    def apply(p):
        used = any(c.get("assetId") == aid for t in p["timeline"]["tracks"] for c in t["clips"])
        if used:
            raise HTTPException(400, "该素材正在时间线上使用，先删除对应片段")
        p["assets"] = [a for a in p["assets"] if a["id"] != aid]
    store.mutate(pid, apply)
    return {"ok": True}


@app.post("/api/projects/{pid}/assets/{aid}/reprocess")
def reprocess(pid: str, aid: str):
    return _start_processing(pid, [aid])


@app.get("/api/projects/{pid}/assets/{aid}/{which}")
def asset_file(pid: str, aid: str, which: str):
    p = P(pid)
    a = store.asset(p, aid)
    if not a or which not in ("proxy", "thumb", "strip", "peaks", "sheet", "path"):
        raise HTTPException(404)
    rel = a.get(which)
    if not rel:
        raise HTTPException(404)
    f = ingest.abspath(pid, rel)
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "no-cache"})


@app.get("/api/projects/{pid}/files/{path:path}")
def project_file(pid: str, path: str, download: int = 0):
    base = store.pdir(pid).resolve()
    f = (base / path).resolve()
    if not f.is_relative_to(base) or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, filename=f.name if download else None)


# --------------------------------------------------------------------------- AI
def _analyze_job(job, pid, aids, force):
    proj = store.load(pid)
    todo = [a for a in proj["assets"] if a["kind"] in ("video", "image") and a.get("origin", "import") == "import"
            and a.get("status") == "ready" and (not aids or a["id"] in aids) and (force or not a.get("analysis"))]
    if not todo:
        return {"count": 0}
    job.progress(0.05, f"{CLAUDE_MODEL} 正在看 {len(todo)} 段素材")
    res = ai.analyze_assets(todo, proj["brief"], lambda a: ingest.abspath(pid, a["sheet"]), job)

    def apply(p):
        for a in p["assets"]:
            if a["id"] in res:
                r = dict(res[a["id"]])
                r.pop("id", None)
                for s in r.get("segments", []):
                    s["start"] = round(max(0, min(a["duration"], s["start"])), 2)
                    s["end"] = round(max(s["start"], min(a["duration"], s["end"])), 2)
                a["analysis"] = r
    store.mutate(pid, apply)
    return {"count": len(res)}


@app.post("/api/projects/{pid}/analyze")
def analyze(pid: str, body: dict = Body(default={})):
    P(pid)
    return jobs.start("analyze", pid, _analyze_job, pid, body.get("assetIds"), bool(body.get("force")))


def _sanitize_script(proj, sc):
    assets = {a["id"]: a for a in proj["assets"]}
    for i, s in enumerate(sc.get("sections", [])):
        s["id"] = f"s{i}"
        s.setdefault("lines", [])
        good = []
        for x in s.get("shots", []):
            a = assets.get(x.get("assetId"))
            if not a:
                continue
            dur = float(a.get("duration") or 0)
            x["in"] = round(max(0.0, min(dur - 0.3, float(x.get("in", 0)))), 2)
            x["out"] = round(max(x["in"] + 0.3, min(dur, float(x.get("out", dur)))), 2)
            x["duration"] = round(max(0.6, float(x.get("duration", x["out"] - x["in"]))), 2)
            good.append(x)
        s["shots"] = good
    return sc


def _script_job(job, pid, feedback):
    proj = store.load(pid)
    if not any(a.get("analysis") for a in proj["assets"]):
        job.progress(0.05, "素材还没分析，先分析素材")
        _analyze_job(job, pid, None, False)
        proj = store.load(pid)
    job.progress(0.5 if feedback is None else 0.2, f"{CLAUDE_MODEL} 正在写剪辑脚本")
    sc = _sanitize_script(proj, ai.generate_script(proj, feedback))

    def apply(p):
        old = p.get("script")
        hist = (old or {}).get("history", [])
        if old:
            hist = (hist + [{k: v for k, v in old.items() if k != "history"}])[-8:]
        sc["history"] = hist
        sc["version"] = ((old or {}).get("version") or 0) + 1
        sc["status"] = "draft"
        sc["feedback"] = feedback or ""
        p["script"] = sc
    store.mutate(pid, apply)
    return {"sections": len(sc["sections"])}


@app.post("/api/projects/{pid}/script")
def make_script(pid: str, body: dict = Body(default={})):
    P(pid)
    return jobs.start("script", pid, _script_job, pid, body.get("feedback"))


@app.post("/api/projects/{pid}/build")
def build_timeline(pid: str):
    P(pid)
    return jobs.start("build", pid, builder.build, pid)


@app.post("/api/projects/{pid}/tts")
def make_tts(pid: str, body: dict = Body(...)):
    """编辑器里改了台词后重新配音。body: {lines:[{zh,en}], voice?, rate?}"""
    proj = P(pid)
    voice = body.get("voice") or proj["brief"].get("voice", "zh-CN-YunyangNeural")
    rate = body.get("rate") or proj["brief"].get("voiceRate", "-4%")
    lines = body["lines"]
    rel = f"audio/vo_{int(time.time() * 1000)}.mp3"
    r = tts.synthesize([builder.speech_text(l, voice) for l in lines], voice, rate, str(store.pdir(pid) / rel))

    def apply(p):
        a = builder.new_audio_asset(p, pid, rel, "tts", body.get("name") or "配音",
                                    {"lines": lines, "spans": r["spans"], "voice": voice, "rate": rate})
        a["suggestedVolume"] = builder.gain_to(builder.active_rms_db(str(store.pdir(pid) / rel)), -19, 4.0)
        return a
    return store.mutate(pid, apply)


@app.post("/api/projects/{pid}/music")
def make_music(pid: str, body: dict = Body(default={})):
    proj = P(pid)
    total = float(body.get("duration") or render.timeline_end(proj) or 60)
    rel = f"audio/bgm_{int(time.time())}.wav"
    import music
    music.synth_bgm(str(store.pdir(pid) / rel), total, float(body.get("bpm", 100)), mood=body.get("mood", "inspiring"))

    def apply(p):
        a = builder.new_audio_asset(p, pid, rel, "music", "AI 合成 BGM")
        a["suggestedVolume"] = builder.gain_to(a["audio"]["rmsDb"], -23, 4.0)
        return a
    return store.mutate(pid, apply)


# --------------------------------------------------------------------------- 预览 / 导出
@app.post("/api/text/render")
def text_render(body: dict = Body(...)):
    png = textfx.render_png(body["clip"], int(body.get("width", 1080)), int(body.get("height", 1920)))
    return Response(png, media_type="image/png", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/projects/{pid}/frame")
def frame(pid: str, body: dict = Body(...)):
    import cv2
    proj = P(pid)
    if body.get("timeline"):
        proj["timeline"] = body["timeline"]
    im = render.preview_frame(proj, store.pdir(pid), float(body.get("t", 0)), body.get("quality", "fast"))
    ok, jpg = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return Response(jpg.tobytes(), media_type="image/jpeg")


@app.post("/api/projects/{pid}/export")
def export(pid: str, body: dict = Body(default={})):
    proj = P(pid)
    return jobs.start("export", pid, render.export, proj, store.pdir(pid), body.get("quality", "high"))


@app.get("/api/projects/{pid}/exports")
def exports(pid: str):
    d = store.pdir(pid) / "exports"
    out = []
    for f in sorted(d.glob("*.mp4"), key=lambda f: -f.stat().st_mtime):
        srt = f.with_suffix(".srt")
        out.append({"name": f.name, "file": f"exports/{f.name}", "size": f.stat().st_size, "time": f.stat().st_mtime,
                    "srt": f"exports/{srt.name}" if srt.exists() else None, "abs": str(f).replace("\\", "/")})
    return out


@app.post("/api/projects/{pid}/reveal")
def reveal(pid: str, body: dict = Body(default={})):
    import subprocess
    base = store.pdir(pid).resolve()
    f = (base / body.get("path", "exports")).resolve()
    if not f.is_relative_to(base):
        raise HTTPException(400)
    if f.is_file():
        subprocess.Popen(["explorer", "/select,", str(f)])
    else:
        subprocess.Popen(["explorer", str(f)])
    return {"ok": True}


# --------------------------------------------------------------------------- 任务
@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404)
    return {k: v for k, v in j.items() if k != "result" or j["status"] == "done"}


@app.get("/api/projects/{pid}/jobs")
def project_jobs(pid: str):
    return jobs.for_project(pid)


@app.post("/api/jobs/{jid}/cancel")
def cancel(jid: str):
    return jobs.cancel(jid)


@app.exception_handler(RuntimeError)
def rt_err(_, e):
    return JSONResponse({"detail": str(e)}, status_code=500)


# --------------------------------------------------------------------------- 前端
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="static")

    @app.get("/{full:path}")
    def spa(full: str):
        f = FRONTEND_DIST / full
        if full and f.is_file() and f.resolve().is_relative_to(FRONTEND_DIST.resolve()):
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
