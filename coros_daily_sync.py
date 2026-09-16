#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COROS Data Daily Sync
รันทุกวันเพื่อดึงข้อมูลจาก COROS-MCP แล้วเก็บใน cache database
"""
import sys
import os
import subprocess
import json
import shutil
from datetime import datetime, timedelta

# ใช้ directory ของ script เป็น base
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import coros_db

# หา coros-mcp จาก PATH ก่อน ถ้าไม่เจอค่อยใช้ node ตรงๆ
COROS_MCP_BIN = shutil.which("coros-mcp") or "coros-mcp"

def _run(*args):
    """เรียก coros-mcp command"""
    cmd = [COROS_MCP_BIN] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)

def check_login():
    """เช็คสถานะ login"""
    result = _run("login-status")
    if result.returncode != 0:
        return False, f"COROS-MCP error: {result.stderr.strip()}"
    if "no pending login session" in result.stdout:
        return False, "Not logged in"
    return True, "Logged in"

def sync_activities():
    """ดึง activity ล่าสุด 5 อันแล้วเก็บ"""
    result = _run("call-tool", "--tool", "querySportRecords",
                  "--arguments-json", json.dumps({"sport": "running", "limit": 5}))
    if result.returncode != 0:
        return False, f"Error: {result.stderr}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return False, f"JSON decode error: {e}"
    count = 0
    for activity in data.get("activities", []):
        coros_db.store_activity(activity)
        count += 1
    return True, f"Synced {count} activities"

def sync_sleep(days=7):
    """ดึง sleep ล่าสุด 7 วันแล้วเก็บ"""
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    result = _run("call-tool", "--tool", "queryDailyHealthData",
                  "--arguments-json", json.dumps({"startDate": start_date, "endDate": end_date}))
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
    ts = datetime.now().isoformat()
    print(f"[{ts}] Starting COROS daily sync...")

    # ถ้ามี env COROS_EMAIL + COROS_PASSWORD → login ก่อน
    email = os.environ.get("COROS_EMAIL")
    password = os.environ.get("COROS_PASSWORD")
    if email and password:
        login_result = _run("login", "--email", email, "--password", password)
        print(f"[{ts}] Login: {login_result.stdout.strip()}")
        if login_result.returncode != 0:
            print(f"[{ts}] Login failed: {login_result.stderr.strip()}")
            return 1

    logged_in, login_msg = check_login()
    if not logged_in:
        print(f"[{ts}] SKIP: {login_msg}")
        return 1

    ok, msg = sync_activities()
    print(f"[{ts}] Activities: {msg}")

    ok, msg = sync_sleep()
    print(f"[{ts}] Sleep/Health: {msg}")

    print(f"[{ts}] Sync complete")
    return 0

if __name__ == "__main__":
    sys.exit(main())
