"""把之前在 Claude Code 里剪的「62_工厂宣传视频」迁移成可编辑的工程。

用法：python import_legacy.py [素材文件夹] [旧会话 scratchpad 目录]
旧工程的 timeline.py / script.json / vo/*.mp3 / audio/music.wav 都在 scratchpad 里。
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import build as builder
import ingest
import media
import store

SRC = Path(sys.argv[1] if len(sys.argv) > 1 else "F:/我的视频分享/62_工厂宣传视频")
OLD = Path(sys.argv[2] if len(sys.argv) > 2 else
           "C:/Users/liyuc/AppData/Local/Temp/claude/F---------62-------/df3f4bb9-b735-4122-8982-5a0d863686d8/scratchpad")


class _Job:
    def progress(self, p, msg=None):
        if msg:
            print(f"  [{p * 100:5.1f}%] {msg}", flush=True)

    cancelled = False


def main():
    spec = importlib.util.spec_from_file_location("old_timeline", OLD / "scripts/timeline.py")
    T = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(T)
    script = json.loads((OLD / "scripts/script.json").read_text(encoding="utf-8"))
    script_by = {s["id"]: s for s in script}
    W, H = 1080, 1920

    proj = store.create("工厂宣传片（从 Claude Code 迁移）", W, H, 30)
    pid = proj["id"]
    d = store.pdir(pid)
    print("项目", pid, d)
    proj["brief"].update({"purpose": "工厂对外宣传视频，用来和品牌方谈合作", "audience": "服装品牌方",
                          "style": "专业、大气、有电影感", "duration": 96})
    # 1. 素材：按文件名排序，与旧工程 c01..c23 一一对应
    files = sorted(SRC.glob("*.mp4"))
    cmap = {}
    for i, f in enumerate(files, 1):
        a = ingest.register(proj, str(f))
        cmap[f"c{i:02d}"] = a["id"]
    store.save(proj)
    print(f"处理 {len(files)} 段素材（预览代理/缩略图/抖动/波形）…")
    ingest.process_job(_Job(), pid, list(cmap.values()))
    proj = store.load(pid)
    assets = {a["id"]: a for a in proj["assets"]}

    # 2. 视频轨
    vclips, tclips, sclips, aclips, mclips, fxclips = [], [], [], [], [], []
    k = 0
    for si, sec in enumerate(T.SECTIONS):
        t = sec["t"]
        for j, (clip, tin, tout, dur, opts) in enumerate(sec["shots"]):
            aid = cmap[clip]
            a = assets[aid]
            tr = {"type": "none", "duration": 0.4}
            if t < 5.0:
                tr = {"type": "flash", "duration": 0.2}
            elif j == 0 and sec["id"] not in ("intro", "s0"):
                tr = {"type": "fade", "duration": 0.4}
            rms = (a.get("audio") or {}).get("rmsDb")
            c = {"id": f"v{k + 1}", "assetId": aid, "start": round(t, 3), "duration": dur, "in": tin, "out": tout,
                 "label": sec["id"], "sectionId": sec["id"], "filter": {"preset": "cinematic", "exposure": T.GRADE.get(clip, {}).get("exp", 1.05)},
                 "transform": {"zoom": 1.07, "kenburns": 0.045 if k % 2 == 0 else -0.04, "rotate": 90 if opts.get("rot") == 1 else 0},
                 "stabilize": True, "smoothSlowmo": True, "ambience": True, "transition": tr,
                 "volume": builder.gain_to(rms, -30 if sec["id"] == "intro" else -36, 2.0) if a.get("hasAudio") else 0}
            vclips.append(c)
            t += dur
            k += 1
    end = next(s for s in T.SECTIONS if s["id"] == "end")
    vclips.append({"id": f"v{k + 1}", "assetId": cmap["c16"], "start": end["t"], "duration": end["d"], "in": 40 / 30, "out": 40 / 30 + 0.1,
                   "freeze": True, "label": "end", "sectionId": "end", "stabilize": False, "volume": 0,
                   "filter": {"preset": "cinematic", "exposure": 1.0, "blur": 22, "brightness": 0.32},
                   "transform": {"zoom": 1.04, "kenburns": 0.0192}, "transition": {"type": "fade", "duration": 1.2}})

    # 3. 文字
    n = [0]

    def tid():
        n[0] += 1
        return f"t{n[0]}"
    intro = T.SECTIONS[0]
    for j, (zh, en) in enumerate(intro["words"]):
        tclips.append({"id": tid(), "preset": "word", "start": round(j * 1.2, 3), "duration": 1.2, "text": zh, "sub": en})
    tclips.append({"id": tid(), "preset": "title", "start": 5.1, "duration": 6.5, "kicker": "FACTORY  PROFILE", "text": "一站式服装制造",
                   "sub": "ONE-STOP GARMENT MANUFACTURING", "extra": "您值得信赖的生产合作伙伴", "backdrop": True})
    st = {s["id"]: s["t"] for s in T.SECTIONS}
    for sid, (num, zh, en) in T.HEADERS.items():
        tclips.append({"id": tid(), "preset": "heading", "start": round(st[sid] + 0.25, 3), "duration": 4.4, "num": num, "text": zh, "sub": en})
    tclips.append({"id": tid(), "preset": "title", "start": round(end["t"] + 0.5, 3), "duration": round(T.TOTAL - end["t"] - 0.5, 3),
                   "kicker": "PARTNER  WITH  US", "text": "诚邀品牌合作", "sub": "LET'S BUILD YOUR BRAND TOGETHER",
                   "extra": "从纸样到交付 · 一站式服装制造\nFrom pattern to delivery, all under one roof", "backdrop": False, "dy": 98})

    # 4. 配音 + 字幕
    for sec in script:
        sid = sec["id"]
        rel = f"audio/vo_{sid}.mp3"
        shutil.copy(OLD / f"vo/{sid}.mp3", d / rel)
        vo = json.loads((OLD / f"vo/{sid}.json").read_text(encoding="utf-8"))
        lines = [{"zh": z, "en": e} for z, e in sec["subs"]]
        a = builder.new_audio_asset(proj, pid, rel, "tts", f"配音·{sid}", {"lines": lines, "spans": vo["spans"],
                                                                          "voice": "zh-CN-YunyangNeural", "rate": "-4%"})
        base = st[sid] + (0.6 if sid == "s0" else T.VO_DELAY)
        aclips.append({"id": f"au{len(aclips) + 1}", "assetId": a["id"], "start": round(base, 3), "duration": round(a["duration"], 3),
                       "in": 0, "volume": builder.gain_to(builder.active_rms_db(str(d / rel)), -19, 4.0), "fadeIn": 0.01, "fadeOut": 0.05,
                       "sectionId": sid, "label": sid})
        sp = vo["spans"]
        for j, ((zh, en), (s0, s1)) in enumerate(zip(sec["subs"], sp)):
            t0 = base + s0 - 0.08
            t1 = base + (sp[j + 1][0] - 0.1 if j + 1 < len(sp) else s1 + 0.45)
            sclips.append({"id": f"s{len(sclips) + 1}", "preset": "subtitle", "start": round(t0, 3), "duration": round(t1 - t0, 3),
                           "text": zh, "sub": en, "sectionId": sid})

    # 5. BGM（按 12-80 秒段的响度对齐到 -23 dB，与原混音一致）
    shutil.copy(OLD / "audio/music.wav", d / "audio/bgm.wav")
    import numpy as np
    m = media.decode_audio(str(d / "audio/bgm.wav"), 16000, 1)[12 * 16000:80 * 16000, 0]
    mdb = 20 * np.log10(np.sqrt(np.mean(m ** 2)) + 1e-12)
    ma = builder.new_audio_asset(proj, pid, "audio/bgm.wav", "music", "原 BGM（程序合成）", {"bpm": 100})
    mclips.append({"id": "m1", "assetId": ma["id"], "start": 0, "in": 0, "duration": T.TOTAL, "volume": builder.gain_to(mdb, -23, 4.0),
                   "duck": True, "duckAmount": 0.55, "fadeIn": 0, "fadeOut": 0})

    # 6. 转场音效
    import music
    music.whoosh(str(d / "audio/whoosh.wav"))
    wa = builder.new_audio_asset(proj, pid, "audio/whoosh.wav", "sfx", "转场·嗖")
    for sec in T.SECTIONS[2:]:
        fxclips.append({"id": f"fx{len(fxclips) + 1}", "assetId": wa["id"], "start": round(sec["t"] - 0.4, 3), "duration": 0.7, "in": 0,
                        "volume": 0.063, "fadeIn": 0, "fadeOut": 0})

    tl = store.empty_timeline()
    by = {t["id"]: t for t in tl["tracks"]}
    by["v1"]["clips"], by["t1"]["clips"], by["t2"]["clips"] = vclips, tclips, sclips
    by["a1"]["clips"], by["a2"]["clips"], by["a3"]["clips"] = aclips, mclips, fxclips
    tl["duration"] = T.TOTAL
    proj["timeline"] = tl

    # 7. 剪辑脚本（只读回顾用）
    secs = []
    for sec in T.SECTIONS:
        sid = sec["id"]
        s = {"id": sid, "start": sec["t"], "dur": sec["d"], "lines": [{"zh": z, "en": e} for z, e in script_by.get(sid, {}).get("subs", [])],
             "shots": [{"assetId": cmap[c], "in": i0, "out": i1, "duration": du, "note": ""} for c, i0, i1, du, _ in sec["shots"]]}
        if sid == "intro":
            s.update(kind="intro", name="开场快剪", words=[{"zh": z, "en": e} for z, e in sec["words"]])
        elif sid == "s0":
            s.update(kind="title", name="主标题", card={"kicker": "FACTORY  PROFILE", "text": "一站式服装制造",
                                                        "sub": "ONE-STOP GARMENT MANUFACTURING", "extra": "您值得信赖的生产合作伙伴"})
        elif sid == "end":
            s.update(kind="ending", name="片尾", card={"kicker": "PARTNER  WITH  US", "text": "诚邀品牌合作", "sub": "LET'S BUILD YOUR BRAND TOGETHER",
                                                      "extra": "从纸样到交付 · 一站式服装制造\nFrom pattern to delivery, all under one roof"})
            s["shots"] = [{"assetId": cmap["c16"], "in": 1.33, "out": 1.43, "duration": sec["d"], "note": "虚化定格作片尾背景"}]
        elif sid in T.HEADERS:
            num, zh, en = T.HEADERS[sid]
            s.update(kind="section", name=zh, heading={"num": num, "zh": zh, "en": en})
        else:
            s.update(kind="section", name="结尾寄语")
        secs.append(s)
    proj["script"] = {"title": "工厂宣传片", "logline": "从一张纸样到一件成衣：按九道工序展示一站式服装制造能力，结尾邀约品牌合作。",
                      "musicMood": "inspiring", "musicBpm": 100, "status": "built", "version": 1, "history": [],
                      "assumptions": ["专属车辆配送", "成衣检验后入库", "熟练技工"], "sections": secs}
    store.save(proj)
    print("完成：", pid, f"{len(vclips)} 个镜头，{len(sclips)} 条字幕，{len(aclips)} 段配音")
    return pid


if __name__ == "__main__":
    main()
