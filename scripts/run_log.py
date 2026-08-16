import csv
import uuid
from datetime import datetime
from pathlib import Path

from .config_loader import BASE_DIR, load_config


def new_run_id() -> str:
    return f"RUN-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _log_path() -> Path:
    cfg = load_config()
    return BASE_DIR / cfg["output"]["run_log_file"]


def append_run(record: dict):
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = [
        "run_id", "date", "start_time", "end_time",
        "total_requests", "total_depts", "files_created",
        "emails_sent", "emails_failed", "unassigned",
        "status", "failure_stage", "failure_reason",
    ]
    row = {c: record.get(c, "") for c in cols}
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return path


def load_runs() -> list:
    path = _log_path()
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))
