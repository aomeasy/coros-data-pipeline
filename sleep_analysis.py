# -*- coding: utf-8 -*-
"""
Sleep Analysis Module v2 — ฟังก์ชันวิเคราะห์การนอนแบบละเอียด (Rule-based, ไม่พึ่ง AI API)
"""
import statistics
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Callable, Any, Tuple


# =============================================================================
# 1. Basic Metrics
# =============================================================================

def sleep_efficiency(record: dict) -> float:
    """
    Sleep Efficiency (%) = (total_sleep_min / time_in_bed_min) × 100
    ถ้าไม่มี time_in_bed_min → ประมาณจาก duration_min + (awake_min * 1.5)
    """
    total_sleep = record.get("total_sleep_min") or record.get("duration_min", 0)
    time_in_bed = record.get("time_in_bed_min")
    if not time_in_bed:
        awake = record.get("awake_min", 0) or 0
        time_in_bed = total_sleep + int(awake * 1.5)
    if time_in_bed <= 0:
        return 0.0
    return round(min((total_sleep / time_in_bed) * 100, 100.0), 1)


def estimate_latency(stage_timeline: list) -> Optional[int]:
    """
    ประมาณ Sleep Onset Latency (นาที)
    stage_timeline: list of (datetime, stage_str) tuples
    """
    if not stage_timeline:
        return None
    first_ts = stage_timeline[0][0]
    for ts, stage in stage_timeline:
        if stage != "awake":
            delta = (ts - first_ts).total_seconds() / 60
            return int(delta)
    return None


def stage_percentages(record: dict) -> dict:
    """
    คำนวณสัดส่วนช่วงนอน (% ของ total_sleep)
    ใช้ค่าจริงจาก record โดยตรง (deep/light/REM pct ที่ COROS ให้มา)
    """
    total = record.get("duration_min", 0) or record.get("total_sleep_min", 0)
    if total <= 0:
        return {}

    stages = {}
    deep_pct = record.get("deep_sleep_pct")
    light_pct = record.get("light_sleep_pct")
    rem_pct = record.get("rem_sleep_pct")

    if deep_pct is not None:
        stages["deep"] = deep_pct
    if light_pct is not None:
        stages["light"] = light_pct
    if rem_pct is not None:
        stages["rem"] = rem_pct

    # If we have the stages dict from detailed data
    if "stages" in record and isinstance(record["stages"], dict):
        stages_data = record["stages"]
        return {
            k: round(v / total * 100, 1)
            for k, v in stages_data.items()
            if k != "awake" and v is not None
        }

    return stages


# =============================================================================
# 2. Sleep Architecture Analysis
# =============================================================================

def compute_baseline(records: list, metric_path: list, window: int = 30) -> dict:
    """
    คำนวณ rolling average/stdev ของ metric ตาม path
    metric_path: list of keys to traverse (e.g. ["duration_min"] or ["stages", "deep"])
    """
    values = []
    for r in records[-window:]:
        v = r
        try:
            for key in metric_path:
                if isinstance(v, dict):
                    v = v.get(key)
                elif isinstance(v, (list, tuple)) and isinstance(key, int):
                    v = v[key] if key < len(v) else None
                else:
                    v = None
                    break
            if v is not None and isinstance(v, (int, float)):
                values.append(float(v))
        except (KeyError, TypeError, IndexError):
            continue

    if len(values) < 5:
        return {"mean": None, "stdev": None, "n": len(values)}

    return {
        "mean": round(statistics.mean(values), 2),
        "stdev": round(statistics.stdev(values), 2) if len(values) >= 2 else 0.0,
        "n": len(values),
    }


def z_score(value: float, baseline: dict) -> Optional[float]:
    """คำนวณ Z-score เทียบ baseline"""
    if baseline.get("stdev") in (None, 0) or value is None:
        return None
    if baseline.get("mean") is None:
        return None
    return round((value - baseline["mean"]) / baseline["stdev"], 2)


def flag_metric(value: float, baseline: dict, invert: bool = False) -> dict:
    """
    Flag metric ว่าอยู่ในเกณฑ์ปกติหรือไม่
    invert=True → ค่ามากเกินดี (เช่น HRV สูง = ดี, RHR ต่ำ = ดี)
    """
    z = z_score(value, baseline)
    z_eff = -z if (z is not None and invert) else z
    status = "normal"
    if z_eff is not None:
        if z_eff <= -2.0:
            status = "critical_low"
        elif z_eff <= -1.5:
            status = "low"
        elif z_eff >= 2.0:
            status = "unusually_high"
        elif z_eff >= 1.5:
            status = "elevated"
    return {"z_score": z, "status": status}


