"""python -m app — 以统一配置启动一个本地服务进程。"""

import uvicorn
from .config import Settings
from .main import create_app


if __name__ == "__main__":
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port,
                log_level=settings.log_level, proxy_headers=False)
