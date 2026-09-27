# -*- coding: utf-8 -*-
"""
Telegram Daily Summary Notifier
ไฟล์: telegram_notify.py

อ่านข้อมูลของ "วันนี้" จาก coros_cache.db (ผ่าน coros_db.py) แล้วสรุปเป็นข้อความ
ส่งเข้า Telegram ผ่าน Bot API

ต้องรันหลัง coros_daily_sync.py และ export.py เสมอ (ต้องมีข้อมูลใน DB ก่อน)

Environment variables ที่ต้องมี:
    TELEGRAM_BOT_TOKEN  - token ของ bot (ขอจาก @BotFather)
    TELEGRAM_CHAT_ID    - chat id ปลายทางที่จะส่งข้อความไปหา

การเปลี่ยนแปลงรอบนี้ (ส่วนอื่นคงเดิมทั้งหมด):
  1. today_str()/yesterday_str() ใช้เวลา ICT (UTC+7) แทนนาฬิกา UTC ของ runner
  2. sport_type แสดงเป็นชื่อกีฬา (รู้จักเฉพาะรหัสที่ยืนยันแล้ว — รหัสอื่นแสดงเป็น "กีฬา (รหัส N)")
  3. ACWR: ถ้าประวัติข้อมูลยังไม่ถึง 28 วัน แสดง "ยังไม่ประเมิน (ข้อมูล X/28 วัน)"
     แทนตัวเลขพร้อมป้ายความเสี่ยง (ประวัติสั้น ค่า ACWR ยังไม่น่าเชื่อถือ)
  4. บรรทัด "HR เฉลี่ย/สูงสุด" ซ่อนเมื่อไม่มีข้อมูลทั้งคู่ (sync ไม่เคยเก็บค่านี้ใน daily_health)
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

import coros_db

# ผู้ใช้อยู่ประเทศไทย (ICT = UTC+7) แต่ GitHub Actions runner ใช้นาฬิกา UTC
ICT = timezone(timedelta(hours=7))

# ประวัติข้อมูลขั้นต่ำ (วัน) ที่ ACWR ถึงจะเชื่อถือได้ — ตรงกับ chronic window ของ strain_engine
ACWR_MIN_HISTORY_DAYS = 28

# รหัสกีฬาของ COROS -> ชื่อที่แสดง
# ใส่เฉพาะรหัสที่ยืนยันแล้วเท่านั้น (100 = running ตามเอกสาร COROS API ที่ไม่เป็นทางการ)
# รหัสอื่นจะแสดงเป็น "กีฬา (รหัส N)" ไม่เดา เพื่อไม่ให้แสดงชื่อผิด — เติมได้เมื่อยืนยันรหัสแล้ว
SPORT_NAMES = {
    "100": "วิ่ง",
    "200": "ปั่นจักรยาน",
    "402": "เวทเทรนนิ่ง",
    "900": "เดิน",
    "904": "โยคะ/สมาธิ",
}


# =============================================================================
# Helpers
# =============================================================================

def today_str():
    """คืนค่าวันที่วันนี้ (เวลาไทย) ในรูปแบบ YYYY-MM-DD"""
    return datetime.now(ICT).strftime("%Y-%m-%d")


def yesterday_str():
    return (datetime.now(ICT) - timedelta(days=1)).strftime("%Y-%m-%d")


def normalize_date(raw):
    """
    coros_daily_sync.py เก็บวันที่ลง DB แบบปนกันสองรูปแบบ:
      - "20260924"        (จาก sync_sleep_and_health, ไม่มีขีด)
      - "2026-09-24"       (จาก sync_activities บาง record, มีขีด)
      - "2026-09-24T10:45:01"  (isoformat เต็ม เมื่อเจอ startTimestamp)
    ฟังก์ชันนี้แปลงทุกแบบให้เป็น "YYYY-MM-DD" เดียวกัน เพื่อเทียบวันที่ได้ถูกต้อง
    คืนค่า None ถ้า parse ไม่ได้
    """
    if not raw:
        return None
    raw = str(raw).strip()

    # "2026-09-24T10:45:01..." หรือ "2026-09-24 10:45:01..." -> ตัดเอาแค่ 10 ตัวแรก
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]

    # "20260924" (8 หลักไม่มีขีด)
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"

    # เผื่อรูปแบบอื่นที่มี "20260924" นำหน้าตามด้วยเวลา เช่น "20260924T104501"
    digits_prefix = raw[:8]
    if len(digits_prefix) == 8 and digits_prefix.isdigit():
        return f"{digits_prefix[0:4]}-{digits_prefix[4:6]}-{digits_prefix[6:8]}"

    return None


def fmt(value, unit="", digits=1, fallback="—"):
    """format ตัวเลขให้อ่านง่าย คืนค่า fallback ถ้าเป็น None"""
    if value is None:
        return fallback
    try:
        if digits == 0:
            return f"{int(round(float(value)))}{unit}"
        return f"{round(float(value), digits)}{unit}"
    except (TypeError, ValueError):
        return fallback


def format_pace(seconds_per_km):
    """แปลงวินาที/กม. เป็น นาที:วินาที/km"""
    if not seconds_per_km:
        return None
    try:
        s = int(seconds_per_km)
        m = s // 60
        sec = s % 60
        return f"{m}:{sec:02d}"
    except (ValueError, TypeError):
        return None

def seconds_to_hm(seconds):
    """แปลงวินาที -> '1h 23m'"""
    if seconds is None:
        return "—"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "—"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def minutes_to_hm(minutes):
    if minutes is None:
        return "—"
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return "—"
    h, m = divmod(minutes, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def sport_label(code):
    """แปลงรหัสกีฬา COROS เป็นชื่อ — รหัสที่ไม่รู้จักแสดงเป็นรหัสตรงๆ ไม่เดาชื่อ"""
    if code is None or str(code).strip() == "":
        return "activity"
    key = str(code).strip()
    return SPORT_NAMES.get(key, f"กีฬา (รหัส {key})")


def acwr_flag(acwr):
    """ให้คำเตือนตามช่วงความเสี่ยงของ ACWR (Acute:Chronic Workload Ratio)"""
    if acwr is None:
        return ""
    try:
        acwr = float(acwr)
    except (TypeError, ValueError):
        return ""
    if acwr > 1.5:
        return " 🔴 เสี่ยงบาดเจ็บสูง (โหลดเพิ่มเร็วเกินไป)"
    if acwr >= 1.3:
        return " ⚠️ โซนเสี่ยง ระวังโหลดเพิ่มเร็ว"
    if acwr < 0.8:
        return " 🔵 โหลดต่ำกว่าปกติ (detraining)"
    return " ✅ อยู่ในช่วงปลอดภัย"


def acwr_line(acwr, history_days=None):
    """
    บรรทัด ACWR ในข้อความ — ถ้าประวัติข้อมูลสั้นกว่า ACWR_MIN_HISTORY_DAYS จะไม่แสดง
    ตัวเลขและป้ายความเสี่ยง เพราะ chronic window (28 วัน) ยังไม่ครบ ค่าที่ได้ไม่น่าเชื่อถือ
    """
    if acwr is None:
        return f"  ACWR: {fmt(acwr, '', 2)}"
    if history_days is not None and history_days < ACWR_MIN_HISTORY_DAYS:
        return f"  ACWR: ยังไม่ประเมิน (ข้อมูล {history_days}/{ACWR_MIN_HISTORY_DAYS} วัน)"
    return f"  ACWR: {fmt(acwr, '', 2)}{acwr_flag(acwr)}"


def _find_history_days(strain):
    """
    หา history_days ที่ strain_engine บันทึกไว้ใน summary_json (ถ้ามี) — ค้นแบบ recursive
    เพราะไม่ทราบว่า run_strain.py เก็บฟิลด์นี้ไว้ระดับไหน คืน None ถ้าไม่พบ
    """
    try:
        obj = json.loads(strain.get("summary_json") or "{}")
    except (TypeError, ValueError):
        return None
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            v = cur.get("history_days")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def _history_days_from_activities(activities, today):
    """สำรอง: นับจากวันแรกที่มีกิจกรรมใน DB จนถึงวันนี้ (รวมทั้งสองวัน)"""
    dates = [normalize_date(a.get("start_time")) for a in activities]
    dates = [d for d in dates if d]
    if not dates:
        return None
    try:
        first = datetime.strptime(min(dates), "%Y-%m-%d")
        last = datetime.strptime(today, "%Y-%m-%d")
    except ValueError:
        return None
    return max(0, (last - first).days + 1)


# =============================================================================
# Data gathering
# =============================================================================

def gather_today_summary():
    """
    ดึงข้อมูลของวันนี้จากทุกตารางที่เกี่ยวข้อง

    หมายเหตุสำคัญ: coros_daily_sync.py เก็บ date/start_time ลง DB แบบปนกันสอง
    รูปแบบ (มีขีด/ไม่มีขีด) ขึ้นอยู่กับว่า record นั้นมี startTimestamp หรือไม่
    ดังนั้นห้ามเทียบ string ตรงๆ หรือใช้ SQL BETWEEN กับ date ที่มีขีดเพียงอย่างเดียว
    (coros_db.get_activities_between จะพลาด record ที่เก็บแบบไม่มีขีด) —
    ต้องดึงมาแบบกว้างๆ ก่อน แล้วค่อยกรองด้วย normalize_date() ในฝั่ง Python แทน
    """
    date = today_str()

    # --- กิจกรรม: ดึงมากว้างๆ (90 วันคือช่วงที่ sync ไว้) แล้วกรองด้วยวันที่ normalize แล้ว ---
    all_recent_activities = coros_db.get_activities_between("00000000", "99999999")
    activities = [
        a for a in all_recent_activities
        if normalize_date(a.get("start_time")) == date
    ]

    # --- sleep: ดึง 10 แถวล่าสุด กรองด้วย normalize_date ---
    # การนอนของ "เมื่อคืน" (คืนที่ผ่านมา) ควรถูกบันทึกด้วยวันที่ตื่น (วันนี้)
    # แต่ COROS บางครั้งอาจบันทึกด้วยวันที่เข้านอน (เมื่อวาน) ลองทั้งสองแบบ
    sleep_rows = coros_db.get_recent_sleep(days=10)
    sleep_today = next((r for r in sleep_rows if normalize_date(r.get("date")) == date), None)
    if not sleep_today:
        # ลองหาด้วยวันที่เมื่อวาน (กรณีบันทึกด้วยวันที่เข้านอน)
        sleep_today = next(
            (r for r in sleep_rows if normalize_date(r.get("date")) == yesterday_str()), None
        )

    # --- สุขภาพรายวัน ---
    health_rows = coros_db.get_recent_daily_health(days=10)
    health_today = next((r for r in health_rows if normalize_date(r.get("date")) == date), None)

    # --- strain / ACWR: get_strain_by_date ใช้ exact match ต้องลองทั้งสองรูปแบบ ---
    strain_today = coros_db.get_strain_by_date(date) or coros_db.get_strain_by_date(date.replace("-", ""))

    # --- ความยาวประวัติข้อมูล (ใช้ตัดสินว่า ACWR เชื่อถือได้หรือยัง) ---
    # ใช้ค่าที่ strain_engine บันทึกไว้ก่อน ถ้าไม่มีให้นับจากวันแรกที่มีกิจกรรม
    history_days = _find_history_days(strain_today) if strain_today else None
    if history_days is None:
        history_days = _history_days_from_activities(all_recent_activities, date)

    # --- journal (manual log): เก็บด้วยมือ ปกติจะเป็น format เดียวกันเสมอ แต่กันไว้ก่อน ---
    journal_today = coros_db.get_journal_by_date(date) or coros_db.get_journal_by_date(date.replace("-", ""))
    
    # --- ดึงข้อมูลวิเคราะห์ SQI, Recovery, Illness Risk จาก export.py/app.py ---
    import sleep_analysis
    
    sqi = None
    recovery_score = None
    illness_risk = None
    baselines = {}
    
    if sleep_today:
        # คำนวณ SQI
        sleep_for_sqi = [sleep_today]
        sqi = sleep_analysis.calculate_sqi(sleep_for_sqi)
        
        # คำนวณ Recovery Score
        recent_sleep = sleep_rows[:7]  # 7 วันล่าสุด
        baselines = {}
        for metric in ["hrv_ms", "resting_hr"]:
            baselines[metric] = sleep_analysis.compute_baseline(
                recent_sleep, [metric], window=7
            )
        
        recovery_score = sleep_analysis.recovery_score(
            hrv_today=sleep_today.get("hrv"),
            hrv_baseline=baselines.get("hrv_ms"),
            rhr_today=sleep_today.get("resting_hr"),
            rhr_baseline=baselines.get("resting_hr"),
            sleep_performance_pct=min((sleep_today.get("duration_min") or 0) / 480 * 100, 100),
            sleep_efficiency_pct=((sleep_today.get("duration_min") or 0) / 
                                  ((sleep_today.get("duration_min") or 0) + (sleep_today.get("awake_min") or 0)) * 100
                                  if (sleep_today.get("duration_min") or 0) + (sleep_today.get("awake_min") or 0) > 0 else 0)
        )
        
        # คำนวณ Illness Risk
        illness_risk = sleep_analysis.compute_illness_risk(sleep_today, baselines)

    # --- ดึงค่า Fitness (CTL/ATL/TSB) ล่าสุดจาก data.json ---
    ctl_now = atl_now = tsb_now = None
    try:
        with open(os.path.join(os.path.dirname(__file__), "docs", "data.json"),
                  "r", encoding="utf-8") as f:
            fitness = json.load(f).get("training_analytics", {}).get("fitness", {})
            ctl_now, atl_now, tsb_now = fitness.get("ctl"), fitness.get("atl"), fitness.get("tsb")
    except Exception:
        pass

    # --- บันทึกค่าวันนี้ลง time-series cache (prerequisite ของกฎ B1/B3/C3/E1/E2) ---
    # ทำทุกครั้งที่รัน notify — ค่าเดิมที่ยังไม่มีวันนี้จะถูกเติม ส่วนค่าที่คำนวณไม่ได้จะไม่ทับของเดิม
    if date:
        dur = sleep_today.get("duration_min") if sleep_today else None
        eff = sleep_analysis.sleep_efficiency(sleep_today) if sleep_today else None
        
        coros_db.upsert_daily_metrics_cache({
            "date": date,
            "ctl": ctl_now,
            "atl": atl_now,
            "tsb": tsb_now,
            "recovery_score": recovery_score.get("recovery_score") if recovery_score else None,
            "sleep_efficiency": eff,
            "sleep_duration_min": dur,
            "hrv": sleep_today.get("hrv") if sleep_today else None,
            "rhr": sleep_today.get("resting_hr") if sleep_today else None,
            "stress": health_today.get("stress_score") if health_today else None,
            "steps": health_today.get("steps") if health_today else None,
            "calories": health_today.get("calories_burned") if health_today else None,
        })

    # --- ประวัติย้อนหลัง 30 วัน (เรียงเก่า -> ใหม่) สำหรับกฎที่ต้องดูแนวโน้ม ---
    history = list(reversed(coros_db.get_daily_metrics_cache(days=30)))

    return {
        "date": date,
        "activities": activities,
        "sleep": sleep_today,
        "health": health_today,
        "strain": strain_today,
        "journal": journal_today,
        "history_days": history_days,
        "sqi": sqi,
        "recovery_score": recovery_score,
        "illness_risk": illness_risk,
        "baselines": baselines,
        "fitness": {"ctl": ctl_now, "atl": atl_now, "tsb": tsb_now},
        "history": history,
    }


# =============================================================================
# Message building
# =============================================================================

def load_user_config():
    config_path = os.path.join(os.path.dirname(__file__), "user_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def build_message(data):
    date = data["date"]
    activities = data["activities"]
    sleep = data["sleep"]
    health = data["health"]
    strain = data["strain"]
    journal = data["journal"]

    lines = [f"🏃 <b>COROS Daily Summary</b> — {date}"]

    # --- กิจกรรม ---
    if activities:
        lines.append("")
        lines.append("📍 <b>กิจกรรม</b>")
        for act in activities:
            sport = sport_label(act.get("sport_type"))
            distance_km = (act.get("distance_m") or 0) / 1000
            
            # เวลาที่ทำกิจกรรม (start_time)
            start_time_str = act.get("start_time", "")
            time_label = ""
            if start_time_str:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                    time_label = f" (เวลา {dt.strftime('%H:%M')})"
                except:
                    pass
            
            # ข้อมูลพื้นฐานกิจกรรม
            dur = seconds_to_hm(act.get('duration_s'))
            hr_avg = fmt(act.get('avg_hr'), '', 0)
            hr_max = fmt(act.get('max_hr'), '', 0)
            cals = fmt(act.get('calories'), ' kcal', 0)
            
            # แสดงระยะทางเฉพาะกีฬาที่มีการเคลื่อนที่ (วิ่ง/ปั่น/เดิน)
            dist_label = ""
            if act.get("sport_type") in ("100", "200", "900") and distance_km > 0:
                dist_label = f"{fmt(distance_km, ' km', 2)} | "
            
            # ข้อมูลเชิงลึกของการวิ่ง/เดิน
            extra_stats = []
            if act.get("sport_type") in ("100", "900"):
                pace = format_pace(act.get('avg_pace_s'))
                if pace: extra_stats.append(f"Pace {pace} /km")
                if act.get('avg_cadence'): extra_stats.append(f"รอบขา {fmt(act.get('avg_cadence'), ' spm', 0)}")
                if act.get('ascent_m') and act.get('ascent_m') > 0: 
                    extra_stats.append(f"ไต่เขา {fmt(act.get('ascent_m'), ' m', 0)}")
            
            score = act.get('score')
            perf_label = f" (Perf. {int(score)}%)" if score else ""
            
            hr_range = f"HR {hr_avg}" if hr_max == "—" else f"HR {hr_avg}-{hr_max}"
            
            lines.append(f"  • {sport}{perf_label}{time_label}: {dist_label}{dur} | {hr_range} | {cals}")
            if extra_stats:
                lines.append(f"    └ " + " | ".join(extra_stats))
    else:
        lines.append("")
        lines.append("📍 <b>กิจกรรม</b>: ไม่มีบันทึกวันนี้")
        
    # --- สรุปภาพรวมรายวัน & ความฟิต ---
    import json
    try:
        with open(os.path.join(os.path.dirname(__file__), "docs", "data.json"), "r", encoding="utf-8") as f:
            full_data = json.load(f)
            
            narrative = full_data.get("narrative", {}).get("summary")
            if narrative:
                lines.insert(1, "")
                lines.insert(2, f"🤖 <b>สรุป:</b> {narrative}")
                
            fitness = full_data.get("training_analytics", {}).get("fitness")
            if fitness and activities: # แสดงความฟิตถ้ามีกิจกรรม
                ctl = fitness.get("ctl")
                atl = fitness.get("atl")
                tsb = fitness.get("tsb")
                if ctl is not None and atl is not None:
                    lines.append("")
                    lines.append("📈 <b>สถานะความฟิต</b>")
                    lines.append(f"  • ความฟิต (CTL): {fmt(ctl, '', 1)} | ล้า (ATL): {fmt(atl, '', 1)}")
                    tsb_sign = "+" if tsb and tsb > 0 else ""
                    form_label = ""
                    if tsb is not None:
                        if tsb > 10: form_label = " (พร้อมซ้อมหนัก/แข่ง)"
                        elif tsb > 5: form_label = " (สดใส)"
                        elif tsb > -5: form_label = " (สมดุล)"
                        elif tsb > -15: form_label = " (ล้าเล็กน้อย)"
                        else: form_label = " (ล้ามาก ควรพัก)"
                    lines.append(f"  • ความสด (Form): {tsb_sign}{fmt(tsb, '', 1)}{form_label}")
            
            economy = full_data.get("training_analytics", {}).get("economy")
            if economy and economy.get("recent_economy"):
                trend = economy.get("trend", "")
                change = economy.get("economy_change_pct", 0)
                change_sign = "+" if change > 0 else ""
                icon = "🟢" if trend == "improving" else "🔴" if trend == "declining" else "🟡"
                lines.append(f"  • Running Economy: {fmt(economy['recent_economy'], '', 1)} {icon} ({change_sign}{fmt(change, '%', 1)})")

    except Exception as e:
        pass

    # --- สุขภาพรายวัน ---
    if health:
        lines.append("")
        lines.append("📊 <b>สุขภาพวันนี้</b>")
        lines.append(f"  👣 ก้าว: {fmt(health.get('steps'), '', 0)}")
        lines.append(f"  🔥 แคลอรี่รวม: {fmt(health.get('calories_burned'), ' kcal', 0)}")
        
        stress = health.get('stress_score')
        stress_label = ""
        if stress:
            s_val = int(stress)
            if s_val < 35: stress_label = " (ต่ำ/ผ่อนคลาย)"
            elif s_val < 55: stress_label = " (ปานกลาง)"
            else: stress_label = " (สูง)"
        lines.append(f"  😰 Stress: {fmt(stress, '/100', 0)}{stress_label}")
        # ซ่อนบรรทัดนี้เมื่อไม่มีข้อมูลทั้งคู่ (sync ยังไม่เคยเก็บ avg/max HR รายวัน)
        if health.get("avg_hr") is not None or health.get("max_hr") is not None:
            lines.append(
                f"  ❤️ HR เฉลี่ย/สูงสุด: {fmt(health.get('avg_hr'), '', 0)} / "
                f"{fmt(health.get('max_hr'), '', 0)}"
            )
        if health.get("spo2_avg") is not None:
            lines.append(
                f"  🫁 SpO2 เฉลี่ย/ต่ำสุด: {fmt(health.get('spo2_avg'), '%', 0)} / "
                f"{fmt(health.get('spo2_min'), '%', 0)}"
            )
        if health.get("respiratory_rate") is not None:
            lines.append(f"  🌬 อัตราการหายใจ: {fmt(health.get('respiratory_rate'), ' /min', 1)}")
        if health.get("skin_temp_deviation_c") is not None:
            lines.append(f"  🌡 อุณหภูมิผิวเบี่ยงเบน: {fmt(health.get('skin_temp_deviation_c'), '°C', 1)}")

    # --- การนอน ---
    if sleep:
        lines.append("")
        sleep_date_str = sleep.get('date', '')
        
        # แสดงเวลาเข้านอน-ตื่น ถ้ามีข้อมูล
        sleep_time_label = ""
        if normalize_date(sleep_date_str) == yesterday_str():
            lines.append("😴 <b>การนอน (เมื่อคืน)</b>")
        else:
            lines.append("😴 <b>การนอน</b>")
        
        duration_min = sleep.get('duration_min') or 0
        lines.append(f"  ระยะเวลารวม: {minutes_to_hm(duration_min)}")
        
        # ดึงเวลาเข้านอน - ตื่นนอน จาก summary_json (ถ้ามี)
        summary_json = sleep.get('summary_json')
        if summary_json:
            try:
                import json
                s_data = json.loads(summary_json)
                start_str = s_data.get("startTime")  # COROS มักจะเก็บ startTime / endTime ใน summary_json
                end_str = s_data.get("endTime")
                if start_str and end_str:
                    lines.append(f"  ⏰ เวลานอน: {start_str} - {end_str}")
            except:
                pass
        
        # แสดง Deep/Light/REM เป็นทั้ง % และเวลา (นาที)
        deep_pct = sleep.get('deep_sleep_pct')
        light_pct = sleep.get('light_sleep_pct')
        rem_pct = sleep.get('rem_sleep_pct')
        
        if deep_pct is not None and duration_min > 0:
            deep_min = int(duration_min * deep_pct / 100)
            lines.append(f"  🟦 Deep: {fmt(deep_pct, '%', 0)} ({minutes_to_hm(deep_min)})")
        
        if light_pct is not None and duration_min > 0:
            light_min = int(duration_min * light_pct / 100)
            lines.append(f"  🟨 Light: {fmt(light_pct, '%', 0)} ({minutes_to_hm(light_min)})")
        
        if rem_pct is not None and duration_min > 0:
            rem_min = int(duration_min * rem_pct / 100)
            lines.append(f"  🟪 REM: {fmt(rem_pct, '%', 0)} ({minutes_to_hm(rem_min)})")
        
        awake_min = sleep.get('awake_min')
        if awake_min:
            lines.append(f"  ⚪ Awake: {minutes_to_hm(awake_min)}")
        
        baselines = data.get("baselines", {})
        hrv_today = sleep.get('hrv')
        hrv_baseline_raw = baselines.get("hrv_ms")
        hrv_baseline = hrv_baseline_raw.get("baseline") if isinstance(hrv_baseline_raw, dict) else hrv_baseline_raw
        
        rhr_today = sleep.get('resting_hr')
        rhr_baseline_raw = baselines.get("resting_hr")
        rhr_baseline = rhr_baseline_raw.get("baseline") if isinstance(rhr_baseline_raw, dict) else rhr_baseline_raw

        hrv_str = fmt(hrv_today, '', 0)
        if hrv_today and hrv_baseline:
            diff = hrv_today - hrv_baseline
            sign = "+" if diff > 0 else ""
            hrv_str += f" ({sign}{diff:.0f} จากค่าเฉลี่ย {hrv_baseline:.0f})"

        rhr_str = fmt(rhr_today, '', 0)
        if rhr_today and rhr_baseline:
            diff = rhr_today - rhr_baseline
            sign = "+" if diff > 0 else ""
            rhr_str += f" ({sign}{diff:.0f} จากค่าเฉลี่ย {rhr_baseline:.0f})"

        lines.append(f"  💓 HRV: {hrv_str} | Resting HR: {rhr_str}")
        
        sqi_data = data.get("sqi") or {}
        sqi_val = sqi_data.get("sqi")
        if sqi_val:
            band = sqi_data.get("band", "")
            icon = "🟢" if band == "good" else "🟡" if band == "fair" else "🔴" if band == "poor" else ""
            lines.append(f"  📊 Sleep Quality (SQI): {fmt(sqi_val, '', 1)}/100 {icon}")

    # --- สุขภาพ & การฟื้นฟู ---
    recovery = data.get("recovery_score")
    illness = data.get("illness_risk")
    if recovery or illness:
        lines.append("")
        lines.append("🩺 <b>การฟื้นฟู & สุขภาพ</b>")
        if recovery:
            rec_score = recovery.get("recovery_score")
            rec_band = recovery.get("band", "")
            rec_label = "ดีมาก" if rec_band == "green" else "ปานกลาง" if rec_band == "yellow" else "ต่ำ"
            lines.append(f"  🔋 Recovery Score: {fmt(rec_score, '', 1)}/100 ({rec_label})")
        if illness:
            risk = illness.get("risk_level", "none")
            risk_label = "ไม่มี" if risk == "none" else "ต่ำ" if risk == "low" else "ปานกลาง" if risk == "medium" else "สูง"
            lines.append(f"  ⚠️ ความเสี่ยงป่วย: {risk_label}")

    # --- Strain / ACWR ---
    if strain:
        lines.append("")
        lines.append("⚡ <b>Strain</b>")
        lines.append(f"  Day strain: {fmt(strain.get('day_strain'), '', 1)}")
        lines.append(f"  TRIMP: {fmt(strain.get('trimp'), '', 1)}")
        lines.append(acwr_line(strain.get("acwr"), data.get("history_days")))

    # --- บทวิเคราะห์เชิงลึก (Insight Analysis) ---
    insights = []
    
    # ดึงค่าที่จำเป็นสำหรับกลุ่มต่างๆ
    rec_score = recovery.get("recovery_score") if recovery else 0
    duration_min = sleep.get("duration_min") if sleep else 0
    awake_min = sleep.get("awake_min") if sleep else 0
    
    import sleep_analysis
    efficiency = sleep_analysis.sleep_efficiency(sleep) if sleep else 0
    
    deep_pct = sleep.get("deep_sleep_pct") if sleep else 0
    rem_pct = sleep.get("rem_sleep_pct") if sleep else 0
    
    hrv_today = sleep.get("hrv") if sleep else None
    baselines_dict = data.get("baselines", {})
    hrv_baseline_raw = baselines_dict.get("hrv_ms")
    hrv_baseline = hrv_baseline_raw.get("baseline") if isinstance(hrv_baseline_raw, dict) else hrv_baseline_raw
    rhr_today = sleep.get("resting_hr") if sleep else None
    rhr_baseline_raw = baselines_dict.get("resting_hr")
    rhr_baseline = rhr_baseline_raw.get("baseline") if isinstance(rhr_baseline_raw, dict) else rhr_baseline_raw
    
    stress_today = float(health.get("stress_score") or 0) if health else 0
    
    # โหลด user_config (ถ้ามี)
    user_config = load_user_config()
    
    # ดึง form, ctl (จาก data.json) สำหรับกลุ่ม B
    form_val = None
    ctl_now = None
    try:
        with open(os.path.join(os.path.dirname(__file__), "docs", "data.json"), "r", encoding="utf-8") as f:
            full_data = json.load(f)
            fitness = full_data.get("training_analytics", {}).get("fitness", {})
            form_val = fitness.get("tsb")
            ctl_now = fitness.get("ctl")
    except Exception:
        pass
        
    steps = float(health.get("steps") or 0) if health else 0

    # ประเมินตามกลุ่ม C: HRV × Stress × RHR (Illness/Overtraining Early Warning)
    c_triggered = False
    if hrv_today and hrv_baseline and rhr_today and rhr_baseline:
        hrv_std_dev = hrv_baseline_raw.get("std_dev", 5) if isinstance(hrv_baseline_raw, dict) and hrv_baseline_raw.get("std_dev") else 5
        # C1 — HRV ต่ำ + RHR สูง + Stress สูง
        if hrv_today < (hrv_baseline - hrv_std_dev) and rhr_today > (rhr_baseline + 5) and stress_today > 60:
            diff = rhr_today - rhr_baseline
            insights.append({"id": "C1", "level": "🔴", "priority": 1, "text": f"พบสัญญาณร่วมกันสามอย่าง: HRV ต่ำกว่าปกติ, Resting HR สูงกว่าค่าเฉลี่ย {diff:.0f} bpm, และ Stress สูง ({stress_today:.0f}/100) ชุดสัญญาณนี้มักปรากฏก่อนอาการเจ็บป่วยหรือ overtraining 1-2 วัน แนะนำให้ลด intensity และสังเกตอาการร่างกายใกล้ชิด"})
            c_triggered = True
        # C2 — RHR สูงกว่า baseline อย่างเดียว
        elif rhr_today > (rhr_baseline + 5) and hrv_today >= (hrv_baseline - hrv_std_dev) and stress_today <= 60:
            insights.append({"id": "C2", "level": "🟢/🟡", "priority": 4, "text": f"Resting HR วันนี้สูงกว่าค่าเฉลี่ยเล็กน้อย ({rhr_today:.0f} vs baseline {rhr_baseline:.0f}) แต่ตัวชี้วัดอื่นยังปกติ อาจเป็นผลจากมื้ออาหาร แอลกอฮอล์ หรือความร้อนของอากาศ ยังไม่ถือเป็นสัญญาณเตือน"})

    # ประเมินกลุ่ม B: Training Load × Activity
    # B2 — Form ติดลบมาก + Recovery ต่ำ
    if form_val is not None and form_val < -20 and rec_score > 0 and rec_score < 60:
        insights.append({"id": "B2", "level": "🔴", "priority": 2, "text": f"Form ติดลบสูง ({form_val:.1f}) ร่วมกับ Recovery ต่ำ ({rec_score:.0f}) แสดงว่าร่างกายสะสมความล้าเกินกว่าที่ฟื้นตัวทัน ควรพิจารณาลด intensity หรือเพิ่มวันพักในสัปดาห์นี้ เพื่อป้องกัน overtraining"})
    
    # B4 — ข้อมูลกิจกรรมผิดปกติ (เช็คกิจกรรมทั้งหมดของวันนี้)
    if activities:
        for act in activities:
            a_dur = float(act.get("duration_s") or 0) / 60.0
            a_cals = float(act.get("calories") or 0)
            if a_dur == 0 and a_cals > 50:
                s_name = sport_label(act.get("sport_type"))
                insights.append({"id": "B4", "level": "🟡", "priority": 3, "text": f"กิจกรรม {s_name} วันนี้บันทึกระยะเวลา 0 นาทีแต่มีแคลอรี่ {a_cals:.0f} kcal ข้อมูลอาจไม่สมบูรณ์จากการซิงค์ ควรตรวจสอบก่อนใช้คำนวณ training load สะสม"})

    # ประเมินกลุ่ม A: Recovery × Sleep
    if sleep and recovery and not c_triggered:
        # A1 — Recovery สูง + Sleep efficiency ต่ำ
        if rec_score >= 70 and efficiency > 0 and efficiency < 85:
            insights.append({"id": "A1", "level": "🟡", "priority": 3, "text": f"แม้ Recovery จะอยู่ในเกณฑ์ดี ({rec_score:.0f}/100) แต่ Sleep Efficiency ต่ำกว่ามาตรฐาน ({efficiency:.0f}%) แปลว่าเวลาที่อยู่บนเตียงมีส่วนที่ไม่ได้หลับสนิทค่อนข้างมาก ({awake_min} นาที) ควรสังเกตว่าเข้านอนเร็วเกินไปหรือมีการตื่นกลางดึกหรือไม่"})
            
        # A2 — Deep sleep สูง + REM ต่ำ
        if deep_pct > 22 and rem_pct < 18:
            insights.append({"id": "A2", "level": "🟡", "priority": 3, "text": f"ร่างกายฟื้นฟูทางกายภาพได้ดี (Deep {deep_pct:.0f}%) แต่ REM ({rem_pct:.0f}%) อยู่ในระดับล่างของเกณฑ์ปกติ ซึ่งเกี่ยวข้องกับการฟื้นฟูทางสมองและความจำ หากเกิดต่อเนื่องหลายวันอาจสัมพันธ์กับความเครียดสะสมหรือแอลกอฮอล์ก่อนนอน"})
            
        # A3 — HRV ต่ำกว่า baseline + Sleep ปกติ
        if hrv_today and hrv_baseline and efficiency >= 85:
            hrv_std_dev = hrv_baseline_raw.get("std_dev", 5) if isinstance(hrv_baseline_raw, dict) and hrv_baseline_raw.get("std_dev") else 5
            if hrv_today < (hrv_baseline - hrv_std_dev):
                insights.append({"id": "A3", "level": "🟡", "priority": 3, "text": f"แม้จะนอนได้ดีคืนนี้ แต่ HRV ({hrv_today:.0f}ms) ต่ำกว่าค่าเฉลี่ย 7 วันของคุณ ({hrv_baseline:.0f}ms) การนอนดีไม่ได้แปลว่าระบบประสาทฟื้นตัวเต็มที่เสมอไป ควรสังเกตความเครียดจากปัจจัยอื่น เช่น งาน อาหาร หรือ training load สะสม"})

    history = data.get("history", [])
    if history:
        # กฎที่ต้องใช้ time-series (B1, B3, C3, E1, E2)
        if len(history) >= 2:
            # C3 — Stress สูง + Recovery เมื่อวานดี
            yesterday_data = history[-2] if history[-1].get("date") == date else history[-1]
            yesterday_rec = yesterday_data.get("recovery_score") or 0
            if stress_today > 60 and yesterday_rec >= 70:
                insights.append({"id": "C3", "level": "🟡", "priority": 3, "text": f"Recovery เมื่อวานอยู่ในเกณฑ์ดี ({yesterday_rec:.0f}/100) แต่ความเครียดวันนี้ค่อนข้างสูง ({stress_today:.0f}/100) ระวังกระทบการนอนคืนนี้"})

        if len(history) >= 8:
            # B3 — เทียบ CTL วันนี้กับ 7 วันก่อน
            ctl_7d_ago = history[-8].get("ctl")
            if ctl_now and ctl_7d_ago and ctl_now < ctl_7d_ago - 3:
                insights.append({"id": "B3", "level": "🟡", "priority": 3, "text": f"ความฟิต (CTL) ลดลงจาก {ctl_7d_ago:.1f} เป็น {ctl_now:.1f} ในรอบสัปดาห์ หากไม่ได้อยู่ในช่วง Taper หรือพักฟื้น ควรพิจารณาเพิ่ม Training Load"})

        if len(history) >= 5:
            # B1 — Form สูงต่อเนื่อง + steps ต่ำ
            form_high_days = sum(1 for d in history[-5:] if (d.get("tsb") or 0) > 10)
            
            # ตรวจสอบว่าเป็นช่วง Taper ของ race_prep หรือไม่
            is_taper = False
            if user_config and user_config.get("user_goal") == "race_prep":
                race_date_str = user_config.get("race_date")
                if race_date_str:
                    try:
                        from datetime import datetime
                        race_dt = datetime.strptime(race_date_str, "%Y-%m-%d")
                        days_to_race = (race_dt - datetime.now()).days
                        if 0 < days_to_race <= 14:
                            is_taper = True
                    except Exception:
                        pass

            if form_high_days >= 5 and steps < 5000 and not is_taper:
                insights.append({"id": "B1", "level": "🟡", "priority": 3, "text": f"Form เป็นบวกต่อเนื่องเกิน 5 วัน (ร่างกายสดชื่นมาก) แต่ก้าวเดินวันนี้น้อย ({steps:.0f} ก้าว) ระวังเข้าสู่ภาวะ Detraining (ความฟิตลด) หากไม่ได้ตั้งใจพัก"})

            # E2 — Sleep eff < 85% ต่อเนื่อง 5 วัน
            bad_sleep_days = sum(1 for d in history[-5:] if d.get("sleep_efficiency") and d.get("sleep_efficiency") < 85)
            if bad_sleep_days >= 5:
                insights.append({"id": "E2", "level": "🔴", "priority": 2, "text": f"Sleep Efficiency ต่ำกว่า 85% ติดต่อกัน 5 วัน คุณภาพการนอนแย่ลงสะสม แนะนำปรับสภาพแวดล้อมห้องนอนหรือลดสิ่งกระตุ้นก่อนนอน"})
                
        if len(history) >= 3:
            # E1 — Recovery ลดลงต่อเนื่อง 3 วัน
            rec_trends = [d.get("recovery_score") or 0 for d in history[-3:]]
            if rec_trends[0] > rec_trends[1] > rec_trends[2]:
                if len(history) >= 5 and sum(1 for i in range(len(history)-5, len(history)-1) if history[i].get("recovery_score") > history[i+1].get("recovery_score")) >= 4:
                    insights.append({"id": "E1_5", "level": "🔴", "priority": 1, "text": f"Recovery Score ลดลงติดต่อกัน 5 วัน (ล่าสุด {rec_trends[2]:.0f}/100) ร่างกายดิ่งสะสมมาก ควรพักการซ้อมหนักทันที"})
                else:
                    insights.append({"id": "E1_3", "level": "🟡", "priority": 3, "text": f"Recovery Score ลดลงติดต่อกัน 3 วัน (ล่าสุด {rec_trends[2]:.0f}/100) ระวังร่างกายดิ่งสะสม ควรพิจารณาพักการซ้อมหนัก"})

    # กลุ่ม D: Goal-aware (ใช้ user_config)
    if user_config:
        goal = user_config.get("user_goal")
        if goal == "improve_fitness":
            if ctl_now and ctl_now > 50:
                insights.append({"id": "D1", "level": "🟢", "priority": 4, "text": f"ฟิตเนส (CTL) ของคุณเกิน 50 แล้ว ถือว่าอยู่ในเกณฑ์ที่ดีมากสำหรับการพัฒนาต่อเนื่อง"})
        elif goal == "race_prep":
            race_date_str = user_config.get("race_date")
            if race_date_str:
                try:
                    from datetime import datetime
                    race_dt = datetime.strptime(race_date_str, "%Y-%m-%d")
                    days_to_race = (race_dt - datetime.now()).days
                    if 0 < days_to_race <= 14:
                        if form_val is not None and form_val < 0:
                            insights.append({"id": "D2_taper", "level": "🟡", "priority": 3, "text": f"เหลืออีก {days_to_race} วันจะถึงวันแข่ง แต่ Form ยังติดลบ ({form_val:.1f}) ควรเริ่ม Taper ลดปริมาณการซ้อมเพื่อให้ร่างกายสดชื่นทันวันแข่ง"})
                        else:
                            insights.append({"id": "D2_ready", "level": "🟢", "priority": 4, "text": f"ใกล้วันแข่ง ({days_to_race} วัน) ร่างกายพักฟื้นพร้อม (Form เป็นบวก) รักษาระดับการซ้อมเบาๆ ไว้"})
                except Exception:
                    pass

    # กลุ่ม E3 — ไม่มีความผิดปกติใดๆ
    if not insights and sleep and recovery:
        if rec_score >= 70 and efficiency >= 85:
            insights.append({"id": "E3_perfect", "level": "🟢", "priority": 5, "text": f"การฟื้นฟูและการนอนหลับสมดุลดีเยี่ยม (Recovery {rec_score:.0f}/100, Efficiency {efficiency:.0f}%) ร่างกายฟื้นตัวได้เต็มที่ทั้งทางกายและระบบประสาท พร้อมรับการซ้อม"})
        elif rec_score >= 40:
            insights.append({"id": "E3_normal", "level": "🟢", "priority": 5, "text": f"วันนี้ทุกตัวชี้วัดอยู่ในเกณฑ์ปกติเมื่อเทียบกับค่าเฉลี่ยของคุณเอง ไม่มีสิ่งที่ต้องปรับ ฝึกตามแผนได้ตามปกติ"})

    if insights:
        # Sort insights by priority (1 is highest)
        insights.sort(key=lambda x: x.get("priority", 99) if isinstance(x, dict) else 99)
        
        lines.append("")
        lines.append("💡 <b>บทวิเคราะห์เชิงลึก (Recovery × Sleep × Load)</b>")
        # กรองแสดงผลแค่สูงสุด 3 ข้อความ เพื่อไม่ให้เกิด alert fatigue
        for ins in insights[:3]:
            if isinstance(ins, dict):
                lines.append(f"  • {ins['level']} {ins['text']}")
            else:
                lines.append(f"  • {ins}")

    # --- Journal (manual) ---
    if journal:
        flags = []
        if journal.get("alcohol_units"):
            flags.append(f"🍺 แอลกอฮอล์ {journal['alcohol_units']} หน่วย")
        if journal.get("caffeine_after_14"):
            flags.append("☕ กาแฟหลังบ่าย 2")
        if journal.get("late_meal"):
            flags.append("🍽 กินดึก")
        if journal.get("screen_before_bed_min"):
            flags.append(f"📱 จอก่อนนอน {journal['screen_before_bed_min']} นาที")
        if journal.get("exercise_evening"):
            flags.append("🏋️ ออกกำลังกายตอนเย็น")
        if journal.get("room_temp_hot"):
            flags.append("🥵 ห้องร้อน")
        if flags:
            lines.append("")
            lines.append("📝 <b>Journal</b>: " + ", ".join(flags))
        if journal.get("notes"):
            lines.append(f"  หมายเหตุ: {journal['notes']}")

    if not (activities or health or sleep or strain):
        lines.append("")
        lines.append("⚠️ ไม่พบข้อมูลใดๆ ของวันนี้ใน database — sync อาจยังไม่สำเร็จ")

    return "\n".join(lines)


# =============================================================================
# Telegram sending
# =============================================================================

def send_telegram_message(text, bot_token, chat_id):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# =============================================================================
# Main
# =============================================================================

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("TELEGRAM_BOT_TOKEN หรือ TELEGRAM_CHAT_ID ไม่ถูกตั้งค่า — ข้ามการแจ้งเตือน")
        # ไม่ทำให้ workflow fail เพราะ Telegram เป็น step เสริม ไม่ใช่ core sync
        sys.exit(0)

    data = gather_today_summary()
    message = build_message(data)

    try:
        send_telegram_message(message, bot_token, chat_id)
        print("ส่งสรุปเข้า Telegram สำเร็จ")
    except requests.exceptions.RequestException as e:
        print(f"ส่ง Telegram ไม่สำเร็จ: {e}")
        # ไม่ raise ต่อ เพื่อไม่ให้ step นี้ทำให้ workflow ทั้งหมด fail
        sys.exit(0)


if __name__ == "__main__":
    main()
