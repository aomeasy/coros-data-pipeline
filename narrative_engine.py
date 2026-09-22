# -*- coding: utf-8 -*-
"""
narrative_engine.py — Phase 6: Narrative Insight Engine

สร้างรายงานภาษาคนจากข้อมูลที่คำนวณแล้ว — rule-based 100% ไม่มี AI API
"""

from typing import Dict, List, Optional
from datetime import datetime, timedelta


# =============================================================================
# Helper
# =============================================================================

def _band_label(value: float, thresholds: list, labels: list) -> str:
    """แปลค่าเป็น band label"""
    for t, l in zip(thresholds, labels):
        if value >= t:
            return l
    return labels[-1]

def _trend_word(change_pct: float) -> str:
    """แปล % change เป็นคำ"""
    if change_pct > 10:
        return "เพิ่มขึ้นมาก"
    elif change_pct > 3:
        return "เพิ่มขึ้น"
    elif change_pct > -3:
        return "คงที่"
    elif change_pct > -10:
        return "ลดลง"
    else:
        return "ลดลงมาก"

def _sign(val: float) -> str:
    return "+" if val >= 0 else ""

def _avg(lst: list) -> float:
    """ค่าเฉลี่ย ค่าเฉลี่ย"""
    if not lst:
        return 0
    return sum(lst) / len(lst)

def _safe_get(d: dict, key: str, default=0):
    v = d.get(key, default)
    return v if v is not None else default


# =============================================================================
# Recovery Narrative
# =============================================================================

def _narrative_recovery(recovery: dict, baselines: dict) -> str:
    """Recovery section แบบเต็ม"""
    score = _safe_get(recovery, "recovery_score", 50)
    band = _safe_get(recovery, "band", "yellow")
    penalty = _safe_get(recovery, "penalty_applied", 0)
    tl_penalty = _safe_get(recovery, "training_load_penalty", 0)
    resp_penalty = _safe_get(recovery, "resp_rate_trend_penalty", 0)

    # Band label
    if band == "green":
        band_text = "ฟื้นฟูดีมาก"
    elif band == "yellow":
        band_text = "ฟื้นฟูปานกลาง"
    else:
        band_text = "ฟื้นฟูต่ำ"

    # ประโยคแรก
    text = f"วันนี้ Recovery Score {score}/100 — {band_text} "

    # บรรยาย components
    components = _safe_get(recovery, "components", {})
    hrv_score = _safe_get(components, "hrv_score", 50)
    rhr_score = _safe_get(components, "rhr_score", 50)
    sleep_perf = _safe_get(components, "sleep_performance", 75)
    sleep_eff = _safe_get(components, "sleep_efficiency", 80)

    text += f"HRV component {hrv_score:.0f} และ RHR component {rhr_score:.0f} อยู่ในเกณฑ์ปกติ "

    # Penalty
    if penalty > 0:
        penalty_parts = []
        if tl_penalty > 0:
            penalty_parts.append(f"Training Load penalty {tl_penalty:.1f}")
        if resp_penalty > 0:
            penalty_parts.append(f"Respiratory trend penalty {resp_penalty:.1f}")
        if penalty - tl_penalty - resp_penalty > 0:
            penalty_parts.append(f"SpO2/Skin Temp penalty {penalty - tl_penalty - resp_penalty:.1f}")
        text += f"ถูกหักคะแนนเพราะ {' และ '.join(penalty_parts)} "
    else:
        text += "ไม่มี penalty ใดๆ "

    # สรุป
    if band == "green":
        text += "สรุป: พร้อมซ้อมหนักได้ตามแผน"
    elif band == "yellow":
        text += "สรุป: ซ้อมได้แต่ควรระวัง ไม่ควรเพิ่ม intensity"
    else:
        text += "สรุป: ควรซ้อมเบาๆ หรือวันหยุด"

    return text


# =============================================================================
# Sleep Narrative
# =============================================================================

