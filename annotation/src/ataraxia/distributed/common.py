import contextlib
import hashlib
import json
import os
from pathlib import Path
import re


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def safe_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', value or ''):
        raise ValueError(f'Unsafe identifier: {value!r}')
    return value


def under(root, relative):
    root = Path(root).resolve()
    p = (root / relative).resolve()
    if not p.is_relative_to(root) or p == root:
        raise ValueError(f'Path escapes root: {relative}')
    return p


@contextlib.contextmanager
def lock(path):
    """OS lock, released on process death. Never infer ownership from file age."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open('a+b')
    try:
        f.seek(0)
        if not f.read(1):
            f.write(b'0'); f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        f.close()


def source_hashes(root):
    files = list((root/'src/ataraxia').rglob('*.py'))
    files += list((root/'commands').glob('distributed*.py'))
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(files)}


def verify_sources(root, hashes):
    for name, expected in hashes.items():
        if sha(under(root, name)) != expected:
            raise RuntimeError(f'Frozen source changed: {name}; use a new run')
