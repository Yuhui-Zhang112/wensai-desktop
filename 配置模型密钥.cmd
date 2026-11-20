@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
if not exist "..\.venv\Scripts\python.exe" (
  echo 请先运行安装环境.cmd。
  pause
  exit /b 1
)
echo 仅在本机系统凭据管理器保存 DeepSeek Key；输入不会回显。
"..\.venv\Scripts\python.exe" -m app.review_agent configure-key
pause
