"""执行剪辑：把确认后的剪辑脚本变成时间线（配音、镜头、转场、调色、标题、字幕、BGM、音效）。"""
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import media
import music
import store
import tts

VO_DELAY = 0.45


def db(x):
    return 10 ** (x / 20)


def gain_to(rms_db, target_db, cap=6.0):
    if rms_db is None:
        return 1.0
    return round(min(cap, db(target_db - rms_db)), 4)


def new_audio_asset(proj, pid, rel, origin, name, extra=None):
    d = store.pdir(pid)
    ids = {a["id"] for a in proj["assets"]}
    n = len(proj["assets"]) + 1
    while f"a{n:02d}" in ids:
        n += 1
    aid = f"a{n:02d}"
    info = media.probe(str(d / rel))
    st = media.audio_stats(str(d / rel), str(d / f"cache/{aid}_peaks.json"))
    a = {"id": aid, "name": name, "path": rel, "proxy": rel, "kind": "audio", "origin": origin, "status": "ready",
         "duration": info["duration"], "hasAudio": True, "audio": st, "peaks": f"cache/{aid}_peaks.json", "width": 0, "height": 0}
    if extra:
        a.update(extra)
    proj["assets"].append(a)
    return a


def active_rms_db(path):
    import numpy as np
    x = media.decode_audio(path, 16000, 1)[:, 0]
    act = x[np.abs(x) > 0.02]
    if len(act) < 100:
        return None
    return 20 * math.log10(float(np.sqrt(np.mean(act ** 2))) + 1e-12)


def speech_text(line, voice):
    return (line.get("en") if voice.startswith("en") else line.get("zh")) or line.get("zh") or line.get("en") or ""


def sub_texts(line, lang):
    zh, en = line.get("zh", ""), line.get("en", "")
    if lang == "zh":
        return zh, ""
    if lang == "en":
        return en, ""
    return zh, en


