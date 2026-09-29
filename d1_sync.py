"""
d1_sync.py -- ซิงก์ coros_cache.db (SQLite ในเครื่อง/GitHub Actions) <-> Cloudflare D1

ใช้:
    python d1_sync.py pull    # ต้นรอบ: ดึงข้อมูลจาก D1 ลงไฟล์ .db ในเครื่อง
    python d1_sync.py push    # ท้ายรอบ: ส่งข้อมูลในเครื่องขึ้น D1

ต้องตั้ง env: CF_ACCOUNT_ID, CF_D1_ID, CF_API_TOKEN
หลักการ:
  - โค้ดเดิมทั้งหมด (coros_db.py, export.py ฯลฯ) ยังอ่าน/เขียนไฟล์ SQLite ตามเดิม
  - D1 คือที่เก็บถาวร; ไฟล์ .db ในเครื่องเป็นแค่ฐานทำงานชั่วคราว
  - push เป็น upsert อย่างเดียว ไม่ลบข้อมูลใน D1 (แถวที่ลบในเครื่องจะไม่ถูกลบใน D1)
  - เก็บค่า id ไว้ทั้งสองฝั่ง เพื่อให้รันซ้ำกี่ครั้งก็ไม่เกิดแถวซ้ำ
  - ไม่พิมพ์เนื้อข้อมูลสุขภาพลง log แสดงแค่จำนวนแถว
"""
import os
import re
import sqlite3
import sys
import time

import requests

BATCH = 20        # จำนวนคำสั่งต่อ 1 batch ตอน push
PAGE = 500        # จำนวนแถวต่อหน้าตอน pull
SKIP_PULL = {"activity_records"}   # จุดข้อมูลรายวินาที ไม่ต้องดึงกลับเครื่อง


def _cfg():
    for k in ("CF_ACCOUNT_ID", "CF_D1_ID", "CF_API_TOKEN"):
        if not os.environ.get(k):
            sys.exit(f"ขาดตัวแปรสภาพแวดล้อม {k}")
    url = (f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}"
           f"/d1/database/{os.environ['CF_D1_ID']}/query")
    hdr = {"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"}
    return url, hdr


def call(body, tries=3):
    url, hdr = _cfg()
    for i in range(tries):
        try:
            r = requests.post(url, headers=hdr, json=body, timeout=60)
            if r.status_code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 * (i + 1))
                continue
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            if i < tries - 1:
                time.sleep(2 * (i + 1))
                continue
            sys.exit(f"D1 request failed: {e}")
        if not data.get("success"):
            sys.exit(f"D1 error: {data.get('errors')}")
        return data["result"]


def q(name):
    return '"' + name.replace('"', '""') + '"'


def is_user_table(name):
    return not (name.startswith("sqlite_") or name.startswith("_cf_")
                or name == "d1_migrations")


def if_not_exists(sql):
    return re.sub(
        r"^\s*CREATE\s+(UNIQUE\s+)?(TABLE|INDEX)\s+(?!IF\s+NOT\s+EXISTS)",
        lambda m: f"CREATE {m.group(1) or ''}{m.group(2)} IF NOT EXISTS ",
        sql, count=1, flags=re.I)


def local_conn():
    import coros_db
    return sqlite3.connect(str(coros_db.DB_PATH))


def local_tables(conn):
    return {n: s for n, s in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL")
        if is_user_table(n)}


def remote_tables():
    res = call({"sql": "SELECT name, sql FROM sqlite_master WHERE type='table'"})[0]["results"]
    return {r["name"]: r["sql"] for r in res if is_user_table(r["name"])}


def remote_columns(table):
    res = call({"sql": f"SELECT name FROM pragma_table_info('{table}')"})[0]["results"]
    return {r["name"] for r in res}


def build(table, row, cols):
    names, marks, params = [], [], []
    for c in cols:
        v = row[c]
        names.append(q(c))
        if v is None:
            marks.append("NULL")
        else:
            marks.append("?")
            params.append(str(v))
    sql = f"INSERT OR REPLACE INTO {q(table)} ({','.join(names)}) VALUES ({','.join(marks)})"
    return {"sql": sql, "params": params}
def multi_insert(table, rows, cols):
    marks, params = [], []
    for r in rows:
        m = []
        for c in cols:
            if r[c] is None:
                m.append("NULL")
            else:
                m.append("?")
                params.append(str(r[c]))
        marks.append("(" + ",".join(m) + ")")
    sql = (f"INSERT OR REPLACE INTO {q(table)} ({','.join(q(c) for c in cols)}) "
           f"VALUES {','.join(marks)}")
    return {"sql": sql, "params": params}


