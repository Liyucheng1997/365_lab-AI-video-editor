"""项目存储：每个项目一个文件夹 projects/<id>/，里面 project.json + media/ + cache/ + audio/ + exports/"""
import json
import threading
import time
import uuid
from pathlib import Path

from config import PROJECTS_DIR

_locks: dict[str, threading.RLock] = {}
_glock = threading.Lock()


def lock(pid: str) -> threading.RLock:
    with _glock:
        if pid not in _locks:
            _locks[pid] = threading.RLock()
        return _locks[pid]


def pdir(pid: str) -> Path:
    p = PROJECTS_DIR / pid
    if not p.resolve().is_relative_to(PROJECTS_DIR.resolve()):
        raise ValueError("bad project id")
    return p


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def empty_timeline():
    return {
        "duration": 0,
        "tracks": [
            {"id": "v1", "type": "video", "name": "视频", "clips": []},
            {"id": "t1", "type": "text", "name": "标题", "clips": []},
            {"id": "t2", "type": "text", "name": "字幕", "clips": []},
            {"id": "a1", "type": "audio", "role": "voice", "name": "配音", "clips": []},
            {"id": "a2", "type": "audio", "role": "music", "name": "BGM", "clips": []},
            {"id": "a3", "type": "audio", "role": "sfx", "name": "音效", "clips": []},
        ],
    }


def create(name: str, width=1080, height=1920, fps=30) -> dict:
    pid = new_id("p_")
    d = pdir(pid)
    for sub in ("media", "cache", "audio", "exports"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    now = time.time()
    proj = {
        "id": pid,
        "name": name,
        "createdAt": now,
        "updatedAt": now,
        "settings": {"width": width, "height": height, "fps": fps, "look": {"vignette": True, "gradients": True, "fadeInOut": True}},
        "brief": {
            "purpose": "",
            "audience": "",
            "style": "专业、大气、有质感",
            "duration": 90,
            "subtitleLang": "zh+en",
            "voice": "zh-CN-YunyangNeural",
            "voiceRate": "-4%",
            "notes": "",
        },
        "assets": [],
        "script": None,
        "timeline": empty_timeline(),
    }
    save(proj)
    return proj


def load(pid: str) -> dict:
    with lock(pid):
        return json.loads((pdir(pid) / "project.json").read_text(encoding="utf-8"))


def save(proj: dict):
    pid = proj["id"]
    with lock(pid):
        proj["updatedAt"] = time.time()
        p = pdir(pid) / "project.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)


def mutate(pid: str, fn):
    """在锁内读-改-写，后台任务用它来避免覆盖前端的修改。"""
    with lock(pid):
        proj = load(pid)
        r = fn(proj)
        save(proj)
        return r


def list_projects():
    out = []
    for d in PROJECTS_DIR.iterdir():
        f = d / "project.json"
        if f.exists():
            try:
                p = json.loads(f.read_text(encoding="utf-8"))
                thumb = next((a.get("thumb") for a in p.get("assets", []) if a.get("thumb") and a.get("origin", "import") == "import"), None)
                out.append({"id": p["id"], "name": p["name"], "updatedAt": p.get("updatedAt", 0),
                            "duration": p.get("timeline", {}).get("duration", 0),
                            "assetCount": sum(1 for a in p.get("assets", []) if a.get("origin", "import") == "import"),
                            "thumb": thumb, "settings": p.get("settings")})
            except Exception:
                pass
    return sorted(out, key=lambda x: -x["updatedAt"])


def asset(proj: dict, aid: str):
    return next((a for a in proj["assets"] if a["id"] == aid), None)
