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

def export():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    activities = [dict(r) for r in conn.execute("SELECT * FROM activities ORDER BY start_time DESC LIMIT 50")]
    sleep = [dict(r) for r in conn.execute("SELECT * FROM sleep_data ORDER BY date DESC LIMIT 30")]
    daily = [dict(r) for r in conn.execute("SELECT * FROM daily_health ORDER BY date DESC LIMIT 30")]
    conn.close()

    # remove blob-like summary_json for size
    for a in activities:
        if 'summary_json' in a:
            del a['summary_json']
    for s in sleep:
        if 'summary_json' in s:
            del s['summary_json']
    for d in daily:
        if 'summary_json' in d:
            del d['summary_json']

    data = {
        "activities": activities,
        "sleep": sleep,
        "daily": daily,
        "stats": {
            "activities_count": len(activities),
            "sleep_count": len(sleep),
            "daily_count": len(daily),
        }
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    print(f"Exported {len(activities)} activities, {len(sleep)} sleep, {len(daily)} daily records")

if __name__ == "__main__":
    export()
