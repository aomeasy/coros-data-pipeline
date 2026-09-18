# -*- coding: utf-8 -*-
"""
Phase 0 — first test suite for sleep_analysis.py.

Scope: the pure, side-effect-free functions that the rest of the pipeline
(app.py's /api/analysis, weekly reports, anomaly detection) all depend on.
These are prioritized first because they're the load-bearing math — a
regression here silently corrupts every Recovery/SQI number downstream.

Run with:  pytest -q
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sleep_analysis as sa


# ---------------------------------------------------------------------------
# sleep_efficiency
# ---------------------------------------------------------------------------
class TestSleepEfficiency:
    def test_uses_explicit_time_in_bed(self):
        rec = {"total_sleep_min": 420, "time_in_bed_min": 480}
        assert sa.sleep_efficiency(rec) == 87.5

    def test_estimates_time_in_bed_from_awake(self):
        # time_in_bed = duration + awake*1.5 = 400 + 20*1.5 = 430
        rec = {"duration_min": 400, "awake_min": 20}
        eff = sa.sleep_efficiency(rec)
        assert eff == round(400 / 430 * 100, 1)

    def test_zero_time_in_bed_returns_zero(self):
        assert sa.sleep_efficiency({"duration_min": 0, "awake_min": 0}) == 0.0

    def test_capped_at_100(self):
        # total_sleep > time_in_bed shouldn't be possible in real data, but
        # the function must not return an efficiency above 100%.
        rec = {"total_sleep_min": 500, "time_in_bed_min": 400}
        assert sa.sleep_efficiency(rec) == 100.0


# ---------------------------------------------------------------------------
# z_score / flag_metric
# ---------------------------------------------------------------------------
class TestZScore:
    def test_basic(self):
        baseline = {"mean": 50, "stdev": 10}
        assert sa.z_score(60, baseline) == 1.0
        assert sa.z_score(40, baseline) == -1.0

    def test_none_when_no_stdev(self):
        assert sa.z_score(60, {"mean": 50, "stdev": 0}) is None
        assert sa.z_score(60, {"mean": 50, "stdev": None}) is None

    def test_none_when_value_none(self):
        assert sa.z_score(None, {"mean": 50, "stdev": 10}) is None


class TestFlagMetric:
    def test_normal_range(self):
        baseline = {"mean": 50, "stdev": 10}
        result = sa.flag_metric(52, baseline)
        assert result["status"] == "normal"

    def test_critical_low(self):
        baseline = {"mean": 50, "stdev": 10}
        result = sa.flag_metric(25, baseline)  # z = -2.5
        assert result["status"] == "critical_low"

    def test_invert_for_rhr_style_metrics(self):
        # High RHR is bad -> invert=True means a *high* value should flag
        # as elevated, not "unusually_high" treated as good.
        baseline = {"mean": 55, "stdev": 5}
        result = sa.flag_metric(70, baseline, invert=True)  # z=+3 -> inverted -3
        assert result["status"] == "critical_low"


# ---------------------------------------------------------------------------
# compute_baseline
# ---------------------------------------------------------------------------
class TestComputeBaseline:
    def test_insufficient_data(self):
        records = [{"hrv": 40}, {"hrv": 42}]
        result = sa.compute_baseline(records, ["hrv"])
        assert result["mean"] is None
        assert result["n"] == 2

    def test_mean_and_stdev(self):
        records = [{"hrv": v} for v in [40, 42, 44, 46, 48]]
        result = sa.compute_baseline(records, ["hrv"])
        assert result["mean"] == 44.0
        assert result["n"] == 5
        assert result["stdev"] > 0

    def test_skips_missing_values(self):
        records = [{"hrv": 40}, {"hrv": None}, {"hrv": 44}, {"hrv": 46}, {"hrv": 48}]
        result = sa.compute_baseline(records, ["hrv"])
        assert result["n"] == 4  # None skipped


# ---------------------------------------------------------------------------
# sleep_performance / cumulative_sleep_debt
# ---------------------------------------------------------------------------
class TestSleepPerformance:
    def test_basic(self):
        assert sa.sleep_performance(420, 480) == 87.5

    def test_capped_at_120_pct(self):
        assert sa.sleep_performance(700, 480) == 120.0

    def test_zero_need(self):
        assert sa.sleep_performance(400, 0) == 0.0


class TestCumulativeSleepDebt:
    def test_no_debt_when_meeting_need(self):
        records = [{"duration_min": 480}] * 7
        needs = [480] * 7
        assert sa.cumulative_sleep_debt(records, needs) == 0.0

    def test_accumulates_debt(self):
        records = [{"duration_min": 400}] * 3  # 80 min short each day
        needs = [480] * 3
        debt = sa.cumulative_sleep_debt(records, needs, decay=1.0)  # no decay
        # day1: 80, day2: 80*1 + 80=160, day3: 160+80=240
        assert debt == 240.0

    def test_decay_reduces_old_debt(self):
        records = [{"duration_min": 400}, {"duration_min": 480}, {"duration_min": 480}]
        needs = [480, 480, 480]
        debt = sa.cumulative_sleep_debt(records, needs, decay=0.9)
        # day1: 80, day2: 80*0.9+0=72, day3: 72*0.9+0=64.8
        assert debt == 64.8


# ---------------------------------------------------------------------------
# calculate_sqi
# ---------------------------------------------------------------------------
class TestCalculateSQI:
    def test_no_records(self):
        result = sa.calculate_sqi([])
        assert result["sqi"] is None
        assert result["band"] == "no_data"

    def test_good_sleep_scores_high(self):
        records = [{
            "total_sleep_min": 480, "time_in_bed_min": 500,
            "duration_min": 480,
            "deep_sleep_pct": 18, "rem_sleep_pct": 22,
            "sleep_start": f"2026-01-{10+i:02d}T23:00:00",
        } for i in range(7)]
        result = sa.calculate_sqi(records)
        assert result["sqi"] is not None
        assert 0 <= result["sqi"] <= 100
        assert result["band"] in ("good", "fair", "poor")

    def test_sqi_bounded_0_100(self):
        # Deliberately bad inputs shouldn't push the composite out of range.
        records = [{"duration_min": 0, "deep_sleep_pct": 0, "rem_sleep_pct": 0}] * 7
        result = sa.calculate_sqi(records)
        assert 0 <= result["sqi"] <= 100


# ---------------------------------------------------------------------------
# recovery_score
# ---------------------------------------------------------------------------
class TestRecoveryScore:
    def test_bounded_0_100(self):
        result = sa.recovery_score(
            hrv_today=20, hrv_baseline={"mean": 50, "stdev": 10},
            rhr_today=80, rhr_baseline={"mean": 55, "stdev": 5},
            sleep_performance_pct=40, sleep_efficiency_pct=50,
            spo2_flag="review_recommended", skin_temp_flag="elevated",
            resp_rate_z=2.0,
        )
        assert 0 <= result["recovery_score"] <= 100
        assert result["band"] in ("green", "yellow", "red")

    def test_good_inputs_yield_green_band(self):
        result = sa.recovery_score(
            hrv_today=60, hrv_baseline={"mean": 50, "stdev": 10},
            rhr_today=48, rhr_baseline={"mean": 55, "stdev": 5},
            sleep_performance_pct=95, sleep_efficiency_pct=92,
            spo2_flag="normal", skin_temp_flag="normal", resp_rate_z=0,
        )
        assert result["band"] == "green"

    def test_defaults_dont_crash_with_missing_data(self):
        result = sa.recovery_score()
        assert 0 <= result["recovery_score"] <= 100


# ---------------------------------------------------------------------------
# fragmentation_index / bedtime_consistency
# ---------------------------------------------------------------------------
class TestFragmentationIndex:
    def test_no_transitions(self):
        timeline = [(i, "light") for i in range(10)]
        assert sa.fragmentation_index(timeline, total_sleep_min=60) == 0.0

    def test_counts_transitions_per_hour(self):
        timeline = [(0, "light"), (1, "deep"), (2, "light"), (3, "rem")]
        # 3 transitions over 60 min = 3 per hour
        result = sa.fragmentation_index(timeline, total_sleep_min=60)
        assert result == 3.0

    def test_empty_timeline(self):
        assert sa.fragmentation_index([], total_sleep_min=60) is None


class TestBedtimeConsistency:
    def test_insufficient_data(self):
        records = [{"sleep_start": "2026-01-01T23:00:00"}]
        assert sa.bedtime_consistency(records) is None

    def test_consistent_bedtimes_score_high(self):
        records = [
            {"sleep_start": f"2026-01-{d:02d}T23:00:00"} for d in range(10, 17)
        ]
        score = sa.bedtime_consistency(records)
        assert score is not None
        assert score > 90  # near-zero stdev -> near-100 score
