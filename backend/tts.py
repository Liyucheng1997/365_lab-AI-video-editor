"""配音：edge-tts 合成，并用逐词时间戳算出每句字幕的起止时间。"""
import asyncio
import re
import time

import edge_tts

_strip = lambda s: re.sub(r"[\s，。、·,.!?！？；;：:“”\"'‘’（）()—\-…]", "", s)


async def _synth(text, voice, rate):
    c = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words, audio = [], bytearray()
    async for ch in c.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            words.append([ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7, ch["text"]])
    return bytes(audio), words


def synthesize(lines: list[str], voice: str, rate: str, out_path: str, retries=8):
    """lines 合成一段连续配音。返回 {words, spans}，spans[i] 为第 i 句在音频里的 [起, 止] 秒。"""
    zh = voice.startswith("zh")
    sep = "。" if zh else ". "
    text = sep.join(l.strip().rstrip("。.") for l in lines if l.strip()) + ("。" if zh else ".")
    last = None
    for k in range(retries):
        try:
            audio, words = asyncio.run(_synth(text, voice, rate))
            if not audio:
                raise RuntimeError("空音频")
            break
        except Exception as e:  # 服务端偶发 403/限流
            last = e
            time.sleep(2 + 2 * k)
    else:
        hint = "（微软会定期更换校验，通常运行 pip install -U edge-tts 并重启后端即可）" if "403" in str(last) else ""
        raise RuntimeError(f"配音合成失败{hint}：{str(last)[:160]}")
    open(out_path, "wb").write(audio)
    lens = [len(_strip(l)) for l in lines]
    spans, wi = [], 0
    for L in lens:
        got, st, en = 0, None, None
        while got < L and wi < len(words):
            w = words[wi]
            n = len(_strip(w[2]))
            if n and st is None:
                st = w[0]
            got += n
            en = w[1]
            wi += 1
        if st is None:  # 没对上（极少见），按上一句结尾顺延
            st = spans[-1][1] + 0.3 if spans else 0.0
            en = st + 0.25 * max(1, L)
        spans.append([round(st, 3), round(en, 3)])
    return {"words": words, "spans": spans}
