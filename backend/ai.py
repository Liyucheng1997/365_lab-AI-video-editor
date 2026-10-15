"""AI：通过本机 Claude Code CLI（本地订阅）调用 Opus，做素材分析和剪辑脚本生成。"""
import base64
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from config import CLAUDE_BIN, CLAUDE_MODEL
from media import NOWIN

SYSTEM = ("你是一名资深的商业视频导演兼剪辑师，擅长企业宣传片、产品片、短视频。"
          "你会根据素材画面做专业判断，输出严格符合给定 JSON Schema 的结果，不要输出任何多余内容。")


def claude_json(text: str, schema: dict, images=(), system=SYSTEM, timeout=900, cwd=None) -> dict:
    content = []
    for p in images:
        data = base64.b64encode(Path(p).read_bytes()).decode()
        mt = "image/png" if str(p).lower().endswith(".png") else "image/jpeg"
        content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
    content.append({"type": "text", "text": text})
    msg = json.dumps({"type": "user", "message": {"role": "user", "content": content}}, ensure_ascii=False)
    cmd = [CLAUDE_BIN, "-p", "--model", CLAUDE_MODEL, "--input-format", "stream-json", "--output-format", "stream-json",
           "--verbose", "--no-session-persistence", "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--system-prompt", system, "--json-schema", json.dumps(schema, ensure_ascii=False)]
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(cmd, input=msg.encode("utf-8"), capture_output=True, timeout=timeout,
                           cwd=cwd or td, creationflags=NOWIN)
    out = r.stdout.decode("utf-8", "replace")
    result = None
    for line in out.splitlines():
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("type") == "result":
            result = d
    if result is None:
        raise RuntimeError("Claude CLI 没有返回结果：" + (r.stderr.decode("utf-8", "replace") or out)[-800:])
    if result.get("is_error"):
        raise RuntimeError("Claude 调用失败：" + str(result.get("result"))[:800])
    so = result.get("structured_output")
    if so is None:
        txt = (result.get("result") or "").strip().strip("`")
        if txt.startswith("json"):
            txt = txt[4:]
        so = json.loads(txt)
    return so


# --------------------------------------------------------------------------- 素材分析
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "assets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "summary": {"type": "string", "description": "一句话概括画面内容（≤30字）"},
                    "scene": {"type": "string", "description": "场景/环节分类，如：裁床、缝制车间、仓库、人物采访、产品特写"},
                    "content": {"type": "string", "description": "详细描述：主体、动作、景别、运镜、光线、背景"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "quality": {
                        "type": "object",
                        "properties": {
                            "score": {"type": "number", "description": "1-10，可用性综合评分"},
                            "issues": {"type": "array", "items": {"type": "string"}, "description": "如：背景杂乱、过曝、抖动、构图偏"},
                        },
                        "required": ["score", "issues"],
                    },
                    "segments": {
                        "type": "array",
                        "description": "最值得用的片段（按时间戳），2-4 个",
                        "items": {
                            "type": "object",
                            "properties": {"start": {"type": "number"}, "end": {"type": "number"},
                                           "desc": {"type": "string"}, "score": {"type": "number"}},
                            "required": ["start", "end", "desc", "score"],
                        },
                    },
                    "usage": {"type": "string", "description": "建议用途：开场快剪/主标题背景/工序展示/细节特写/空镜/结尾等"},
                },
                "required": ["id", "summary", "scene", "content", "tags", "quality", "segments", "usage"],
            },
        }
    },
    "required": ["assets"],
}


def _asset_line(a):
    m = a.get("motion") or {}
    au = a.get("audio") or {}
    orient = "竖屏" if a["height"] > a["width"] else "横屏"
    s = f"素材 {a['id']}（文件 {a['name']}）：时长 {a['duration']:.1f}s，{orient} {a['width']}x{a['height']}"
    if a.get("hdr"):
        s += "，iPhone HDR（已转 SDR 预览）"
    if m:
        s += f"，手持抖动 {m.get('jitter', 0):.1f}px，运镜速度 {m.get('pan', 0):.1f}px/帧"
    if au:
        s += f"，原声响度 {au.get('rmsDb')}dB"
    return s


def analyze_batch(assets, brief, sheets):
    lines = "\n".join(_asset_line(a) for a in assets)
    ctx = brief.get("purpose") or "（用户还没写用途）"
    text = (f"以下是 {len(assets)} 段视频素材的帧拼图（每张图左上角是素材编号，每帧左上角是该帧时间戳）。\n"
            f"视频用途：{ctx}\n\n{lines}\n\n"
            "请逐个分析：画面内容、属于哪个场景/环节、质量问题、最值得用的时间片段（start/end 秒，必须在素材时长内，"
            "每段 1.5-6 秒，避开明显晃动或构图差的部分），以及建议用途。id 必须和给出的素材编号一致。")
    r = claude_json(text, ANALYSIS_SCHEMA, images=sheets)
    return r["assets"]


def analyze_assets(assets, brief, sheet_of, job=None, batch=6, workers=4):
    groups = [assets[i:i + batch] for i in range(0, len(assets), batch)]
    done = {"n": 0}
    out = {}

    def one(g):
        res = analyze_batch(g, brief, [sheet_of(a) for a in g])
        done["n"] += len(g)
        if job:
            job.progress(0.1 + 0.85 * done["n"] / len(assets), f"已分析 {done['n']}/{len(assets)} 段素材")
        return res

    with ThreadPoolExecutor(workers) as ex:
        for res in ex.map(one, groups):
            for r in res:
                out[r["id"]] = r
    return out


