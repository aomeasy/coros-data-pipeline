# -*- coding: utf-8 -*-
"""
Breath Analysis Module — วิเคราะห์การหายใจ ออกซิเจน สถานะฟื้นฟู
จาก breath-coach skill formulas
"""
from typing import Optional


def analyze_respiratory_rate(rr: float) -> dict:
    """
    วิเคราะห์อัตราการหายใจ (breaths/min)
    คนปกติ: 12-20 รอบ/นาที
    นักกีฬาที่ฟิตดี: 8-12 รอบ/นาที (> 20 = ควรฟื้นฟู)
    """
    if rr is None:
        return {"value": None, "status": "no_data", "description": "-"}
    
    rr = float(rr)
    if rr < 12:
        status = "excellent"
        description = "ฟิตมาก (นักกีฬา)"
    elif 12 <= rr <= 18:
        status = "normal"
        description = "ปกติดี"
    elif 18 < rr <= 22:
        status = "fair"
        description = "ปกติ"
    else:
        status = "elevated"
        description = "ควรฟื้นฟูเพิ่ม"
    
    return {
        "value": rr,
        "status": status,
        "description": description,
        "unit": "br/min"
    }


def analyze_spo2(avg: Optional[float], min_val: Optional[float]) -> dict:
    """
    วิเคราะห์ระดับออกซิเจนในเลือด (%)
    ปกติ: 95-100%, ต่ำกว่าปกติ: 90-94%, ต่ำมาก: <90%
    """
    if avg is None:
        return {"avg": None, "min": None, "status": "no_data", "description": "-"}
    
    if min_val is None:
        min_val = avg
    
    if avg >= 95:
        status = "normal"
        description = "ปกติ"
    elif 90 <= avg < 95:
        status = "low"
        description = "ต่ำกว่าปกติ (ควรสังเกต)"
    else:
        status = "critical"
        description = "ต่ำมาก (ควรปรึกษาแพทย์)"
    
    return {
        "avg": avg,
        "min": min_val,
        "status": status,
        "description": description,
        "unit": "%"
    }


def recovery_status(recovery_pct: Optional[float], est_hours: Optional[float] = None) -> dict:
    """
    วิเคราะห์สถานะการฟื้นฟู
    ≥80%: พร้อมฝึกหนักได้
    60-79%: ฝึกปานกลางได้
    <60%: ควรพักผ่อน
    """
    if recovery_pct is None:
        return {"value": None, "level": "no_data", "description": "-"}
    
    recovery_pct = float(recovery_pct)
    if recovery_pct >= 80:
        level = "ready"
        description = "พร้อมฝึกหนักได้"
    elif 60 <= recovery_pct < 80:
        level = "moderate"
        description = "ฝึกปานกลางได้"
    else:
        level = "low"
        description = "ควรพักผ่อน"
    
    result = {
        "value": recovery_pct,
        "level": level,
        "description": description,
        "unit": "%"
    }
    
    if est_hours is not None:
        result["est_hours_to_full"] = est_hours
    
    return result


def training_load_ratio(short_term: Optional[float], long_term: Optional[float]) -> dict:
    """
    วิเคราะห์ Load Ratio = Short-term / Long-term
    0.8-1.3: สมดุลดี (Optimal Training Zone)
    >1.3: ฝึกมากเกินไป (Overreaching)
    <0.8: ฝึกน้อยเกินไป (Detraining)
    """
    if short_term is None or long_term is None or long_term <= 0:
        return {
            "ratio": None,
            "short_term": short_term,
            "long_term": long_term,
            "status": "no_data",
            "description": "-"
        }
    
    ratio = short_term / long_term
    
    if 0.8 <= ratio <= 1.3:
        status = "optimal"
        description = "สมดุลดี (Optimal Zone)"
    elif ratio > 1.3:
        status = "overreaching"
        description = "ฝึกมากเกินไป (Overreaching)"
    else:
        status = "detraining"
        description = "ฝึกน้อยเกินไป (Detraining)"
    
    return {
        "ratio": round(ratio, 2),
        "short_term": short_term,
        "long_term": long_term,
        "status": status,
        "description": description
    }


