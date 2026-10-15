import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS_DIR = Path(os.environ.get("AICUT_PROJECTS", ROOT / "projects"))
FRONTEND_DIST = ROOT / "frontend" / "dist"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


def _find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise RuntimeError("找不到 ffmpeg：请安装 ffmpeg 或 pip install imageio-ffmpeg")


FFMPEG = _find_ffmpeg()

# AI: 走本机 Claude Code CLI（本地订阅登录），不需要 API key
CLAUDE_BIN = os.environ.get("AICUT_CLAUDE", shutil.which("claude") or "claude")
CLAUDE_MODEL = os.environ.get("AICUT_MODEL", "claude-opus-5-5")

FONT_DIR = Path(os.environ.get("AICUT_FONTS", "C:/Windows/Fonts"))
# 预览与最终渲染共用同一套字体，保证所见即所得
FONTS = {
    "serif": "Source Han Serif SC Heavy (TrueType).ttf",
    "zh_bold": "Noto Sans SC Bold (TrueType).otf",
    "zh_medium": "Noto Sans SC Medium (TrueType).otf",
    "en_light": "segoeuil.ttf",
    "en_semilight": "segoeuisl.ttf",
    "en_semibold": "seguisb.ttf",
}
FONT_FALLBACK = "msyh.ttc"

MEDIA_EXT = {
    "video": {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mts", ".3gp"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp"},
}

VOICES = [
    {"id": "zh-CN-YunyangNeural", "name": "云扬（男·新闻播音，沉稳）"},
    {"id": "zh-CN-YunxiNeural", "name": "云希（男·阳光活力）"},
    {"id": "zh-CN-YunjianNeural", "name": "云健（男·浑厚有力）"},
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（女·温暖亲切）"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊（女·活泼）"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "name": "晓北（女·东北话）"},
    {"id": "en-US-AndrewNeural", "name": "Andrew（英·男·温和）"},
    {"id": "en-US-GuyNeural", "name": "Guy（英·男·播音）"},
    {"id": "en-US-AriaNeural", "name": "Aria（英·女）"},
]
