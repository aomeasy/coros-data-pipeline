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
import strain_engine  # Phase 2.2

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


def _compute_and_store_strain(activities, days=28):
    """
    Phase 2.2 — เรียก strain_engine กับ activities ที่มี แล้วเก็บผลลง daily_strain

    NOTE: สมมติว่า strain_engine.py มีฟังก์ชัน compute_daily_strain(activities) -> list[dict]
    ที่ return รายการต่อวัน [{"date": "YYYY-MM-DD", "day_strain": float,
                              "trimp": float, "acwr": float, ...}, ...]
    ตาม integration point ที่ออกแบบไว้ — ถ้าฟังก์ชัน/พารามิเตอร์จริงในไฟล์คุณชื่ออื่น
    แก้แค่บรรทัด strain_engine.compute_daily_strain(...) จุดเดียวด้านล่างนี้พอ
    """
    try:
        strain_results = strain_engine.compute_daily_strain(activities)
    except AttributeError:
        # เผื่อชื่อฟังก์ชันจริงต่างไป — ป้องกัน endpoint ทั้งตัวพังเพราะจุดเดียว
        return []

    for s in strain_results:
        if s.get("date"):
            coros_db.store_daily_strain(s)

    return coros_db.get_recent_daily_strain(days=days)


@app.route("/api/analysis")
def api_analysis():
    """Run sleep_analysis + breath_analysis + strain_engine, return JSON"""
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
    baseline_resp_rate = sleep_analysis.compute_baseline(daily_records, ["respiratory_rate"])

    # ---------------------------------------------------------------
    # Phase 2.2 — Strain Engine: คำนวณจาก activities แล้วเก็บ + ดึงกลับ
    # ---------------------------------------------------------------
    strain_series = _compute_and_store_strain(activities, days=28)
    latest_strain = strain_series[0] if strain_series else None  # ORDER BY date DESC

    # ---------------------------------------------------------------
    # Recovery Score — แก้ให้ sleep_performance_pct เป็นค่าจริง (ของเดิม hardcode
    # ไว้ที่ 85 เสมอ) + ผูก training_load จาก strain (โหลดเมื่อวานกระทบ need วันนี้)
    # + pass resp_rate_z / spo2_flag / skin_temp_flag ที่ของเดิมไม่เคยส่งเข้า
    # recovery_score() เลยทั้งที่ฟังก์ชันรับพารามิเตอร์นี้อยู่แล้ว
    # ---------------------------------------------------------------
    latest = sleep_for_analysis[-1] if sleep_for_analysis else {}
    latest_daily = daily_records[-1] if daily_records else {}

    training_load_prev_day = latest_strain.get("trimp") if latest_strain else 0
    sleep_need = sleep_analysis.calculate_sleep_need(
        training_load=training_load_prev_day or 0,
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

    rec_score = sleep_analysis.recovery_score(
        hrv_today=latest.get("hrv"),
        hrv_baseline=baseline_hrv,
        rhr_today=latest.get("resting_hr"),
        rhr_baseline=baseline_rhr,
        sleep_performance_pct=sp_pct,
        sleep_efficiency_pct=latest.get("duration_min", 0) / max(latest.get("time_in_bed_min", 1), 1) * 100 if latest else 80,
        spo2_flag=spo2_flag,
        skin_temp_flag=skin_temp_flag,
        resp_rate_z=resp_rate_z,
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
            "respiratory_rate": baseline_resp_rate,
        },
        "recovery_score": rec_score,
        "daily_strain": strain_series,          # Phase 2.2 — คู่กับ recovery_score
        "latest_strain": latest_strain,         # ให้ frontend โชว์ ring คู่ได้ง่ายๆ
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
