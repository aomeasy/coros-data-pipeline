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


def main():
    print("เริ่มคำนวณ Strain / ACWR ...")

    activities = fetch_all_activities()
    sleep_records = fetch_sleep_records()

    print(f"  พบ activities ทั้งหมด: {len(activities)} รายการ")
    print(f"  พบ sleep records: {len(sleep_records)} รายการ")

    if not activities:
        print("  ไม่มี activity เลยในระบบ — ข้ามการคำนวณ strain")
        return 0

    try:
        strain_results = strain_engine.compute_strain_for_all_days(activities, sleep_records)
    except Exception as e:
        print(f"  strain_engine.compute_strain_for_all_days ล้มเหลว: {e}")
        return 1

    stored = 0
    for s in strain_results:
        date = s.get("date")
        if not date:
            continue

        acwr_result = s.get("acwr") or {}

        # field mapping ตรงกับ schema จริงของ coros_db.store_daily_strain()
        # (day_strain / trimp / acwr เป็นตัวเลขเดี่ยว ไม่ใช่ dict ทั้งก้อน)
        coros_db.store_daily_strain({
            "date": date,
            "day_strain": s.get("strain"),
            "trimp": s.get("trimp"),
            "acwr": acwr_result.get("acwr"),
            "acwr_risk": acwr_result.get("risk"),
            "acwr_confidence": acwr_result.get("confidence"),
            "acute_avg": acwr_result.get("acute_avg"),
            "chronic_avg": acwr_result.get("chronic_avg"),
        })
        stored += 1

    print(f"  บันทึก strain ลง DB สำเร็จ: {stored} วัน")

    # โชว์ผลของวันล่าสุดให้เห็นทันทีใน log
    if strain_results:
        latest = strain_results[-1]
        acwr = latest.get("acwr") or {}
        print(
            f"  ล่าสุด ({latest.get('date')}): "
            f"strain={latest.get('strain')} | trimp={latest.get('trimp')} | "
            f"ACWR={acwr.get('acwr')} ({acwr.get('risk', 'unknown')})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
