# -*- coding: utf-8 -*-
"""
Unit tests สำหรับ strain_engine.py (Phase 2, Layer 1)
รัน: pytest test_strain_engine.py -v
"""

import math
import pytest
from strain_engine import (
    estimate_hr_max,
    estimate_hr_rest,
    banister_trimp,
    daily_trimp_from_activities,
    trimp_to_strain,
    compute_acwr,
    compute_strain_for_all_days,
    DEFAULT_HR_MAX_FALLBACK,
    DEFAULT_HR_REST_FALLBACK,
    STRAIN_SCALE_MAX,
)


# ---------------------------------------------------------------------------
# estimate_hr_max / estimate_hr_rest
# ---------------------------------------------------------------------------

def test_estimate_hr_max_uses_observed_max():
    activities = [{"max_hr": 180}, {"max_hr": 195}, {"max_hr": 170}]
    assert estimate_hr_max(activities) == 195

def test_estimate_hr_max_falls_back_when_no_data():
    assert estimate_hr_max([]) == DEFAULT_HR_MAX_FALLBACK

def test_estimate_hr_max_ignores_missing_field():
    activities = [{}, {"max_hr": None}]
    assert estimate_hr_max(activities) == DEFAULT_HR_MAX_FALLBACK

def test_estimate_hr_rest_averages_recent_sleep_records():
    sleep_records = [{"resting_hr": 50}, {"resting_hr": 60}]
    assert estimate_hr_rest(sleep_records) == 55

def test_estimate_hr_rest_falls_back_when_no_data():
    assert estimate_hr_rest([]) == DEFAULT_HR_REST_FALLBACK

def test_estimate_hr_rest_uses_only_last_14():
    # 20 records, only last 14 should count — first 6 are outliers at 200
    sleep_records = [{"resting_hr": 200}] * 6 + [{"resting_hr": 50}] * 14
    assert estimate_hr_rest(sleep_records) == 50


# ---------------------------------------------------------------------------
# banister_trimp
# ---------------------------------------------------------------------------

def test_banister_trimp_basic_male():
    trimp = banister_trimp(duration_min=60, avg_hr=150, hr_rest=55, hr_max=185, sex="male")
    hr_reserve = (150 - 55) / (185 - 55)
    expected = round(60 * hr_reserve * 0.64 * math.exp(1.92 * hr_reserve), 2)
    assert trimp == expected

def test_banister_trimp_female_uses_different_constants():
    trimp_m = banister_trimp(60, 150, 55, 185, sex="male")
    trimp_f = banister_trimp(60, 150, 55, 185, sex="female")
    assert trimp_m != trimp_f

def test_banister_trimp_missing_inputs_returns_none():
    assert banister_trimp(None, 150, 55, 185) is None
    assert banister_trimp(60, None, 55, 185) is None
    assert banister_trimp(60, 150, None, 185) is None
    assert banister_trimp(60, 150, 55, None) is None

def test_banister_trimp_invalid_hr_max_leq_rest():
    assert banister_trimp(60, 150, 60, 60) is None
    assert banister_trimp(60, 150, 70, 60) is None

def test_banister_trimp_clips_below_rest_hr():
    # avg_hr below hr_rest (sensor noise) should clip hr_reserve to 0, not go negative
    trimp = banister_trimp(60, 40, 55, 185)
    assert trimp == 0.0

def test_banister_trimp_zero_duration_is_none():
    assert banister_trimp(0, 150, 55, 185) is None


# ---------------------------------------------------------------------------
# daily_trimp_from_activities
# ---------------------------------------------------------------------------

def test_daily_trimp_sums_same_day_activities():
    activities = [
        {"start_time": "2026-09-15T06:00:00", "duration_s": 1800, "avg_hr": 130},
        {"start_time": "2026-09-15T18:00:00", "duration_s": 3600, "avg_hr": 150},
        {"start_time": "2026-09-16T06:00:00", "duration_s": 1800, "avg_hr": 130},
    ]
    daily = daily_trimp_from_activities(activities, hr_rest=55, hr_max=185)
    assert set(daily.keys()) == {"2026-09-15", "2026-09-16"}
    t1 = banister_trimp(30, 130, 55, 185)
    t2 = banister_trimp(60, 150, 55, 185)
    assert daily["2026-09-15"] == round(t1 + t2, 2)

