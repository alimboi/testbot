import os
import json
import time
import threading
from pathlib import Path

AUDIT_FILE = Path(os.getenv("AUDIT_FILE", "logs/audit.jsonl"))
_audit_lock = threading.Lock()

def log_action(
    actor_id: int,
    action: str,
    ok: bool = True,
    target_id: int | None = None,
    group_id: int | None = None,
    test_id: str | None = None,
    note: str | None = None,
    extra: dict | None = None
) -> None:
    rec = {
        "ts": int(time.time()),
        "actor_id": actor_id,
        "action": action,
        "ok": bool(ok),
    }
    if target_id is not None:
        rec["target_id"] = target_id
    if group_id is not None:
        rec["group_id"] = group_id
    if test_id is not None:
        rec["test_id"] = test_id
    if note:
        rec["note"] = str(note)
    if extra:
        rec["extra"] = extra

    with _audit_lock:
        try:
            AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
            with AUDIT_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception as e:
            import sys
            print(f"AUDIT LOG ERROR: {e} | Record: {rec}", file=sys.stderr)

def read_audit_logs(limit: int = 1000) -> list[dict]:
    if not AUDIT_FILE.exists():
        return []
    try:
        lines = []
        with AUDIT_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return lines[-limit:] if limit > 0 else lines
    except Exception:
        return []