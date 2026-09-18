# -*- coding: utf-8 -*-
"""
COROS Data Cache Manager
ไฟล์: coros_db.py
DB Path: C:/Users/Adcharaporn-U1200/AppData/Local/hermes/coros_cache.db

ใช้เก็บข้อมูล COROS ทั้งหมด (กิจกรรม, การนอน, สุขภาพรายวัน) ไว้ใน SQLite
ทุก skill เรียกใช้ได้ ไม่ต้องเรียก COROS API ซ้ำ
"""
import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

import data_validation as _dv
from logging_utils import get_logger

_log = get_logger("coros_db")

# ใช้ directory ของ script เป็น base — รันใน GitHub Actions เท่านั้น
DB_PATH = Path(__file__).parent / "coros_cache.db"

# ---------------------------------------------------------------------------
# Schema versioning / migrations (Phase 0 hardening)
#
# Every new column/table added in future phases (Strain, baselines, etc.)
# should be added as a new numbered entry in MIGRATIONS instead of editing
# init_db()'s CREATE TABLE statements directly. This lets an existing
# coros_cache.db (with real synced data) upgrade in place instead of forcing
# a destructive re-sync.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1

# Each migration is (version, description, list-of-SQL-statements).
# Statements should be idempotent-safe (IF NOT EXISTS) where possible so
# re-running a migration that partially applied doesn't error out.
MIGRATIONS = [
    (1, "baseline schema (activities, sleep_data, daily_health, journal_entries)", []),
    # Future example:
    # (2, "add daily_strain table", ["CREATE TABLE IF NOT EXISTS daily_strain (...)"]),
]


def _ensure_schema_meta(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    conn.commit()


def get_schema_version(conn=None) -> int:
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    _ensure_schema_meta(conn)
    row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    if own_conn:
        conn.close()
    return int(row[0]) if row else 0


def _set_schema_version(conn, version: int):
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )
    conn.commit()


def migrate():
    """Apply any migrations newer than the DB's current schema_version.

    Safe to call every run (it's called from init_db() below): if the DB is
    already at SCHEMA_VERSION, this is a no-op.
    """
    conn = get_conn()
    _ensure_schema_meta(conn)
    current = get_schema_version(conn)
    applied = []
    for version, description, statements in MIGRATIONS:
        if version <= current:
            continue
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()
        _set_schema_version(conn, version)
        applied.append((version, description))
        current = version
    conn.close()
    return applied


def get_conn():
    """เปิด connection ไปยัง SQLite database"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

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
        summary_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS baselines_daily (
        date            TEXT NOT NULL,
        metric_name     TEXT NOT NULL,
        context         TEXT,
        mean            REAL,
        stdev           REAL,
        n               INTEGER,
        confidence      TEXT,
        half_life_days  REAL,
        log_transformed INTEGER,
        PRIMARY KEY (date, metric_name, context)
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
    """)
    conn.commit()
    _ensure_schema_meta(conn)
    # If this is a brand-new DB, stamp it at the current baseline version
    # without re-running migration statements that assume the base tables
    # didn't exist yet.
    if get_schema_version(conn) == 0:
        _set_schema_version(conn, 1)
    conn.close()
    # Apply any migrations newer than version 1 (no-op on a fresh DB).
    migrate()

def store_activity(activity):
    """
    เก็บกิจกรรมลง database
    activity: dict จาก COROS getActivityDetail

    ผ่าน data_validation ก่อนเสมอ: ค่าที่หลุดช่วงที่เป็นไปได้จริง (เช่น
    distance ติดลบ, avg_hr 900) จะถูก null ทิ้งแทนที่จะถูกเก็บลง DB และไป
    บิดเบือนทุก metric ที่คำนวณต่อจากมัน — record ที่ไม่มี activity_id เลย
    จะถูก reject ไม่บันทึกอะไรทั้งแถว
    """
    row = {
        "activity_id": activity.get("activityId"),
        "distance_m": activity.get("distance", 0),
        "duration_s": activity.get("duration", 0),
        "avg_hr": activity.get("averageHeartRate"),
        "max_hr": activity.get("maxHeartRate"),
        "calories_burned": activity.get("caloriesBurned"),
    }
    clean, issues = _dv.clean_activity_record(row)
    if _dv.has_blocking_issue(issues):
        _log.warning("activity_rejected", issues=[i.as_dict() for i in issues])
        return False
    for issue in issues:
        _log.warning("activity_field_issue", **issue.as_dict())

    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO activities 
    (activity_id, sport_type, start_time, distance_m, duration_s, 
     avg_pace_s, avg_cadence, calories, avg_hr, max_hr,
     ascent_m, descent_m, score, summary_json, created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        clean["activity_id"],
        activity.get("sportType"),
        activity.get("startTime"),
        clean["distance_m"],
        clean["duration_s"],
        activity.get("averagePace"),
        activity.get("averageCadence"),
        activity.get("caloriesBurned"),
        clean["avg_hr"],
        clean["max_hr"],
        activity.get("ascent"),
        activity.get("descent"),
        activity.get("score"),
        json.dumps(activity, ensure_ascii=False),
        now, now
    ))
    conn.commit()
    conn.close()
    return True

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