# --------------------------------------------------------------------------- 剪辑脚本
_LINE = {"type": "object", "properties": {"zh": {"type": "string"}, "en": {"type": "string"}}, "required": ["zh", "en"]}
SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string", "description": "一句话说明影片的叙事思路"},
        "musicMood": {"type": "string", "enum": ["inspiring", "calm", "upbeat"]},
        "musicBpm": {"type": "number", "description": "BGM 速度，80-120"},
        "assumptions": {"type": "array", "items": {"type": "string"},
                        "description": "旁白里根据画面推断、需要用户确认的说法"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["intro", "title", "section", "ending"]},
                    "name": {"type": "string", "description": "段落名，给用户看的"},
                    "heading": {"type": "object", "description": "kind=section 时的段落标题",
                                "properties": {"num": {"type": "string"}, "zh": {"type": "string"}, "en": {"type": "string"}},
                                "required": ["num", "zh", "en"]},
                    "card": {"type": "object", "description": "kind=title/ending 时的大字标题卡",
                             "properties": {"kicker": {"type": "string"}, "text": {"type": "string"},
                                            "sub": {"type": "string"}, "extra": {"type": "string"}},
                             "required": ["kicker", "text", "sub", "extra"]},
                    "words": {"type": "array", "items": _LINE, "description": "kind=intro 时每个镜头上的关键词大字"},
                    "lines": {"type": "array", "items": _LINE, "description": "旁白，每句即一条字幕"},
                    "shots": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "assetId": {"type": "string"},
                                "in": {"type": "number"}, "out": {"type": "number"},
                                "duration": {"type": "number", "description": "镜头在成片中的时长"},
                                "note": {"type": "string"},
                            },
                            "required": ["assetId", "in", "out", "duration", "note"],
                        },
                    },
                },
                "required": ["id", "kind", "name", "lines", "shots"],
            },
        },
    },
    "required": ["title", "logline", "musicMood", "musicBpm", "assumptions", "sections"],
}

SCRIPT_RULES = """剪辑脚本规则：
1. 结构：可选的 intro（开场快剪，3-5 个短镜头，每个镜头配一个关键词大字 words，无旁白）→ title（主标题卡 card，1 个舒展的镜头，配 1-2 句点题旁白）→ 若干 section（每段一个环节，带 heading 编号标题，2-4 个镜头）→ ending（片尾卡 card，shots 放 1 个镜头作为虚化背景，lines 可为空）。也可以按用途灵活调整，但 kind 只能用这四种。
2. 镜头：assetId 必须是给出的素材编号；in/out 是素材内的秒数，0 ≤ in < out ≤ 素材时长；优先使用分析里推荐的片段，避开质量问题。duration 是成片里的时长，(out-in)/duration 为播放速度，必须在 0.5-1.0 之间（≤1 表示慢放更有质感，不要快放）。同一素材的同一片段不要重复使用。
3. 旁白：中文口语化、专业克制，每句 ≤ 18 个字，一段 1-4 句；语速约每秒 4 个字，一段旁白总时长要小于该段镜头时长总和。en 是对应的地道英文翻译（若只要中文字幕，en 也照样填）。
4. 只描述画面里看得到的东西，不要编造数据（年产量、员工数、年份等）。根据画面推断的说法写进 assumptions 让用户确认。
5. 总时长尽量接近目标时长，所有 section 时长按约 2.4 秒（一小节音乐）的整数倍规划，便于卡点。"""


def _asset_brief(a):
    an = a.get("analysis") or {}
    segs = "；".join(f"{s['start']:.1f}-{s['end']:.1f}s {s['desc']}（{s['score']}分）" for s in an.get("segments", []))
    q = an.get("quality") or {}
    return (f"- {a['id']}｜{a['duration']:.1f}s｜{'竖' if a['height'] > a['width'] else '横'}屏｜{an.get('scene', '')}｜{an.get('summary', a['name'])}\n"
            f"  详情：{an.get('content', '')}\n  推荐片段：{segs}\n  质量：{q.get('score', '?')}分 {'、'.join(q.get('issues', []))}；建议用途：{an.get('usage', '')}")


def generate_script(proj, feedback: str = None):
    b = proj["brief"]
    assets = [a for a in proj["assets"] if a["kind"] in ("video", "image") and a.get("origin", "import") == "import"]
    lang = {"zh+en": "中英双语", "zh": "仅中文", "en": "仅英文"}.get(b.get("subtitleLang"), "中英双语")
    s = proj["settings"]
    text = (f"请为下面的素材写一份剪辑脚本。\n\n【需求】\n用途：{b.get('purpose') or '未说明'}\n受众：{b.get('audience') or '未说明'}\n"
            f"风格：{b.get('style')}\n目标时长：约 {b.get('duration')} 秒\n画幅：{s['width']}x{s['height']}\n字幕：{lang}\n"
            f"补充说明：{b.get('notes') or '无'}\n\n【素材】\n" + "\n".join(_asset_brief(a) for a in assets) +
            f"\n\n{SCRIPT_RULES}")
    if feedback and proj.get("script"):
        old = {k: v for k, v in proj["script"].items() if k not in ("status", "version", "history")}
        text += ("\n\n【上一版脚本】\n" + json.dumps(old, ensure_ascii=False) +
                 f"\n\n【用户的修改意见】\n{feedback}\n\n请在上一版基础上按修改意见调整，没提到的部分尽量保持不变。")
    return claude_json(text, SCRIPT_SCHEMA)
