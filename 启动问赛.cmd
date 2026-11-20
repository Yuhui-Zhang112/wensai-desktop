@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 首次使用请先双击“安装环境.cmd”。
  pause
  exit /b 1
)
set WENSAI_OPEN_UI=1
echo 本地服务启动后，在浏览器中使用问赛。关闭本窗口会结束本地服务。
".venv\Scripts\python.exe" "wensai\serve.py"
pause
