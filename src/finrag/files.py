import hashlib
import json
import os
import tempfile
from pathlib import Path


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_jsonl(path: Path, rows) -> None:
    atomic_json(
        path, "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", raw=True
    )


def atomic_json(path: Path, data, raw: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Unique temporary names prevent concurrent requests for the same cache key from racing.
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(data if raw else json.dumps(data, ensure_ascii=False, indent=2))
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