def push_records(conn):
    """ส่งเฉพาะกิจกรรมที่ D1 ยังมีแถวไม่ครบ"""
    remote = {r["activity_id"]: r["n"] for r in call({"sql":
        "SELECT activity_id, COUNT(*) AS n FROM activity_records GROUP BY activity_id"
    })[0]["results"]}
    local = conn.execute(
        "SELECT activity_id, COUNT(*) AS n FROM activity_records GROUP BY activity_id"
    ).fetchall()
    cols = ["activity_id", "ts", "lat", "lon", "hr", "speed",
            "altitude", "cadence", "distance", "power"]
    sent = 0
    for aid, n in local:
        if remote.get(aid) == n:
            continue
        rows = conn.execute(
            "SELECT * FROM activity_records WHERE activity_id=?", (aid,)).fetchall()
        # 10 คอลัมน์ x 10 แถว = 100 params (เพดานต่อคำสั่งของ D1)
        stmts = [multi_insert("activity_records", rows[i:i + 10], cols)
                 for i in range(0, len(rows), 10)]
        for i in range(0, len(stmts), BATCH):
            call({"batch": stmts[i:i + BATCH]})
        sent += len(rows)
    print(f"push activity_records: ส่งใหม่ {sent} แถว")

def push():
    conn = local_conn()
    conn.row_factory = sqlite3.Row
    lt = local_tables(conn)
    rt = remote_tables()

    # 1) สร้างตาราง / เติมคอลัมน์ที่ขาดใน D1
    for name, sql in lt.items():
        if name not in rt:
            call({"sql": if_not_exists(sql)})
            print(f"push: สร้างตาราง {name} ใน D1")
            continue
        have = remote_columns(name)
        for _, col, typ, *_ in conn.execute(f"PRAGMA table_info({q(name)})"):
            if col not in have:
                call({"sql": f"ALTER TABLE {q(name)} ADD COLUMN {q(col)} {typ or ''}".strip()})
                print(f"push: {name} เพิ่มคอลัมน์ {col}")

    # 2) index (ไม่ร้ายแรงถ้าพลาด)
    for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        try:
            call({"sql": if_not_exists(sql)})
        except SystemExit as e:
            print(f"push: ข้าม index {name} ({e})")


    # 3) ส่งข้อมูล
    for name in lt:
        if name == "activity_records":
            push_records(conn)
            continue
        rows = conn.execute(f"SELECT * FROM {q(name)}").fetchall()
        cols = rows[0].keys() if rows else []
        for i in range(0, len(rows), BATCH):
            call({"batch": [build(name, r, cols) for r in rows[i:i + BATCH]]})
        n = call({"sql": f"SELECT COUNT(*) AS n FROM {q(name)}"})[0]["results"][0]["n"]
        print(f"push {name}: local {len(rows)} แถว -> D1 {n} แถว")
    conn.close()


def pull():
    import coros_db
    coros_db.init_db()                      # ให้ schema ในเครื่องเป็นไปตามโค้ดก่อน
    conn = local_conn()
    lt = local_tables(conn)
    for name, sql in remote_tables().items():
        if name not in lt:
            conn.execute(if_not_exists(sql))
            print(f"pull: สร้างตาราง {name} ในเครื่อง (มีใน D1 แต่ไม่มีในโค้ด)")
        lcols = {c[1] for c in conn.execute(f"PRAGMA table_info({q(name)})")}
        total, offset = 0, 0
        while True:
            res = call({"sql": f"SELECT * FROM {q(name)} ORDER BY rowid "
                               f"LIMIT {PAGE} OFFSET {offset}"})[0]["results"]
            if not res:
                break
            cols = [c for c in res[0].keys() if c in lcols]
            conn.executemany(
                f"INSERT OR REPLACE INTO {q(name)} ({','.join(q(c) for c in cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [[r[c] for c in cols] for r in res])
            total += len(res)
            offset += len(res)
            if len(res) < PAGE:
                break
        conn.commit()
        print(f"pull {name}: {total} แถว")
    conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("pull", "push"):
        sys.exit("ใช้: python d1_sync.py pull|push")
    {"pull": pull, "push": push}[sys.argv[1]]()