def interpret_vo2max(vo2max: Optional[float], age: int = 30, gender: str = "female") -> dict:
    """
    ตีค่า VO2max ตามเกณฑ์
    ผู้หญิง 30-39 ปี: ดีมาก >42, ดี 36-42, ปานกลาง 31-36
    ผู้ชาย 30-39 ปี: ดีมาก >50, ดี 44-50, ปานกลาง 38-44
    """
    if vo2max is None:
        return {"value": None, "level": "no_data", "description": "-"}
    
    vo2max = float(vo2max)
    
    # Use 30-39 as default
    if gender == "male":
        if vo2max > 50:
            level = "excellent"
            description = "ดีมาก"
        elif 44 <= vo2max <= 50:
            level = "good"
            description = "ดี"
        elif 38 <= vo2max < 44:
            level = "fair"
            description = "ปานกลาง"
        else:
            level = "poor"
            description = "ควรปรับปรุง"
    else:
        if vo2max > 42:
            level = "excellent"
            description = "ดีมาก"
        elif 36 <= vo2max <= 42:
            level = "good"
            description = "ดี"
        elif 31 <= vo2max < 36:
            level = "fair"
            description = "ปานกลาง"
        else:
            level = "poor"
            description = "ควรปรับปรุง"
    
    return {
        "value": vo2max,
        "level": level,
        "description": description,
        "unit": "ml/kg/min"
    }


def breathing_efficiency_score(
    rr: Optional[float],
    spo2: Optional[float],
    hrv: Optional[float],
    hrv_baseline: Optional[float] = None
) -> dict:
    """
    Breathing Efficiency Score (0-100)
    Efficiency = (respiratory_score × 0.4) + (spo2_score × 0.3) + (hrv_score × 0.3)
    """
    # Respiratory score (base 12 br/min)
    if rr is not None:
        respiratory_score = 100 - max(0, (rr - 12) * 5)
        respiratory_score = max(0, min(100, respiratory_score))
    else:
        respiratory_score = None
    
    # SpO2 score (95% = 67, 100% = 100)
    if spo2 is not None:
        spo2_score = (spo2 - 85) * 6.67
        spo2_score = max(0, min(100, spo2_score))
    else:
        spo2_score = None
    
    # HRV score
    if hrv is not None and hrv_baseline and hrv_baseline > 0:
        hrv_score = min(100, (hrv / hrv_baseline) * 70)
    elif hrv is not None:
        hrv_score = min(100, (hrv / 50) * 70)  # Use 50 as default baseline
    else:
        hrv_score = None
    
    # Weighted average
    scores = []
    weights = []
    if respiratory_score is not None:
        scores.append(respiratory_score * 0.4)
        weights.append(0.4)
    if spo2_score is not None:
        scores.append(spo2_score * 0.3)
        weights.append(0.3)
    if hrv_score is not None:
        scores.append(hrv_score * 0.3)
        weights.append(0.3)
    
    if scores and weights:
        total_weight = sum(weights)
        efficiency = round(sum(scores) / total_weight, 1) if total_weight > 0 else 0
    else:
        efficiency = None
    
    if efficiency is not None:
        if efficiency >= 80:
            status = "good"
            description = "การหายใจมีประสิทธิภาพดี"
        elif 60 <= efficiency < 80:
            status = "fair"
            description = "ปานกลาง"
        else:
            status = "poor"
            description = "ต้องปรับปรุง"
    else:
        status = "no_data"
        description = "-"
    
    return {
        "score": efficiency,
        "status": status,
        "description": description,
        "components": {
            "respiratory_score": round(respiratory_score, 1) if respiratory_score is not None else None,
            "spo2_score": round(spo2_score, 1) if spo2_score is not None else None,
            "hrv_score": round(hrv_score, 1) if hrv_score is not None else None,
        }
    }
