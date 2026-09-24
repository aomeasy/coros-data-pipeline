# -*- coding: utf-8 -*-
"""
COROS Data Cache Manager
ไฟล์: coros_db.py
DB Path: coros_cache.db (อยู่โฟลเดอร์เดียวกับไฟล์นี้ — รันใน GitHub Actions)

ใช้เก็บข้อมูล COROS ทั้งหมด (กิจกรรม, การนอน, สุขภาพรายวัน, strain) ไว้ใน SQLite
ทุก skill เรียกใช้ได้ ไม่ต้องเรียก COROS API ซ้ำ

การเปลี่ยนแปลงรอบนี้ (ส่วนอื่นคงเดิมทั้งหมด):
  1. store_* ทุกตัวคืน True/False (เดิมคืน None เสมอ ทำให้ log "rejected" เป็นเท็จ)
  2. sleep_data / daily_health เปลี่ยนจาก INSERT OR REPLACE เป็น upsert แบบ COALESCE
     ค่า NULL จากการ sync รอบใหม่จะไม่ลบค่าที่เคยเก็บไว้ (เช่น HRV)
  3. journal_mode เปลี่ยน WAL -> DELETE เพื่อให้ได้ไฟล์ .db ไฟล์เดียวตอน commit เข้า git
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

# ใช้ directory ของ script เป็น base — รันใน GitHub Actions เท่านั้น
DB_PATH = Path(__file__).parent / "coros_cache.db"


def get_conn():
    """เปิด connection ไปยัง SQLite database"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # DELETE (ไม่ใช่ WAL): workflow commit ไฟล์ coros_cache.db ไฟล์เดียวเข้า repo
    # ถ้าเป็น WAL ข้อมูลล่าสุดอาจค้างใน -wal แล้วไม่ถูก commit
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _upsert(sql, params):
    """
    รัน INSERT/UPSERT แล้วคืน True ถ้าเขียนสำเร็จ / False ถ้า DB ปฏิเสธ
    (เช่น key เป็น NULL, ชนกับ constraint) — ปิด connection เสมอ
    """
    conn = get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"DB write failed: {e}")
        return False
    finally:
        conn.close()


def init_db():
    """สร้างตารางทั้งหมดถ้ายังไม่มี"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS activities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id TEXT UNIQUE NOT NULL,
            sport_type TEXT,
            start_time TEXT,
            distance_m REAL,
            duration_s INTEGER,
            avg_pace_s REAL,
            avg_cadence REAL,
            calories INTEGER,
            avg_hr REAL,
            max_hr REAL,
            ascent_m REAL,
            descent_m REAL,
            score INTEGER,
            summary_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sleep_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            sleep_score INTEGER,
            duration_min INTEGER,
            deep_sleep_pct REAL,
            light_sleep_pct REAL,
            rem_sleep_pct REAL,
            awake_min INTEGER,
            hrv INTEGER,
            resting_hr INTEGER,
            summary_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_health (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            sleep_score INTEGER,
            steps INTEGER,
            stress_score INTEGER,
            avg_hr REAL,
            max_hr REAL,
            calories_burned INTEGER,
            respiratory_rate REAL,
            skin_temp_deviation_c REAL,
            spo2_avg REAL,
            spo2_min REAL,
            summary_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_activities_sport ON activities(sport_type);
        CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time);
        CREATE INDEX IF NOT EXISTS idx_sleep_date ON sleep_data(date);
        CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_health(date);

        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            alcohol_units INTEGER DEFAULT 0,
            caffeine_after_14 INTEGER DEFAULT 0,
            late_meal INTEGER DEFAULT 0,
            screen_before_bed_min INTEGER DEFAULT 0,
            stress_level INTEGER DEFAULT 0,
            exercise_evening INTEGER DEFAULT 0,
            room_temp_hot INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);

        -- Phase 2.2: Strain Engine
        CREATE TABLE IF NOT EXISTS daily_strain (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            day_strain REAL,
            trimp REAL,
            acwr REAL,
            summary_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_strain_date ON daily_strain(date);

        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            signals TEXT,
            created_at TEXT NOT NULL
        );
    """)
    # Backward-compatible migration: ถ้า DB เดิมมี daily_health อยู่แล้วก่อนเพิ่มคอลัมน์นี้
    # (ตาราง CREATE TABLE IF NOT EXISTS จะไม่เติมคอลัมน์ใหม่ให้ของเดิมที่มีอยู่แล้ว)
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(daily_health)").fetchall()}
    if "respiratory_rate" not in existing_cols:
        conn.execute("ALTER TABLE daily_health ADD COLUMN respiratory_rate REAL")
    if "skin_temp_deviation_c" not in existing_cols:
        conn.execute("ALTER TABLE daily_health ADD COLUMN skin_temp_deviation_c REAL")
    if "spo2_avg" not in existing_cols:
        conn.execute("ALTER TABLE daily_health ADD COLUMN spo2_avg REAL")
    if "spo2_min" not in existing_cols:
        conn.execute("ALTER TABLE daily_health ADD COLUMN spo2_min REAL")
    conn.commit()
    conn.close()