def estimate_cycles(stage_timeline: list) -> dict:
    """
    ประมาณจำนวน sleep cycles จาก stage timeline
    cycle ≈ การเปลี่ยนจาก light → deep → rem
    """
    if not stage_timeline:
        return {"cycle_count": 0, "avg_cycle_length_min": None}

    cycles = 0
    prev_stage = None
    entered_light_since_last_deep = False

    for ts, stage in stage_timeline:
        if stage == "light":
            entered_light_since_last_deep = True
        if stage in ("deep", "rem") and entered_light_since_last_deep and prev_stage != stage:
            cycles += 1
            entered_light_since_last_deep = False
        prev_stage = stage

    total_sleep_min = sum(1 for _, s in stage_timeline if s != "awake")
    avg_cycle_len = round(total_sleep_min / cycles, 1) if cycles > 0 else None
    return {"cycle_count": cycles, "avg_cycle_length_min": avg_cycle_len}


def fragmentation_index(stage_timeline: list, total_sleep_min: float) -> Optional[float]:
    """
    Fragmentation Index = transitions per hour
    <8/ชม. ดี, 8–15 ปานกลาง, >15 ไม่ต่อเนื่อง
    """
    if not stage_timeline or total_sleep_min <= 0:
        return None
    transitions = sum(
        1
        for i in range(1, len(stage_timeline))
        if stage_timeline[i][1] != stage_timeline[i - 1][1]
    )
    hours = total_sleep_min / 60
    return round(transitions / hours, 2) if hours > 0 else None


# =============================================================================
# 3. Sleep Debt & Need
# =============================================================================

def calculate_sleep_need(
    base_need_min: int = 480,
    training_load: float = 0,
    load_baseline: float = 150,
    prior_debt_min: int = 0,
    nap_min: int = 0,
) -> dict:
    """
    Sleep Need แบบ dynamic
    ถ้า training load สูงกว่า baseline → เพิ่ม need
    """
    load_excess = max(0, training_load - load_baseline)
    strain_adjustment = int((load_excess / 50) * 10)
    total_need = base_need_min + strain_adjustment + prior_debt_min - nap_min
    return {
        "sleep_need_min": max(total_need, 360),
        "strain_adjustment_min": strain_adjustment,
    }


def cumulative_sleep_debt(
    records: list, needs: list, decay: float = 0.9, window: int = 7
) -> float:
    """
    Sleep Debt สะสม พร้อม decay factor
    decay=0.9 หมายถึงหนี้เก่าลดลง 10% ต่อวัน
    """
    debt = 0.0
    for r, need in zip(records[-window:], needs[-window:]):
        actual = r.get("duration_min", 0) or r.get("total_sleep_min", 0)
        daily_debt = max(0, need - actual)
        debt = debt * decay + daily_debt
    return round(debt, 1)


def sleep_performance(actual_min: int, need_min: int) -> float:
    """
    Sleep Performance (% ของ need ที่ได้)
    cap ที่ 120% เพื่อไม่ให้ค่าเบี่ยงเบนมากเกินไป
    """
    if need_min <= 0:
        return 0.0
    return round(min(actual_min / need_min, 1.2) * 100, 1)


# =============================================================================
# 4. SpO2 Analysis
# =============================================================================

def analyze_spo2(record: dict, dip_threshold: int = 90, sustained_min: int = 2) -> dict:
    """
    วิเคราะห์ SpO2 readings
    dip_threshold: ค่าที่ถือว่าต่ำผิดปกติ
    sustained_min: จำนวน readings ที่ต้องต่อเนื่องถึงนับเป็น event
    """
    readings = record.get("spo2_readings", [])

    if not readings:
        return {
            "avg": record.get("spo2_avg"),
            "min": record.get("spo2_min"),
            "dip_events": None,
            "time_below_threshold_pct": None,
        }

    dip_events = 0
    consecutive_low = 0
    for r in readings:
        val = r["value"] if isinstance(r, dict) else r
        if val < dip_threshold:
            consecutive_low += 1
            if consecutive_low == sustained_min:
                dip_events += 1
        else:
            consecutive_low = 0

    values = [r["value"] if isinstance(r, dict) else r for r in readings]
    below_count = sum(1 for v in values if v < dip_threshold)

    return {
        "avg": round(sum(values) / len(values), 1) if values else None,
        "min": min(values) if values else None,
        "dip_events": dip_events,
        "time_below_threshold_pct": round(below_count / len(values) * 100, 1)
        if values
        else None,
    }


