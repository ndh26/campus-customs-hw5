"""Append-only audit trail for the agent suite: output/audit_trail.json.

Every event is written as soon as it happens, so a run that crashes halfway still leaves
a record. The file is a JSON array; new events are appended and earlier runs are never
removed or rewritten.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from models import AuditEvent

HW_DIR = Path(__file__).resolve().parent.parent
AUDIT_PATH = Path(os.environ.get("AUDIT_PATH", HW_DIR / "output" / "audit_trail.json"))

MAX_FIELD_CHARS = 4000  # long tool results are clipped so the file stays readable


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_FIELD_CHARS:
        return value[:MAX_FIELD_CHARS] + f"... [clipped, {len(value)} chars total]"
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip(v) for v in value]
    return value


class AuditTrail:
    def __init__(self, run_id: str, path: Path = AUDIT_PATH):
        self.run_id = run_id
        self.path = path
        self.seq = 0

    def log(self, agent: str, event: str, *, parent: str | None = None, ticket_id: int | None = None,
            step: int | None = None, usage: dict[str, int] | None = None, **detail: Any) -> None:
        self.seq += 1
        entry = AuditEvent(
            run_id=self.run_id,
            seq=self.seq,
            timestamp=datetime.now().isoformat(timespec="milliseconds"),
            agent=agent,
            parent_agent=parent,
            ticket_id=ticket_id,
            step=step,
            event=event,
            detail=_clip(json.loads(json.dumps(detail, default=str))),
            usage=usage,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        events = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
        events.append(entry.model_dump())
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(events, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # atomic swap: a crash mid-write can't corrupt earlier runs
