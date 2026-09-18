# -*- coding: utf-8 -*-
"""
baseline_engine.py — Phase 1: Personalized Adaptive Baseline Engine

เป้าหมาย (ตาม roadmap.md Phase 1):
  1. EWMA แทน rolling mean/stdev คงที่ (half-life ปรับได้ต่อ metric)
  2. minimum data requirement + confidence band (building / moderate / stable)
  3. แยก baseline ตาม context (rest_day vs hard_training)
  4. ln(RMSSD) transform ก่อนคำนวณ z-score ของ HRV
  5. เก็บ baseline history ลง SQLite (ตาราง baselines_daily) แทนการ compute ใหม่ทุกครั้ง

Design note:
  - ไฟล์นี้ "ไม่แก้" sleep_analysis.py — เป็น module ใหม่แยกต่างหาก
  - compute_baseline_v2() คืนค่าเป็น superset ของ compute_baseline() เดิม
    (ยังมี key "mean"/"stdev"/"n" เหมือนเดิม) เพื่อให้สลับใช้แทนได้แบบ drop-in
    โดย detect_anomalies() / z_score() / flag_metric() ใน sleep_analysis.py
    ไม่ต้องแก้เลยในตอนนี้
"""

import math
import statistics
from datetime import datetime
from typing import List, Dict, Optional, Callable, Any

# =============================================================================
# Config — half-life ต่อ metric (หน่วย: วัน)
# =============================================================================

DEFAULT_HALF_LIFE_DAYS = {
    "resting_hr": 7,
    "hrv_ms": 14,
    "hrv_ln_rmssd": 14,
    "deep": 14,
    "rem": 14,
    "spo2_avg": 14,
    "resp_rate": 14,
}

MIN_DAYS_FOR_STABLE = 30
MIN_DAYS_FOR_MODERATE = 14


# =============================================================================
# 1. Transform helpers
# =============================================================================

def ln_rmssd(hrv_raw_ms: Optional[float]) -> Optional[float]:
    """
    HRV ดิบ (RMSSD, ms) มีการกระจายแบบ log-normal ไม่ใช่ normal
    งานวิจัย sleep/HRV มาตรฐานจึงแปลงเป็น ln(RMSSD) ก่อนคำนวณ z-score
    """
    if hrv_raw_ms is None or hrv_raw_ms <= 0:
        return None
    return round(math.log(hrv_raw_ms), 4)


def classify_context(record: dict, hard_load_threshold: float = 150) -> str:
    """
    แยก record ว่าเป็น 'rest' หรือ 'hard_training' วันก่อนหน้า
    ใช้ training_load_prev_day ถ้ามี (จะมีจริงหลัง Phase 2 สร้าง daily_strain แล้ว)
    ถ้ายังไม่มี (สถานะปัจจุบันของ DB ณ Phase 1) ให้ merge ค่า proxy เข้ามาก่อน
    ด้วย attach_training_load_proxy() แล้วค่อยเรียกฟังก์ชันนี้
    """
    load = record.get("training_load_prev_day")
    if load is None:
        return "unknown"
    return "hard_training" if load >= hard_load_threshold else "rest"


def estimate_training_load_proxy(activities: list, target_date: str) -> float:
    """
    Proxy ชั่วคราวสำหรับ training load ก่อน Phase 2 (Strain Engine) จะเสร็จ
    เพราะตอนนี้ DB (coros_db.py) ยังไม่มีตาราง daily_strain / คอลัมน์ training_load
    เลย — ใช้ข้อมูลจากตาราง `activities` ที่มีอยู่แล้วแทน (แบบ TRIMP หยาบๆ)

    สูตร: sum( duration_s / 60 * (avg_hr / 100) ) ของทุก activity ที่ start_time
    ตรงกับ target_date (YYYY-MM-DD)

    หมายเหตุ: นี่เป็นของชั่วคราวเท่านั้น — เมื่อ Phase 2 สร้าง daily_strain
    เสร็จแล้ว ให้เปลี่ยนไปอ่านจากตารางนั้นแทน แล้วลบฟังก์ชันนี้ทิ้งได้เลย
    """
    load = 0.0
    for a in activities:
        start = a.get("start_time", "") or ""
        if not start.startswith(target_date):
            continue
        duration_min = (a.get("duration_s") or 0) / 60
        avg_hr = a.get("avg_hr") or 0
        if duration_min and avg_hr:
            load += duration_min * (avg_hr / 100)
    return round(load, 1)