def flag_spo2_risk(spo2_analysis: dict) -> str:
    """Flag ความเสี่ยงจาก SpO2"""
    if spo2_analysis.get("min") is None:
        return "no_data"
    if spo2_analysis["min"] < 88 or (spo2_analysis.get("dip_events") or 0) >= 5:
        return "review_recommended"
    if spo2_analysis.get("avg", 100) < 94:
        return "monitor"
    return "normal"


# =============================================================================
# 5. Skin Temperature Analysis
# =============================================================================

def analyze_skin_temp(records: list, window: int = 7) -> dict:
    """
    วิเคราะห์ skin temperature deviation แบบ rolling trend
    """
    recent = [
        r["skin_temp_deviation_c"]
        for r in records[-window:]
        if r.get("skin_temp_deviation_c") is not None
    ]
    if not recent:
        return {"trend": None, "flag": "no_data"}

    latest = recent[-1]
    avg_recent = round(sum(recent) / len(recent), 2)

    flag = "normal"
    if latest >= 0.5:
        flag = "elevated"
    elif latest <= -0.5:
        flag = "lowered"

    return {"latest_deviation": latest, "avg_recent": avg_recent, "flag": flag}
 
# =============================================================================
# 6. Recovery Composite Score
# =============================================================================
 

def recovery_score(
    hrv_today: float = None,
    hrv_baseline: dict = None,
    rhr_today: float = None,
    rhr_baseline: dict = None,
    sleep_performance_pct: float = None,
    sleep_efficiency_pct: float = None,
    spo2_flag: str = "normal",
    skin_temp_flag: str = "normal",
    resp_rate_z: float = 0,
    weights: dict = None,
    training_load: float = 0.0,
    load_baseline: float = None,
    resp_rate_trend: float = 0.0,        
) -> dict:

    
    """
    Weighted composite:
      HRV / RHR / Sleep Perf / Sleep Eff  (รวม = 1.0, normalize อัตโนมัติ)
      SpO2/Temp/Resp  = penalty เท่านั้น ไม่อยู่ใน weighted sum
      Training Load   = penalty โดยตรง (โหลดหนักเมื่อวาน ลด recovery คาดการณ์ก่อนเห็น HRV)
    """
    import recovery_config
    default_weights = recovery_config.DEFAULT_RECOVERY_WEIGHTS
    w = {**default_weights, **(weights or {})}

    total = sum(w.values())
    if total <= 0:
        raise ValueError("recovery weights must sum to a positive number")
    w = {k: v / total for k, v in w.items()}

    # Default baselines to neutral if not provided
    if hrv_baseline is None:
        hrv_baseline = {"mean": 50, "stdev": 10}
    if rhr_baseline is None:
        rhr_baseline = {"mean": 55, "stdev": 5}

    hrv_z = z_score(hrv_today, hrv_baseline) if hrv_today is not None else 0
    rhr_z = z_score(rhr_today, rhr_baseline) if rhr_today is not None else 0

    def z_to_score(z, invert=False):
        if z is None:
            return 50
        z = -z if invert else z
        score = 50 + (z * 20)
        return max(0, min(100, score))

    hrv_component = z_to_score(hrv_z)
    rhr_component = z_to_score(rhr_z, invert=True)

    sp = sleep_performance_pct if sleep_performance_pct is not None else 75
    se = sleep_efficiency_pct if sleep_efficiency_pct is not None else 80




    base_composite = (
        hrv_component * w["hrv"]
        + rhr_component * w["rhr"]
        + sp * w["sleep_performance"]
        + se * w["sleep_efficiency"]
    )

    # Training load penalty — ถ้าโหลดเมื่อวานเกิน baseline ลด recovery โดยตรง
    # (ก่อนที่ HRV จะเปลี่ยน — เป็น early indicator ของ fatigue)
    if load_baseline is None:
        import recovery_config
        load_baseline = recovery_config.DEFAULT_LOAD_BASELINE
    if training_load and load_baseline and training_load > load_baseline:
        excess_ratio = (training_load - load_baseline) / load_baseline
        training_load_penalty = min(
            recovery_config.TRAINING_LOAD_PENALTY_MAX,
            excess_ratio * recovery_config.TRAINING_LOAD_PENALTY_SLOPE
        )
    else:
        training_load_penalty = 0.0

    # Penalty from SpO2/skin temp/respiratory
    penalty = 0
    if spo2_flag == "review_recommended":
        penalty += 15
    elif spo2_flag == "monitor":
        penalty += 7
    if skin_temp_flag in ("elevated", "lowered"):
        penalty += 8
    if resp_rate_z and abs(resp_rate_z) >= 1.5:
        penalty += 5

    total_penalty = penalty + training_load_penalty
 
    # Respiratory rate trend penalty
    resp_trend_penalty = 0.0
    if resp_rate_trend > 0.15:
        resp_trend_penalty = min(8, round(resp_rate_trend * 20, 1))

    composite = max(0, base_composite - total_penalty - resp_trend_penalty)

    
    band = "green" if composite >= 67 else "yellow" if composite >= 34 else "red"

    return {
        "recovery_score": round(composite, 1),
        "band": band,
        "penalty_applied": penalty,
        "training_load_penalty": round(training_load_penalty, 1),
        "resp_rate_trend_penalty": resp_trend_penalty,   
        "weights_used": w,
        "components": {
            "hrv_score": round(hrv_component, 1),
            "rhr_score": round(rhr_component, 1),
            "sleep_performance": round(sp, 1),
            "sleep_efficiency": round(se, 1),
        },
    }



