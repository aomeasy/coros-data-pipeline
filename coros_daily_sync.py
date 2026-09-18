#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COROS Data Daily Sync — parse text responses into SQLite
"""
import sys
import os
import subprocess
import json
import re
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import coros_db
from logging_utils import get_logger

log = get_logger("coros_daily_sync")

# Phase 0 hardening: retry/timeout config for the npx coros-mcp subprocess.
# The CLI shells out to COROS's servers — transient network hiccups or a
# slow cold-start of `npx` (which may need to download the package) should
# not fail an entire morning's sync on the first hiccup.
SUBPROCESS_TIMEOUT_S = 60
MAX_RETRIES = 3
RETRY_BACKOFF_S = 5  # multiplied by attempt number (5s, 10s, 15s...)


def _run(*args, stdin_input=None, timeout=SUBPROCESS_TIMEOUT_S, retries=MAX_RETRIES):
    """Run `npx coros-mcp <args>` with a timeout and retry/backoff.

    Returns an object with .returncode/.stdout/.stderr, same shape as
    subprocess.run's result, even on timeout (returncode=-1) so callers
    don't need to special-case exceptions.
    """
    cmd = ["npx", "coros-mcp"] + list(args)
    last_result = None
    for attempt in range(1, retries + 1):
        try:
            result = subprocess.run(
                cmd,
                input=stdin_input,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=True,
                timeout=timeout,
            )
            if result.stdout is None:
                result.stdout = ""
            if result.stderr is None:
                result.stderr = ""
            if result.returncode == 0:
                if attempt > 1:
                    log.info("subprocess_retry_succeeded", cmd=args[0] if args else "?", attempt=attempt)
                return result
            last_result = result
            log.warning(
                "subprocess_nonzero_exit",
                cmd=args[0] if args else "?",
                attempt=attempt,
                returncode=result.returncode,
                stderr=result.stderr[:300],
            )
        except subprocess.TimeoutExpired:
            log.warning("subprocess_timeout", cmd=args[0] if args else "?",
                        attempt=attempt, timeout_s=timeout)
            last_result = subprocess.CompletedProcess(cmd, -1, "", f"Timed out after {timeout}s")
        except OSError as e:
            log.warning("subprocess_os_error", cmd=args[0] if args else "?",
                        attempt=attempt, error=str(e))
            last_result = subprocess.CompletedProcess(cmd, -1, "", str(e))

        if attempt < retries:
            sleep_s = RETRY_BACKOFF_S * attempt
            log.info("subprocess_retry_backoff", seconds=sleep_s, next_attempt=attempt + 1)
            time.sleep(sleep_s)

    log.error("subprocess_failed_all_retries", cmd=args[0] if args else "?", retries=retries)
    return last_result


def login(email, password):
    result = _run("login", "--legacy", "--username", email,
                  stdin_input=password + "\n")
    return result.returncode == 0, result.stdout.strip(), result.stderr.strip()


def call_tool_text(tool_name, args):
    """เรียก tool และคืน text response"""
    raw = _run("call-tool", "--tool", tool_name,
               "--arguments-json", json.dumps(args))
    if raw.returncode != 0:
        return False, f"CLI error: {raw.stderr}", None
    try:
        resp = json.loads(raw.stdout)
    except json.JSONDecodeError:
        return False, f"Invalid JSON: {raw.stdout[:500]}", None
    
    if resp.get("isError"):
        content = resp.get("content", [])
        texts = [c.get("text","") for c in content if isinstance(c, dict)]
        return False, f"Tool error: {' '.join(texts)[:500]}", None
    
    content = resp.get("content", [])
    texts = [c.get("text","") for c in content if isinstance(c, dict)]
    combined = "\n".join(texts)
    # Unescape
    combined = combined.replace('\\n', '\n').replace('\\"', '"')
    if combined.startswith('"') and combined.endswith('"'):
        combined = combined[1:-1]
    return True, "OK", combined


def parse_duration(s):
    """แปลง '29:27' หรือ '1h 10min' เป็นวินาที"""
    if not s:
        return 0
    s = s.strip()
    # 1h 10min format
    m = re.match(r'(?:(\d+)h\s*)?(\d+)min', s)
    if m:
        h = int(m.group(1) or 0)
        mi = int(m.group(2))
        return h * 3600 + mi * 60
    # 29:27 format
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def parse_hm(s):
    """แปลง '1h 0min' เป็นนาที"""
    if not s:
        return 0
    s = s.strip()
    m = re.match(r'(?:(\d+)h\s*)?(\d+)min', s)
    if m:
        h = int(m.group(1) or 0)
        mi = int(m.group(2))
        return h * 60 + mi
    return 0


def parse_pace_to_seconds(s):
    """แปลง '8:18 /km' เป็นวินาที"""
    if not s:
        return None
    m = re.search(r'(\d+):(\d+)', s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


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
        "limit": 20,
    }
    ok, msg, text = call_tool_text("querySportRecords", args)
    if not ok:
        return False, msg
    if not text:
        return False, "Empty response"
    
    print(f"  Raw preview: {text[:300]}")
    
    # Parse sport records
    count = 0
    rejected = 0
    # Split by numbered entries
    entries = re.split(r'\n\d+\.\s+', text)
    for entry in entries[1:]:  # skip header
        lines = [l.strip() for l in entry.strip().split('\n') if l.strip()]
        if not lines:
            continue
        
        # First line: "Outdoor Run — 2026-09-16"
        sport_type = "running"
        date_str = ""
        m = re.match(r'.*—\s*(\d{4}-\d{2}-\d{2})', lines[0])
        if m:
            date_str = m.group(1).replace("-", "")
        
        activity = {
            "activityId": "",
            "sportType": 100,
            "startTime": date_str,
            "distance": 0,
            "duration": 0,
            "averagePace": None,
            "averageHeartRate": None,
            "maxHeartRate": None,
            "caloriesBurned": 0,
            "score": None,
            "ascent": 0,
            "descent": 0,
            "averageCadence": None,
        }
        
        full_text = " ".join(lines)
        
        # LabelId → activity_id (required)
        m = re.search(r'LabelId:\s*(\d+)', full_text)
        if m:
            activity["activityId"] = m.group(1)
        m = re.search(r'SportType:\s*(\d+)', full_text)
        if m:
            activity["sportType"] = int(m.group(1))
        
        # Duration and Distance — "Duration: 29:27 | Distance: 3.55 km"
        m = re.search(r'Duration:\s*([\d:]+)\s*\|\s*Distance:\s*([\d.]+)\s*km', full_text)
        if m:
            dur_str = m.group(1)
            parts = dur_str.split(":")
            if len(parts) == 2:
                activity["duration"] = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                activity["duration"] = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            activity["distance"] = float(m.group(2)) * 1000
        
        # Pace
        m = re.search(r'Average Pace:\s*([\d:]+\s*/km)', full_text)
        if m:
            activity["averagePace"] = parse_pace_to_seconds(m.group(1))
        
        # HR
        m = re.search(r'Avg HR:\s*(\d+)\s*bpm', full_text)
        if m:
            activity["averageHeartRate"] = int(m.group(1))
        
        # Calories
        m = re.search(r'Calories:\s*(\d+)\s*kcal', full_text)
        if m:
            activity["caloriesBurned"] = int(m.group(1))
        
        # Timestamps
        m = re.search(r'startTimestamp=(\d+)', full_text)
        if m:
            ts = int(m.group(1))
            activity["startTime"] = datetime.fromtimestamp(ts).isoformat()
        
        if coros_db.store_activity(activity):
            count += 1
        else:
            rejected += 1

    if rejected:
        log.warning("activities_rejected", count=rejected)
    return True, f"Synced {count} activities ({rejected} rejected by validation)"


def sync_sleep_and_health(days=7):
    ok, msg, text = call_tool_text("queryDailyHealthData", {"days": days})
    if not ok:
        return False, msg
    if not text:
        return False, "Empty response"
    
    print(f"  Raw preview: {text[:300]}")
    
    sleep_count = 0
    daily_count = 0
    sleep_rejected = 0
    daily_rejected = 0

    # Split by date sections
    sections = re.split(r'---\s*(\d{4}\d{2}\d{2})\s*---', text)
    # sections[0] is the report header — NOT a date section, but it carries
    # report-wide baseline values (e.g. "Resting HR: 50 bpm | HRV Baseline: 42 ms")
    # that used to be silently discarded. Parse them here so every day in this
    # sync at least gets a value instead of permanent NULL.
    header = sections[0] if sections else ""

    baseline_resting_hr = None
    m = re.search(r'Resting HR:\s*(\d+)\s*bpm', header)
    if m:
        baseline_resting_hr = int(m.group(1))

    baseline_hrv = None
    m = re.search(r'HRV Baseline:\s*(\d+)\s*ms', header)
    if m:
        baseline_hrv = int(m.group(1))

    if baseline_resting_hr is not None or baseline_hrv is not None:
        print(f"  Header baseline → Resting HR: {baseline_resting_hr} bpm, HRV: {baseline_hrv} ms")

    # sections[0] is header, then alternating date/date_content
    i = 1
    while i < len(sections) - 1:
        date_str = sections[i]
        content = sections[i + 1]
        i += 2
        
        sleep_rec = {"date": date_str}
        daily_rec = {"date": date_str}
        
        # Steps
        m = re.search(r'Steps:\s*([\d,]+)', content)
        if m:
            daily_rec["steps"] = int(m.group(1).replace(",", ""))
        
        # Calories
        m = re.search(r'Calories:\s*(\d+)\s*kcal', content)
        if m:
            daily_rec["caloriesBurned"] = int(m.group(1))
        
        # Stress
        m = re.search(r'Stress:\s*Avg\s*(\d+)', content)
        if m:
            daily_rec["stressLevel"] = int(m.group(1))
        
        # Sleep data
        if "Sleep Summary:" in content:
            sleep_section = content.split("Sleep Summary:")[1]
            
            m = re.search(r'Total:\s*([\d+h\s]+\d+min)', sleep_section)
            if m:
                sleep_rec["duration"] = parse_hm(m.group(1))
            
            m = re.search(r'Deep:\s*([\d+h\s]+\d+min)', sleep_section)
            if m:
                deep_min = parse_hm(m.group(1))
                if sleep_rec.get("duration", 0) > 0:
                    sleep_rec["deepSleepRatio"] = round(deep_min / sleep_rec["duration"] * 100, 1)
            
            m = re.search(r'Light:\s*([\d+h\s]+\d+min)', sleep_section)
            if m:
                light_min = parse_hm(m.group(1))
                if sleep_rec.get("duration", 0) > 0:
                    sleep_rec["lightSleepRatio"] = round(light_min / sleep_rec["duration"] * 100, 1)
            
            m = re.search(r'REM:\s*([\d+h\s]+\d+min)', sleep_section)
            if m:
                rem_min = parse_hm(m.group(1))
                if sleep_rec.get("duration", 0) > 0:
                    sleep_rec["remSleepRatio"] = round(rem_min / sleep_rec["duration"] * 100, 1)
            
            m = re.search(r'Awake:\s*(\d+)\s*min', sleep_section)
            if m:
                sleep_rec["awakeDuration"] = int(m.group(1))

        # HRV / Resting HR / Sleep Score — try per-day value first (in case
        # COROS ever includes it inside a day's block), then fall back to the
        # report-wide baseline parsed from the header above. Without this,
        # these three fields were ALWAYS None/NULL regardless of how many
        # times the sync ran.
        m = re.search(r'HRV:\s*(\d+)\s*ms', content)
        sleep_rec["hrv"] = int(m.group(1)) if m else baseline_hrv

        m = re.search(r'Resting HR:\s*(\d+)\s*bpm', content)
        sleep_rec["restingHeartRate"] = int(m.group(1)) if m else baseline_resting_hr

        m = re.search(r'Sleep Score:\s*(\d+)', content)
        if m:
            sleep_rec["sleepScore"] = int(m.group(1))

        if "Sleep Summary:" in content:
            if coros_db.store_sleep(sleep_rec):
                sleep_count += 1
            else:
                sleep_rejected += 1

        if coros_db.store_daily_health(daily_rec):
            daily_count += 1
        else:
            daily_rejected += 1

    if sleep_rejected or daily_rejected:
        log.warning("health_records_rejected", sleep_rejected=sleep_rejected, daily_rejected=daily_rejected)

    return True, (
        f"Synced {sleep_count} sleep ({sleep_rejected} rejected) + "
        f"{daily_count} daily health ({daily_rejected} rejected) records"
    )


def main():
    ts = datetime.now().isoformat()
    log.info("sync_started", ts=ts)

    email = os.environ.get("COROS_EMAIL")
    password = os.environ.get("COROS_PASSWORD")
    if not email or not password:
        log.critical("sync_skipped_missing_credentials")
        return 1

    log.info("login_attempt", email=email)
    ok, out, err = login(email, password)
    if not ok:
        log.critical("login_failed", error=err or out)
        return 1
    log.info("login_ok", detail=out[:200])

    # Phase 0: each sync step is isolated so a bug/exception in one (e.g.
    # a new COROS response format breaking the activities regex) doesn't
    # take down the other. Both are attempted; overall exit code reflects
    # whether *any* step failed so CI/Actions still surfaces a red run.
    had_failure = False

    try:
        ok, msg = sync_activities()
        (log.info if ok else log.error)("activities_sync_done", ok=ok, message=msg)
        had_failure = had_failure or not ok
    except Exception as e:
        log.error("activities_sync_exception", error=str(e))
        had_failure = True

    try:
        ok, msg = sync_sleep_and_health()
        (log.info if ok else log.error)("sleep_health_sync_done", ok=ok, message=msg)
        had_failure = had_failure or not ok
    except Exception as e:
        log.error("sleep_health_sync_exception", error=str(e))
        had_failure = True

    if had_failure:
        log.warning("sync_completed_with_errors")
        return 2

    log.info("sync_completed_ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
