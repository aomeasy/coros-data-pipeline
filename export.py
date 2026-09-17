#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export SQLite data to JSON for GitHub Pages, including journals and computed metrics"""
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


def compute_metrics(sleep_records, daily_records):
    """Compute aggregated metrics for export"""
    if not sleep_records:
        return {}

    total_eff = 0
    count = 0
    for s in sleep_records:
        duration = s.get("duration_min", 0) or 0
        awake = s.get("awake_min", 0) or 0
        time_in_bed = duration + int(awake * 1.5)
        if time_in_bed > 0:
            total_eff += min((duration / time_in_bed) * 100, 100.0)
            count += 1

    avg_efficiency = round(total_eff / count, 1) if count > 0 else None

    deep_pcts = [s.get("deep_sleep_pct") for s in sleep_records if s.get("deep_sleep_pct") is not None]
    avg_deep = round(sum(deep_pcts) / len(deep_pcts), 1) if deep_pcts else None

    rem_pcts = [s.get("rem_sleep_pct") for s in sleep_records if s.get("rem_sleep_pct") is not None]
    avg_rem = round(sum(rem_pcts) / len(rem_pcts), 1) if rem_pcts else None

    durations = [s.get("duration_min") for s in sleep_records if s.get("duration_min")]
    avg_duration = round(sum(durations) / len(durations), 0) if durations else None

    # Steps total
    steps = [d.get("steps", 0) or 0 for d in daily_records]
    total_steps = sum(steps)

    return {
        "avg_sleep_efficiency": avg_efficiency,
        "avg_deep_pct": avg_deep,
        "avg_rem_pct": avg_rem,
        "avg_duration_min": avg_duration,
        "total_steps": total_steps,
        "recovery_score": None,  # Could be computed from latest data
        "sqi": None,
    }


def export():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    activities = [dict(r) for r in conn.execute(
        "SELECT * FROM activities ORDER BY start_time DESC LIMIT 50"
    )]
    sleep = [dict(r) for r in conn.execute(
        "SELECT * FROM sleep_data ORDER BY date DESC LIMIT 30"
    )]
    daily = [dict(r) for r in conn.execute(
        "SELECT * FROM daily_health ORDER BY date DESC LIMIT 30"
    )]
    journals = [dict(r) for r in conn.execute(
        "SELECT * FROM journal_entries ORDER BY date DESC LIMIT 30"
    )]
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
            "calories_burned": a.get("calories"),
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

    # Transform journals
    journals_out = []
    for j in journals:
        journals_out.append({
            "date": j.get("date"),
            "alcohol_units": j.get("alcohol_units", 0),
            "caffeine_after_14": bool(j.get("caffeine_after_14")),
            "late_meal": bool(j.get("late_meal")),
            "screen_before_bed_min": j.get("screen_before_bed_min", 0),
            "stress_level": j.get("stress_level", 0),
            "exercise_evening": bool(j.get("exercise_evening")),
            "room_temp_hot": bool(j.get("room_temp_hot")),
            "notes": j.get("notes", ""),
        })

    # Compute aggregated metrics
    metrics = compute_metrics(sleep_out, daily_out)

    data = {
        "activities": acts_out,
        "sleep": sleep_out,
        "daily": daily_out,
        "journals": journals_out,
        "computed_metrics": metrics,
        "stats": {
            "activities_count": len(acts_out),
            "sleep_count": len(sleep_out),
            "daily_count": len(daily_out),
            "journal_count": len(journals_out),
            "last_updated": __import__("datetime").datetime.now().isoformat(),
        },
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    print(
        f"Exported {len(acts_out)} activities, {len(sleep_out)} sleep, "
        f"{len(daily_out)} daily, {len(journals_out)} journal records"
    )


if __name__ == "__main__":
    export()
