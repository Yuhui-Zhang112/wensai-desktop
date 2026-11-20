@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先运行安装环境.cmd。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r wensai\requirements-test.txt
if errorlevel 1 goto failed
cd wensai
"..\.venv\Scripts\python.exe" -m pytest tests/test_goal_agent.py tests/test_desktop.py tests/test_adapters.py task_b_tests task_c_tests -q
if errorlevel 1 goto failed
echo 测试通过，真实 DeepSeek 请求未在此测试集运行。
pause
exit /b 0
:failed
echo 测试或依赖安装失败，请保留上方报错。
pause
exit /b 1
