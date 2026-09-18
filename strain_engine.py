# -*- coding: utf-8 -*-
"""
strain_engine.py — Phase 2.2 Layer 1: Strain จาก activities table (ของที่มีอยู่แล้ว)

สถานะ: นี่คือ "ชั้นที่ 1" ตามที่คุยกันไว้ — ครอบคลุมแค่ภาระตอนออกกำลังกาย
(ไม่ใช่ทั้งวันแบบ Whoop จริง เพราะยังไม่ได้ดึง continuous HR จาก
queryHealthCheckTimeSeries) แต่ใช้งานได้ทันที ไม่ต้องแก้ coros_daily_sync.py
หรือเรียก COROS API เพิ่มเลย

หลักการ (อ้างอิง sports-science มาตรฐาน ไม่ใช่ black box — ตาม design
principle ข้อ 4 ของ roadmap "ทุก score ต้องอธิบายได้"):
  1. Banister TRIMP ต่อ activity จาก duration + avg_hr (heart-rate reserve method)
  2. รวม TRIMP ทั้งวัน -> แปลงเป็น Strain scale 0-21 แบบ Whoop ด้วย saturating
     exponential (ยิ่งโหลดเยอะ ยิ่งเพิ่มช้าลง — สื่อ "diminishing marginal
     strain" เหมือนที่ Whoop อธิบายไว้)
  3. ACWR = avg(7 วันล่าสุด) / avg(28 วันล่าสุด) ของ TRIMP รายวัน
  4. เก็บลงตาราง daily_strain

TODO เมื่อ Layer 2 มา (queryHealthCheckTimeSeries):
  - แทน per-activity TRIMP ด้วย time-in-zone จาก continuous HR ทั้งวัน
  - ลบ estimate_hr_max()/estimate_hr_rest() fallback แล้วใช้ HR zone จริงจาก
    device profile แทน
"""

import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional


# =============================================================================
# Config
# =============================================================================

DEFAULT_HR_MAX_FALLBACK = 190   # ใช้ถ้าไม่มี max_hr สังเกตได้เลยจาก activities
DEFAULT_HR_REST_FALLBACK = 60   # ใช้ถ้าไม่มี resting_hr เลยจาก sleep_data
STRAIN_SCALE_MAX = 21.0         # ตาม Whoop convention (0-21)
STRAIN_K = 0.015                # ค่าคุมความชันของ saturating curve — ปรับได้ภายหลัง
                                 # เมื่อมีข้อมูลจริงมากพอจะ calibrate ใหม่ได้


# =============================================================================
# 1. HR max / HR rest estimation (ชั่วคราว จนกว่าจะมี device profile จริง)
# =============================================================================

def estimate_hr_max(activities: List[dict], fallback: float = DEFAULT_HR_MAX_FALLBACK) -> float:
    """
    ประมาณ HR max จาก max_hr สูงสุดที่เคยสังเกตได้จริงในกิจกรรมทั้งหมด
    (ดีกว่าสูตรอายุ 220-age เพราะเป็นค่าที่ COROS วัดได้จริงจากอุปกรณ์)
    """
    observed = [a.get("max_hr") for a in activities if a.get("max_hr")]
    if not observed:
        return fallback
    return max(max(observed), fallback * 0.8)  # กันกรณี observed ต่ำผิดปกติ (data error)


def estimate_hr_rest(sleep_records: List[dict], fallback: float = DEFAULT_HR_REST_FALLBACK) -> float:
    """
    ประมาณ HR rest จาก resting_hr ล่าสุดใน sleep_data (ค่าที่แม่นกว่า HR
    นิ่งตอนกลางวัน เพราะวัดตอนนอนหลับลึก)
    """
    recent = [r.get("resting_hr") for r in sleep_records[-14:] if r.get("resting_hr")]
    if not recent:
        return fallback
    return sum(recent) / len(recent)


# =============================================================================
# 2. Banister TRIMP ต่อ activity
# =============================================================================

