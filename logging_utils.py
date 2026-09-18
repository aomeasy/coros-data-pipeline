# -*- coding: utf-8 -*-
"""
logging_utils.py — Structured (JSON-lines) logging for the COROS pipeline.

Phase 0 goal: every sync run must leave a machine-readable trail so we can
answer "did today's sync succeed, and if not, why?" without re-reading raw
stdout. Human-readable console output is preserved (print still works),
this just *also* appends one JSON object per event to a log file.

Usage:
    from logging_utils import get_logger
    log = get_logger("coros_daily_sync")
    log.info("sync_started", email=email)
    log.warning("field_missing", field="hrv", date=date_str)
    log.error("login_failed", error=str(err))

Each call writes a line like:
    {"ts": "2026-09-18T09:00:12+07:00", "level": "INFO",
     "logger": "coros_daily_sync", "event": "sync_started", "email": "..."}

Log files live in ./logs/<name>-<YYYY-MM-DD>.jsonl (one file per day, so old
runs can be pruned/rotated trivially and GitHub Actions artifacts stay small).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"


class StructuredLogger:
    """Minimal dependency-free structured logger.

    Not meant to replace the stdlib `logging` module's full feature set —
    just enough to get consistent, greppable/parseable JSON lines out of a
    small pipeline without adding a new dependency.
    """

    LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}

    def __init__(self, name: str, min_level: str = "INFO", also_print: bool = True):
        self.name = name
        self.min_level = self.LEVELS.get(min_level.upper(), 20)
        self.also_print = also_print
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        self.log_path = LOG_DIR / f"{name}-{today}.jsonl"

    def _emit(self, level: str, event: str, **fields):
        if self.LEVELS.get(level, 0) < self.min_level:
            return
        record = {
            "ts": datetime.now(timezone.utc).astimezone().isoformat(),
            "level": level,
            "logger": self.name,
            "event": event,
        }
        # Fields must be JSON-serializable; fall back to str() if not.
        for k, v in fields.items():
            try:
                json.dumps(v)
                record[k] = v
            except (TypeError, ValueError):
                record[k] = str(v)

        line = json.dumps(record, ensure_ascii=False)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            # Logging must never crash the pipeline it's trying to observe.
            sys.stderr.write(f"[logging_utils] failed to write log: {e}\n")

        if self.also_print:
            stream = sys.stderr if level in ("ERROR", "CRITICAL") else sys.stdout
            extra = " ".join(f"{k}={v}" for k, v in fields.items())
            stream.write(f"[{record['ts']}] {level:8s} {event} {extra}\n".rstrip() + "\n")

    def debug(self, event: str, **fields):
        self._emit("DEBUG", event, **fields)

    def info(self, event: str, **fields):
        self._emit("INFO", event, **fields)

    def warning(self, event: str, **fields):
        self._emit("WARNING", event, **fields)

    def error(self, event: str, **fields):
        self._emit("ERROR", event, **fields)

    def critical(self, event: str, **fields):
        self._emit("CRITICAL", event, **fields)


_loggers: dict[str, StructuredLogger] = {}


def get_logger(name: str = "coros_pipeline", min_level: str | None = None) -> StructuredLogger:
    """Get (or create) a StructuredLogger, cached by name."""
    if name not in _loggers:
        level = min_level or os.environ.get("COROS_LOG_LEVEL", "INFO")
        _loggers[name] = StructuredLogger(name, min_level=level)
    return _loggers[name]
