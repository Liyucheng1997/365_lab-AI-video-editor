"""极简后台任务：线程执行，前端轮询进度。"""
import threading
import time
import traceback
import uuid

JOBS: dict[str, dict] = {}
_lock = threading.Lock()


class Job:
    def __init__(self, d):
        self.d = d

    def progress(self, p: float, msg: str = None):
        self.d["progress"] = max(0.0, min(1.0, p))
        if msg is not None:
            self.d["message"] = msg
            self.d["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")
            del self.d["log"][:-200]

    def log(self, msg):
        self.progress(self.d["progress"], msg)

    @property
    def cancelled(self):
        return self.d["status"] == "cancelled"


def start(kind: str, project_id: str, fn, *args, **kw) -> dict:
    jid = uuid.uuid4().hex[:10]
    d = {"id": jid, "kind": kind, "projectId": project_id, "status": "running", "progress": 0.0,
         "message": "排队中", "log": [], "error": None, "result": None, "startedAt": time.time(), "endedAt": None}
    with _lock:
        JOBS[jid] = d
    job = Job(d)

    def run():
        try:
            d["result"] = fn(job, *args, **kw)
            if d["status"] == "running":
                d["status"] = "done"
                d["progress"] = 1.0
        except Exception as e:  # noqa
            traceback.print_exc()
            d["status"] = "error"
            d["error"] = str(e) or e.__class__.__name__
            d["log"].append(traceback.format_exc()[-1500:])
        d["endedAt"] = time.time()

    threading.Thread(target=run, daemon=True, name=f"job-{kind}-{jid}").start()
    return d


def get(jid):
    return JOBS.get(jid)


def for_project(pid):
    return [j for j in JOBS.values() if j["projectId"] == pid and (j["status"] == "running" or time.time() - (j["endedAt"] or 0) < 600)]


def cancel(jid):
    j = JOBS.get(jid)
    if j and j["status"] == "running":
        j["status"] = "cancelled"
        j["message"] = "已取消"
    return j
