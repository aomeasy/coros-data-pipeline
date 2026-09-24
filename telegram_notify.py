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
"""

import os
import sys
from datetime import datetime, timedelta

import requests

import coros_db


# =============================================================================
# Helpers
# =============================================================================

def today_str():
    """คืนค่าวันที่วันนี้ในรูปแบบ YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")


def yesterday_str():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


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


# =============================================================================
# Data gathering
# =============================================================================

def gather_today_summary():
    """ดึงข้อมูลของวันนี้จากทุกตารางที่เกี่ยวข้อง"""
    date = today_str()

    # กิจกรรมของวันนี้ (start_time ขึ้นต้นด้วยวันนี้)
    activities = coros_db.get_activities_between(date, date)

    # sleep ของ "เมื่อคืน" มักถูกบันทึกเป็นวันที่ตื่นนอน (วันนี้) — ลองทั้งสองวันกันพลาด
    sleep_rows = coros_db.get_recent_sleep(days=3)
    sleep_today = next((r for r in sleep_rows if r.get("date") == date), None)
    if not sleep_today:
        sleep_today = next((r for r in sleep_rows if r.get("date") == yesterday_str()), None)

    # สุขภาพรายวัน
    health_rows = coros_db.get_recent_daily_health(days=3)
    health_today = next((r for r in health_rows if r.get("date") == date), None)

    # strain / ACWR
    strain_today = coros_db.get_strain_by_date(date)

    # journal (manual log)
    journal_today = coros_db.get_journal_by_date(date)

    return {
        "date": date,
        "activities": activities,
        "sleep": sleep_today,
        "health": health_today,
        "strain": strain_today,
        "journal": journal_today,
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
            sport = act.get("sport_type") or "activity"
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
        acwr = strain.get("acwr")
        lines.append(f"  ACWR: {fmt(acwr, '', 2)}{acwr_flag(acwr)}")

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