# =============================================================================
# 7. Journal Correlation Engine
# =============================================================================

def correlate_journal_factor(
    records: list, journals: list, factor_key: str, metric_fn: Callable
) -> dict:
    """
    เปรียบเทียบ metric เมื่อมี factor vs ไม่มี factor
    factor_key: key ใน journal dict
    metric_fn: function(record) -> float
    """
    by_date_journal = {j["date"]: j for j in journals}
    with_factor, without_factor = [], []

    for r in records:
        date_key = r.get("date", "")
        # Try to match date formats
        j = by_date_journal.get(date_key)
        if not j:
            # Try alternate format (20260917 -> 2026-09-17)
            if len(date_key) == 8 and date_key.isdigit():
                alt = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"
                j = by_date_journal.get(alt)
        if not j:
            continue

        value = metric_fn(r)
        if value is None:
            continue

        flag = j.get(factor_key)
        if isinstance(flag, (int, float)):
            is_present = flag > 0
        elif isinstance(flag, str):
            is_present = flag.lower() in ("true", "yes", "1")
        else:
            is_present = bool(flag)

        if is_present:
            with_factor.append(value)
        else:
            without_factor.append(value)

    if len(with_factor) < 3 or len(without_factor) < 3:
        return {"insufficient_data": True}

    mean_with = statistics.mean(with_factor)
    mean_without = statistics.mean(without_factor)
    return {
        "factor": factor_key,
        "mean_with": round(mean_with, 1),
        "mean_without": round(mean_without, 1),
        "difference": round(mean_with - mean_without, 1),
        "n_with": len(with_factor),
        "n_without": len(without_factor),
    }


def rank_journal_impacts(records: list, journals: list, metric_fn: Callable) -> list:
    """
    จัดอันดับปัจจัยที่กระทบ metric มากที่สุด
    """
    factors = [
        "alcohol_units",
        "caffeine_after_14",
        "late_meal",
        "stress_level",
        "exercise_evening",
        "room_temp_hot",
    ]
    results = []
    for f in factors:
        r = correlate_journal_factor(records, journals, f, metric_fn)
        if not r.get("insufficient_data"):
            results.append(r)
    return sorted(results, key=lambda x: abs(x["difference"]), reverse=True)


# =============================================================================
# 8. Correlation & Trend Engine
# =============================================================================