def get_activity_by_id(activity_id):
    """ดึงกิจกรรมตาม activity_id"""
    conn = get_conn()
    row = conn.execute("""
    SELECT * FROM activities WHERE activity_id = ?
    """, (activity_id,)).fetchone()
    conn.close()
    return dict(r) if row else None

def store_sleep(data):
    """
    เก็บข้อมูลการนอน
    data: dict จาก queryDailyHealthData หรือ querySleepData

    ผ่าน data_validation ก่อนเสมอ (ดูเหตุผลใน store_activity)
    """
    row = {
        "date": data.get("date"),
        "sleep_score": data.get("sleepScore"),
        "duration_min": data.get("duration", 0),
        "deep_sleep_pct": data.get("deepSleepRatio"),
        "light_sleep_pct": data.get("lightSleepRatio"),
        "rem_sleep_pct": data.get("remSleepRatio"),
        "awake_min": data.get("awakeDuration"),
        "hrv": data.get("hrv"),
        "resting_hr": data.get("restingHeartRate"),
    }
    clean, issues = _dv.clean_sleep_record(row)
    if _dv.has_blocking_issue(issues):
        _log.warning("sleep_record_rejected", issues=[i.as_dict() for i in issues])
        return False
    for issue in issues:
        _log.warning("sleep_field_issue", date=row.get("date"), **issue.as_dict())

    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO sleep_data 
    (date, sleep_score, duration_min, deep_sleep_pct, light_sleep_pct,
     rem_sleep_pct, awake_min, hrv, resting_hr, summary_json, created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        clean["date"],
        clean["sleep_score"],
        clean["duration_min"],
        clean["deep_sleep_pct"],
        clean["light_sleep_pct"],
        clean["rem_sleep_pct"],
        clean["awake_min"],
        clean["hrv"],
        clean["resting_hr"],
        json.dumps(data, ensure_ascii=False),
        now, now
    ))
    conn.commit()
    conn.close()
    return True

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

    ผ่าน data_validation ก่อนเสมอ (ดูเหตุผลใน store_activity)
    """
    row = {
        "date": data.get("date"),
        "steps": data.get("steps"),
        "stress_score": data.get("stressLevel"),
        "avg_hr": data.get("averageHeartRate"),
        "max_hr": data.get("maxHeartRate"),
        "calories_burned": data.get("caloriesBurned"),
    }
    clean, issues = _dv.clean_daily_health_record(row)
    if _dv.has_blocking_issue(issues):
        _log.warning("daily_health_rejected", issues=[i.as_dict() for i in issues])
        return False
    for issue in issues:
        _log.warning("daily_health_field_issue", date=row.get("date"), **issue.as_dict())

    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO daily_health 
    (date, sleep_score, steps, stress_score, avg_hr, max_hr, calories_burned, summary_json, created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        clean["date"],
        data.get("sleepScore"),
        clean["steps"],
        clean["stress_score"],
        clean["avg_hr"],
        clean["max_hr"],
        clean["calories_burned"],
        json.dumps(data, ensure_ascii=False),
        now, now
    ))
    conn.commit()
    conn.close()
    return True

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
    """ล้างข้อมูลทั้งหมดใน cache (ระวัง!)"""
    conn = get_conn()
    conn.executescript("""
    DELETE FROM activities;
    DELETE FROM sleep_data;
    DELETE FROM daily_health;
    """)
    conn.commit()
    conn.close()

def get_db_stats():
    """ดูสถิติของ database"""
    conn = get_conn()
    activities_count = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    sleep_count = conn.execute("SELECT COUNT(*) FROM sleep_data").fetchone()[0]
    daily_count = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    conn.close()
    schema_version = get_schema_version()
    return {
        "activities": activities_count,
        "sleep_records": sleep_count,
        "daily_health": daily_count,
        "db_path": str(DB_PATH),
        "schema_version": schema_version,
    }

def store_journal(data):
    """
    เก็บ journal entry
    data: dict ของ journal entry
    """
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
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
    conn.commit()
    conn.close()

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

# เริ่มสร้างตารางตอน import
init_db()