def test_daily_trimp_skips_bad_date_format():
    activities = [{"start_time": "not-a-date", "duration_s": 1800, "avg_hr": 130}]
    daily = daily_trimp_from_activities(activities, 55, 185)
    assert daily == {}

def test_daily_trimp_skips_activity_with_no_hr():
    activities = [{"start_time": "2026-09-15T06:00:00", "duration_s": 1800, "avg_hr": None}]
    daily = daily_trimp_from_activities(activities, 55, 185)
    assert daily == {}


# ---------------------------------------------------------------------------
# trimp_to_strain
# ---------------------------------------------------------------------------

def test_trimp_to_strain_zero_is_zero():
    assert trimp_to_strain(0) == 0.0
    assert trimp_to_strain(None) == 0.0
    assert trimp_to_strain(-5) == 0.0

def test_trimp_to_strain_saturates_near_max():
    # Mathematically asymptotic (never truly reaches 21), but rounds to 21.0
    # at absurd trimp values — that's a display rounding artifact, not a bug.
    # What matters: it never EXCEEDS the scale max.
    strain = trimp_to_strain(100000)
    assert strain <= STRAIN_SCALE_MAX
    # a realistic "very hard day" (trimp ~300) should still leave headroom
    assert trimp_to_strain(300) < STRAIN_SCALE_MAX

def test_trimp_to_strain_monotonic_increasing():
    vals = [trimp_to_strain(t) for t in [0, 20, 50, 100, 200]]
    assert all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))


# ---------------------------------------------------------------------------
# compute_acwr
# ---------------------------------------------------------------------------

def _make_daily_trimp(start_date, values):
    from datetime import datetime, timedelta
    d0 = datetime.strptime(start_date, "%Y-%m-%d")
    return {(d0 + timedelta(days=i)).strftime("%Y-%m-%d"): v for i, v in enumerate(values)}

def test_compute_acwr_insufficient_data_returns_building():
    daily = _make_daily_trimp("2026-09-01", [50] * 5)
    result = compute_acwr(daily, "2026-09-05")
    assert result["confidence"] == "building"
    assert result["risk"] == "unknown"

def test_compute_acwr_high_risk_flag():
    # 28 days of low steady load, then 7 days of high load -> ACWR should spike > 1.5
    values = [20] * 21 + [80] * 7
    daily = _make_daily_trimp("2026-08-01", values)
    last_date = sorted(daily.keys())[-1]
    result = compute_acwr(daily, last_date)
    assert result["acwr"] > 1.5
    assert result["risk"] == "high"

def test_compute_acwr_normal_when_steady():
    values = [40] * 28
    daily = _make_daily_trimp("2026-08-01", values)
    last_date = sorted(daily.keys())[-1]
    result = compute_acwr(daily, last_date)
    assert 0.9 <= result["acwr"] <= 1.1
    assert result["risk"] == "normal"

def test_compute_acwr_bad_date_returns_none():
    assert compute_acwr({}, "not-a-date") is None


# ---------------------------------------------------------------------------
# compute_strain_for_all_days — integration
# ---------------------------------------------------------------------------

def test_compute_strain_for_all_days_end_to_end():
    activities = [
        {"start_time": "2026-09-15T18:00:00", "duration_s": 3600, "avg_hr": 150, "max_hr": 180},
        {"start_time": "2026-09-16T18:00:00", "duration_s": 1800, "avg_hr": 130, "max_hr": 170},
    ]
    sleep_records = [{"resting_hr": 55}] * 5
    results = compute_strain_for_all_days(activities, sleep_records)
    assert len(results) == 2
    dates = [r["date"] for r in results]
    assert dates == sorted(dates)  # เรียงเก่า->ใหม่
    for r in results:
        assert r["trimp"] > 0
        assert 0 <= r["strain"] <= STRAIN_SCALE_MAX

def test_compute_strain_for_all_days_no_activities_returns_empty():
    assert compute_strain_for_all_days([], []) == []
