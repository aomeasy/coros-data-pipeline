# -*- coding: utf-8 -*-
"""
training_analytics.py — Phase 4: Training & Performance Analytics

- CTL/ATL/TSB (Fitness/Fatigue/Form) แบบ TrainingPeaks
- Running Economy Trend (Pace ที่ HR เดียวกัน)
- Race/Event Readiness Score
- Strain ↔ Performance Lag Correlation
"""

import math
from typing import List, Dict, Optional
import numpy


# =============================================================================
# Config
# =============================================================================

CTL_HALF_LIFE = 42   # Fitness: 42 วัน
ATL_HALF_LIFE = 7    # Fatigue: 7 วัน
ECONOMY_WINDOW = 14  # 14 วันสำหรับ running economy


# =============================================================================
# 1. CTL / ATL / TSB Engine
# =============================================================================

def compute_ctl_atl_tsb(daily_loads: List[float]) -> dict:
    """
    คำนวณ CTL/ATL/TSB จาก training load รายวัน

    CTL = EWMA 42 วัน (Fitness)
    ATL = EWMA 7 วัน (Fatigue)
    TSB = CTL - ATL (Form)

    daily_loads: list ของ TRIMP/TRIMP_equivalent รายวัน (เก่า -> ใหม่)
    """
    if not daily_loads or len(daily_loads) < 7:
        return {"ctl": None, "atl": None, "tsb": None, "confidence": "building"}

    def ewma(values, half_life):
        alpha = 1 - math.exp(-math.log(2) / half_life)
        result = values[0]
        for v in values[1:]:
            result = alpha * v + (1 - alpha) * result
        return result

    ctl = ewma(daily_loads, CTL_HALF_LIFE)
    atl = ewma(daily_loads, ATL_HALF_LIFE)
    tsb = ctl - atl

    confidence = "stable" if len(daily_loads) >= 42 else "moderate" if len(daily_loads) >= 14 else "building"

    return {
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(tsb, 1),
        "confidence": confidence,
    }


# =============================================================================
# 2. Running Economy Trend
# =============================================================================

def compute_running_economy(activities: List[dict], window: int = ECONOMY_WINDOW) -> dict:
    """
    Running Economy = Pace ที่ HR เฉลี่ยเดียวกัน
    ค่าลด = ดีขึ้น (วิ่งเร็วขึ้นด้วย HR เดียวกัน)

    activities: list ของ dict ที่มี duration_s, distance_m, avg_hr
    """
    runs = []
    for a in activities:
        dist = a.get("distance_m", 0) or 0
        dur = a.get("duration_s", 0) or 0
        hr = a.get("avg_hr") or 0
        if dist > 1000 and dur > 120 and hr > 100:
            pace = dur / (dist / 1000)
            runs.append({"date": a.get("start_time", ""), "pace": pace, "hr": hr})

    if len(runs) < 3:
        return {"trend": None, "economy_change": None, "confidence": "insufficient"}

    mid = len(runs) // 2
    first_half = runs[:mid]
    second_half = runs[mid:]

    def avg_economy(run_list):
        valid = [r for r in run_list if 140 <= r["hr"] <= 170]
        if len(valid) < 2:
            return None
        return sum(r["pace"] for r in valid) / len(valid)

    econ1 = avg_economy(first_half)
    econ2 = avg_economy(second_half)

    if econ1 is None or econ2 is None or econ1 == 0:
        return {"trend": None, "economy_change": None, "confidence": "insufficient"}

    change = ((econ2 - econ1) / econ1) * 100

    return {
        "trend": "improving" if change < -1 else "declining" if change > 1 else "stable",
        "economy_change_pct": round(change, 2),
        "recent_economy": round(econ2, 1),
        "confidence": "moderate" if len(runs) >= 10 else "building",
    }


# =============================================================================
# 3. Race/Event Readiness Score
# =============================================================================

