# Sleep Analysis Module v2 — ฟังก์ชันวิเคราะห์การนอนแบบละเอียด (Rule-based, ไม่พึ่ง AI API)

อัปเดตจาก v1: เพิ่ม SpO2, Skin Temperature (มีจริงใน COROS), ใช้ REM จริงจาก sensor (ไม่ต้อง estimate แล้ว), เพิ่ม Journal Correlation ที่รับ input จากผู้ใช้ผ่านหน้าเว็บ

---

## 0. Input Schema (ข้อมูลดิบที่ต้องมี)

```python
# ต่อ 1 คืน (1 record) — ดึงจาก COROS MCP
SleepRecord = {
    "date": "2026-09-17",
    "sleep_start": "2026-09-16T23:12:00",
    "sleep_end": "2026-09-17T06:45:00",
    "time_in_bed_min": 453,
    "total_sleep_min": 421,
    "stages": {
        "awake": 32,
        "light": 240,
        "deep": 95,
        "rem": 86                       # COROS แยกให้ตรงๆ แล้ว ใช้ค่าจริงได้เลย ไม่ต้อง estimate
    },
    "wake_events": 4,
    "sleep_stress": 18,                 # 0-100
    "resting_hr": 54,
    "hrv_ms": 62,
    "respiratory_rate": 14.2,
    "spo2_avg": 96.5,                   # % เฉลี่ยทั้งคืน
    "spo2_min": 91,                     # % ต่ำสุดที่วัดได้
    "spo2_readings": [                  # ถ้ามี timeline (ทุก N นาที)
        {"ts": "2026-09-16T23:30:00", "value": 97},
        {"ts": "2026-09-16T23:35:00", "value": 96}
    ],
    "skin_temp_deviation_c": 0.3,       # ส่วนเบี่ยงเบนจาก baseline ของตัวเอง (°C) ที่ COROS คำนวณให้
    "training_load_prev_day": 210
}

# บันทึกโดยผู้ใช้เองผ่าน UI (ไม่มาจาก COROS)
JournalEntry = {
    "date": "2026-09-17",
    "alcohol_units": 0,
    "caffeine_after_14": False,
    "late_meal": False,          # กินมื้อหนักใกล้เข้านอน (<3 ชม.)
    "screen_before_bed_min": 20,
    "stress_level": 3,           # 1-5 self-report
    "exercise_evening": False,
    "room_temp_hot": False,
    "notes": ""
}
```

เก็บ `SleepRecord` และ `JournalEntry` แยกตาราง เชื่อมกันด้วย `date` — โครงสร้างนี้ทำให้ backfill ข้อมูลเก่าที่ไม่มี journal ได้โดยไม่กระทบ metric อื่น

---

## 1. Basic Metrics

### 1.1 Sleep Efficiency
```
Sleep Efficiency (%) = (total_sleep_min / time_in_bed_min) × 100
```
```python
def sleep_efficiency(record: dict) -> float:
    return round((record["total_sleep_min"] / record["time_in_bed_min"]) * 100, 1)
```
เกณฑ์: ≥85% ดี, 75-84% พอใช้, <75% ควรปรับปรุง

### 1.2 Sleep Onset Latency
```python
def estimate_latency(stage_timeline: list) -> int:
    for ts, stage in stage_timeline:
        if stage != "awake":
            return int((ts - stage_timeline[0][0]).total_seconds() / 60)
    return None
```

### 1.3 Stage Percentage (ใช้ค่าจริงทั้งหมด รวม REM)
```python
def stage_percentages(record: dict) -> dict:
    total = record["total_sleep_min"]
    return {k: round(v / total * 100, 1) for k, v in record["stages"].items() if k != "awake"}
```

**ค่าอ้างอิงมาตรฐานผู้ใหญ่:**
| Stage | % ปกติของ total sleep |
|---|---|
| Light | 45–55% |
| Deep (SWS) | 13–23% |
| REM | 20–25% |
| Awake (ใน time in bed) | <10% ของ time in bed |

---

## 2. Sleep Architecture Analysis

