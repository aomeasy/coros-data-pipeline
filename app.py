#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""COROS Data Pipeline — Web UI"""
import os
import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "coros_cache.db")

# import DB layer
sys.path.insert(0, SCRIPT_DIR)
import coros_db

HTML_TEMPLATE = open(os.path.join(SCRIPT_DIR, "templates", "index.html")).read()


def get_db():
    conn = coros_db.get_conn()
    conn.row_factory = sqlite3.Row
    return conn


def fmt_pace(s):
    if not s: return "-"
    m = int(s) // 60
    sec = int(s) % 60
    return f"{m}:{sec:02d}"


def fmt_duration(s):
    if not s: return "-"
    h = int(s) // 3600
    m = (int(s) % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def fmt_dist(m):
    if not m: return "-"
    if m >= 1000:
        return f"{m/1000:.2f} km"
    return f"{m:.0f} m"


def render():
    conn = get_db()
    acts = conn.execute("SELECT * FROM activities ORDER BY start_time DESC LIMIT 20").fetchall()
    sleeps = conn.execute("SELECT * FROM sleep_data ORDER BY date DESC LIMIT 14").fetchall()
    daily = conn.execute("SELECT * FROM daily_health ORDER BY date DESC LIMIT 14").fetchall()
    conn.close()

    # stats
    act_count = len(acts)
    sleep_count = len(sleeps)
    daily_count = len(daily)
    last_sync = datetime.now().strftime("%Y-%m-%d %H:%M")

    # activities rows
    act_rows = ""
    for a in acts:
        a = dict(a)
        act_rows += f"""<tr>
<td>{a.get('start_time','')[:16]}</td>
<td><span class="badge run">{a.get('sport_type','run')}</span></td>
<td>{fmt_dist(a.get('distance_m'))}</td>
<td>{fmt_duration(a.get('duration_s'))}</td>
<td>{fmt_pace(a.get('avg_pace_s'))}</td>
<td>{a.get('avg_hr','-')}</td>
<td>{a.get('score','-')}</td>
</tr>"""

    # sleep rows
    sleep_rows = ""
    for s in sleeps:
        s = dict(s)
        sleep_rows += f"""<tr>
<td>{s.get('date','')}</td>
<td><span class="badge sleep">{s.get('sleep_score','-')}</span></td>
<td>{fmt_duration(s.get('duration_min',0)*60)}</td>
<td>{s.get('deep_sleep_pct','-')}</td>
<td>{s.get('light_sleep_pct','-')}</td>
<td>{s.get('rem_sleep_pct','-')}</td>
<td>{s.get('awake_min','-')}</td>
<td>{s.get('hrv','-')}</td>
<td>{s.get('resting_hr','-')}</td>
</tr>"""

    # daily rows
    daily_rows = ""
    for d in daily:
        d = dict(d)
        daily_rows += f"""<tr>
<td>{d.get('date','')}</td>
<td><span class="badge health">{d.get('sleep_score','-')}</span></td>
<td>{d.get('steps','-'):,}</td>
<td>{d.get('stress_score','-')}</td>
<td>{d.get('avg_hr','-')}</td>
<td>{d.get('max_hr','-')}</td>
<td>{d.get('calories_burned','-'):,}</td>
</tr>"""

    html = HTML_TEMPLATE
    html = html.replace("{{activities_count}}", str(act_count))
    html = html.replace("{{sleep_count}}", str(sleep_count))
    html = html.replace("{{daily_count}}", str(daily_count))
    html = html.replace("{{last_sync}}", last_sync)
    html = html.replace("{{activities_rows}}", act_rows)
    html = html.replace("{{sleep_rows}}", sleep_rows)
    html = html.replace("{{daily_rows}}", daily_rows)
    return html


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(render().encode("utf-8"))
        elif self.path.startswith("/api/sync"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # run sync
            env = os.environ.copy()
            env["COROS_EMAIL"] = os.environ.get("COROS_EMAIL", "")
            env["COROS_PASSWORD"] = os.environ.get("COROS_PASSWORD", "")
            result = subprocess.run(
                [sys.executable, os.path.join(SCRIPT_DIR, "coros_daily_sync.py")],
                capture_output=True, text=True, env=env,
            )
            self.wfile.write(json.dumps({
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }).encode())
        else:
            super().do_GET()

    def log_message(self, format, *args):
        pass  # suppress logs


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"COROS Data Pipeline UI → http://localhost:{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