def compute_race_readiness(
    recovery_score: float = 50,
    ctl: float = 0,
    ctl_baseline: float = 100,
    sleep_debt: float = 0,
    training_load_7d: float = 0,
) -> dict:
    """
    Race Readiness Score (0-100)
    รวม Recovery + Fitness + Sleep + Load
    """
    rec_component = min(recovery_score, 100) * 0.30

    if ctl_baseline > 0:
        fitness_ratio = min(ctl / ctl_baseline, 1.2)
    else:
        fitness_ratio = 0.5
    fitness_component = fitness_ratio * 100 * 0.30

    debt_penalty = min(sleep_debt / 60, 3) * 10
    sleep_component = (100 - debt_penalty) * 0.20

    load_penalty = min(training_load_7d / 500, 1) * 30
    load_component = (100 - load_penalty) * 0.20

    total = rec_component + fitness_component + sleep_component + load_component
    total = round(max(0, min(100, total)), 1)

    if total >= 80:
        band = "ready"
    elif total >= 60:
        band = "moderate"
    else:
        band = "not_ready"

    return {
        "readiness_score": total,
        "band": band,
        "components": {
            "recovery": round(rec_component / 0.30, 1),
            "fitness": round(fitness_component / 0.30, 1),
            "sleep": round(sleep_component / 0.20, 1),
            "load": round(load_component / 0.20, 1),
        },
    }


# =============================================================================
# 4. Strain ↔ Performance Lag Correlation
# =============================================================================

def correlate_strain_performance(
    strain_series: List[dict],
    activities: List[dict],
    max_lag: int = 3,
) -> dict:
    """
    หา lag correlation ระหว่าง Strain กับ Performance (Pace/HR)
    บอกว่าซ้อมหนักแล้ว performance ลดลงกี่วัน
    """
    if len(strain_series) < 7 or len(activities) < 5:
        return {"lag_days": None, "correlation": None, "confidence": "insufficient"}

    strain_by_date = {}
    for s in strain_series:
        d = s.get("date", "")
        if d:
            strain_by_date[d[:10]] = s.get("trimp", 0)

    perf_by_date = {}
    for a in activities:
        d = a.get("start_time", "")
        dist = a.get("distance_m", 0) or 0
        dur = a.get("duration_s", 0) or 0
        hr = a.get("avg_hr") or 0
        if dist > 1000 and dur > 120 and hr > 100:
            pace = dur / (dist / 1000)
            perf_by_date[d[:10]] = pace / hr

    if len(strain_by_date) < 5 or len(perf_by_date) < 5:
        return {"lag_days": None, "correlation": None, "confidence": "insufficient"}

    best_lag = 0
    best_corr = 0

    for lag in range(0, min(max_lag + 1, len(strain_by_date))):
        strain_vals = []
        perf_vals = []

        for date_str in sorted(strain_by_date.keys()):
            from datetime import datetime, timedelta
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                perf_date = (d + timedelta(days=lag)).strftime("%Y-%m-%d")
                if perf_date in perf_by_date:
                    strain_vals.append(strain_by_date[date_str])
                    perf_vals.append(perf_by_date[perf_date])
            except ValueError:
                continue

        if len(strain_vals) >= 5:
            try:
                corr = float(numpy.corrcoef(strain_vals, perf_vals)[0, 1])
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_lag = lag
            except:
                continue

    return {
        "lag_days": best_lag,
        "correlation": round(best_corr, 3) if best_corr else None,
        "confidence": "moderate" if len(strain_series) >= 14 else "building",
    }


# =============================================================================
# High-level entry point
# =============================================================================

def compute_training_analytics(
    activities: List[dict],
    strain_series: List[dict],
    sleep_records: List[dict],
    recovery_score: float = 50,
    ctl_baseline: float = 100,
) -> dict:
    """
    คำนวณ training analytics ทั้งหมดในที่เดียว
    """
    # CTL/ATL/TSB
    daily_loads = [s.get("trimp", 0) for s in strain_series]
    fitness = compute_ctl_atl_tsb(daily_loads)

    # Running Economy
    economy = compute_running_economy(activities)

    # Race Readiness
    sleep_debt = 0
    if sleep_records:
        avg_duration = sum(r.get("duration_min", 0) or 0 for r in sleep_records[-7:]) / max(len(sleep_records[-7:]), 1)
        sleep_debt = max(0, 480 - avg_duration) * 7

    load_7d = sum(daily_loads[-7:]) if len(daily_loads) >= 7 else 0

    readiness = compute_race_readiness(
        recovery_score=recovery_score,
        ctl=fitness.get("ctl", 0),
        ctl_baseline=ctl_baseline,
        sleep_debt=sleep_debt,
        training_load_7d=load_7d,
    )

    # Strain ↔ Performance
    lag_corr = correlate_strain_performance(strain_series, activities)

    return {
        "fitness": fitness,
        "economy": economy,
        "readiness": readiness,
        "strain_performance": lag_corr,
    }
