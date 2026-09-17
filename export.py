#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export SQLite data to JSON for GitHub Pages"""
import os
import sys
import json
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "coros_cache.db")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "docs")

def fmt_date(d):
    """20260917 -> 2026-09-17"""
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d

def export():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    activities = [dict(r) for r in conn.execute("SELECT * FROM activities ORDER BY start_time DESC LIMIT 50")]
    sleep = [dict(r) for r in conn.execute("SELECT * FROM sleep_data ORDER BY date DESC LIMIT 30")]
    daily = [dict(r) for r in conn.execute("SELECT * FROM daily_health ORDER BY date DESC LIMIT 30")]
    conn.close()

    # Transform activities: rename fields for UI compat
    acts_out = []
    for a in activities:
        acts_out.append({
            "activity_id": a.get("activity_id"),
            "sport_type": a.get("sport_type"),
            "start_time": a.get("start_time"),
            "distance_m": a.get("distance_m"),
            "duration_s": a.get("duration_s"),
            "avg_pace_s": a.get("avg_pace_s"),
            "avg_cadence": a.get("avg_cadence"),
            "caloriesBurned": a.get("calories"),
            "avg_hr": a.get("avg_hr"),
            "max_hr": a.get("max_hr"),
            "ascent_m": a.get("ascent_m"),
            "descent_m": a.get("descent_m"),
            "score": a.get("score"),
        })
    
    # Transform sleep
    sleep_out = []
    for s in sleep:
        sleep_out.append({
            "date": fmt_date(s.get("date", "")),
            "sleep_score": s.get("sleep_score"),
            "duration_min": s.get("duration_min"),
            "deep_sleep_pct": s.get("deep_sleep_pct"),
            "light_sleep_pct": s.get("light_sleep_pct"),
            "rem_sleep_pct": s.get("rem_sleep_pct"),
            "awake_min": s.get("awake_min"),
            "hrv": s.get("hrv"),
            "resting_hr": s.get("resting_hr"),
        })
    
    # Transform daily health
    daily_out = []
    for d in daily:
        daily_out.append({
            "date": fmt_date(d.get("date", "")),
            "sleep_score": d.get("sleep_score"),
            "steps": d.get("steps"),
            "stress_score": d.get("stress_score"),
            "avg_hr": d.get("avg_hr"),
            "max_hr": d.get("max_hr"),
            "calories_burned": d.get("calories_burned"),
        })

    data = {
        "activities": acts_out,
        "sleep": sleep_out,
        "daily": daily_out,
        "stats": {
            "activities_count": len(acts_out),
            "sleep_count": len(sleep_out),
            "daily_count": len(daily_out),
        }
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    print(f"Exported {len(acts_out)} activities, {len(sleep_out)} sleep, {len(daily_out)} daily records")

if __name__ == "__main__":
    export()
