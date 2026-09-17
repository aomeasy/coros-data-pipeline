#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COROS Data Daily Sync
"""
import sys
import os
import subprocess
import json
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import coros_db


def _run(*args, stdin_input=None):
    cmd = ["npx", "coros-mcp"] + list(args)
    result = subprocess.run(
        cmd,
        input=stdin_input,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=True,
    )
    if result.stdout is None:
        result.stdout = ""
    if result.stderr is None:
        result.stderr = ""
    return result


def login(email, password):
    result = _run("login", "--legacy", "--username", email,
                  stdin_input=password + "\n")
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def call_tool(tool_name, args):
    """เรียก COROS-MCP tool และ parse response"""
    raw = _run(
        "call-tool", "--tool", tool_name,
        "--arguments-json", json.dumps(args),
    )
    if raw.returncode != 0:
        return False, f"CLI error: {raw.stderr}", None
    try:
        resp = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return False, f"Invalid JSON: {raw.stdout[:500]}", None
    
    # Debug: show structure
    print(f"  [{tool_name}] response keys: {list(resp.keys())}")
    if resp.get("isError"):
        content = resp.get("content", [])
        print(f"  [{tool_name}] ERROR content: {content}")
        return False, f"Tool error: {content}", None
    
    # Extract actual data from MCP content wrapper
    content = resp.get("content", [])
    if isinstance(content, list) and len(content) > 0:
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                data = json.loads(first["text"])
                return True, "OK", data
            except json.JSONDecodeError:
                return False, f"Content not JSON: {first['text'][:300]}", None
    # If no content wrapper, return resp directly
    return True, "OK", resp


def sync_activities():
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    args = {
        "startDate": start_date,
        "endDate": end_date,
        "sportTypeCodes": [100, 101, 102, 103],
        "minDistanceKm": None,
        "maxDistanceKm": None,
        "minDurationMinutes": None,
        "maxDurationMinutes": None,
        "maxAveragePace": None,
        "locationKeyword": None,
        "limit": 10,
    }
    ok, msg, data = call_tool("querySportRecords", args)
    if not ok:
        return False, msg
    if data is None:
        return False, "No data returned"
    
    records = data.get("records") or data.get("activities") or data.get("sportRecords") or []
    count = 0
    for rec in records:
        coros_db.store_activity(rec)
        count += 1
    return True, f"Synced {count} activities"


def sync_sleep(days=7):
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    args = {"startDate": start_date, "endDate": end_date, "days": days}
    ok, msg, data = call_tool("querySleepData", args)
    if not ok:
        return False, msg
    if data is None:
        return False, "No data returned"
    
    records = data.get("sleepData") or data.get("dailyHealthData") or data.get("sleepRecords") or []
    count = 0
    for rec in records:
        coros_db.store_sleep(rec)
        count += 1
    return True, f"Synced {count} sleep records"


def sync_daily_health(days=7):
    ok, msg, data = call_tool("queryDailyHealthData", {"days": days})
    if not ok:
        return False, msg
    if data is None:
        return False, "No data returned"
    
    records = data.get("dailyHealthData") or data.get("records") or []
    count = 0
    for rec in records:
        coros_db.store_daily_health(rec)
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
    print(f"[{ts}] Sleep: {msg}")

    ok, msg = sync_daily_health()
    print(f"[{ts}] Daily Health: {msg}")

    print(f"[{ts}] Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
