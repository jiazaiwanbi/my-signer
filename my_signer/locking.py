"""OS locks are released by the kernel even if Qinglong kills the process."""
from contextlib import contextmanager
from pathlib import Path
import os


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def state_lock(state_dir):
    path = Path(state_dir)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (path / ".signer.lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise AlreadyRunning("同一数据目录已有任务运行；跳过本次执行。") from exc
        else:
            import fcntl
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AlreadyRunning("同一数据目录已有任务运行；跳过本次执行。") from exc
        yield
    finally:
        lock.close()


def private_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    if os.name != "nt":
        path.chmod(0o600)