### 2.1 Personal Baseline (rolling average)
```python
import statistics

def compute_baseline(records: list, metric_path: list, window: int = 30) -> dict:
    values = []
    for r in records[-window:]:
        v = r
        for key in metric_path:
            v = v[key]
        if v is not None:
            values.append(v)
    if len(values) < 5:
        return {"mean": None, "stdev": None, "n": len(values)}
    return {
        "mean": round(statistics.mean(values), 2),
        "stdev": round(statistics.stdev(values), 2),
        "n": len(values)
    }
```

### 2.2 Z-score เทียบ Baseline
```python
def z_score(value: float, baseline: dict) -> float:
    if baseline["stdev"] in (None, 0):
        return None
    return round((value - baseline["mean"]) / baseline["stdev"], 2)

def flag_metric(value: float, baseline: dict, invert: bool = False) -> dict:
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
    return {"z_score": z, "status": status}
```
|Z| ≥ 1.5 → สังเกต, |Z| ≥ 2.0 → flag ชัดเจน

### 2.3 Sleep Cycle Estimation
```python
def estimate_cycles(stage_timeline: list) -> dict:
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
    avg_cycle_len = round(total_sleep_min / cycles, 1) if cycles else None
    return {"cycle_count": cycles, "avg_cycle_length_min": avg_cycle_len}
```
Heuristic proxy — ไม่ใช่ physiological cycle detection ระดับ EEG

### 2.4 Fragmentation Index
```python
def fragmentation_index(stage_timeline: list, total_sleep_min: float) -> float:
    transitions = sum(
        1 for i in range(1, len(stage_timeline))
        if stage_timeline[i][1] != stage_timeline[i-1][1]
    )
    hours = total_sleep_min / 60
    return round(transitions / hours, 2) if hours else None
```
<8/ชม. ดี, 8–15 ปานกลาง, >15 ไม่ต่อเนื่อง

---

## 3. Sleep Debt & Need

### 3.1 Sleep Need แบบ dynamic
```python
def calculate_sleep_need(
    base_need_min: int = 480,
    training_load: float = 0,
    load_baseline: float = 150,
    prior_debt_min: int = 0,
    nap_min: int = 0
) -> dict:
    load_excess = max(0, training_load - load_baseline)
    strain_adjustment = int((load_excess / 50) * 10)
    total_need = base_need_min + strain_adjustment + prior_debt_min - nap_min
    return {
        "sleep_need_min": max(total_need, 360),
        "strain_adjustment_min": strain_adjustment
    }
```

### 3.2 Sleep Debt สะสม
```python
def cumulative_sleep_debt(records: list, needs: list, decay: float = 0.9, window: int = 7) -> float:
    debt = 0
    for r, need in zip(records[-window:], needs[-window:]):
        daily_debt = max(0, need - r["total_sleep_min"])
        debt = debt * decay + daily_debt
    return round(debt, 1)
```

### 3.3 Sleep Performance
```python
def sleep_performance(actual_min: int, need_min: int) -> float:
    return round(min(actual_min / need_min, 1.2) * 100, 1)
```

---

## 4. SpO2 Analysis (ใหม่)

### 4.1 ค่าเฉลี่ยและ Desaturation Events
```python
def analyze_spo2(record: dict, dip_threshold: int = 90, sustained_min: int = 2) -> dict:
    """
    dip_threshold: ค่า SpO2 ที่ถือว่าต่ำผิดปกติ (ทั่วไปใช้ <90%)
    sustained_min: ต้องต่ำต่อเนื่องกี่ reading ถึงนับเป็น event จริง (กัน noise)
    """
    readings = record.get("spo2_readings", [])
    if not readings:
        return {"avg": record.get("spo2_avg"), "min": record.get("spo2_min"), "dip_events": None}

    dip_events = 0
    consecutive_low = 0
    for r in readings:
        if r["value"] < dip_threshold:
            consecutive_low += 1
            if consecutive_low == sustained_min:
                dip_events += 1
        else:
            consecutive_low = 0

    return {
        "avg": record.get("spo2_avg"),
        "min": record.get("spo2_min"),
        "dip_events": dip_events,
        "time_below_threshold_pct": round(
            sum(1 for r in readings if r["value"] < dip_threshold) / len(readings) * 100, 1
        )
    }
```

