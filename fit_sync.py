# -*- coding: utf-8 -*-
"""ดาวน์โหลดไฟล์ FIT ของกิจกรรมที่ยังไม่เคยโหลด แล้วเก็บจุดข้อมูลลง SQLite"""
import io, json, re, shutil, subprocess
from datetime import datetime

import requests
from fitparse import FitFile

import coros_db

MAX_PER_RUN = 3                      # กันชนโควตาดาวน์โหลดต่อวัน (workflow รัน 3 รอบ/วัน)
COROS = shutil.which("coros-mcp") or "coros-mcp"

# ล้างสถานะ no_url ที่เกิดจาก first_url() เวอร์ชันเก่าที่พัง (หมดอายุเองหลังวันนี้)
STALE_NO_URL_BEFORE = "2026-09-30"

URL_RE = re.compile(r"https?://[^\s\"'<>]+\.fit[^\s\"'<>]*")

SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_records (
  activity_id TEXT NOT NULL,
  ts TEXT NOT NULL,
  lat REAL, lon REAL,
  hr INTEGER, speed REAL, altitude REAL,
  cadence INTEGER, distance REAL, power INTEGER,
  PRIMARY KEY (activity_id, ts)
);
CREATE TABLE IF NOT EXISTS fit_imported (
  activity_id TEXT PRIMARY KEY,
  status TEXT,
  n_records INTEGER,
  imported_at TEXT
);
"""


def call_tool(tool, args):
    r = subprocess.run(
        [COROS, "call-tool", "--tool", tool, "--arguments-json", json.dumps(args)],
        capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or r.stdout.strip())
    return json.loads(r.stdout)


def first_url(obj):
    """หา URL ไฟล์ .fit แรกในผลลัพธ์ (รองรับ dict/list ซ้อน และข้อความล้วน)"""
    if isinstance(obj, str):
        m = URL_RE.search(obj)
        return m.group(0) if m else None
    if isinstance(obj, dict):
        for v in obj.values():
            u = first_url(v)
            if u:
                return u
    if isinstance(obj, list):
        for v in obj:
            u = first_url(v)
            if u:
                return u
    return None

def _row(ts, lat, lon, hr, speed, alt, cad, dist, pwr):
    return (ts.isoformat(),
            lat * 180 / 2**31 if lat is not None else None,
            lon * 180 / 2**31 if lon is not None else None,
            hr, speed, alt, cad, dist, pwr)


def parse_fit(data):
    """ลอง garmin-fit-sdk ก่อน (ทนไฟล์แปลก) ถ้าไม่มี/พังค่อยใช้ fitparse"""
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError:
        Decoder = None

    if Decoder:
        decoder = Decoder(Stream.from_byte_array(bytearray(data)))
        messages, errors = decoder.read(
            apply_scale_and_offset=True,
            convert_datetimes_to_dates=True,
            convert_types_to_strings=False,
            enable_crc_check=False,
            expand_sub_fields=True,
            expand_components=True,
            merge_heart_rates=True,
        )
        records = messages.get("record_mesgs", [])
        if errors:
            print(f"  decoder warnings: {errors[:2]}")
        if records:
            out = []
            for d in records:
                if not d.get("timestamp"):
                    continue
                out.append(_row(
                    d["timestamp"], d.get("position_lat"), d.get("position_long"),
                    d.get("heart_rate"),
                    d.get("enhanced_speed", d.get("speed")),
                    d.get("enhanced_altitude", d.get("altitude")),
                    d.get("cadence"), d.get("distance"), d.get("power")))
            return out

    # สำรอง: fitparse
    out = []
    for m in FitFile(io.BytesIO(data)).get_messages("record"):
        d = {f.name: f.value for f in m}
        if not d.get("timestamp"):
            continue
        out.append(_row(
            d["timestamp"], d.get("position_lat"), d.get("position_long"),
            d.get("heart_rate"),
            d.get("enhanced_speed", d.get("speed")),
            d.get("enhanced_altitude", d.get("altitude")),
            d.get("cadence"), d.get("distance"), d.get("power")))
    return out

def main():
    conn = coros_db.get_conn()
    conn.executescript(SCHEMA)

    conn.execute(
        "DELETE FROM fit_imported WHERE status = 'no_url' AND imported_at < ?",
        (STALE_NO_URL_BEFORE,))
    conn.commit()

    pending = conn.execute("""
        SELECT activity_id, sport_type FROM activities
        WHERE activity_id NOT IN (SELECT activity_id FROM fit_imported)
        ORDER BY start_time DESC LIMIT ?
    """, (MAX_PER_RUN,)).fetchall()
    print(f"pending: {len(pending)}")

    for row in pending:
        aid = row["activity_id"]
        try:
            sport = int(row["sport_type"])
        except (TypeError, ValueError):
            print(f"{aid}: sport_type ใช้ไม่ได้ ({row['sport_type']!r}) ข้าม")
            continue
        try:
            res = call_tool("queryActivityFitFileDownloadUrls",
                            {"labelId": str(aid), "sportType": sport})
            url = first_url(res)
            now = datetime.now().isoformat()
            if not url:
                print(f"{aid}: ไม่มี URL -> {json.dumps(res, ensure_ascii=False)[:300]}")
                conn.execute("INSERT OR REPLACE INTO fit_imported VALUES (?,?,?,?)",
                             (aid, "no_url", 0, now))
                conn.commit()
                continue
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            try:
                rows = [(aid, *r) for r in parse_fit(resp.content)]
            except Exception as pe:
                print(f"{aid}: parse ไม่ได้ ({pe}) บันทึก parse_error แล้วข้าม")
                conn.execute("INSERT OR REPLACE INTO fit_imported VALUES (?,?,?,?)",
                             (aid, "parse_error", 0, now))
                conn.commit()
                continue
            conn.executemany(
                "INSERT OR IGNORE INTO activity_records "
                "(activity_id,ts,lat,lon,hr,speed,altitude,cadence,distance,power) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            conn.execute("INSERT OR REPLACE INTO fit_imported VALUES (?,?,?,?)",
                         (aid, "ok", len(rows), now))
            conn.commit()
            print(f"{aid}: {len(rows)} records")
        except Exception as e:
            print(f"{aid}: error {e}")   # ไม่บันทึกสถานะ รอบหน้าลองใหม่
            break                         # มักเป็นโควตาเต็ม หยุดเลย
    conn.close()


if __name__ == "__main__":
    main()
