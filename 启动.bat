@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist frontend\dist\index.html (
  echo 首次运行，正在构建前端...
  cd frontend && call npm install && call npm run build && cd ..
)
start "" http://127.0.0.1:8765
python backend\app.py