### 4.2 Flag ความเสี่ยง
```python
def flag_spo2_risk(spo2_analysis: dict) -> str:
    if spo2_analysis["min"] is None:
        return "no_data"
    if spo2_analysis["min"] < 88 or (spo2_analysis.get("dip_events") or 0) >= 5:
        return "review_recommended"   # ไม่ใช่การวินิจฉัย แค่ธงให้สังเกต ควรปรึกษาแพทย์ถ้าเกิดซ้ำ
    if spo2_analysis["avg"] < 94:
        return "monitor"
    return "normal"
```
⚠️ ค่า SpO2 ต่ำต่อเนื่องอาจสัมพันธ์กับภาวะเช่น sleep apnea — ฟังก์ชันนี้เป็นแค่ตัวช่วยสังเกตแนวโน้ม **ไม่ใช่การวินิจฉัย** ถ้า flag ขึ้น `review_recommended` บ่อยควรปรึกษาแพทย์

---

## 5. Skin Temperature Analysis (ใหม่)

COROS ให้ค่า deviation จาก baseline มาโดยตรง (`skin_temp_deviation_c`) — ใช้ต่อได้เลยไม่ต้องคำนวณ baseline เอง แต่ควรทำ rolling trend เพื่อดู pattern

```python
def analyze_skin_temp(records: list, window: int = 7) -> dict:
    recent = [r["skin_temp_deviation_c"] for r in records[-window:] if r.get("skin_temp_deviation_c") is not None]
    if not recent:
        return {"trend": None, "flag": "no_data"}

    latest = recent[-1]
    avg_recent = round(sum(recent) / len(recent), 2)

    flag = "normal"
    if latest >= 0.5:
        flag = "elevated"          # อาจสัมพันธ์กับการเจ็บป่วย/ovulation(ถ้าเป็นผู้หญิง)/สภาพแวดล้อมร้อน
    elif latest <= -0.5:
        flag = "lowered"

    return {"latest_deviation": latest, "avg_recent": avg_recent, "flag": flag}
```
เกณฑ์ ±0.5°C จาก baseline เป็นจุดเริ่มสังเกต (ปรับตามความไวที่ต้องการ) — deviation สูงต่อเนื่องหลายคืนมักมีนัยมากกว่าคืนเดียว

---

## 6. Recovery Composite Score (รวม SpO2 เข้าไปด้วย)

```python
def recovery_score(
    hrv_today: float, hrv_baseline: dict,
    rhr_today: float, rhr_baseline: dict,
    sleep_performance_pct: float,
    sleep_efficiency_pct: float,
    spo2_flag: str = "normal",
    skin_temp_flag: str = "normal",
    resp_rate_z: float = 0
) -> dict:
    """
    Weighted composite:
      HRV        30%
      RHR        20%
      Sleep Perf 25%
      Sleep Eff  15%
      SpO2/Temp  10% (penalty เท่านั้น ไม่ให้คะแนนบวก)
    """
    hrv_z = z_score(hrv_today, hrv_baseline) or 0
    rhr_z = z_score(rhr_today, rhr_baseline) or 0

    def z_to_score(z, invert=False):
        z = -z if invert else z
        score = 50 + (z * 20)
        return max(0, min(100, score))

    hrv_component = z_to_score(hrv_z)
    rhr_component = z_to_score(rhr_z, invert=True)

    base_composite = (
        hrv_component * 0.30 +
        rhr_component * 0.20 +
        sleep_performance_pct * 0.25 +
        sleep_efficiency_pct * 0.15
    )

    # penalty จาก SpO2/skin temp/respiratory (สัญญาณเจ็บป่วยหรือพักฟื้นไม่เต็มที่)
    penalty = 0
    if spo2_flag == "review_recommended":
        penalty += 15
    elif spo2_flag == "monitor":
        penalty += 7
    if skin_temp_flag in ("elevated", "lowered"):
        penalty += 8
    if resp_rate_z and abs(resp_rate_z) >= 1.5:
        penalty += 5

    composite = max(0, base_composite - penalty)
    band = "green" if composite >= 67 else "yellow" if composite >= 34 else "red"
    return {"recovery_score": round(composite, 1), "band": band, "penalty_applied": penalty}
```

