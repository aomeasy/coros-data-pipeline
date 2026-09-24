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
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import coros_db
from logging_utils import get_logger

log = get_logger("coros_daily_sync")

SUBPROCESS_TIMEOUT_S = 60
MAX_RETRIES = 3
RETRY_BACKOFF_S = 5

# ผู้ใช้อยู่ประเทศไทย (ICT = UTC+7) แต่ GitHub Actions runner รันด้วยนาฬิกา UTC
# ถ้าใช้ datetime.fromtimestamp() เฉยๆ (ไม่ระบุ tz) มันจะแปลงตาม timezone ของ
# เครื่องที่รัน (UTC บน runner) ไม่ใช่เวลาไทย ทำให้กิจกรรมที่เกิดช่วงเที่ยงคืน
# ถึงตี 7 ตามเวลาไทย ถูกเก็บวันที่ผิดเพี้ยนไปเป็นวันก่อนหน้า (บั๊กที่เจอจาก
# การตรวจ DB จริง: กิจกรรมที่ COROS ระบุว่า "2026-09-23" ถูกเก็บเป็น
# "2026-09-22T23:21:52" เพราะ startTimestamp ถูกแปลงแบบ UTC)
ICT = timezone(timedelta(hours=7))


def _run(*args, stdin_input=None, timeout=SUBPROCESS_TIMEOUT_S, retries=MAX_RETRIES):
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
    combined = combined.replace('\\n', '\n').replace('\\"', '"')
    if combined.startswith('"') and combined.endswith('"'):
        combined = combined[1:-1]
    return True, "OK", combined


def parse_duration(s):
    if not s:
        return 0
    s = s.strip()
    m = re.match(r'(?:(\d+)h\s*)?(\d+)min', s)
    if m:
        h = int(m.group(1) or 0)
        mi = int(m.group(2))
        return h * 3600 + mi * 60
    parts = s.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return 0


def parse_hm(s):
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
        "sportTypeCodes": None,
        "minDistanceKm": None,
        "maxDistanceKm": None,
        "minDurationMinutes": None,
        "maxDurationMinutes": None,
        "maxAveragePace": None,
        "locationKeyword": None,
        "limit": 50,
    }
    ok, msg, text = call_tool_text("querySportRecords", args)
    if not ok:
        return False, msg
    if not text:
        return False, "Empty response"

    print(f"  Raw preview: {text[:300]}")

    count = 0
    rejected = 0
    entries = re.split(r'\n\d+\.\s+', text)
    for entry in entries[1:]:
        lines = [l.strip() for l in entry.strip().split('\n') if l.strip()]
        if not lines:
            continue

        sport_type = "running"
        date_str = ""
        m = re.match(r'.*—\s*(\d{4}-\d{2}-\d{2})', lines[0])
        if m:
            date_str = m.group(1)  # เก็บแบบมีขีดไว้เหมือนเดิม (ไม่ .replace("-", "") อีกต่อไป)

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

        m = re.search(r'LabelId:\s*(\d+)', full_text)
        if m:
            activity["activityId"] = m.group(1)
        m = re.search(r'SportType:\s*(\d+)', full_text)
        if m:
            activity["sportType"] = int(m.group(1))

        m = re.search(r'Duration:\s*([\d:]+)\s*\|\s*Distance:\s*([\d.]+)\s*km', full_text)
        if m:
            dur_str = m.group(1)
            parts = dur_str.split(":")
            if len(parts) == 2:
                activity["duration"] = int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                activity["duration"] = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            activity["distance"] = float(m.group(2)) * 1000

        m = re.search(r'Average Pace:\s*([\d:]+\s*/km)', full_text)
        if m:
            activity["averagePace"] = parse_pace_to_seconds(m.group(1))

        m = re.search(r'Avg HR:\s*(\d+)\s*bpm', full_text)
        if m:
            activity["averageHeartRate"] = int(m.group(1))

        m = re.search(r'Calories:\s*(\d+)\s*kcal', full_text)
        if m:
            activity["caloriesBurned"] = int(m.group(1))

        m = re.search(r'startTimestamp=(\d+)', full_text)
        if m:
            ts = int(m.group(1))
            # BUGFIX: fromtimestamp() แบบไม่ระบุ tz จะแปลงตาม timezone ของเครื่อง
            # ที่รัน (UTC บน GitHub Actions runner) ไม่ใช่เวลาไทย ทำให้กิจกรรม
            # ช่วงเที่ยงคืน-ตี7 ตามเวลาไทยตกไปอยู่วันก่อนหน้าใน DB
            # แก้โดยระบุ tz=ICT ตรงๆ แล้วค่อยตัด tzinfo ออกก่อนเก็บ (เก็บเป็น
            # naive datetime string ตามเวลาไทย ให้ format เหมือนของเดิม)
            activity["startTime"] = datetime.fromtimestamp(ts, tz=ICT).replace(tzinfo=None).isoformat()

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

    sections = re.split(r'---\s*(\d{4}\d{2}\d{2})\s*---', text)
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

    # BUGFIX: เดิมเทียบ date_str กับ "วันนี้ตามนาฬิกาเครื่อง" (datetime.now())
    # แต่ COROS มักยังไม่มีข้อมูลของ "วันนี้" ครบ (sleep ถูกระบุด้วยวันที่ตื่น
    # และถ้า sync รันตอนเช้ามืดข้อมูลของคืนล่าสุดอาจยังไม่ sync ขึ้น cloud)
    # ทำให้วันล่าสุดที่ "มีอยู่จริง" ในรายงานมักเป็นเมื่อวาน ไม่ใช่วันนี้ —
    # การเทียบกับนาฬิกาเครื่องจึงทำให้ is_latest_day เป็น False เสมอ และ
    # baseline HRV/RestingHR จาก header ไม่เคยถูกใช้เลย
    # แก้โดยหา "วันล่าสุดที่ปรากฏจริงในรายงาน" จาก section ทั้งหมดก่อน แล้วค่อย
    # เทียบกับค่านั้นแทน
    all_section_dates = [sections[i] for i in range(1, len(sections) - 1, 2)]
    latest_section_date = max(all_section_dates) if all_section_dates else None

    i = 1
    while i < len(sections) - 1:
        date_str = sections[i]
        content = sections[i + 1]
        i += 2

        sleep_rec = {"date": date_str}
        daily_rec = {"date": date_str}

        m = re.search(r'Steps:\s*([\d,]+)', content)
        if m:
            daily_rec["steps"] = int(m.group(1).replace(",", ""))

        m = re.search(r'Calories:\s*(\d+)\s*kcal', content)
        if m:
            daily_rec["caloriesBurned"] = int(m.group(1))

        m = re.search(r'Stress:\s*Avg\s*(\d+)', content)
        if m:
            daily_rec["stressLevel"] = int(m.group(1))

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

        # is_latest_day เทียบกับวันล่าสุดที่ "มีอยู่จริงในรายงานนี้" แทนนาฬิกาเครื่อง
        is_latest_day = (latest_section_date is not None and date_str == latest_section_date)

        m = re.search(r'HRV:\s*(\d+)\s*ms', content)
        if m:
            sleep_rec["hrv"] = int(m.group(1))
        elif is_latest_day:
            sleep_rec["hrv"] = baseline_hrv
        else:
            sleep_rec["hrv"] = None

        m = re.search(r'Resting HR:\s*(\d+)\s*bpm', content)
        if m:
            sleep_rec["restingHeartRate"] = int(m.group(1))
        elif is_latest_day:
            sleep_rec["restingHeartRate"] = baseline_resting_hr
        else:
            sleep_rec["restingHeartRate"] = None

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
