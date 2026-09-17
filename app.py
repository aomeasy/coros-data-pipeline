#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""COROS Data Pipeline — Flask Web UI"""
import os
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, send_file

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "coros_cache.db")
DOCS_DIR = os.path.join(SCRIPT_DIR, "docs")

# import DB layer
sys.path.insert(0, SCRIPT_DIR)
import coros_db
import sleep_analysis
import breath_analysis

app = Flask(__name__, static_folder=DOCS_DIR, static_url_path="")


def get_db():
    conn = coros_db.get_conn()
    conn.row_factory = sqlite3.Row
    return conn


@app.route("/")
def index():
    return send_file(os.path.join(DOCS_DIR, "index.html"))


@app.route("/journal.html")
def journal_page():
    return send_file(os.path.join(DOCS_DIR, "journal.html"))


@app.route("/api/data")
def api_data():
    """Serve docs/data.json"""
    data_path = os.path.join(DOCS_DIR, "data.json")
    if os.path.exists(data_path):
        return send_file(data_path)
    return jsonify({"error": "data.json not found"}), 404


@app.route("/api/analysis")
def api_analysis():
    """Run sleep_analysis + breath_analysis, return JSON"""
    conn = get_db()
    sleep_records = [dict(r) for r in conn.execute(
        "SELECT * FROM sleep_data ORDER BY date ASC"
    ).fetchall()]
    daily_records = [dict(r) for r in conn.execute(
        "SELECT * FROM daily_health ORDER BY date ASC"
    ).fetchall()]
    activities = [dict(r) for r in conn.execute(
        "SELECT * FROM activities ORDER BY start_time DESC LIMIT 20"
    ).fetchall()]
    journals = [dict(r) for r in conn.execute(
        "SELECT * FROM journal_entries ORDER BY date ASC"
    ).fetchall()]
    conn.close()

    # Normalize sleep records for analysis
    sleep_for_analysis = []
    for s in sleep_records:
        rec = {
            "date": s.get("date", ""),
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

    # Sleep analysis
    sleep_metrics = []
    for rec in sleep_for_analysis:
        eff = sleep_analysis.sleep_efficiency(rec)
        stages = sleep_analysis.stage_percentages(rec)
        sleep_metrics.append({
            "date": rec["date"],
            "efficiency": eff,
            "duration_min": rec["duration_min"],
            "deep_pct": rec.get("deep_sleep_pct"),
            "light_pct": rec.get("light_sleep_pct"),
            "rem_pct": rec.get("rem_sleep_pct"),
            "awake_min": rec.get("awake_min"),
            "hrv": rec.get("hrv"),
            "resting_hr": rec.get("resting_hr"),
            "stages": stages,
        })

    # Baselines
    baseline_deep = sleep_analysis.compute_baseline(sleep_for_analysis, ["deep_sleep_pct"])
    baseline_rem = sleep_analysis.compute_baseline(sleep_for_analysis, ["rem_sleep_pct"])
    baseline_hrv = sleep_analysis.compute_baseline(sleep_for_analysis, ["hrv"])
    baseline_rhr = sleep_analysis.compute_baseline(sleep_for_analysis, ["resting_hr"])

    # Recovery score (latest)
    latest = sleep_for_analysis[-1] if sleep_for_analysis else {}
    rec_score = sleep_analysis.recovery_score(
        hrv_today=latest.get("hrv"),
        hrv_baseline=baseline_hrv,
        rhr_today=latest.get("resting_hr"),
        rhr_baseline=baseline_rhr,
        sleep_performance_pct=85,
        sleep_efficiency_pct=latest.get("duration_min", 0) / max(latest.get("time_in_bed_min", 1), 1) * 100 if latest else 80,
    )

    # SQI
    sqi = sleep_analysis.calculate_sqi(sleep_for_analysis)

    # Weekly report
    weekly_report = sleep_analysis.generate_weekly_report(sleep_for_analysis, journals)

    # Journal correlation
    journal_correlations = []
    if journals and len(journals) >= 3:
        try:
            journal_correlations = sleep_analysis.rank_journal_impacts(
                sleep_for_analysis, journals, sleep_analysis.sleep_efficiency
            )
        except Exception:
            pass

    # Breath analysis (from daily health)
    breath_metrics = []
    for d in daily_records:
        rr = d.get("respiratory_rate")
        spo2 = d.get("spo2_avg")
        hrv = d.get("avg_hr")
        breath_metrics.append({
            "date": d.get("date", ""),
            "respiratory_rate": breath_analysis.analyze_respiratory_rate(rr),
            "spo2": breath_analysis.analyze_spo2(spo2, d.get("spo2_min")),
        })

    # Breathing efficiency (latest)
    latest_daily = daily_records[-1] if daily_records else {}
    breath_eff = breath_analysis.breathing_efficiency_score(
        rr=latest_daily.get("respiratory_rate"),
        spo2=latest_daily.get("spo2_avg"),
        hrv=latest_daily.get("avg_hr"),
        hrv_baseline=baseline_hrv.get("mean") if baseline_hrv.get("mean") else None,
    )

    # Anomaly detection
    baselines_dict = {
        "deep": baseline_deep,
        "rem": baseline_rem,
        "hrv_ms": baseline_hrv,
        "resting_hr": baseline_rhr,
    }
    anomalies = []
    if sleep_for_analysis:
        anomalies = sleep_analysis.detect_anomalies(sleep_for_analysis[-1], baselines_dict)

    # Bedtime consistency
    consistency = sleep_analysis.bedtime_consistency(sleep_for_analysis)

    # Rolling averages
    eff_trend = sleep_analysis.rolling_average(
        sleep_for_analysis, sleep_analysis.sleep_efficiency, window=7
    )

    return jsonify({
        "sleep_metrics": sleep_metrics,
        "baselines": {
            "deep": baseline_deep,
            "rem": baseline_rem,
            "hrv": baseline_hrv,
            "resting_hr": baseline_rhr,
        },
        "recovery_score": rec_score,
        "sqi": sqi,
        "weekly_report": weekly_report,
        "journal_correlations": journal_correlations,
        "breath_metrics": breath_metrics,
        "breathing_efficiency": breath_eff,
        "anomalies": anomalies,
        "bedtime_consistency": consistency,
        "efficiency_trend": eff_trend,
        "activities": activities,
        "daily_health": daily_records,
    })


@app.route("/api/journal", methods=["GET"])
def api_journal_get():
    """Get all journal entries"""
    journals = coros_db.get_all_journals()
    return jsonify({"journals": journals})


@app.route("/api/journal", methods=["POST"])
def api_journal_post():
    """Save journal entry"""
    data = request.get_json(force=True)
    if not data.get("data"):
        return jsonify({"error": "missing 'data' field"}), 400
    
    entry = data["data"]
    if not entry.get("date"):
        entry["date"] = datetime.now().strftime("%Y-%m-%d")
    
    # Convert boolean fields to int
    bool_fields = ["caffeine_after_14", "late_meal", "exercise_evening", "room_temp_hot"]
    for f in bool_fields:
        if f in entry:
            entry[f] = 1 if entry[f] else 0
    
    coros_db.store_journal(entry)
    return jsonify({"ok": True, "date": entry["date"]})


@app.route("/api/sync", methods=["POST"])
def api_sync():
    """Trigger coros_daily_sync"""
    env = os.environ.copy()
    env["COROS_EMAIL"] = os.environ.get("COROS_EMAIL", "")
    env["COROS_PASSWORD"] = os.environ.get("COROS_PASSWORD", "")
    result = subprocess.run(
        [sys.executable, os.path.join(SCRIPT_DIR, "coros_daily_sync.py")],
        capture_output=True, text=True, env=env,
    )
    return jsonify({
        "ok": result.returncode == 0,
        "stdout": result.stdout[-2000:] if result.stdout else "",
        "stderr": result.stderr[-1000:] if result.stderr else "",
    })


@app.route("/api/stats")
def api_stats():
    """DB stats"""
    return jsonify(coros_db.get_db_stats())


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"COROS Health Dashboard → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