def banister_trimp(
    duration_min: float,
    avg_hr: float,
    hr_rest: float,
    hr_max: float,
    sex: str = "male",
) -> Optional[float]:
    """
    TRIMP = duration_min * HRr * 0.64 * e^(k * HRr)
    HRr (heart rate reserve fraction) = (avg_hr - hr_rest) / (hr_max - hr_rest)
    k = 1.92 (male) หรือ 1.67 (female) — ตามสูตร Banister ดั้งเดิม

    คืน None ถ้าข้อมูลไม่พอคำนวณ (กัน garbage-in-garbage-out)
    """
    if not duration_min or not avg_hr or hr_max is None or hr_rest is None:
        return None
    if hr_max <= hr_rest:
        return None

    hr_reserve = (avg_hr - hr_rest) / (hr_max - hr_rest)
    hr_reserve = max(0.0, min(1.0, hr_reserve))  # clip กัน HR ต่ำกว่า rest (sensor noise)

    k = 1.67 if sex == "female" else 1.92
    b = 0.86 if sex == "female" else 0.64

    trimp = duration_min * hr_reserve * b * math.exp(k * hr_reserve)
    return round(trimp, 2)


# =============================================================================
# 3. รวม TRIMP รายวันจากตาราง activities
# =============================================================================

def daily_trimp_from_activities(
    activities: List[dict],
    hr_rest: float,
    hr_max: float,
    sex: str = "male",
) -> Dict[str, float]:
    """
    รวม TRIMP ของทุก activity ในแต่ละวัน (key = 'YYYY-MM-DD')
    activities: list ของ dict ตามรูปแบบ coros_db.py (มี start_time, duration_s, avg_hr)
    """
    daily: Dict[str, float] = {}
    for a in activities:
        start = a.get("start_time") or ""
        date_key = start[:10]  # 'YYYY-MM-DDTHH:MM:SS' -> 'YYYY-MM-DD'
        try:
            datetime.strptime(date_key, "%Y-%m-%d")
        except ValueError:
            continue  # ป้องกัน string แปลก ๆ ที่ยาวพอดี 10 ตัวแต่ไม่ใช่วันที่จริง

        duration_min = (a.get("duration_s") or 0) / 60
        avg_hr = a.get("avg_hr")
        trimp = banister_trimp(duration_min, avg_hr, hr_rest, hr_max, sex)
        if trimp is None:
            continue

        daily[date_key] = round(daily.get(date_key, 0.0) + trimp, 2)
    return daily


# =============================================================================
# 4. แปลง TRIMP -> Strain scale (0-21, saturating)
# =============================================================================

def trimp_to_strain(trimp: float, k: float = STRAIN_K) -> float:
    """
    แปลง TRIMP รายวันเป็น Strain 0-21 แบบ saturating exponential
    strain = 21 * (1 - e^(-k * trimp))
    วันพัก (trimp=0) -> strain=0, วันซ้อมหนักมาก -> เข้าใกล้ 21 แต่ไม่เกิน
    """
    if trimp is None or trimp <= 0:
        return 0.0
    strain = STRAIN_SCALE_MAX * (1 - math.exp(-k * trimp))
    return round(strain, 1)


# =============================================================================
# 5. ACWR (Acute:Chronic Workload Ratio)
# =============================================================================

