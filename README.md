# AI 剪辑 v1.0

本地网页版 AI 视频剪辑软件。流程：导入素材 → AI 分析素材 → AI 生成剪辑脚本 → 你确认/修改脚本 → 一键执行剪辑（配音、卡点排镜头、调色、防抖、转场、标题、字幕、BGM、音效）→ 在时间线上手动精修 → 导出。

AI 走本机的 Claude Code CLI（`claude -p`，用你本地登录的订阅），默认模型 `claude-opus-5-5`，不需要 API key。

## 启动

双击 `启动.bat`，或：

```bash
python backend/app.py
```

然后打开 http://127.0.0.1:8765

第一次运行前需要构建前端（`启动.bat` 会自动做）：

```bash
cd frontend && npm install && npm run build
```

开发前端时可以用 `npm run dev`（5173 端口，接口代理到 8765）。

## 依赖

- Python 3.11+：`pip install -r backend/requirements.txt`（edge-tts 要保持最新，旧版会被微软服务拒绝，报 403）
- Node 18+（只在构建前端时需要）
- Claude Code CLI 已登录（`claude --version` 能运行）
- 字体：思源宋体 Heavy、Noto Sans SC、Segoe UI（`C:/Windows/Fonts`，见 `backend/config.py`）

环境变量（可选）：`AICUT_MODEL` 换模型，`AICUT_CLAUDE` 指定 claude 可执行文件，`AICUT_PROJECTS` 改项目存放目录。

## 目录

```
backend/
  app.py            接口（FastAPI），也负责托管前端
  ai.py             调用 claude CLI：素材分析、剪辑脚本（JSON Schema 结构化输出，帧拼图作为图片输入）
  ingest.py media.py  素材导入：探测、HDR→SDR 预览代理、缩略图/胶片条、波形、抖动分析、AI 帧拼图
  build.py          执行剪辑：脚本 → 时间线（配音、段落卡小节、镜头、转场、字幕、BGM、音效）
  render.py         最终渲染：逐帧合成（防抖/光流慢放补帧/调色 LUT/转场/文字动画），多进程分段编码，混音，-14 LUFS
  textfx.py         文字排版（预览和导出共用，所见即所得）
  tts.py music.py   edge-tts 配音（逐句时间戳），程序合成 BGM 和转场音效
  import_legacy.py  把之前在 Claude Code 里剪的「62_工厂宣传视频」迁移成可编辑工程
frontend/src/
  components/Timeline.tsx   时间线（拖动、裁剪、分割、吸附、跨轨道、撤销重做）
  components/Preview.tsx    预览播放器（多视频同步、转场/调色近似、文字图层由后端渲染）
  components/Inspector.tsx  属性面板（变速、转场、滤镜、画面、音量、改台词重新配音）
  components/AIPanel.tsx    AI 剪辑流程（需求 → 脚本编辑/按意见修改/历史版本 → 执行剪辑）
  components/MediaPanel.tsx 素材库（拖拽上传、本机文件夹导入、AI 分析结果）
projects/<id>/      每个项目：project.json + media/ cache/ audio/ exports/
```

## 预览与成片的差别

编辑器预览用浏览器播放 540p 预览代理，调色用 CSS 近似；防抖和慢放补帧只在导出时生效。点预览下方「成片效果预览」可以用导出的同一套渲染管线渲染当前帧。文字图层在预览和导出里是同一份排版。