def store_alert(date, alert_type, risk_level, signals=None):
    """เก็บ alert log ลง database — คืน True/False"""
    return _upsert(
        """INSERT INTO alert_history (date, alert_type, risk_level, signals, created_at) VALUES (?, ?, ?, ?, ?)""",
        (date, alert_type, risk_level, json.dumps(signals) if signals else None, datetime.now().isoformat())
    )


def store_activity(activity):
    """
    เก็บกิจกรรมลง database (INSERT OR REPLACE ตาม activity_id — logic เดิม)
    activity: dict จาก COROS getActivityDetail
    คืน True ถ้าเขียนสำเร็จ / False ถ้า activityId ว่างหรือ DB ปฏิเสธ
    """
    # activityId ว่าง ("") ผ่าน NOT NULL ได้ แต่จะชนกันเองแล้วทับกันหมด จึงปฏิเสธ
    if not activity.get("activityId"):
        return False
    now = datetime.now().isoformat()
    return _upsert("""
        INSERT OR REPLACE INTO activities
        (activity_id, sport_type, start_time, distance_m, duration_s,
         avg_pace_s, avg_cadence, calories, avg_hr, max_hr,
         ascent_m, descent_m, score, summary_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        activity.get("activityId"),
        activity.get("sportType"),
        activity.get("startTime"),
        activity.get("distance", 0),
        activity.get("duration", 0),
        activity.get("averagePace"),
        activity.get("averageCadence"),
        activity.get("caloriesBurned"),
        activity.get("averageHeartRate"),
        activity.get("maxHeartRate"),
        activity.get("ascent"),
        activity.get("descent"),
        activity.get("score"),
        json.dumps(activity, ensure_ascii=False),
        now, now
    ))


def get_recent_activities(sport="running", limit=5):
    """ดึงกิจกรรมล่าสุดจาก database"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM activities
        WHERE sport_type LIKE ?
        ORDER BY start_time DESC LIMIT ?
    """, (f"%{sport}%", limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_activities_between(start_date, end_date):
    """
    ดึงกิจกรรมทั้งหมดในช่วงวันที่ (inclusive) — ใช้โดย strain_engine
    start_date/end_date: 'YYYY-MM-DD' (เทียบกับ start_time ด้วย string prefix match)
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM activities
        WHERE substr(start_time, 1, 10) BETWEEN ? AND ?
        ORDER BY start_time ASC
    """, (start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_activity_by_id(activity_id):
    """ดึงกิจกรรมตาม activity_id"""
    conn = get_conn()
    row = conn.execute("""
        SELECT * FROM activities WHERE activity_id = ?
    """, (activity_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def store_sleep(data):
    """
    เก็บข้อมูลการนอน
    data: dict จาก queryDailyHealthData หรือ querySleepData

    upsert ตาม date: ค่าใหม่ที่เป็น NULL จะไม่ทับค่าเดิมที่มีอยู่แล้ว
    (sync ดึงย้อน 7 วันทุกรอบ ค่า HRV ที่เคยเติมไว้จึงไม่ถูกลบ)
    คืน True ถ้าเขียนสำเร็จ / False ถ้า date ว่างหรือ DB ปฏิเสธ
    """
    if not data.get("date"):
        return False
    now = datetime.now().isoformat()
    return _upsert("""
        INSERT INTO sleep_data
        (date, sleep_score, duration_min, deep_sleep_pct, light_sleep_pct,
         rem_sleep_pct, awake_min, hrv, resting_hr, summary_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            sleep_score     = COALESCE(excluded.sleep_score, sleep_data.sleep_score),
            duration_min    = COALESCE(NULLIF(excluded.duration_min, 0), sleep_data.duration_min),
            deep_sleep_pct  = COALESCE(excluded.deep_sleep_pct, sleep_data.deep_sleep_pct),
            light_sleep_pct = COALESCE(excluded.light_sleep_pct, sleep_data.light_sleep_pct),
            rem_sleep_pct   = COALESCE(excluded.rem_sleep_pct, sleep_data.rem_sleep_pct),
            awake_min       = COALESCE(excluded.awake_min, sleep_data.awake_min),
            hrv             = COALESCE(excluded.hrv, sleep_data.hrv),
            resting_hr      = COALESCE(excluded.resting_hr, sleep_data.resting_hr),
            summary_json    = excluded.summary_json,
            updated_at      = excluded.updated_at
    """, (
        data.get("date"),
        data.get("sleepScore"),
        data.get("duration", 0),
        data.get("deepSleepRatio"),
        data.get("lightSleepRatio"),
        data.get("remSleepRatio"),
        data.get("awakeDuration"),
        data.get("hrv"),
        data.get("restingHeartRate"),
        json.dumps(data, ensure_ascii=False),
        now, now
    ))


def get_recent_sleep(days=7):
    """ดึงข้อมูลการนอนล่าสุดจาก database"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM sleep_data
        ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def store_daily_health(data):
    """
    เก็บข้อมูลสุขภาพรายวัน
    data: dict จาก queryDailyHealthData

    upsert ตาม date: ค่าใหม่ที่เป็น NULL จะไม่ทับค่าเดิม
    คืน True ถ้าเขียนสำเร็จ / False ถ้า date ว่างหรือ DB ปฏิเสธ
    """
    if not data.get("date"):
        return False
    now = datetime.now().isoformat()
    return _upsert("""
        INSERT INTO daily_health
        (date, sleep_score, steps, stress_score, avg_hr, max_hr, calories_burned,
         respiratory_rate, skin_temp_deviation_c, spo2_avg, spo2_min,
         summary_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(date) DO UPDATE SET
            sleep_score           = COALESCE(excluded.sleep_score, daily_health.sleep_score),
            steps                 = COALESCE(excluded.steps, daily_health.steps),
            stress_score          = COALESCE(excluded.stress_score, daily_health.stress_score),
            avg_hr                = COALESCE(excluded.avg_hr, daily_health.avg_hr),
            max_hr                = COALESCE(excluded.max_hr, daily_health.max_hr),
            calories_burned       = COALESCE(excluded.calories_burned, daily_health.calories_burned),
            respiratory_rate      = COALESCE(excluded.respiratory_rate, daily_health.respiratory_rate),
            skin_temp_deviation_c = COALESCE(excluded.skin_temp_deviation_c, daily_health.skin_temp_deviation_c),
            spo2_avg              = COALESCE(excluded.spo2_avg, daily_health.spo2_avg),
            spo2_min              = COALESCE(excluded.spo2_min, daily_health.spo2_min),
            summary_json          = excluded.summary_json,
            updated_at            = excluded.updated_at
    """, (
        data.get("date"),
        data.get("sleepScore"),
        data.get("steps"),
        data.get("stressLevel"),
        data.get("averageHeartRate"),
        data.get("maxHeartRate"),
        data.get("caloriesBurned"),
        data.get("respiratoryRate"),
        data.get("skinTempDeviationC"),
        data.get("spo2Avg"),
        data.get("spo2Min"),
        json.dumps(data, ensure_ascii=False),
        now, now
    ))


def get_recent_daily_health(days=7):
    """ดึงข้อมูลสุขภาพรายวันล่าสุด"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM daily_health
        ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cache_daily_health(start_date, end_date):
    """
    ดึงข้อมูลจาก COROS-MCP แล้วเก็บใน database ทีเดียว
    ใช้เมื่อต้องการ sync ข้อมูลหลายวัน
    """
    import subprocess
    result = subprocess.run(
        ["coros-mcp", "call-tool", "--tool", "queryDailyHealthData",
         "--arguments-json", json.dumps({"startDate": start_date, "endDate": end_date})],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error calling COROS-MCP: {result.stderr}")
        return None

    data = json.loads(result.stdout)
    for day in data.get("dailyHealthData", []):
        store_daily_health(day)
        if day.get("sleepScore"):
            store_sleep(day)

    return data


def clear_cache():
    """
    ล้างข้อมูลใน cache (ระวัง!)
    หมายเหตุ: ไม่ล้าง journal_entries และ alert_history (พฤติกรรมเดิม)
    """
    conn = get_conn()
    conn.executescript("""
        DELETE FROM activities;
        DELETE FROM sleep_data;
        DELETE FROM daily_health;
        DELETE FROM daily_strain;
    """)
    conn.commit()
    conn.close()


def get_db_stats():
    """ดูสถิติของ database"""
    conn = get_conn()
    activities_count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    sleep_count = conn.execute("SELECT COUNT(*) FROM sleep_data").fetchone()[0]
    daily_count = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    strain_count = conn.execute("SELECT COUNT(*) FROM daily_strain").fetchone()[0]
    conn.close()
    return {
        "activities": activities_count,
        "sleep_records": sleep_count,
        "daily_health": daily_count,
        "daily_strain": strain_count,
        "db_path": str(DB_PATH)
    }


def store_journal(data):
    """
    เก็บ journal entry
    data: dict ของ journal entry
    คืน True ถ้าเขียนสำเร็จ / False ถ้า date ว่างหรือ DB ปฏิเสธ
    """
    if not data.get("date"):
        return False
    now = datetime.now().isoformat()
    return _upsert("""
        INSERT OR REPLACE INTO journal_entries
        (date, alcohol_units, caffeine_after_14, late_meal,
         screen_before_bed_min, stress_level, exercise_evening,
         room_temp_hot, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("date"),
        data.get("alcohol_units", 0),
        data.get("caffeine_after_14", 0),
        data.get("late_meal", 0),
        data.get("screen_before_bed_min", 0),
        data.get("stress_level", 0),
        data.get("exercise_evening", 0),
        data.get("room_temp_hot", 0),
        data.get("notes", ""),
        now, now
    ))


def get_journal_by_date(date):
    """ดึง journal ตาม date"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM journal_entries WHERE date = ?", (date,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_journals():
    """ดึง journal ทั้งหมด"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM journal_entries ORDER BY date DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# =============================================================================
# Phase 2.2 — Strain Engine storage
# =============================================================================

def store_daily_strain(data):
    """
    เก็บผลลัพธ์ strain รายวัน (จาก strain_engine.py)
    data: dict ต้องมีอย่างน้อย {"date": "YYYY-MM-DD", "day_strain": float,
                                  "trimp": float, "acwr": float}
    ฟิลด์อื่นที่ strain_engine ส่งมาเพิ่มจะถูกเก็บทั้งชุดไว้ใน summary_json
    คืน True ถ้าเขียนสำเร็จ / False ถ้า date ว่างหรือ DB ปฏิเสธ
    """
    if not data.get("date"):
        return False
    now = datetime.now().isoformat()
    return _upsert("""
        INSERT OR REPLACE INTO daily_strain
        (date, day_strain, trimp, acwr, summary_json, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?)
    """, (
        data.get("date"),
        data.get("day_strain"),
        data.get("trimp"),
        data.get("acwr"),
        json.dumps(data, ensure_ascii=False),
        now, now
    ))


def get_recent_daily_strain(days=28):
    """
    ดึง strain ล่าสุดจาก database
    default 28 วัน เพราะ ACWR ต้องมองย้อน chronic window (28 วัน)
    """
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM daily_strain
        ORDER BY date DESC LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_strain_by_date(date):
    """ดึง strain ตาม date เดียว — ใช้จับคู่กับ recovery ของวันเดียวกัน"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM daily_strain WHERE date = ?", (date,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# เริ่มสร้างตารางตอน import
init_db()
