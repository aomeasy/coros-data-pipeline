import io, json, subprocess, sys
import requests
from fitparse import FitFile

def call_tool(tool, args):
    r = subprocess.run(
        ["coros-mcp", "call-tool", "--tool", tool,
         "--arguments-json", json.dumps(args)],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)

def find_urls(obj):
    """หา URL ในผลลัพธ์ (ยังไม่รู้โครงสร้างจริง จึงเดินหาทุกชั้น)"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and v.startswith("http"):
                yield obj.get("labelId", k), v
            else:
                yield from find_urls(v)
    elif isinstance(obj, list):
        for i in obj:
            yield from find_urls(i)

def num(v):
    return "NULL" if v is None else str(round(v, 6) if isinstance(v, float) else v)

def parse_fit(data):
    for m in FitFile(io.BytesIO(data)).get_messages("record"):
        d = {f.name: f.value for f in m}
        if not d.get("timestamp"):
            continue
        lat, lon = d.get("position_lat"), d.get("position_long")
        yield (
            d["timestamp"].isoformat(),
            lat * 180 / 2**31 if lat is not None else None,   # semicircles -> degrees
            lon * 180 / 2**31 if lon is not None else None,
            d.get("heart_rate"),
            d.get("enhanced_speed", d.get("speed")),
            d.get("enhanced_altitude", d.get("altitude")),
            d.get("cadence"), d.get("distance"), d.get("power"),
        )

def main(start, end, out="fit_import.sql"):
    res = call_tool("queryActivityFitFileDownloadUrls",
                    {"startDate": start, "endDate": end, "limit": 10})
    print(json.dumps(res, indent=2)[:1500])   # ดูโครงสร้างจริงใน log ครั้งแรก

    with open(out, "w", encoding="utf-8") as f:
        for label_id, url in find_urls(res):
            data = requests.get(url, timeout=60).content
            rows = [
                "('%s','%s',%s,%s,%s,%s,%s,%s,%s,%s)" % (
                    label_id, r[0], *map(num, r[1:]))
                for r in parse_fit(data)
            ]
            for i in range(0, len(rows), 300):     # แบ่ง statement ไม่ให้ยาวเกิน
                f.write(
                    "INSERT OR IGNORE INTO activity_records "
                    "(activity_id,ts,lat,lon,hr,speed,altitude,cadence,distance,power) VALUES\n"
                    + ",\n".join(rows[i:i+300]) + ";\n")
            print(f"{label_id}: {len(rows)} records")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