def attach_training_load_proxy(sleep_records: list, activities: list) -> list:
    """
    Merge training_load_prev_day (proxy) เข้าไปใน sleep_records แต่ละวัน
    โดยดูจาก activities ของ "วันก่อนหน้า" วันที่นอน (date ใน sleep_data
    คือคืนที่นอน ซึ่งตามหลังวันออกกำลังกาย)
    คืน list ใหม่ (ไม่แก้ของเดิม in-place)
    """
    from datetime import datetime, timedelta

    out = []
    for r in sleep_records:
        r2 = dict(r)
        date_str = r.get("date", "")
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            prev_day = (d - timedelta(days=1)).strftime("%Y-%m-%d")
            r2["training_load_prev_day"] = estimate_training_load_proxy(activities, prev_day)
        except (ValueError, TypeError):
            r2["training_load_prev_day"] = None
        out.append(r2)
    return out


# =============================================================================
# 2. EWMA core
# =============================================================================

def _half_life_to_alpha(half_life_days: float) -> float:
    """
    แปลง half-life -> smoothing factor alpha สำหรับ EWMA
    alpha = 1 - exp(ln(0.5) / half_life)
    """
    if half_life_days <= 0:
        return 1.0
    return 1 - math.exp(math.log(0.5) / half_life_days)


def ewma_series(values: List[float], half_life_days: float) -> List[float]:
    """
    คำนวณ EWMA ของ series (เรียงเก่า -> ใหม่)
    คืน list ความยาวเท่าเดิม (ค่า EWMA ณ แต่ละจุดเวลา)
    """
    if not values:
        return []
    alpha = _half_life_to_alpha(half_life_days)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return out


def ewma_stdev(values: List[float], half_life_days: float) -> Optional[float]:
    """
    EWMA-weighted stdev รอบค่า EWMA ล่าสุด
    ใช้ weighted variance แบบเดียวกับที่ Whoop/Oura ใช้ในทางปฏิบัติ
    """
    if len(values) < 2:
        return None
    alpha = _half_life_to_alpha(half_life_days)
    ewma_vals = ewma_series(values, half_life_days)
    mean = ewma_vals[-1]

    weighted_sq_diff = 0.0
    weight_sum = 0.0
    w = 1.0
    # ให้ค่าล่าสุดน้ำหนักมากสุด ไล่ย้อนหลังลดลงตาม alpha
    for v in reversed(values):
        weighted_sq_diff += w * (v - mean) ** 2
        weight_sum += w
        w *= (1 - alpha)
    if weight_sum == 0:
        return None
    variance = weighted_sq_diff / weight_sum
    return round(math.sqrt(variance), 3)


# =============================================================================
# 3. Confidence band
# =============================================================================

def confidence_band(n: int) -> str:
    if n < MIN_DAYS_FOR_MODERATE:
        return "building"
    if n < MIN_DAYS_FOR_STABLE:
        return "moderate"
    return "stable"


# =============================================================================
# 4. Value extraction (เหมือน compute_baseline เดิม แต่แยกออกมาใช้ซ้ำได้)
# =============================================================================

def _extract_metric_values(records: list, metric_path: list) -> List[float]:
    values = []
    for r in records:
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
    return values


# =============================================================================
# 5. Main entry point — drop-in replacement ของ compute_baseline()
# =============================================================================