---

## 7. Journal Correlation Engine (ใหม่ — รับ input จาก UI)

### 7.1 เชื่อม Journal กับ Sleep metric
```python
def correlate_journal_factor(records: list, journals: list, factor_key: str, metric_fn) -> dict:
    """
    factor_key: เช่น "alcohol_units" > 0, "late_meal" == True
    metric_fn: function(record) -> float เช่น deep sleep %, sleep efficiency
    เปรียบเทียบคืนที่มี factor vs ไม่มี factor (t-test แบบง่าย โดยใช้ mean diff)
    """
    by_date_journal = {j["date"]: j for j in journals}
    with_factor, without_factor = [], []

    for r in records:
        j = by_date_journal.get(r["date"])
        if not j:
            continue
        value = metric_fn(r)
        if value is None:
            continue
        flag = j.get(factor_key)
        is_present = (flag > 0) if isinstance(flag, (int, float)) else bool(flag)
        (with_factor if is_present else without_factor).append(value)

    if len(with_factor) < 3 or len(without_factor) < 3:
        return {"insufficient_data": True}

    import statistics
    mean_with = statistics.mean(with_factor)
    mean_without = statistics.mean(without_factor)
    return {
        "factor": factor_key,
        "mean_with": round(mean_with, 1),
        "mean_without": round(mean_without, 1),
        "difference": round(mean_with - mean_without, 1),
        "n_with": len(with_factor),
        "n_without": len(without_factor)
    }
```

### 7.2 สรุปปัจจัยที่กระทบการนอนมากที่สุด
```python
def rank_journal_impacts(records: list, journals: list, metric_fn) -> list:
    factors = ["alcohol_units", "caffeine_after_14", "late_meal",
               "stress_level", "exercise_evening", "room_temp_hot"]
    results = []
    for f in factors:
        r = correlate_journal_factor(records, journals, f, metric_fn)
        if not r.get("insufficient_data"):
            results.append(r)
    return sorted(results, key=lambda x: abs(x["difference"]), reverse=True)
```
ใช้ metric_fn เป็น deep sleep %, sleep efficiency, หรือ recovery score ก็ได้ตามที่อยากรู้ผลกระทบ

---

## 8. Correlation & Trend Engine

```python
def correlate_load_vs_sleep(records: list, lag_days: int = 1) -> float:
    import numpy as np
    loads = [r["training_load_prev_day"] for r in records[lag_days:]]
    deep_pct = [
        r["stages"]["deep"] / r["total_sleep_min"] * 100
        for r in records[:-lag_days] if r["total_sleep_min"] > 0
    ]
    n = min(len(loads), len(deep_pct))
    if n < 10:
        return None
    return round(float(np.corrcoef(loads[:n], deep_pct[:n])[0, 1]), 3)


def rolling_average(records: list, metric_fn, window: int = 7) -> list:
    values = [metric_fn(r) for r in records]
    result = []
    for i in range(len(values)):
        window_vals = [v for v in values[max(0, i-window+1):i+1] if v is not None]
        result.append(round(sum(window_vals) / len(window_vals), 1) if window_vals else None)
    return result


def bedtime_consistency(records: list, window: int = 7) -> float:
    import statistics
    from datetime import datetime

    minutes_from_midnight = []
    for r in records[-window:]:
        t = datetime.fromisoformat(r["sleep_start"])
        m = t.hour * 60 + t.minute
        if t.hour < 12:
            m += 1440
        minutes_from_midnight.append(m)

    if len(minutes_from_midnight) < 3:
        return None
    stdev = statistics.stdev(minutes_from_midnight)
    score = max(0, 100 - stdev * 1.2)
    return round(score, 1)
```

---

