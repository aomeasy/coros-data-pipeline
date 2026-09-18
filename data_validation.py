# -*- coding: utf-8 -*-
"""
data_validation.py — Sanity-checks records BEFORE they hit SQLite.

Phase 0 goal: a parsing bug or a weird COROS API response should never
silently poison the database with a physiologically impossible value
(negative HRV, 40-hour sleep, SpO2 of 12%, ...). Every downstream metric in
sleep_analysis.py / breath_analysis.py trusts these numbers, so bad data in
== confidently wrong recovery scores out.

Design:
- Pure functions, no DB / IO — easy to unit test.
- `validate_sleep_record`, `validate_daily_health_record`,
  `validate_activity_record` each return a list of `ValidationIssue`.
- Issues have a `severity` of "warning" (value looks suspicious but is kept,
  e.g. clamped or flagged) or "reject" (value is physiologically impossible
  and must be dropped/nulled before storage).
- `clean_sleep_record` etc. apply the fixes and return (clean_record, issues)
  so callers can log what happened without hand-writing that logic per field.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple


@dataclass
class ValidationIssue:
    field: str
    message: str
    severity: str  # "warning" | "reject"
    original_value: Any = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
            "original_value": self.original_value,
        }


# ---------------------------------------------------------------------------
# Plausible physiological ranges. Deliberately generous (these are sanity
# checks against parsing bugs / API glitches, not medical thresholds) — see
# sleep_analysis.py baselines for what's actually "normal" for a given user.
# ---------------------------------------------------------------------------
RANGES = {
    "hrv": (2, 300),               # ms (rMSSD-style values from COROS)
    "resting_hr": (25, 140),       # bpm
    "duration_min": (0, 960),      # sleep duration, cap at 16h
    "awake_min": (0, 600),
    "deep_sleep_pct": (0, 100),
    "light_sleep_pct": (0, 100),
    "rem_sleep_pct": (0, 100),
    "sleep_score": (0, 100),
    "spo2_avg": (60, 100),
    "spo2_min": (50, 100),
    "steps": (0, 100000),
    "stress_score": (0, 100),
    "avg_hr": (25, 230),
    "max_hr": (25, 250),
    "calories_burned": (0, 20000),
    "distance_m": (0, 500000),     # 500 km ceiling — generous for ultras
    "duration_s": (0, 172800),     # 48h ceiling for an activity
}


def _check_range(rec: dict, key: str) -> List[ValidationIssue]:
    issues = []
    if key not in rec or rec[key] is None:
        return issues
    lo, hi = RANGES[key]
    val = rec[key]
    if not isinstance(val, (int, float)):
        issues.append(ValidationIssue(key, f"expected numeric, got {type(val).__name__}",
                                       "reject", val))
        return issues
    if val < lo or val > hi:
        issues.append(ValidationIssue(
            key, f"value {val} outside plausible range [{lo}, {hi}]",
            "reject", val,
        ))
    return issues


def validate_sleep_record(rec: dict) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for key in ("hrv", "resting_hr", "duration_min", "awake_min",
                "deep_sleep_pct", "light_sleep_pct", "rem_sleep_pct", "sleep_score"):
        issues += _check_range(rec, key)

    # Cross-field checks: stage percentages shouldn't sum wildly over 100.
    stage_sum = sum(
        rec.get(k) or 0 for k in ("deep_sleep_pct", "light_sleep_pct", "rem_sleep_pct")
    )
    if stage_sum > 105:  # small slack for rounding
        issues.append(ValidationIssue(
            "stage_pct_sum", f"deep+light+rem = {stage_sum:.1f}% (expected ~100%)",
            "warning", stage_sum,
        ))

    if not rec.get("date"):
        issues.append(ValidationIssue("date", "missing date — record cannot be stored", "reject", None))

    return issues


def validate_daily_health_record(rec: dict) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for key in ("steps", "stress_score", "avg_hr", "max_hr", "calories_burned",
                "spo2_avg", "spo2_min"):
        issues += _check_range(rec, key)

    if not rec.get("date"):
        issues.append(ValidationIssue("date", "missing date — record cannot be stored", "reject", None))

    return issues


def validate_activity_record(rec: dict) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    for key in ("distance_m", "duration_s", "avg_hr", "max_hr", "calories_burned"):
        issues += _check_range(rec, key)

    if not rec.get("activity_id") and not rec.get("activityId"):
        issues.append(ValidationIssue("activity_id", "missing activity id — record cannot be stored",
                                       "reject", None))
    return issues


def _apply_fixes(rec: dict, issues: List[ValidationIssue]) -> dict:
    """Null out fields with a 'reject' severity issue; leave 'warning' fields as-is."""
    clean = dict(rec)
    for issue in issues:
        if issue.severity == "reject" and issue.field in clean:
            clean[issue.field] = None
    return clean


def clean_sleep_record(rec: dict) -> Tuple[dict, List[ValidationIssue]]:
    issues = validate_sleep_record(rec)
    return _apply_fixes(rec, issues), issues


def clean_daily_health_record(rec: dict) -> Tuple[dict, List[ValidationIssue]]:
    issues = validate_daily_health_record(rec)
    return _apply_fixes(rec, issues), issues


def clean_activity_record(rec: dict) -> Tuple[dict, List[ValidationIssue]]:
    issues = validate_activity_record(rec)
    return _apply_fixes(rec, issues), issues


def has_blocking_issue(issues: List[ValidationIssue]) -> bool:
    """True if the record is missing something required (e.g. date/id) and
    should not be stored at all, as opposed to a field that was merely
    nulled out."""
    return any(
        i.severity == "reject" and i.field in ("date", "activity_id")
        for i in issues
    )
