@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 本版使用 Python 3.12。首次安装需要网络；不会调用模型。
py -3.12 --version >nul 2>&1
if errorlevel 1 goto missingpython
py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r wensai\requirements.txt
if errorlevel 1 goto failed
echo 安装完成。请双击“启动问赛.cmd”。
pause
exit /b 0
:missingpython
echo 未找到 Python 3.12，请先安装该版本和 Python Launcher。
echo 不安装也能看界面：双击“先看智能体界面.cmd”。
pause
exit /b 1
:failed
echo 安装失败。请保留上方报错；不要把密钥粘贴到窗口或聊天中。
pause
exit /b 1
