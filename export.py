#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export SQLite data to JSON for GitHub Pages, including journals, computed metrics, and narrative"""
import os
import sys
import json
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "coros_cache.db")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "docs")

# Import analysis modules
sys.path.insert(0, SCRIPT_DIR)
import sleep_analysis
import baseline_engine
import strain_engine
import training_analytics
import narrative_engine


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
        "recovery_score": None,
        "sqi": None,
    }


def compute_full_analysis(sleep_for_analysis, daily_records, activities, journals, strain_series):
    """Compute full analysis including narrative for static export"""
    if not sleep_for_analysis:
        return {}

    latest = sleep_for_analysis[-1] if sleep_for_analysis else {}
    latest_daily = daily_records[-1] if daily_records else {}

    # Baselines
    baseline_deep = baseline_engine.compute_baseline_v2(
        sleep_for_analysis, ["deep_sleep_pct"], metric_name="deep")
    baseline_rem = baseline_engine.compute_baseline_v2(
        sleep_for_analysis, ["rem_sleep_pct"], metric_name="rem")
    baseline_hrv = baseline_engine.compute_baseline_v2(
        sleep_for_analysis, ["hrv"], metric_name="hrv_ln_rmssd", log_transform=True)
    baseline_rhr = baseline_engine.compute_baseline_v2(
        sleep_for_analysis, ["resting_hr"], metric_name="resting_hr")
    baseline_resp_rate = baseline_engine.compute_baseline_v2(
        daily_records, ["respiratory_rate"], metric_name="resp_rate")

    # Recovery Score
    training_load_prev_day = strain_series[0].get("trimp", 0) if strain_series else 0
    strain_3day = [s.get("trimp", 0) for s in strain_series[-3:] if s.get("trimp")] if strain_series else []

    sleep_need = sleep_analysis.calculate_sleep_need(
        training_load=training_load_prev_day or 0,
        strain_3day=strain_3day if len(strain_3day) >= 2 else None,
    )
    sp_pct = sleep_analysis.sleep_performance(
        actual_min=latest.get("duration_min", 0) or 0,
        need_min=sleep_need["sleep_need_min"],
    )

    resp_rate_z = sleep_analysis.z_score(
        latest_daily.get("respiratory_rate"), baseline_resp_rate
    ) or 0

    skin_temp_analysis = sleep_analysis.analyze_skin_temp(daily_records, window=7)
    skin_temp_flag = skin_temp_analysis.get("flag", "normal")

    spo2_analysis = sleep_analysis.analyze_spo2({
        "spo2_avg": latest_daily.get("spo2_avg"),
        "spo2_min": latest_daily.get("spo2_min"),
    })
    spo2_flag = sleep_analysis.flag_spo2_risk(spo2_analysis)

    hrv_today_ln = baseline_engine.ln_rmssd(latest.get("hrv"))

    # Respiratory rate trend
    recent_rr = [d.get("respiratory_rate") for d in daily_records[-7:] if d.get("respiratory_rate")]
    resp_rate_trend = 0.0
    if len(recent_rr) >= 5:
        resp_rate_trend = round((recent_rr[-1] - recent_rr[0]) / len(recent_rr), 3)

    rec_score = sleep_analysis.recovery_score(
        hrv_today=hrv_today_ln,
        hrv_baseline=baseline_hrv,
        rhr_today=latest.get("resting_hr"),
        rhr_baseline=baseline_rhr,
        sleep_performance_pct=sp_pct,
        sleep_efficiency_pct=latest.get("duration_min", 0) / max(latest.get("time_in_bed_min", 1), 1) * 100 if latest else 80,
        spo2_flag=spo2_flag,
        skin_temp_flag=skin_temp_flag,
        resp_rate_z=resp_rate_z,
        training_load=training_load_prev_day or 0,
        resp_rate_trend=resp_rate_trend,
    )

    # SQI
    sqi = sleep_analysis.calculate_sqi(sleep_for_analysis)

    # Anomalies
    baselines_dict = {
        "deep": baseline_deep,
        "rem": baseline_rem,
        "hrv_ms": baseline_hrv,
        "resting_hr": baseline_rhr,
    }
    anomalies = sleep_analysis.detect_anomalies(latest, baselines_dict) if sleep_for_analysis else []

    # Sleep Coach
    coach_recommendations = sleep_analysis.generate_sleep_coach_recommendations(
        sleep_for_analysis, journals=journals, anomalies=anomalies
    )

    # Bedtime consistency
    consistency = sleep_analysis.bedtime_consistency(sleep_for_analysis)

    # Training Analytics
    rec_val = rec_score.get("recovery_score", 50)
    if strain_series:
        training_analytics_result = training_analytics.compute_training_analytics(
            activities, strain_series, sleep_for_analysis,
            recovery_score=rec_val, ctl_baseline=150
        )
    else:
        training_analytics_result = {"fitness": {}, "economy": {}, "readiness": {}, "strain_performance": {}}

    # Illness & Overtraining
    illness_baselines = {
        "resting_hr": baseline_rhr,
        "hrv_ms": baseline_hrv,
        "respiratory_rate": baseline_resp_rate,
    }
    illness_risk = sleep_analysis.compute_illness_risk(latest, illness_baselines)
    recovery_scores_list = [{"recovery_score": rec_val}]
    overtraining = sleep_analysis.detect_overtraining(strain_series, recovery_scores_list, sleep_for_analysis)

    # Journal correlations
    journal_correlations = []
    if journals and len(journals) >= 3:
        try:
            journal_correlations = sleep_analysis.rank_journal_impacts(
                sleep_for_analysis, journals, sleep_analysis.sleep_efficiency
            )
        except Exception:
            pass

    # Narrative
    narrative = narrative_engine.generate_daily_narrative(
        recovery=rec_score,
        sleep=latest,
        strain_series=strain_series,
        training_analytics=training_analytics_result,
        illness=illness_risk,
        overtraining=overtraining,
        consistency=consistency if consistency else 0,
    )

    weekly_narrative = narrative_engine.generate_weekly_digest(
        sleep_records=sleep_for_analysis,
        strain_series=strain_series,
        training_analytics=training_analytics_result,
        journal_correlations=journal_correlations,
    )

    return {
        "recovery_score": rec_score,
        "sqi": sqi,
        "anomalies": anomalies,
        "coach_recommendations": coach_recommendations,
        "bedtime_consistency": consistency,
        "illness_risk": illness_risk,
        "overtraining": overtraining,
        "training_analytics": training_analytics_result,
        "narrative": narrative,
        "weekly_narrative": weekly_narrative,
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

    # Get strain series
    strain_records = [dict(r) for r in conn.execute(
        "SELECT * FROM daily_strain ORDER BY date DESC LIMIT 30"
    )]
    conn.close()

    # Reverse to chronological order for analysis
    sleep_chronological = list(reversed(sleep))
    daily_chronological = list(reversed(daily))
    strain_chronological = list(reversed(strain_records))

    # Normalize sleep records for analysis
    sleep_for_analysis = []
    for s in sleep_chronological:
        rec = {
            "date": fmt_date(s.get("date", "")),
            "duration_min": s.get("duration_min", 0),
            "total_sleep_min": s.get("duration_min", 0),
            "time_in_bed_min": s.get("duration_min", 0) + int((s.get("awake_min", 0) or 0) * 1.5),
            "deep_sleep_pct": s.get("deep_sleep_pct"),
            "light_sleep_pct": s.get("light_sleep_pct"),
            "rem_sleep_pct": s.get("rem_sleep_pct"),
            "awake_min": s.get("awake_min", 0),
            "hrv": s.get("hrv"),
            "resting_hr": s.get("resting_hr"),
            "sleep_score": s.get("sleep_score"),
        }
        sleep_for_analysis.append(rec)

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

    # Compute full analysis for narrative
    analysis = compute_full_analysis(
        sleep_for_analysis, daily_chronological, acts_out, journals_out, strain_chronological
    )

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

    # Merge analysis into data (for GitHub Pages static consumption)
    data.update(analysis)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)
    print(
        f"Exported {len(acts_out)} activities, {len(sleep_out)} sleep, "
        f"{len(daily_out)} daily, {len(journals_out)} journal records"
    )
    if analysis.get("narrative"):
        print("Narrative generated OK")


if __name__ == "__main__":
    export()
