# -*- coding: utf-8 -*-
"""Tests for data_validation.py (Phase 0 hardening)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import data_validation as dv


class TestValidateSleepRecord:
    def test_valid_record_has_no_issues(self):
        rec = {
            "date": "2026-09-17", "hrv": 45, "resting_hr": 52,
            "duration_min": 420, "awake_min": 15,
            "deep_sleep_pct": 18, "light_sleep_pct": 60, "rem_sleep_pct": 22,
            "sleep_score": 85,
        }
        issues = dv.validate_sleep_record(rec)
        assert issues == []

    def test_negative_hrv_rejected(self):
        rec = {"date": "2026-09-17", "hrv": -5}
        issues = dv.validate_sleep_record(rec)
        assert any(i.field == "hrv" and i.severity == "reject" for i in issues)

    def test_impossible_duration_rejected(self):
        rec = {"date": "2026-09-17", "duration_min": 2000}  # > 16h
        issues = dv.validate_sleep_record(rec)
        assert any(i.field == "duration_min" and i.severity == "reject" for i in issues)

    def test_missing_date_is_blocking(self):
        rec = {"hrv": 45}
        issues = dv.validate_sleep_record(rec)
        assert dv.has_blocking_issue(issues)

    def test_stage_pct_sum_over_100_warns(self):
        rec = {"date": "2026-09-17", "deep_sleep_pct": 40, "light_sleep_pct": 50, "rem_sleep_pct": 30}
        issues = dv.validate_sleep_record(rec)
        warn = [i for i in issues if i.field == "stage_pct_sum"]
        assert len(warn) == 1
        assert warn[0].severity == "warning"

    def test_none_values_are_skipped_not_flagged(self):
        rec = {"date": "2026-09-17", "hrv": None, "resting_hr": None}
        issues = dv.validate_sleep_record(rec)
        assert issues == []


class TestValidateDailyHealthRecord:
    def test_valid_record(self):
        rec = {"date": "2026-09-17", "steps": 8000, "avg_hr": 70, "spo2_avg": 97}
        assert dv.validate_daily_health_record(rec) == []

    def test_absurd_steps_rejected(self):
        rec = {"date": "2026-09-17", "steps": 5_000_000}
        issues = dv.validate_daily_health_record(rec)
        assert any(i.field == "steps" and i.severity == "reject" for i in issues)

    def test_missing_date_blocking(self):
        rec = {"steps": 1000}
        assert dv.has_blocking_issue(dv.validate_daily_health_record(rec))


class TestValidateActivityRecord:
    def test_valid_record(self):
        rec = {"activity_id": "12345", "distance_m": 5000, "duration_s": 1800, "avg_hr": 150}
        assert dv.validate_activity_record(rec) == []

    def test_missing_activity_id_blocking(self):
        rec = {"distance_m": 5000}
        assert dv.has_blocking_issue(dv.validate_activity_record(rec))

    def test_negative_distance_rejected(self):
        rec = {"activity_id": "1", "distance_m": -100}
        issues = dv.validate_activity_record(rec)
        assert any(i.field == "distance_m" and i.severity == "reject" for i in issues)


class TestCleanFunctions:
    def test_clean_sleep_record_nulls_bad_field_keeps_good_ones(self):
        rec = {"date": "2026-09-17", "hrv": -10, "resting_hr": 55}
        clean, issues = dv.clean_sleep_record(rec)
        assert clean["hrv"] is None
        assert clean["resting_hr"] == 55
        assert clean["date"] == "2026-09-17"

    def test_clean_daily_health_record(self):
        rec = {"date": "2026-09-17", "steps": -1, "avg_hr": 70}
        clean, issues = dv.clean_daily_health_record(rec)
        assert clean["steps"] is None
        assert clean["avg_hr"] == 70

    def test_clean_activity_record_preserves_valid_id(self):
        rec = {"activity_id": "999", "avg_hr": 999999}
        clean, issues = dv.clean_activity_record(rec)
        assert clean["activity_id"] == "999"
        assert clean["avg_hr"] is None
