#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_strain.py — เรียก strain_engine.py ตรงๆ ใน pipeline ของ GitHub Actions

เหตุผลที่มีไฟล์นี้: strain_engine.py ถูกออกแบบไว้ให้ app.py (Flask) เรียกผ่าน
/api/analysis แต่ app.py ไม่เคยถูกรันเป็น live server จริง (docs/ ที่ deploy
อยู่บน GitHub Pages เป็นแค่ static hosting รัน Python ไม่ได้) ทำให้ตาราง
daily_strain ว่างเปล่ามาตลอด

ไฟล์นี้ตัดตอนเฉพาะ "ส่วนคำนวณ strain" จาก app.py._compute_and_store_strain()
มาเรียกตรงๆ ในสคริปต์ที่รันบน GitHub Actions runner เลย ไม่ต้องพึ่ง Flask/HTTP
เลยแม้แต่นิดเดียว — ใช้ field mapping เดียวกับที่ app.py แก้ไว้แล้ว (ตรงกับ
schema จริงของ coros_db.store_daily_strain())

รันหลัง coros_daily_sync.py เสมอ (ต้องมี activities/sleep ใหม่ใน DB ก่อน)

การเปลี่ยนแปลงรอบนี้ (ส่วนอื่นคงเดิมทั้งหมด):
  1. เช็คค่าที่ coros_db.store_daily_strain() คืนมา — เดิมนับ "สำเร็จ" ทุกวันโดยไม่ดูผล
     (coros_db เวอร์ชันใหม่ไม่โยน exception แล้ว แต่คืน False แทน) และคืน exit code 1
     ถ้ามีวันที่บันทึกไม่สำเร็จ (พฤติกรรมเทียบเท่าเดิมที่ exception ทำให้ step ล้ม)
  2. เก็บ history_days ลง summary_json เพื่อให้ telegram_notify.py ตัดสินได้ว่า ACWR
     เชื่อถือได้หรือยัง
  3. ลบแถว daily_strain ของวันที่ engine ไม่ได้คำนวณให้แล้ว (เช่น วันที่เพี้ยนจาก
     timezone bug ก่อนแก้ ซึ่งหลัง re-sync กิจกรรมย้ายไปวันที่ถูกแล้ว แต่แถว strain
     ของวันเก่ายังค้าง) — ทำเมื่อบันทึกครบทุกวันเท่านั้น
  4. ตั้งค่า sex ผ่าน environment variable STRAIN_SEX ("male"/"female") ได้
     ค่าเริ่มต้น "male" เท่าเดิม (ค่าคงที่ของ Banister TRIMP ต่างกันตามเพศ)
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import coros_db
import strain_engine


def fetch_all_activities():
    """
    ดึงกิจกรรมทั้งหมด — ใช้ช่วงกว้างสุดเพื่อกันพลาดจาก date format ที่อาจปนกัน
    (เหมือนที่ใช้ใน telegram_notify.py) แทนที่จะเสี่ยงพลาดข้อมูลจาก BETWEEN
    ที่แคบเกินไป
    """
    return coros_db.get_activities_between("0000-01-01", "9999-12-31")


def fetch_sleep_records(days=60):
    """
    ดึง sleep ย้อนหลังพอสมควร (ใช้แค่หา resting_hr เฉลี่ย 14 วันล่าสุด
    ใน estimate_hr_rest() แต่ดึงมากกว่านั้นไว้กันวันที่ไม่มี resting_hr บันทึก)
    """
    return coros_db.get_recent_sleep(days=days)


def get_sex():
    """อ่านเพศจาก env STRAIN_SEX — ค่าที่ไม่รู้จักถือเป็น "male" (ค่าเริ่มต้นเดิม)"""
    raw = os.environ.get("STRAIN_SEX", "male").strip().lower()
    return "female" if raw == "female" else "male"


def prune_stale_strain(valid_dates):
    """
    ลบแถว daily_strain ที่ date ไม่อยู่ในผลคำนวณล่าสุด (แถวค้างจากกิจกรรมที่ย้ายวันแล้ว)
    engine คำนวณใหม่ทั้งหมดทุกรอบ จึงลบได้อย่างปลอดภัย คืนจำนวนแถวที่ลบ
    """
    if not valid_dates:
        return 0
    conn = coros_db.get_conn()
    try:
        marks = ",".join("?" for _ in valid_dates)
        cur = conn.execute(
            f"DELETE FROM daily_strain WHERE date NOT IN ({marks})", list(valid_dates)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def main():
    print("เริ่มคำนวณ Strain / ACWR ...")

    activities = fetch_all_activities()
    sleep_records = fetch_sleep_records()

    print(f"  พบ activities ทั้งหมด: {len(activities)} รายการ")
    print(f"  พบ sleep records: {len(sleep_records)} รายการ")

    if not activities:
        print("  ไม่มี activity เลยในระบบ — ข้ามการคำนวณ strain")
        return 0

    sex = get_sex()
    print(f"  ใช้ค่าคงที่ TRIMP ของเพศ: {sex} (ตั้งได้ด้วย env STRAIN_SEX)")

    try:
        strain_results = strain_engine.compute_strain_for_all_days(
            activities, sleep_records, sex=sex
        )
    except Exception as e:
        print(f"  strain_engine.compute_strain_for_all_days ล้มเหลว: {e}")
        return 1

    stored = 0
    failed = 0
    stored_dates = []
    for s in strain_results:
        date = s.get("date")
        if not date:
            continue

        acwr_result = s.get("acwr") or {}

        # field mapping ตรงกับ schema จริงของ coros_db.store_daily_strain()
        # (day_strain / trimp / acwr เป็นตัวเลขเดี่ยว ไม่ใช่ dict ทั้งก้อน)
        ok = coros_db.store_daily_strain({
            "date": date,
            "day_strain": s.get("strain"),
            "trimp": s.get("trimp"),
            "acwr": acwr_result.get("acwr"),
            "acwr_risk": acwr_result.get("risk"),
            "acwr_confidence": acwr_result.get("confidence"),
            "acute_avg": acwr_result.get("acute_avg"),
            "chronic_avg": acwr_result.get("chronic_avg"),
            "history_days": acwr_result.get("history_days"),
        })
        if ok:
            stored += 1
            stored_dates.append(date)
        else:
            failed += 1
            print(f"  บันทึก strain ของ {date} ไม่สำเร็จ")

    print(f"  บันทึก strain ลง DB สำเร็จ: {stored} วัน" + (f" (ไม่สำเร็จ {failed} วัน)" if failed else ""))

    if failed:
        print("  ข้ามการลบแถว strain เก่า เพราะยังบันทึกไม่ครบทุกวัน")
    else:
        removed = prune_stale_strain(stored_dates)
        if removed:
            print(f"  ลบแถว strain เก่าที่ไม่มีกิจกรรมรองรับแล้ว: {removed} แถว")

    # โชว์ผลของวันล่าสุดให้เห็นทันทีใน log
    if strain_results:
        latest = strain_results[-1]
        acwr = latest.get("acwr") or {}
        print(
            f"  ล่าสุด ({latest.get('date')}): "
            f"strain={latest.get('strain')} | trimp={latest.get('trimp')} | "
            f"ACWR={acwr.get('acwr')} ({acwr.get('risk', 'unknown')}, "
            f"ประวัติ {acwr.get('history_days')} วัน)"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