## 9. Anomaly Detection & Alerting

```python
def detect_anomalies(record: dict, baselines: dict) -> list:
    anomalies = []
    checks = [
        ("deep_sleep_low", record["stages"]["deep"], baselines.get("deep"), False),
        ("rem_low", record["stages"]["rem"], baselines.get("rem"), False),
        ("hrv_drop", record["hrv_ms"], baselines.get("hrv_ms"), False),
        ("resting_hr_spike", record["resting_hr"], baselines.get("resting_hr"), True),
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
        anomalies.append({"type": "skin_temp_deviation", "value": skin_temp, "severity": "warning"})

    return anomalies


def should_alert(records: list, metric_path: list, threshold: float, consecutive_days: int = 3) -> bool:
    recent = records[-consecutive_days:]
    if len(recent) < consecutive_days:
        return False
    for r in recent:
        v = r
        for key in metric_path:
            v = v[key]
        if v is None or v >= threshold:
            return False
    return True
```

---

## 10. Weekly Report Generator (template-based)

```python
def generate_weekly_report(records: list, journals: list) -> str:
    n = len(records)
    avg_eff = round(sum(sleep_efficiency(r) for r in records) / n, 1)
    avg_deep = round(sum(r["stages"]["deep"] for r in records) / n, 1)
    avg_rem = round(sum(r["stages"]["rem"] for r in records) / n, 1)
    avg_spo2 = round(sum(r.get("spo2_avg", 0) for r in records) / n, 1)
    consistency = bedtime_consistency(records)
    top_impact = rank_journal_impacts(records, journals, sleep_efficiency)
    top_line = (
        f"- ปัจจัยกระทบมากสุด: {top_impact[0]['factor']} (ต่าง {top_impact[0]['difference']} จุด)"
        if top_impact else "- ยังไม่มีข้อมูล journal เพียงพอสำหรับวิเคราะห์ปัจจัย"
    )

    report = f"""
📊 สรุปการนอนประจำสัปดาห์ ({n} คืน)
- Sleep Efficiency เฉลี่ย: {avg_eff}%
- Deep Sleep เฉลี่ย: {avg_deep} นาที/คืน
- REM เฉลี่ย: {avg_rem} นาที/คืน
- SpO2 เฉลี่ย: {avg_spo2}%
- Bedtime Consistency: {consistency}/100
{top_line}
""".strip()
    return report
```

---

## 11. ลำดับการ implement แนะนำ

1. Loader: normalize ข้อมูลจาก COROS MCP → schema ข้อ 0 (รวม spo2/skin_temp/rem จริง)
2. สร้างหน้า Journal input (ดู UI ที่แนบมาให้) — เก็บลง DB/Sheets แยกตาราง เชื่อมด้วย `date`
3. Implement ข้อ 1, 4, 5 (basic + spo2 + skin temp) — ใช้ได้ทันทีไม่ต้องรอ baseline
4. เก็บข้อมูลสะสม ≥30 วัน แล้วเปิดข้อ 2, 6 (baseline-dependent)
5. เก็บ journal ควบคู่ไป ≥2-3 สัปดาห์ก่อนเปิดข้อ 7 (correlation ต้องการ sample ≥3 ต่อกลุ่ม)
6. ข้อ 8 (correlation กับ training load) ต้องการข้อมูล ≥30-60 วัน
7. ต่อข้อ 9-10 เข้า Telegram/Sheets ตาม pipeline เดิม

---

## หมายเหตุสำคัญ
- ทุกสูตรเป็น **heuristic/statistical** ไม่ใช่การวินิจฉัยทางการแพทย์ โดยเฉพาะ SpO2/Skin Temp ที่อาจสัมพันธ์กับปัญหาสุขภาพ — flag เหล่านี้คือ "ควรสังเกต" ไม่ใช่ "เป็นโรค"
- Coefficient (weight ใน recovery score, threshold ต่างๆ) เป็นค่าตั้งต้น ควร **calibrate ด้วยข้อมูลจริงของตัวเอง** เมื่อสะสมได้ ≥60 วัน