def _narrative_sleep(sleep: dict, consistency: float, debt: float) -> str:
    """Sleep section แบบเต็ม"""
    duration = _safe_get(sleep, "duration_min", 0)
    eff = _safe_get(sleep, "efficiency", 85)
    deep = _safe_get(sleep, "deep_sleep_pct", 0)
    light = _safe_get(sleep, "light_sleep_pct", 0)
    rem = _safe_get(sleep, "rem_sleep_pct", 0)
    hrv = _safe_get(sleep, "hrv", 0)
    rhr = _safe_get(sleep, "resting_hr", 0)
    nap = _safe_get(sleep, "nap_min", 0)

    h = int(duration // 60)
    m = int(duration % 60)
    text = f"นอนทั้งหมด {h} ชั่วโมง {m} นาที — Sleep Efficiency {eff}% "

    # Band
    if eff >= 90:
        text += "(ดีมาก) "
    elif eff >= 80:
        text += "(ดี) "
    elif eff >= 70:
        text += "(พอใช้) "
    else:
        text += "(ควรปรับปรุง) "

    # Stages
    text += f"Deep Sleep {deep:.0f}% "
    if 13 <= deep <= 23:
        text += "(ปกติ) "
    elif deep < 13:
        text += "(ต่ำ) "
    else:
        text += "(สูง) "

    text += f"REM {rem:.0f}% "
    if 20 <= rem <= 25:
        text += "(ปกติ) "
    elif rem < 20:
        text += "(ต่ำ) "
    else:
        text += "(สูง) "

    text += f"Light Sleep {light:.0f}%. "

    # HRV & RHR ขณะนอน
    if hrv > 0:
        text += f"HRV ขณะนอน {hrv:.0f}ms "
    if rhr > 0:
        text += f"Resting HR {rhr:.0f}bpm "

    # Consistency
    if consistency:
        text += f"\nBedtime Consistency {consistency:.0f}/100 — "
        if consistency >= 85:
            text += "นอนตรงเวลาดีมาก"
        elif consistency >= 65:
            text += "นอนตรงเวลาพอใช้"
        else:
            text += "เวลานอนไม่สม่ำเสมอ ลองปรับให้ตรงเวลา"
        text += ". "

    # Debt
    if debt > 0:
        text += f"\nSleep Debt สะสม {debt:.0f} นาที — ยังมีหนี้ต้องฟื้นฟู"
    else:
        text += "\nไม่มี Sleep Debt — นอนพอดี"

    # Nap
    if nap > 0:
        text += f"\nNap {nap:.0f} นาที"
        if nap > 30:
            text += " (ยาวเกินไป อาจกระทบนอนหลัก)"
        else:
            text += " (พอดีช่วยฟื้นฟู)"

    return text


# =============================================================================
# Training Load Narrative
# =============================================================================

def _narrative_training(strain_series: list, training_analytics: dict) -> str:
    """Training section แบบเต็ม"""
    if not strain_series:
        return "ไม่มีข้อมูลการซ้อม"

    latest = strain_series[0] if strain_series else {}
    strain = _safe_get(latest, "day_strain", 0)
    trimp = _safe_get(latest, "trimp", 0)
    acwr = _safe_get(latest, "acwr", 0)
    acwr_risk = _safe_get(latest, "acwr_risk", "unknown")

    text = f"Strain วันนี้ {strain:.1f}/21 — "

    if strain < 5:
        text += "วันพักผ่อนหรือซ้อมเบาๆ "
    elif strain < 10:
        text += "ซ้อมระดับปานกลาง "
    elif strain < 14:
        text += "ซ้อมหนัก "
    elif strain < 18:
        text += "ซ้อมหนักมาก "
    else:
        text += "ซ้อมสุดขีด ต้องพักฟื้นหลังจากนี้"

    text += f"TRIMP {trimp:.1f}. "

    # ACWR
    if acwr:
        text += f"ACWR {acwr:.2f} — "
        if acwr_risk == "high":
            text += "เสี่ยงบาดเจ็บสูง! ควรลดโหลดทันที"
        elif acwr_risk == "normal":
            text += "ปลอดภัย สามารถซ้อมต่อได้"
        elif acwr_risk == "detraining":
            text += "โหลดลดมากเกินไป อาจสูญเสีย fitness"
        else:
            text += f"สถานะ {acwr_risk}"

    # CTL/ATL/TSB
    fitness = _safe_get(training_analytics, "fitness", {})
    ctl = _safe_get(fitness, "ctl", 0)
    atl = _safe_get(fitness, "atl", 0)
    tsb = _safe_get(fitness, "tsb", 0)
    confidence = _safe_get(fitness, "confidence", "building")

    if ctl:
        text += f"\nFitness (CTL) {ctl:.1f} / Fatigue (ATL) {atl:.1f} / Form (TSB) {tsb:+.1f} — "
        if tsb > 10:
            text += "สภาพร่างกายสดใส พร้อมทำผลงานได้ดี"
        elif tsb > -5:
            text += "สภาพร่างกายใช้งานได้ดี"
        elif tsb > -15:
            text += "เริ่มเหนื่อย ควรซ้อมเบาๆ บ้าง"
        else:
            text += "เหนื่อยมาก ต้องฟื้นฟู"

    return text


# =============================================================================
# Health Risk Narrative
# =============================================================================

def _narrative_health(illness: dict, overtraining: dict) -> str:
    """Health Risk section แบบเต็ม"""
    sections = []

    # Illness
    if illness:
        level = _safe_get(illness, "risk_level", "none")
        signals = _safe_get(illness, "signals", [])
        score = _safe_get(illness, "risk_score", 0)

        if level in ("medium", "high"):
            text = f"ความเสี่ยงป่วย: {level} ({score}/4 สัญญาณ"
            if signals:
                signal_labels = {
                    "rhr_high": "RHR สูงผิดปกติ",
                    "hrv_low": "HRV ต่ำผิดปกติ",
                    "skin_temp_high": "Skin Temp สูงผิดปกติ",
                    "resp_rate_high": "Respiratory Rate สูงผิดปกติ"
                }
                labeled = [signal_labels.get(s, s) for s in signals]
                text += f": {', '.join(labeled)}"
            text += ")"
            sections.append(text)
        else:
            sections.append("ความเสี่ยงป่วย: ไม่พบสัญญาณผิดปกติ")

    # Overtraining
    if overtraining:
        level = _safe_get(overtraining, "risk_level", "none")
        flags = _safe_get(overtraining, "flags", [])

        if level in ("medium", "high"):
            text = f"ความเสี่ยง Overtraining: {level}"
            if flags:
                flag_labels = {
                    "acwr_high": "ACWR สูงต่อเนื่อง",
                    "hrv_declining": "HRV แนวโน้มลด",
                    "recovery_low": "Recovery ต่ำติดต่อกัน"
                }
                labeled = [flag_labels.get(f, f) for f in flags]
                text += f" ({', '.join(labeled)})"
            sections.append(text)
        elif level == "low":
            sections.append("ความเสี่ยง Overtraining: ต่ำ (มีสัญญาณเล็กน้อย ยังไม่ต้องกังวล)")
        else:
            sections.append("ความเสี่ยง Overtraining: ไม่พบสัญญาณ")

    return "\n".join(sections)


# =============================================================================
# Action Items
# =============================================================================

def _action_items(recovery: dict, strain_series: list, illness: dict, overtraining: dict) -> List[str]:
    """คำแนะนำเชิงปฏิบัติ"""
    actions = []

    # จาก recovery
    band = _safe_get(recovery, "band", "yellow")
    if band == "green":
        actions.append("ซ้อมได้ตามแผน — Recovery ดี")
    elif band == "yellow":
        actions.append("ซ้อมเบาลง 10-15% — Recovery ปานกลาง")
    else:
        actions.append("พักหรือ active recovery — Recovery ต่ำ")

    # จาก ACWR
    if strain_series:
        latest = strain_series[0] if strain_series else {}
        acwr = _safe_get(latest, "acwr", 0)
        acwr_risk = _safe_get(latest, "acwr_risk", "unknown")
        if acwr_risk == "high":
            actions.append(f"ACWR {acwr:.2f} สูง — ลด Training Load 10-20% สัปดาห์หน้า")

    # จาก illness
    if illness:
        level = _safe_get(illness, "risk_level", "none")
        if level == "high":
            actions.append("สัญญาณป่วยสูง — ซ้อมเบาๆ หรือพัก")
        elif level == "medium":
            actions.append("มีสัญญาณป่วย — สังเกตอาการ อาจลด intensity")

    # จาก overtraining
    if overtraining:
        level = _safe_get(overtraining, "risk_level", "none")
        if level == "high":
            actions.append("เสี่ยง Overtraining สูง — deload week ทันที")
        elif level == "medium":
            actions.append("เริ่มมีสัญญาณ overtraining — เพิ่มวันพัก")

    return actions


# =============================================================================
# High-level entry point — Daily
# =============================================================================

def generate_daily_narrative(
    recovery: dict,
    sleep: dict,
    strain_series: list,
    training_analytics: dict,
    illness: dict = None,
    overtraining: dict = None,
    consistency: float = 0,
    sleep_debt: float = 0,
) -> dict:
    """
    สร้างรายงานประจำวันแบบเต็มรูปแบบ — rule-based 100%
    """
    sections = {
        "recovery": _narrative_recovery(recovery, {}),
        "sleep": _narrative_sleep(sleep, consistency, sleep_debt),
        "training": _narrative_training(strain_series, training_analytics),
        "health": _narrative_health(illness or {}, overtraining or {}),
    }

    # Summary
    score = _safe_get(recovery, "recovery_score", 50)
    band = _safe_get(recovery, "band", "yellow")
    band_text = {"green": "ดีมาก", "yellow": "ปานกลาง", "red": "ต่ำ"}.get(band, "")
    duration = _safe_get(sleep, "duration_min", 0)
    eff = _safe_get(sleep, "efficiency", 85)

    h = int(duration // 60)
    m = int(duration % 60)

    summary = (
        f"วันนี้ Recovery {score:.0f}/100 ({band_text}) — "
        f"นอน {h}ช {m}ผ่าน Sleep Efficiency {eff:.0f}%"
    )

    return {
        "summary": summary,
        "sections": sections,
        "action_items": _action_items(recovery, strain_series, illness, overtraining),
        "generated_at": datetime.now().isoformat(),
    }


# =============================================================================
# Weekly Digest
# =============================================================================

def generate_weekly_digest(
    sleep_records: List[dict],
    strain_series: list,
    training_analytics: dict,
    journal_correlations: list = None,
) -> dict:
    """
    สร้างรายงานประจำสัปดาห์แบบเต็มรูปแบบ — rule-based 100%
    """
    if not sleep_records:
        return {"overview": "ไม่มีข้อมูลเพียงพอสำหรับสร้างรายงาน"}

    # 7-day averages
    last_7 = sleep_records[-7:]
    prev_7 = sleep_records[-14:-7] if len(sleep_records) >= 14 else []

    avg_eff = _avg([_safe_get(r, "efficiency", 0) or _safe_get(r, "sleep_efficiency", 0) for r in last_7])
    avg_duration = _avg([_safe_get(r, "duration_min", 0) for r in last_7])
    avg_deep = _avg([_safe_get(r, "deep_sleep_pct", 0) for r in last_7])
    avg_rem = _avg([_safe_get(r, "rem_sleep_pct", 0) for r in last_7])
    avg_hrv = _avg([_safe_get(r, "hrv", 0) for r in last_7 if r.get("hrv")])
    avg_rhr = _avg([_safe_get(r, "resting_hr", 0) for r in last_7 if r.get("resting_hr")])

    # เทียบกับสัปดาห์ก่อน
    prev_eff = _avg([_safe_get(r, "efficiency", 0) or _safe_get(r, "sleep_efficiency", 0) for r in prev_7]) if prev_7 else 0
    prev_duration = _avg([_safe_get(r, "duration_min", 0) for r in prev_7]) if prev_7 else 0

    eff_change = ((avg_eff - prev_eff) / prev_eff * 100) if prev_eff > 0 else 0
    dur_change = ((avg_duration - prev_duration) / prev_duration * 100) if prev_duration > 0 else 0

    # Overview text
    overview = (
        f"สัปดาห์นี้นอนค่าเฉลี่ย {int(avg_duration // 60)} ชั่วโมง {int(avg_duration % 60)} นาที "
        f"— Sleep Efficiency {avg_eff:.1f}% "
        f"({_trend_word(eff_change)}จากสัปดาห์ก่อน {_sign(eff_change)}{eff_change:.1f}%) "
        f"Deep Sleep {avg_deep:.1f}% / REM {avg_rem:.1f}%"
    )

    # Strain trend
    recent_strain = [s.get("day_strain", 0) for s in strain_series[-7:] if s.get("day_strain")]
    prev_strain = [s.get("day_strain", 0) for s in strain_series[-14:-7] if s.get("day_strain")]
    avg_strain = _avg(recent_strain) if recent_strain else 0
    prev_avg_strain = _avg(prev_strain) if prev_strain else 0

    strain_change = ((avg_strain - prev_avg_strain) / prev_avg_strain * 100) if prev_avg_strain > 0 else 0

    strain_text = f"Training Load เฉลี่ย {avg_strain:.1f}/21 — {_trend_word(strain_change)} {_sign(strain_change)}{strain_change:.1f}% จากสัปดาห์ก่อน"

    # CTL/ATL/TSB trend
    fitness = _safe_get(training_analytics, "fitness", {})
    ctl = _safe_get(fitness, "ctl", 0)
    atl = _safe_get(fitness, "atl", 0)
    tsb = _safe_get(fitness, "tsb", 0)

    fitness_text = ""
    if ctl:
        fitness_text = f"Fitness (CTL) {ctl:.1f} / Fatigue (ATL) {atl:.1f} / Form (TSB) {tsb:+.1f}"

    # Economy
    economy = _safe_get(training_analytics, "economy", {})
    econ_trend = _safe_get(economy, "trend", None)
    econ_change = _safe_get(economy, "economy_change_pct", 0)

    economy_text = ""
    if econ_trend:
        if econ_trend == "improving":
            economy_text = f"Running Economy ดีขึ้น {abs(econ_change):.1f}% — วิ่งเร็วขึ้นที่ HR เดียวกัน"
        elif econ_trend == "declining":
            economy_text = f"Running Economy แย่ลง {abs(econ_change):.1f}% — อาจยังไม่ฟื้น"
        else:
            economy_text = "Running Economy คงที่"

    # Journal insights
    insights = []
    if journal_correlations:
        for jc in journal_correlations[:3]:
            factor = _safe_get(jc, "factor", "")
            diff = _safe_get(jc, "difference", 0)
            if abs(diff) > 3:
                direction = "เพิ่ม" if diff > 0 else "ลด"
                factor_labels = {
                    "alcohol_units": "การดื่มแอลกอฮอล์",
                    "caffeine_after_14": "คาเฟอินหลัง 14:00",
                    "late_meal": "อาหารมื้อดึก",
                    "stress_level": "ความเครียด",
                    "exercise_evening": "การออกกำลังกายตอนเย็น",
                    "room_temp_hot": "ห้องร้อน",
                }
                label = factor_labels.get(factor, factor)
                insights.append(f"{label}ส่งผลให้ Sleep Efficiency {direction} {abs(diff):.1f}%")

    # Next week advice
    next_week = []
    if avg_eff < 80:
        next_week.append("ปรับปรุงการนอน — Efficiency ต่ำกว่า 80%")
    if avg_strain > 14:
        next_week.append("ลด Training Load — โหลดสูงมาก")
    elif avg_strain < 5:
        next_week.append("เพิ่ม Training Load เล็กน้อน — ซ้อมเบาเกินไป")
    if tsb < -15:
        next_week.append("deload week — TSB ต่ำมาก")
    elif tsb > 15:
        next_week.append("สภาพพร้อม peak — อาจวางแผนแข่งได้")
    if insights:
        next_week.append(f"ลด {insights[0].split('ส่งผล')[0].strip()} เพื่อนอนดีขึ้น")

    return {
        "overview": overview,
        "sleep_trends": {
            "efficiency_avg": round(avg_eff, 1),
            "efficiency_change": round(eff_change, 1),
            "duration_avg": round(avg_duration, 0),
            "deep_avg": round(avg_deep, 1),
            "rem_avg": round(avg_rem, 1),
        },
        "training_trends": {
            "strain_avg": round(avg_strain, 1),
            "strain_change": round(strain_change, 1),
        },
        "fitness": fitness_text,
        "economy": economy_text,
        "insights": insights,
        "next_week": next_week,
        "generated_at": datetime.now().isoformat(),
    }
