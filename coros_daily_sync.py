#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COROS Data Daily Sync
รันทุกวันเพื่อดึงข้อมูลจาก COROS-MCP แล้วเก็บใน cache database
เวลาเริ่มต้น: 01:00 น. ทุกวัน
"""
import sys
import subprocess
import json
from datetime import datetime, timedelta

sys.path.insert(0, "C:/Users/Adcharaporn-U1200/AppData/Local/hermes")
import coros_db

COROS_MCP_NODE = "C:/Users/Adcharaporn-U1200/AppData/Roaming/npm/node_modules/coros-mcp/dist/cli.js"

def check_login():
    """เช็คสถานะ login"""
    result = subprocess.run(
        ["node", COROS_MCP_NODE, "login-status"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, "Coros-MCP command failed"
    if "no pending login session" in result.stdout:
        return False, "Not logged in"
    return True, "Logged in"

def sync_activities():
    """ดึง activity ล่าสุด 5 อันแล้วเก็บ"""
    result = subprocess.run(
        ["node", COROS_MCP_NODE, "call-tool", "--tool", "querySportRecords",
         "--arguments-json", json.dumps({"sport": "running", "limit": 5})],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, f"Error: {result.stderr}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return False, f"JSON decode error: {e}"
    count = 0
    activities = data.get("activities", [])
    for activity in activities:
        coros_db.store_activity(activity)
        count += 1
    return True, f"Synced {count} activities"

def sync_sleep(days=7):
    """ดึง sleep ล่าสุด 7 วันแล้วเก็บ"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    result = subprocess.run(
        ["node", COROS_MCP_NODE, "call-tool", "--tool", "queryDailyHealthData",
         "--arguments-json", json.dumps({"startDate": start_date, "endDate": end_date})],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return False, f"Error: {result.stderr}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return False, f"JSON decode error: {e}"
    count = 0
    for day in data.get("dailyHealthData", []):
        coros_db.store_daily_health(day)
        if day.get("sleepScore"):
            coros_db.store_sleep(day)
        count += 1
    return True, f"Synced {count} daily health records"

def main():
    timestamp = datetime.now().isoformat()
    print(f"[{timestamp}] Starting COROS daily sync...")

    logged_in, login_msg = check_login()
    if not logged_in:
        print(f"[{timestamp}] SKIP: {login_msg}")
        return 1

    success, msg = sync_activities()
    print(f"[{timestamp}] Activities: {msg}")

    success, msg = sync_sleep()
    print(f"[{timestamp}] Sleep/Health: {msg}")

    print(f"[{timestamp}] Sync complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
