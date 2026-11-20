"""Single localhost service serves both the real UI and the A/B/C integration API."""
import os
from pathlib import Path
import uvicorn
from fastapi.staticfiles import StaticFiles
from app.main import create_app
from app.config import Settings

root = Path(__file__).resolve().parent.parent
data = root / 'data'
os.environ.setdefault('WENSAI_DB_PATH', str(data / 'wensai.sqlite3'))
os.environ.setdefault('WENSAI_FILE_ROOT', str(data / 'projects'))
from dataclasses import replace
settings = replace(Settings.from_env(), max_file_bytes=30*1024*1024)
app = create_app(settings)
frontend = root / 'frontend/dist'
if frontend.is_dir():
    app.mount('/', StaticFiles(directory=frontend, html=True), name='desktop-ui')

if __name__ == '__main__':
    if os.environ.get('WENSAI_OPEN_UI') == '1':
        import threading
        import time
        import urllib.request
        import webbrowser
        def open_when_ready():
            address = 'http://127.0.0.1:' + os.environ.get('WENSAI_PORT', '8765')
            for _ in range(60):
                try:
                    with urllib.request.urlopen(address + '/health', timeout=.5) as response:
                        if response.status == 200:
                            webbrowser.open(address)
                            return
                except Exception:
                    time.sleep(.25)
        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('WENSAI_PORT', '8765')), proxy_headers=False)