def compute_baseline_v2(
    records: list,
    metric_path: list,
    metric_name: str = None,
    context: str = None,           # "rest" | "hard_training" | None (=ทุก context)
    half_life_days: float = None,  # ถ้าไม่ใส่ จะเดาจาก metric_name หรือ default 14
    log_transform: bool = False,   # True สำหรับ HRV ดิบ -> ln(RMSSD)
) -> dict:
    """
    คืนค่า superset ของ compute_baseline() เดิม:
      mean, stdev, n            <- เหมือนเดิม เข้ากันได้กับ z_score()/flag_metric()
      confidence                <- "building" | "moderate" | "stable"  (ใหม่)
      half_life_days            <- ใหม่
      context                   <- ใหม่ ("rest"/"hard_training"/None)
      log_transformed           <- ใหม่ (bool)
    """
    if context is not None:
        records = [r for r in records if classify_context(r) == context]

    if half_life_days is None:
        half_life_days = DEFAULT_HALF_LIFE_DAYS.get(metric_name, 14)

    raw_values = _extract_metric_values(records, metric_path)

    if log_transform:
        values = [ln_rmssd(v) for v in raw_values]
        values = [v for v in values if v is not None]
    else:
        values = raw_values

    n = len(values)
    if n < 5:
        return {
            "mean": None,
            "stdev": None,
            "n": n,
            "confidence": "building",
            "half_life_days": half_life_days,
            "context": context,
            "log_transformed": log_transform,
        }

    ewma_vals = ewma_series(values, half_life_days)
    mean = round(ewma_vals[-1], 3)
    stdev = ewma_stdev(values, half_life_days)
    if stdev is None or stdev == 0:
        # fallback กันหารด้วยศูนย์ใน z_score()
        stdev = round(statistics.stdev(values), 3) if n >= 2 else 0.0

    return {
        "mean": mean,
        "stdev": stdev,
        "n": n,
        "confidence": confidence_band(n),
        "half_life_days": half_life_days,
        "context": context,
        "log_transformed": log_transform,
    }


def suppress_critical_if_building(anomaly: dict, baseline: dict) -> dict:
    """
    ใช้ครอบผลลัพธ์จาก detect_anomalies() เดิม:
    ถ้า baseline ยัง 'building' (< 14 วัน) ห้ามฟันธง severity = critical
    ลดเป็น warning แทน เพื่อลด false alarm ตอนข้อมูลยังน้อย
    """
    if baseline.get("confidence") == "building" and anomaly.get("severity") == "critical":
        anomaly = dict(anomaly)
        anomaly["severity"] = "warning"
        anomaly["note"] = "baseline_building_downgraded"
    return anomaly


# =============================================================================
# 6. Persistence — บันทึก baseline รายวันลง SQLite (baselines_daily)
# =============================================================================

BASELINES_DAILY_SCHEMA = """
CREATE TABLE IF NOT EXISTS baselines_daily (
    date            TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    context         TEXT,              -- 'rest' | 'hard_training' | NULL(=all)
    mean            REAL,
    stdev           REAL,
    n               INTEGER,
    confidence      TEXT,
    half_life_days  REAL,
    log_transformed INTEGER,
    PRIMARY KEY (date, metric_name, context)
);
"""


def save_baseline_snapshot(conn, date: str, metric_name: str, baseline: dict):
    """
    บันทึก snapshot ของ baseline ณ วันนั้นลงตาราง baselines_daily
    conn: sqlite3.Connection ที่เปิดจาก coros_db.py (ใช้ connection เดิม ไม่เปิดใหม่)

    ใช้ทำ trend ของ baseline เอง (baseline drift = สัญญาณ fitness เปลี่ยนระยะยาว)
    ตาม deliverable ของ Phase 1
    """
    conn.execute(BASELINES_DAILY_SCHEMA)
    conn.execute(
        """
        INSERT OR REPLACE INTO baselines_daily
            (date, metric_name, context, mean, stdev, n, confidence,
             half_life_days, log_transformed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            date,
            metric_name,
            baseline.get("context"),
            baseline.get("mean"),
            baseline.get("stdev"),
            baseline.get("n"),
            baseline.get("confidence"),
            baseline.get("half_life_days"),
            int(bool(baseline.get("log_transformed"))),
        ),
    )
    conn.commit()
