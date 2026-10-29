"""Scan actual Git index bytes before commit/push. Never echo matched secret values."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "provider_key": re.compile(rb"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    "github_fine_token": re.compile(rb"github_pat_[A-Za-z0-9_]{30,}"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "database_password": re.compile(rb"postgres(?:ql)?://[^\s/@:]+:[^\s/@]+@"),
    "personal_home_path": re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
}


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main():
    secrets = []
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, sep, value = line.partition("=")
            value = value.strip().strip("\"'")
            if sep and re.search(r"KEY|TOKEN|SECRET|PASSWORD", key) and len(value) >= 16:
                secrets.append(value.encode())
    files = [p.decode() for p in git("ls-files", "-z").split(b"\0") if p]
    failures, total = [], 0
    for name in files:
        parts = Path(name).parts
        if (
            name == ".env"
            or (Path(name).name.startswith(".env.") and name != ".env.example")
            or any(
                p in parts
                for p in (".venv", "__pycache__", "raw", "processed", "cache", "logs", "archive")
            )
        ):
            failures.append({"path": name, "reason": "private_or_generated_path"})
        data = git("show", ":" + name)
        total += len(data)
        if len(data) > 2 * 1024 * 1024:
            failures.append({"path": name, "reason": "oversize_artifact"})
        for label, pattern in PATTERNS.items():
            if pattern.search(data):
                failures.append({"path": name, "reason": label})
        if any(secret in data for secret in secrets):
            failures.append({"path": name, "reason": "matches_local_credential"})
        mode = git("ls-files", "-s", "--", name).split(b" ", 1)[0]
        if mode == b"120000":
            target = (Path(name).parent / data.decode()).as_posix()
            # The publication should not rely on ignored local report symlink targets.
            if target not in files:
                failures.append({"path": name, "reason": "unstaged_symlink_target"})
    print(json.dumps({"files": len(files), "bytes": total, "failures": failures}, indent=2))
    if failures or not files:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