def correlate_load_vs_sleep(records: list, lag_days: int = 1) -> Optional[float]:
    """
    คำนวณ correlation ระหว่าง training load กับ deep sleep %
    ใช้ numpy corrcoef
    """
    try:
        loads = []
        deep_pct = []
        for i in range(lag_days, len(records)):
            r_load = records[i]
            r_sleep = records[i - lag_days]
            load_val = r_load.get("training_load_prev_day")
            total_sleep = r_sleep.get("duration_min", 0) or r_sleep.get("total_sleep_min", 0)
            if load_val is not None and total_sleep > 0:
                deep = r_sleep.get("deep_sleep_pct")
                if deep is not None:
                    loads.append(load_val)
                    deep_pct.append(deep)

        n = min(len(loads), len(deep_pct))
        if n < 10:
            return None
        return round(float(np.corrcoef(loads[:n], deep_pct[:n])[0, 1]), 3)
    except (ImportError, ValueError):
        return None


def rolling_average(records: list, metric_fn: Callable, window: int = 7) -> list:
    """
    คำนวณ rolling average ของ metric
    """
    values = [metric_fn(r) for r in records]
    result = []
    for i in range(len(values)):
        window_vals = [
            v for v in values[max(0, i - window + 1) : i + 1] if v is not None
        ]
        if window_vals:
            result.append(round(sum(window_vals) / len(window_vals), 1))
        else:
            result.append(None)
    return result


def bedtime_consistency(records: list, window: int = 7) -> Optional[float]:
    """
    คำนวณ Bedtime Consistency Score (0-100)
    stdev ของ bedtime < 60 min = ดีมาก
    """
    minutes_from_midnight = []
    for r in records[-window:]:
        sleep_start = r.get("sleep_start", "")
        if not sleep_start:
            continue
        try:
            if isinstance(sleep_start, str):
                t = datetime.fromisoformat(sleep_start.replace("Z", "+00:00"))
            else:
                t = sleep_start
            m = t.hour * 60 + t.minute
            if t.hour < 12:  # Assume late night / past midnight
                m += 1440
            minutes_from_midnight.append(m)
        except (ValueError, TypeError):
            continue

    if len(minutes_from_midnight) < 3:
        return None
    stdev = statistics.stdev(minutes_from_midnight)
    score = max(0, 100 - stdev * 1.2)
    return round(score, 1)


# =============================================================================
# 9. Anomaly Detection & Alerting
# =============================================================================

def detect_anomalies(record: dict, baselines: dict) -> list:
    """
    Detect anomalies in a sleep record based on baselines
    baselines: dict of metric_name -> baseline dict (from compute_baseline)
    """
    anomalies = []

    checks = [
        ("deep_sleep_low", record.get("deep_sleep_pct"), baselines.get("deep"), False),
        ("rem_low", record.get("rem_sleep_pct"), baselines.get("rem"), False),
        ("hrv_drop", record.get("hrv"), baselines.get("hrv_ms"), False),
        ("resting_hr_spike", record.get("resting_hr"), baselines.get("resting_hr"), True),
        ("spo2_drop", record.get("spo2_avg"), baselines.get("spo2_avg"), False),
    ]

    for name, value, baseline, invert in checks:
        if not baseline or value is None:
            continue
        z = z_score(value, baseline)
        if z is None:
            continue
        threshold_z = -z if invert else z
        if threshold_z <= -2.0:
            anomalies.append({"type": name, "z_score": z, "severity": "critical"})
        elif threshold_z <= -1.5:
            anomalies.append({"type": name, "z_score": z, "severity": "warning"})

    eff = sleep_efficiency(record)
    if eff < 75:
        anomalies.append({"type": "low_sleep_efficiency", "value": eff, "severity": "warning"})

    skin_temp = record.get("skin_temp_deviation_c")
    if skin_temp is not None and abs(skin_temp) >= 0.5:
        anomalies.append(
            {"type": "skin_temp_deviation", "value": skin_temp, "severity": "warning"}
        )

    return anomalies


def should_alert(
    records: list, metric_path: list, threshold: float, consecutive_days: int = 3
) -> bool:
    """
    ตรวจสอบว่า metric ต่ำกว่า threshold ต่อเนื่อง N วันหรือไม่
    """
    recent = records[-consecutive_days:]
    if len(recent) < consecutive_days:
        return False
    for r in recent:
        v = r
        try:
            for key in metric_path:
                v = v.get(key) if isinstance(v, dict) else None
                if v is None:
                    break
        except (KeyError, AttributeError):
            return False
        if v is None or v >= threshold:
            return False
    return True


