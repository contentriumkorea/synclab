from pathlib import Path
import os
import tempfile


def protect_sources(path, clips):
    target = Path(path).resolve()
    for clip in clips:
        source = clip.path.resolve()
        if target == source or (target.exists() and source.exists() and os.path.samefile(target, source)):
            raise ValueError("원본 미디어 파일에 덮어쓸 수 없습니다.")
    return target


def atomic_write(path, data):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".synclab-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
