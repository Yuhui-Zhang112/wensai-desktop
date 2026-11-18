"""防止同一台机器上的两个 Worker 同时恢复同一数据库或清理同一文件根目录。"""

import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def instance_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # 保留锁文件；由操作系统在进程退出时自动释放锁，避免删除后锁住不同 inode。
    with path.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f"无法取得服务锁，请检查是否已有问赛实例正在使用 {path}") from exc
        yield
