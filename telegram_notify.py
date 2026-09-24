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
    sleep_rows = coros_db.get_recent_sleep(days=10)
    sleep_today = next((r for r in sleep_rows if normalize_date(r.get("date")) == date), None)
    if not sleep_today:
        # sleep ของ "เมื่อคืน" บางทีถูกบันทึกด้วยวันที่เข้านอน (เมื่อวาน) แทนวันที่ตื่น
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

    return {
        "date": date,
        "activities": activities,
        "sleep": sleep_today,
        "health": health_today,
        "strain": strain_today,
        "journal": journal_today,
        "history_days": history_days,
    }


# =============================================================================
# Message building
# =============================================================================

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
            lines.append(
                f"  • {sport}: {fmt(distance_km, ' km', 2)} "
                f"| {seconds_to_hm(act.get('duration_s'))} "
                f"| HR เฉลี่ย {fmt(act.get('avg_hr'), '', 0)} "
                f"| {fmt(act.get('calories'), ' kcal', 0)}"
            )
    else:
        lines.append("")
        lines.append("📍 <b>กิจกรรม</b>: ไม่มีบันทึกวันนี้")

    # --- สุขภาพรายวัน ---
    if health:
        lines.append("")
        lines.append("📊 <b>สุขภาพวันนี้</b>")
        lines.append(f"  👣 ก้าว: {fmt(health.get('steps'), '', 0)}")
        lines.append(f"  🔥 แคลอรี่รวม: {fmt(health.get('calories_burned'), ' kcal', 0)}")
        lines.append(f"  😰 Stress: {fmt(health.get('stress_score'), '/100', 0)}")
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
        lines.append("😴 <b>การนอน</b>")
        lines.append(f"  ระยะเวลา: {minutes_to_hm(sleep.get('duration_min'))}")
        lines.append(f"  Sleep score: {fmt(sleep.get('sleep_score'), '', 0)}")
        lines.append(
            f"  Deep/Light/REM: {fmt(sleep.get('deep_sleep_pct'), '%', 0)} / "
            f"{fmt(sleep.get('light_sleep_pct'), '%', 0)} / "
            f"{fmt(sleep.get('rem_sleep_pct'), '%', 0)}"
        )
        lines.append(
            f"  HRV: {fmt(sleep.get('hrv'), '', 0)} | Resting HR: {fmt(sleep.get('resting_hr'), '', 0)}"
        )

    # --- Strain / ACWR ---
    if strain:
        lines.append("")
        lines.append("⚡ <b>Strain</b>")
        lines.append(f"  Day strain: {fmt(strain.get('day_strain'), '', 1)}")
        lines.append(f"  TRIMP: {fmt(strain.get('trimp'), '', 1)}")
        lines.append(acwr_line(strain.get("acwr"), data.get("history_days")))

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
