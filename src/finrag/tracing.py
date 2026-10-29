"""Explicit local spans. Only allowlisted request data is handed to this recorder."""

import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4


class Trace:
    def __init__(self, query_id, inputs):
        self.data = {
            "schema_version": 1,
            "run_id": uuid4().hex,
            "query_id": query_id,
            "created_at": datetime.now(UTC).isoformat(),
            "backend": "local_only",
            "inputs": inputs,
            "stages": [],
            "status": "running",
        }
        self.stack = []

    @contextmanager
    def stage(self, name, inputs=None):
        row = {
            "id": uuid4().hex,
            "parent_id": self.stack[-1] if self.stack else None,
            "name": name,
            "inputs": inputs or {},
            "outputs": {},
            "status": "running",
            "started_at": datetime.now(UTC).isoformat(),
        }
        self.data["stages"].append(row)
        self.stack.append(row["id"])
        started = time.perf_counter()
        try:
            yield row
            row["status"] = "ok"
        except Exception as exc:
            row["status"] = "error"
            # Exception bodies can contain headers or provider responses; never serialize them.
            row["error_type"] = type(exc).__name__
            raise
        finally:
            row["duration_seconds"] = time.perf_counter() - started
            row["ended_at"] = datetime.now(UTC).isoformat()
            self.stack.pop()
