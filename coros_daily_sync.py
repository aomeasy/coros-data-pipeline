#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COROS Data Daily Sync
รันทุกวันผ่าน GitHub Actions — ดึงข้อมูลจาก COROS-MCP แล้วเก็บใน SQLite
"""
import sys
import os
import subprocess
import json
from datetime import datetime, timedelta

# ใช้ directory ของ script เป็น base
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import coros_db

COROS_MCP_BIN = "npx"


def _run(*args, stdin_input=None):
    """เรียก coros-mcp command"""
    cmd = ["npx", "coros-mcp"] + list(args)
    return subprocess.run(
        cmd,
        input=stdin_input,
        capture_output=True,
        text=True,
    )


def login(email, password):
    result = _run(
        "login", "--legacy", "--username", email,
        stdin_input=password + "\n",
    )
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def check_login():
    result = _run("login-status")
    if result.returncode != 0:
        return False
    return "logged in" in result.stdout.lower() or "no pending login" not in result.stdout


def sync_activities():
    result = _run(
        "call-tool", "--tool", "querySportRecords",
        "--arguments-json", json.dumps({"sport": "running", "limit": 5}),
    )
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
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    result = _run(
        "call-tool", "--tool", "queryDailyHealthData",
        "--arguments-json", json.dumps({"startDate": start_date, "endDate": end_date}),
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
    ts = datetime.now().isoformat()
    print(f"[{ts}] Starting COROS daily sync...")

    email = os.environ.get("COROS_EMAIL")
    password = os.environ.get("COROS_PASSWORD")
    if not email or not password:
        print(f"[{ts}] SKIP: COROS_EMAIL and COROS_PASSWORD required")
        return 1

    print(f"[{ts}] Logging in as {email}...")
    ok, stdout_msg, stderr_msg = login(email, password)
    if not ok:
        print(f"[{ts}] Login failed: {stderr_msg or stdout_msg}")
        return 1
    print(f"[{ts}] Login: {stdout_msg}")

    ok, msg = sync_activities()
    print(f"[{ts}] Activities: {msg}")

    ok, msg = sync_sleep()
    print(f"[{ts}] Sleep/Health: {msg}")

    print(f"[{ts}] Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