def build(job, pid):
    proj = store.load(pid)
    sc = proj.get("script")
    if not sc or not sc.get("sections"):
        raise RuntimeError("还没有剪辑脚本")
    b = proj["brief"]
    voice, rate, lang = b.get("voice", "zh-CN-YunyangNeural"), b.get("voiceRate", "-4%"), b.get("subtitleLang", "zh+en")
    d = store.pdir(pid)
    (d / "audio").mkdir(exist_ok=True)
    assets = {a["id"]: a for a in proj["assets"]}
    secs = sc["sections"]
    # 删除旧的生成音频素材
    proj["assets"] = [a for a in proj["assets"] if a.get("origin") not in ("tts", "music", "sfx")]

    # ---- 1. 配音
    job.progress(0.03, "生成配音")
    todo = [s for s in secs if any(speech_text(l, voice).strip() for l in s.get("lines", []))]
    vo = {}

    def synth(s):
        lines = [speech_text(l, voice) for l in s["lines"]]
        rel = f"audio/vo_{s['id']}.mp3"
        r = tts.synthesize(lines, voice, rate, str(d / rel))
        return s["id"], rel, r

    with ThreadPoolExecutor(3) as ex:
        for k, (sid, rel, r) in enumerate(ex.map(synth, todo)):
            vo[sid] = (rel, r)
            job.progress(0.03 + 0.4 * (k + 1) / max(1, len(todo)), f"配音 {k + 1}/{len(todo)}")

    # ---- 2. 段落时长（卡音乐小节）
    bpm = float(sc.get("musicBpm") or 100)
    bpm = min(130, max(70, bpm))
    BAR = 240 / bpm
    t = 0.0
    plan = []
    for s in secs:
        shots = [x for x in s.get("shots", []) if x.get("assetId") in assets]
        want = sum(max(0.6, float(x.get("duration", 2))) for x in shots)
        delay = 0.6 if s["kind"] == "title" else VO_DELAY
        vneed = 0
        if s["id"] in vo:
            vneed = delay + media.audio_duration(str(d / vo[s["id"]][0])) + 0.9
        if s["kind"] == "intro":
            dur = max(want, 0.6 * len(shots))
            dur = max(BAR, round(dur / (BAR / 2)) * (BAR / 2))
        elif s["kind"] == "ending":
            dur = max(want, vneed, 3 * BAR)
            dur = math.ceil(dur / BAR - 0.1) * BAR
        else:
            dur = max(want, vneed, BAR)
            dur = math.ceil(dur / BAR - 0.15) * BAR
            if dur < vneed:
                dur += BAR
        plan.append({"s": s, "t": round(t, 3), "d": round(dur, 3), "shots": shots, "delay": delay})
        t += dur
    total = round(t, 3)

    # ---- 3. 视频轨
    job.progress(0.5, "排列镜头")
    vclips, tclips, sclips, aclips, mclips, fxclips = [], [], [], [], [], []
    cid = [0]

    def nid(p):
        cid[0] += 1
        return f"{p}{cid[0]}"

    first_body = next((i for i, p in enumerate(plan) if p["s"]["kind"] == "section"), None)
    for si, p in enumerate(plan):
        s, shots = p["s"], p["shots"]
        if not shots:
            continue
        want = sum(max(0.6, float(x.get("duration", 2))) for x in shots)
        tt = p["t"]
        for j, x in enumerate(shots):
            a = assets[x["assetId"]]
            dur = p["d"] * max(0.6, float(x.get("duration", 2))) / want if j < len(shots) - 1 else p["t"] + p["d"] - tt
            dur = round(dur, 3)
            adur = float(a.get("duration") or 0)
            i0, i1 = max(0.0, float(x.get("in", 0))), float(x.get("out", 0))
            i1 = min(adur - 0.05, i1) if adur else i1
            if i1 - i0 < 0.2:
                i0, i1 = 0.0, min(adur, dur)
            src = i1 - i0
            if src > dur:  # 不快放
                i1 = i0 + dur
            elif src < 0.5 * dur:  # 最慢 0.5 倍，素材够长就往外扩
                need = 0.5 * dur
                i1 = min(adur - 0.05, i0 + need)
                if i1 - i0 < need:
                    i0 = max(0.0, i1 - need)
            last_end = (s["kind"] == "ending")
            c = {"id": nid("v"), "assetId": a["id"], "start": round(tt, 3), "duration": dur, "in": round(i0, 3), "out": round(i1, 3),
                 "label": s.get("name", ""), "sectionId": s["id"], "note": x.get("note", ""),
                 "filter": {"preset": "cinematic"}, "transform": {"zoom": 1.07, "kenburns": 0.045 if len(vclips) % 2 == 0 else -0.04},
                 "stabilize": True, "smoothSlowmo": True, "ambience": True,
                 "transition": {"type": "none", "duration": 0.4}}
            if s["kind"] == "intro" or (s["kind"] == "title" and j == 0):
                c["transition"] = {"type": "flash", "duration": 0.2}
            elif j == 0 and si > 0:
                c["transition"] = {"type": "fade", "duration": 0.4}
            if last_end:
                c.update({"freeze": True, "stabilize": False, "volume": 0, "transition": {"type": "fade", "duration": 1.2},
                          "transform": {"zoom": 1.04, "kenburns": 0.02},
                          "filter": {"preset": "cinematic", "blur": 22 * proj["settings"]["width"] / 1080, "brightness": 0.32}})
            else:
                rms = (a.get("audio") or {}).get("rmsDb")
                c["volume"] = gain_to(rms, -30 if s["kind"] == "intro" else -36, 2.0) if a.get("hasAudio") else 0
            vclips.append(c)
            # 开场关键词
            words = s.get("words") or []
            if s["kind"] == "intro" and j < len(words):
                w = words[j]
                tclips.append({"id": nid("t"), "preset": "word", "start": round(tt, 3), "duration": dur,
                               "text": w.get("zh", ""), "sub": w.get("en", "").upper()})
            tt += dur

    # ---- 4. 标题 / 段落标题 / 字幕 / 配音
    job.progress(0.6, "生成字幕和标题")
    for p in plan:
        s = p["s"]
        if s["kind"] == "title" and s.get("card"):
            cd = s["card"]
            tclips.append({"id": nid("t"), "preset": "title", "start": round(p["t"] + 0.3, 3), "duration": round(p["d"] - 0.7, 3),
                           "kicker": cd.get("kicker", ""), "text": cd.get("text", ""), "sub": cd.get("sub", ""), "extra": cd.get("extra", ""),
                           "backdrop": True})
        if s["kind"] == "ending" and s.get("card"):
            cd = s["card"]
            tclips.append({"id": nid("t"), "preset": "title", "start": round(p["t"] + 0.5, 3), "duration": round(p["d"] - 0.5, 3),
                           "kicker": cd.get("kicker", ""), "text": cd.get("text", ""), "sub": cd.get("sub", ""), "extra": cd.get("extra", ""),
                           "backdrop": False, "dy": 98})
        if s["kind"] == "section" and s.get("heading"):
            h = s["heading"]
            tclips.append({"id": nid("t"), "preset": "heading", "start": round(p["t"] + 0.25, 3), "duration": round(min(4.4, p["d"] - 0.4), 3),
                           "num": h.get("num", ""), "text": h.get("zh", ""), "sub": (h.get("en") or "").upper()})
        if s["id"] in vo:
            rel, r = vo[s["id"]]
            path = str(d / rel)
            a = new_audio_asset(proj, pid, rel, "tts", f"配音·{s.get('name', s['id'])}",
                                {"lines": s["lines"], "spans": r["spans"], "voice": voice, "rate": rate})
            base = p["t"] + p["delay"]
            aclips.append({"id": nid("au"), "assetId": a["id"], "start": round(base, 3), "duration": round(a["duration"], 3), "in": 0,
                           "volume": gain_to(active_rms_db(path), -19, 4.0), "fadeIn": 0.01, "fadeOut": 0.05,
                           "sectionId": s["id"], "label": s.get("name", "")})
            sp = r["spans"]
            for k, (line, (a0, a1)) in enumerate(zip(s["lines"], sp)):
                t0 = base + a0 - 0.08
                t1 = base + (sp[k + 1][0] - 0.1 if k + 1 < len(sp) else a1 + 0.45)
                zh, en = sub_texts(line, lang)
                sclips.append({"id": nid("s"), "preset": "subtitle", "start": round(t0, 3), "duration": round(max(0.4, t1 - t0), 3),
                               "text": zh, "sub": en, "sectionId": s["id"]})

    # ---- 5. 背景音乐
    job.progress(0.7, "生成背景音乐")
    tstart = next((p["t"] for p in plan if p["s"]["kind"] == "title"), None)
    gstart = plan[first_body]["t"] if first_body is not None else None
    estart = next((p["t"] for p in plan if p["s"]["kind"] == "ending"), None)
    user_music = store.asset(proj, b.get("musicAssetId")) if b.get("musicAssetId") else None
    if user_music:
        mrms = (user_music.get("audio") or {}).get("rmsDb")
        mclips.append({"id": nid("m"), "assetId": user_music["id"], "start": 0, "in": 0,
                       "duration": round(min(total, user_music["duration"]), 3), "volume": gain_to(mrms, -23, 4.0),
                       "duck": True, "duckAmount": 0.55, "fadeIn": 0.5, "fadeOut": 2.0})
    else:
        rel = "audio/bgm.wav"
        music.synth_bgm(str(d / rel), total, bpm, tstart, gstart, estart, sc.get("musicMood", "inspiring"))
        a = new_audio_asset(proj, pid, rel, "music", "AI 合成 BGM", {"bpm": bpm})
        mclips.append({"id": nid("m"), "assetId": a["id"], "start": 0, "in": 0, "duration": round(min(total, a["duration"]), 3),
                       "volume": gain_to(a["audio"]["rmsDb"], -23, 4.0), "duck": True, "duckAmount": 0.55, "fadeIn": 0.0, "fadeOut": 0.0})

    # ---- 6. 转场音效
    if not (d / "audio/whoosh.wav").exists():
        music.whoosh(str(d / "audio/whoosh.wav"))
    wa = new_audio_asset(proj, pid, "audio/whoosh.wav", "sfx", "转场·嗖")
    for p in plan[(first_body or len(plan)):]:
        fxclips.append({"id": nid("fx"), "assetId": wa["id"], "start": round(max(0, p["t"] - 0.4), 3), "duration": 0.7, "in": 0,
                        "volume": 0.063, "fadeIn": 0, "fadeOut": 0})

    job.progress(0.9, "写入时间线")
    tl = store.empty_timeline()
    byid = {t["id"]: t for t in tl["tracks"]}
    byid["v1"]["clips"], byid["t1"]["clips"], byid["t2"]["clips"] = vclips, tclips, sclips
    byid["a1"]["clips"], byid["a2"]["clips"], byid["a3"]["clips"] = aclips, mclips, fxclips
    tl["duration"] = total
    new_assets = proj["assets"]

    def apply(pp):
        keep = [a for a in pp["assets"] if a.get("origin") not in ("tts", "music", "sfx")]
        gen = [a for a in new_assets if a.get("origin") in ("tts", "music", "sfx")]
        pp["assets"] = keep + gen
        pp["timeline"] = tl
        pp["script"]["status"] = "built"
        for pl in plan:
            for s in pp["script"]["sections"]:
                if s["id"] == pl["s"]["id"]:
                    s["start"], s["dur"] = pl["t"], pl["d"]
    store.mutate(pid, apply)
    return {"duration": total, "clips": len(vclips), "subtitles": len(sclips)}