# =============================================================================
# 10. Weekly Report Generator
# =============================================================================

def generate_weekly_report(records: list, journals: list = None) -> str:
    """
    สร้างสรุปการนอนประจำสัปดาห์แบบ template-based
    """
    if not records:
        return "ไม่มีข้อมูลการนอนเพียงพอสำหรับสร้างรายงาน"

    n = len(records)
    avg_eff = round(sum(sleep_efficiency(r) for r in records) / n, 1)
    avg_deep = round(
        sum(r.get("deep_sleep_pct", 0) or 0 for r in records) / n, 1
    )
    avg_rem = round(
        sum(r.get("rem_sleep_pct", 0) or 0 for r in records) / n, 1
    )
    avg_duration = round(
        sum(r.get("duration_min", 0) or 0 for r in records) / n, 0
    )

    # SpO2 average
    spo2_vals = [r.get("spo2_avg") for r in records if r.get("spo2_avg") is not None]
    avg_spo2 = round(sum(spo2_vals) / len(spo2_vals), 1) if spo2_vals else None

    # Consistency
    consistency = bedtime_consistency(records)
    consistency_str = f"{consistency}/100" if consistency else "ไม่มีข้อมูล"

    # Journal correlation
    top_line = "- ยังไม่มีข้อมูล journal เพียงพอสำหรับวิเคราะห์ปัจจัย"
    if journals and len(journals) >= 3:
        try:
            top_impact = rank_journal_impacts(records, journals, sleep_efficiency)
            if top_impact:
                top = top_impact[0]
                direction = "ลด" if top["difference"] < 0 else "เพิ่ม"
                top_line = (
                    f"- ปัจจัยกระทบมากสุด: {top['factor']} "
                    f"({direction} {abs(top['difference'])} จุด)"
                )
        except Exception:
            pass

    # Band classification
    if avg_eff >= 85:
        eff_band = "ดีมาก"
    elif avg_eff >= 75:
        eff_band = "พอใช้"
    else:
        eff_band = "ควรปรับปรุง"

    report = f"""📊 สรุปการนอนประจำสัปดาห์ ({n} คืน)
- Sleep Efficiency เฉลี่ย: {avg_eff}% ({eff_band})
- Deep Sleep เฉลี่ย: {avg_deep}%
- REM เฉลี่ย: {avg_rem}%
- เวลานอนเฉลี่ย: {avg_duration:.0f} นาที ({avg_duration/60:.1f} ชม.)
{f"- SpO2 เฉลี่ย: {avg_spo2}%" if avg_spo2 else ""}
- Bedtime Consistency: {consistency_str}
{top_line}"""

    return report


# =============================================================================
# 11. SQI — Sleep Quality Index
# =============================================================================

def calculate_sqi(records: list) -> dict:
    """
    Sleep Quality Index (0-100)
    SQI = 0.3*(Efficiency/100) + 0.2*(Stage_Balance) + 0.15*(Consistency/100) + 0.35*(1 - Debt_Ratio)
    """
    if not records:
        return {"sqi": None, "band": "no_data"}

    n = len(records)
    avg_eff = sum(sleep_efficiency(r) for r in records) / n

    # Stage balance: check if deep/REM in normal range
    deep_ok = sum(1 for r in records if 13 <= (r.get("deep_sleep_pct") or 0) <= 23)
    rem_ok = sum(1 for r in records if 20 <= (r.get("rem_sleep_pct") or 0) <= 25)
    stage_balance = (deep_ok + rem_ok) / (2 * n)

    # Consistency
    consistency = bedtime_consistency(records)
    consistency_pct = (consistency or 50) / 100

    # Debt ratio (assume 8h need)
    total_deficit = 0
    for r in records:
        need = 480
        actual = r.get("duration_min", 0) or 0
        total_deficit += max(0, need - actual)
    debt_ratio = min(1, total_deficit / (480 * max(n, 7)))

    sqi = (
        0.30 * (avg_eff / 100)
        + 0.20 * stage_balance
        + 0.15 * consistency_pct
        + 0.35 * (1 - debt_ratio)
    ) * 100

    sqi = round(max(0, min(100, sqi)), 1)
    band = "good" if sqi >= 80 else "fair" if sqi >= 60 else "poor"

    return {"sqi": sqi, "band": band}