def compute_acwr(daily_trimp: Dict[str, float], as_of_date: str) -> Optional[dict]:
    """
    ACWR = เฉลี่ย TRIMP 7 วันล่าสุด / เฉลี่ย TRIMP 28 วันล่าสุด (นับถึง as_of_date)
    ACWR > 1.5 = ความเสี่ยงบาดเจ็บสูง (มาตรฐานวงการกีฬา)
    ต้องมีข้อมูลอย่างน้อย 28 วันถึงจะคำนวณ chronic ได้แม่นยำ — ถ้าน้อยกว่านั้น
    คืน confidence: "building" เหมือนกับ baseline_engine
    """
    try:
        ref_date = datetime.strptime(as_of_date, "%Y-%m-%d")
    except ValueError:
        return None

    def _avg_window(days: int) -> Optional[float]:
        vals = []
        for i in range(days):
            d = (ref_date - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in daily_trimp:
                vals.append(daily_trimp[d])
        if not vals:
            return None
        return sum(vals) / days  # หารด้วย days ทั้งหมด (ไม่ใช่แค่ len(vals))
        # ตั้งใจหารด้วย days คงที่: วันที่ไม่มีกิจกรรม = TRIMP 0 จริงๆ (พักผ่อน)
        # ไม่ใช่ missing data ในความหมายเดียวกับ baseline_engine

    acute = _avg_window(7)
    chronic = _avg_window(28)

    days_with_data = sum(
        1 for i in range(28)
        if (ref_date - timedelta(days=i)).strftime("%Y-%m-%d") in daily_trimp
    )
    confidence = "stable" if days_with_data >= 21 else "moderate" if days_with_data >= 7 else "building"

    if acute is None or chronic is None or chronic == 0:
        return {"acwr": None, "acute_avg": acute, "chronic_avg": chronic,
                "confidence": confidence, "risk": "unknown"}

    ratio = round(acute / chronic, 2)
    if ratio > 1.5:
        risk = "high"
    elif ratio < 0.8:
        risk = "detraining"
    else:
        risk = "normal"

    return {
        "acwr": ratio,
        "acute_avg": round(acute, 1),
        "chronic_avg": round(chronic, 1),
        "confidence": confidence,
        "risk": risk if confidence != "building" else "unknown",  # ไม่ฟันธง risk ตอนข้อมูลน้อย
    }


# =============================================================================
# 6. Persistence — daily_strain table
#
# ⚠️ DEPRECATED / ไม่ได้ใช้งานจริง: app.py เก็บผลลัพธ์ผ่าน coros_db.store_daily_strain()
# ซึ่งใช้ schema คนละแบบกับ DAILY_STRAIN_SCHEMA ด้านล่างนี้ (column ชื่อไม่ตรงกัน:
# coros_db ใช้ "day_strain" + "summary_json", ที่นี่ใช้ "strain" + "acwr_risk" + "source")
# ถ้ามีใครเผลอเรียก save_daily_strain() นี้แทน coros_db.store_daily_strain() จะได้
# sqlite3.OperationalError: no such column เพราะตารางจริงถูกสร้างจาก coros_db.py ไปแล้ว
# เก็บไว้เป็น reference/legacy เฉยๆ — อย่าเรียกใช้ฟังก์ชันนี้จาก app.py หรือที่อื่น
# =============================================================================

DAILY_STRAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_strain (
    date        TEXT PRIMARY KEY,
    trimp       REAL,
    strain      REAL,
    acwr        REAL,
    acwr_risk   TEXT,
    source      TEXT DEFAULT 'activities_only',  -- 'activities_only' | 'hr_timeseries' (Layer 2)
    updated_at  TEXT NOT NULL
);
"""


def save_daily_strain(conn, date: str, trimp: float, strain: float, acwr_result: Optional[dict]):
    """บันทึก strain ของวันนั้นลง SQLite (ใช้ conn เดิมจาก coros_db.get_conn())"""
    conn.execute(DAILY_STRAIN_SCHEMA)
    conn.execute(
        """
        INSERT OR REPLACE INTO daily_strain
            (date, trimp, strain, acwr, acwr_risk, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            date,
            trimp,
            strain,
            (acwr_result or {}).get("acwr"),
            (acwr_result or {}).get("risk"),
            "activities_only",
            datetime.now().isoformat(),
        ),
    )
    conn.commit()


# =============================================================================
# 7. High-level entry point — เรียกอันเดียวจบ
# =============================================================================

def compute_strain_for_all_days(
    activities: List[dict],
    sleep_records: List[dict],
    sex: str = "male",
) -> List[dict]:
    """
    คำนวณ strain/TRIMP/ACWR ของทุกวันที่มีข้อมูล activity
    คืน list เรียงตามวันที่ (เก่า->ใหม่) พร้อมใช้ save_daily_strain() ต่อ หรือ
    ส่งตรงให้ app.py /api/analysis ได้เลย
    """
    hr_max = estimate_hr_max(activities)
    hr_rest = estimate_hr_rest(sleep_records)

    daily_trimp = daily_trimp_from_activities(activities, hr_rest, hr_max, sex)

    results = []
    for date in sorted(daily_trimp.keys()):
        trimp = daily_trimp[date]
        strain = trimp_to_strain(trimp)
        acwr = compute_acwr(daily_trimp, date)
        results.append({
            "date": date,
            "trimp": trimp,
            "strain": strain,
            "acwr": acwr,
        })
    return results
