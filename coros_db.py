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

DB_PATH = Path.home() / "AppData" / "Local" / "hermes" / "coros_cache.db"

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
    CREATE INDEX IF NOT EXISTS idx_activities_sport ON activities(sport_type);
    CREATE INDEX IF NOT EXISTS idx_activities_start ON activities(start_time);
    CREATE INDEX IF NOT EXISTS idx_sleep_date ON sleep_data(date);
    CREATE INDEX IF NOT EXISTS idx_daily_date ON daily_health(date);
    """)
    conn.close()

def store_activity(activity):
    """
    เก็บกิจกรรมลง database
    activity: dict จาก COROS getActivityDetail
    """
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
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
    conn.commit()
    conn.close()

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
    """
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO sleep_data 
    (date, sleep_score, duration_min, deep_sleep_pct, light_sleep_pct,
     rem_sleep_pct, awake_min, hrv, resting_hr, summary_json, created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
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
    conn.commit()
    conn.close()

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
    """
    now = datetime.now().isoformat()
    conn = get_conn()
    conn.execute("""
    INSERT OR REPLACE INTO daily_health 
    (date, sleep_score, steps, stress_score, avg_hr, max_hr, calories_burned, summary_json, created_at, updated_at)
    VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (
        data.get("date"),
        data.get("sleepScore"),
        data.get("steps"),
        data.get("stressLevel"),
        data.get("averageHeartRate"),
        data.get("maxHeartRate"),
        data.get("caloriesBurned"),
        json.dumps(data, ensure_ascii=False),
        now, now
    ))
    conn.commit()
    conn.close()

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
    return {
        "activities": activities_count,
        "sleep_records": sleep_count,
        "daily_health": daily_count,
        "db_path": str(DB_PATH)
    }

# เริ่มสร้างตารางตอน import
init_db()
