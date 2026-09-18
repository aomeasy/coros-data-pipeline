# 📘 คู่มืออธิบายโปรเจกต์ `coros-data-pipeline`

> Repository: [github.com/aomeasy/coros-data-pipeline](https://github.com/aomeasy/coros-data-pipeline)
> Live Dashboard: https://aomeasy.github.io/coros-data-pipeline/
> License: MIT

โปรเจกต์นี้เป็น **local data pipeline สำหรับนาฬิกา COROS** ที่ดึงข้อมูลกิจกรรม (activities), การนอน (sleep) และสุขภาพรายวัน (daily health) มาเก็บไว้ใน SQLite แล้วนำมาวิเคราะห์/แสดงผลผ่านหน้าเว็บ (GitHub Pages) โดยอัตโนมัติทุกวันผ่าน GitHub Actions

---

## 🏗️ ภาพรวมสถาปัตยกรรม (Architecture)

```
COROS API (ผ่าน COROS-MCP)
        │
        ▼
coros_daily_sync.py   ← รันทุกวันผ่าน GitHub Actions
        │
        ▼
    SQLite DB (coros_cache.db)
        │
        ├── activities
        ├── sleep_data
        ├── daily_health
        └── journal_entries
        │
        ▼
export.py → docs/data.json  ← สร้างโดย GitHub Actions
        │
        ▼
docs/index.html / docs/journal.html   ← หน้าเว็บ static (GitHub Pages)
        │
        ▲ (ทางเลือก: รันแบบ local server)
app.py (Flask)  ← ให้ API แบบ dynamic + คำนวณ analysis สด ๆ
        │
        ├── sleep_analysis.py   (วิเคราะห์การนอนแบบละเอียด)
        └── breath_analysis.py  (วิเคราะห์การหายใจ/ออกซิเจน/ฟื้นฟู)
```

แนวคิดหลัก: **ดึงข้อมูลจาก COROS ครั้งเดียวต่อวัน → cache ไว้ใน SQLite → คำนวณ metric ด้วยสูตรสถิติ (ไม่พึ่ง AI API) → export เป็น JSON แสดงบนเว็บ** ทำให้ไม่ต้องยิง COROS API ซ้ำ ๆ และเปิดดูข้อมูลย้อนหลังได้เร็ว

---

## 📂 รายชื่อไฟล์ทั้งหมดในโปรเจกต์

| ไฟล์/โฟลเดอร์ | ประเภท | หน้าที่หลัก |
|---|---|---|
| `README.md` | เอกสาร | ภาพรวมโปรเจกต์แบบสั้น |
| `app.py` | Python (Flask) | เว็บเซิร์ฟเวอร์สำหรับรัน dashboard/API แบบ local |
| `coros_db.py` | Python | ชั้นจัดการ SQLite database (schema + CRUD) |
| `coros_daily_sync.py` | Python | สคริปต์ sync ข้อมูลจาก COROS-MCP → parse → เก็บ DB |
| `sleep_analysis.py` | Python | โมดูลคำนวณ/วิเคราะห์การนอนแบบละเอียด (rule-based) |
| `breath_analysis.py` | Python | โมดูลวิเคราะห์การหายใจ, SpO2, recovery, VO2max |
| `export.py` | Python | Export ข้อมูลจาก SQLite → `docs/data.json` |
| `fix_script.py` | Python (one-off) | สคริปต์แพตช์ (patch) บั๊กใน `docs/index.html` ครั้งเดียว |
| `sleep analysis.md` | เอกสาร | เอกสารสูตร/ที่มาของฟังก์ชันใน `sleep_analysis.py` (มีรายละเอียดเชิงทฤษฎีมากกว่าโค้ดจริง) |
| `coros_cache.db` | SQLite DB | ไฟล์ฐานข้อมูลจริง (คอมมิตเข้า repo ไว้เป็น cache) |
| `.gitignore` | Config | ไฟล์/โฟลเดอร์ที่ไม่ให้ git ติดตาม |
| `docs/` | โฟลเดอร์ | เว็บหน้า static ที่ GitHub Pages เสิร์ฟ (index.html, journal.html, data.json) |
| `templates/` | โฟลเดอร์ | เทมเพลตเสริม (ใช้ร่วมกับ Flask หรือหน้าเว็บ) |
| `.github/workflows/` | โฟลเดอร์ | GitHub Actions workflow สำหรับรัน sync/export อัตโนมัติทุกวัน |

> ⚠️ หมายเหตุ: ไฟล์ในโฟลเดอร์ `docs/`, `templates/` และ `.github/workflows/` ไม่สามารถเปิดเนื้อหาแบบ raw ได้ตรง ๆ ในตอนที่ทำเอกสารนี้ (ติด robots restriction ของ GitHub) แต่ **บทบาทของมันสามารถอนุมานได้ชัดเจนจากโค้ดที่อ้างอิงถึง** (เช่น `app.py`, `export.py`, `fix_script.py`, และ README) ซึ่งอธิบายไว้ในหัวข้อที่เกี่ยวข้องด้านล่าง

---

## 1️⃣ `coros_db.py` — ชั้นจัดการฐานข้อมูล (Data Access Layer)

ไฟล์นี้เป็น **หัวใจของการเก็บข้อมูล** ทุกอย่างที่ดึงมาจาก COROS จะถูกยัดเข้ามาที่นี่ก่อนเสมอ

### โครงสร้างตาราง (Schema)
สร้างด้วย `init_db()` ซึ่งจะถูกเรียกอัตโนมัติทันทีที่ import โมดูลนี้ (`init_db()` อยู่บรรทัดสุดท้ายของไฟล์)

| ตาราง | คีย์หลัก | ฟิลด์สำคัญ |
|---|---|---|
| `activities` | `activity_id` (unique) | sport_type, start_time, distance_m, duration_s, avg_pace_s, avg_cadence, calories, avg_hr, max_hr, ascent_m, descent_m, score, summary_json |
| `sleep_data` | `date` (unique) | sleep_score, duration_min, deep/light/rem_sleep_pct, awake_min, hrv, resting_hr, summary_json |
| `daily_health` | `date` (unique) | sleep_score, steps, stress_score, avg_hr, max_hr, calories_burned, summary_json |
| `journal_entries` | `date` (unique) | alcohol_units, caffeine_after_14, late_meal, screen_before_bed_min, stress_level, exercise_evening, room_temp_hot, notes |

- ทุกตารางมี `created_at` / `updated_at` และ index ที่คอลัมน์สำคัญ (sport_type, start_time, date) เพื่อ query เร็วขึ้น
- เปิด connection ด้วย `PRAGMA journal_mode=WAL` (เขียนพร้อมอ่านได้ดีขึ้น) และ `PRAGMA foreign_keys=ON`
- `summary_json` เก็บ raw JSON response ทั้งก้อนจาก COROS ไว้ด้วย เผื่อย้อนดูฟิลด์ที่ไม่มีคอลัมน์เฉพาะ

### ฟังก์ชันหลัก
- `get_conn()` — เปิด connection พร้อมตั้งค่า pragma
- `store_activity()`, `store_sleep()`, `store_daily_health()`, `store_journal()` — บันทึกแบบ `INSERT OR REPLACE` (กัน record ซ้ำด้วย unique key)
- `get_recent_activities()`, `get_recent_sleep()`, `get_recent_daily_health()`, `get_all_journals()`, `get_journal_by_date()` — query อ่านข้อมูลย้อนหลัง
- `cache_daily_health(start_date, end_date)` — เรียก `coros-mcp` CLI ตรงจากในนี้เลย (ไม่ผ่าน `coros_daily_sync.py`) แล้วเก็บลง DB ทันที เหมาะกับใช้ sync แบบระบุช่วงวันที่เอง
- `clear_cache()` — ล้างข้อมูลกิจกรรม/sleep/daily ทั้งหมด (⚠️ ไม่ล้าง journal)
- `get_db_stats()` — คืนจำนวน record ในแต่ละตาราง + path ของ DB (ใช้แสดงผลผ่าน `/api/stats`)

**DB path**: ใช้ `Path(__file__).parent / "coros_cache.db"` เสมอ — วางไว้ข้าง ๆ ไฟล์ .py จึงพกพา/รันบน GitHub Actions ได้โดยไม่ต้อง config path เพิ่ม

---

## 2️⃣ `coros_daily_sync.py` — สคริปต์ Sync หลัก (รันทุกวัน)

นี่คือสคริปต์ที่ **GitHub Actions รันอัตโนมัติทุกวัน** เพื่อดึงข้อมูลใหม่จาก COROS

### วิธีทำงาน
1. **Login**: เรียก `npx coros-mcp login --legacy --username <email>` แล้วส่ง password ผ่าน stdin (อ่านจาก env var `COROS_EMAIL` / `COROS_PASSWORD`)
2. **เรียก MCP tool แบบ subprocess**: ฟังก์ชัน `_run()` เรียก `npx coros-mcp call-tool --tool <name> --arguments-json <json>` แล้วอ่านผลลัพธ์จาก stdout
3. **Parse ข้อความดิบ (text) เป็นข้อมูลโครงสร้าง**: จุดที่น่าสนใจคือ COROS-MCP คืนค่าเป็น "ข้อความอ่านง่าย" (human-readable text) ไม่ใช่ JSON ล้วน ๆ เช่น:
   ```
   1. Outdoor Run — 2026-09-16
      Duration: 29:27 | Distance: 3.55 km
      Average Pace: 8:18 /km
      Avg HR: 142 bpm | Calories: 320 kcal
   ```
   ไฟล์นี้จึงใช้ **regular expression (regex)** จำนวนมากในการดึงตัวเลขออกจากข้อความ เช่น `parse_duration()`, `parse_hm()`, `parse_pace_to_seconds()`

### ฟังก์ชันสำคัญ
- `sync_activities()` — ดึงกิจกรรม 90 วันล่าสุด (running/cycling ฯลฯ ผ่าน `sportTypeCodes`) แยกแต่ละกิจกรรมด้วย regex `\n\d+\.\s+` แล้วดึงค่า LabelId, SportType, Duration, Distance, Pace, HR, Calories, timestamp ออกมาเก็บผ่าน `coros_db.store_activity()`
- `sync_sleep_and_health(days=7)` — ดึงข้อมูลสุขภาพรายวัน 7 วันล่าสุด แยกแต่ละวันด้วย regex `---\s*(\d{8})\s*---` แล้วดึง Steps, Calories, Stress, และในส่วน "Sleep Summary:" ดึง Total/Deep/Light/REM/Awake ออกมาคำนวณเป็น % แล้วเก็บผ่าน `store_sleep()` และ `store_daily_health()`
- `main()` — ลำดับการทำงาน: ตรวจ env var → login → sync activities → sync sleep/health → print log พร้อม timestamp

### จุดสำคัญด้าน Robustness
- ถ้าไม่มี `COROS_EMAIL`/`COROS_PASSWORD` จะ **SKIP** ไม่ crash (สำคัญมากสำหรับ GitHub Actions ที่บาง run อาจไม่มี secret)
- ใช้ `errors="replace"` ตอน decode text กัน encoding พัง
- คืน exit code 1 เมื่อ login/sync ล้มเหลว เพื่อให้ GitHub Actions รายงานสถานะ fail ได้ถูกต้อง

---

## 3️⃣ `sleep_analysis.py` — โมดูลวิเคราะห์การนอน (Rule-based, ไม่ใช้ AI)

ไฟล์นี้ยาวและซับซ้อนที่สุดในโปรเจกต์ (726 บรรทัด) แบ่งเป็น **11 กลุ่มฟังก์ชัน**:

### 1. Basic Metrics
- `sleep_efficiency(record)` = (เวลานอนจริง / เวลาบนเตียง) × 100 — ถ้าไม่มี time_in_bed จะประมาณจาก `duration_min + awake_min×1.5`
- `estimate_latency()` — ประมาณเวลากว่าจะหลับจาก stage timeline
- `stage_percentages()` — คำนวณสัดส่วน deep/light/REM

### 2. Sleep Architecture Analysis
- `compute_baseline(records, metric_path, window=30)` — คำนวณ mean/stdev แบบ rolling (ต้องมีข้อมูล ≥5 จุดถึงจะคำนวณ)
- `z_score()` / `flag_metric()` — แปลงค่าเป็น Z-score เทียบ baseline ส่วนตัว แล้ว flag เป็น `critical_low / low / normal / elevated / unusually_high`
- `estimate_cycles()` — ประมาณจำนวนรอบการนอน (light→deep/rem)
- `fragmentation_index()` — จำนวนการเปลี่ยน stage ต่อชั่วโมง (ยิ่งมากยิ่งนอนไม่ต่อเนื่อง)

### 3. Sleep Debt & Need
- `calculate_sleep_need()` — คำนวณความต้องการนอนแบบ dynamic โดยปรับตาม training load
- `cumulative_sleep_debt()` — หนี้การนอนสะสมแบบมี decay factor (หนี้เก่าลดลง 10%/วัน โดย default)
- `sleep_performance()` — % ของที่นอนได้จริงเทียบกับที่ต้องการ (cap ที่ 120%)

### 4. SpO2 Analysis
- `analyze_spo2()` — หา dip events (จำนวนครั้งที่ SpO2 ต่ำกว่า threshold ต่อเนื่อง)
- `flag_spo2_risk()` — flag เป็น `normal / monitor / review_recommended`

### 5. Skin Temperature Analysis
- `analyze_skin_temp()` — ดู deviation จาก baseline ของตัวเอง (COROS คำนวณ deviation มาให้แล้ว) ± 0.5°C ถือว่าผิดปกติ

### 6. Recovery Composite Score
- `recovery_score()` — คะแนนรวมแบบ weighted:
  - HRV 30% + RHR 20% + Sleep Performance 25% + Sleep Efficiency 15%
  - หัก penalty จาก SpO2 (7-15 คะแนน), skin temp (8 คะแนน), respiratory rate ผิดปกติ (5 คะแนน)
  - แบ่ง band: `green ≥67`, `yellow ≥34`, `red <34`

### 7. Journal Correlation Engine
- `correlate_journal_factor()` — เทียบ metric ระหว่างวันที่ "มี" vs "ไม่มี" ปัจจัย (เช่นดื่มแอลกอฮอล์) ต้องมีข้อมูลอย่างน้อย 3 record ต่อกลุ่ม
- `rank_journal_impacts()` — จัดอันดับปัจจัย (alcohol, caffeine, late meal, stress, exercise evening, room temp) ที่กระทบการนอนมากที่สุด

### 8. Correlation & Trend Engine
- `correlate_load_vs_sleep()` — หา correlation ระหว่าง training load กับ deep sleep % (ใช้ numpy, ต้องมีข้อมูล ≥10 จุด)
- `rolling_average()` — ค่าเฉลี่ยเคลื่อนที่ (default 7 วัน)
- `bedtime_consistency()` — ให้คะแนนความสม่ำเสมอของเวลาเข้านอน (stdev ต่ำ = คะแนนสูง)

### 9. Anomaly Detection & Alerting
- `detect_anomalies()` — ตรวจ deep sleep ต่ำ, REM ต่ำ, HRV ตก, RHR พุ่ง, SpO2 ตก เทียบ baseline แล้วให้ severity `critical`/`warning`
- `should_alert()` — เช็คว่า metric ต่ำกว่า threshold ต่อเนื่องกี่วัน (default 3 วัน) เพื่อตัดสินใจแจ้งเตือน

### 10. Weekly Report Generator
- `generate_weekly_report()` — สร้างสรุปข้อความภาษาไทยแบบ template (ไม่ใช้ AI) รวม efficiency, deep/REM เฉลี่ย, SpO2, bedtime consistency, และปัจจัยจาก journal ที่กระทบมากสุด

### 11. SQI — Sleep Quality Index
- `calculate_sqi()` — ดัชนีคุณภาพการนอนรวม (0-100) จากสูตร:
  ```
  SQI = 0.30×(Efficiency/100) + 0.20×Stage_Balance + 0.15×(Consistency/100) + 0.35×(1-Debt_Ratio)
  ```
  แบ่ง band: `good ≥80`, `fair ≥60`, `poor <60`

> 📌 **หมายเหตุสำคัญที่ผู้เขียนโค้ดใส่ไว้เอง**: ทุกสูตรเป็น heuristic/สถิติ **ไม่ใช่การวินิจฉัยทางการแพทย์** — ค่า threshold/weight ต่าง ๆ เป็นค่าตั้งต้นที่ควร calibrate ด้วยข้อมูลจริงของแต่ละคนเมื่อสะสมได้ ≥60 วัน

---

## 4️⃣ `sleep analysis.md` — เอกสารอ้างอิงสูตรของ sleep_analysis.py

ไฟล์นี้คือ **"blueprint" หรือเอกสารออกแบบ** ของ `sleep_analysis.py` เขียนด้วยภาษาไทยผสมโค้ดตัวอย่าง มีเนื้อหาเพิ่มเติมที่ไม่ได้อยู่ในโค้ดจริงทั้งหมด เช่น:

- **Input Schema** เต็มรูปแบบของ `SleepRecord` และ `JournalEntry` ที่ควรได้จาก COROS MCP (รวม `spo2_readings` แบบ timeline, `skin_temp_deviation_c`, `training_load_prev_day`)
- ตารางค่าอ้างอิงมาตรฐานสัดส่วนการนอนของผู้ใหญ่ (Light 45-55%, Deep 13-23%, REM 20-25%)
- **ลำดับการ implement ที่แนะนำ** (ข้อ 11 ในเอกสาร) เป็น roadmap 7 ขั้นตอน:
  1. Loader normalize ข้อมูลจาก COROS MCP
  2. สร้างหน้า Journal input
  3. Implement basic + SpO2 + skin temp ก่อน (ใช้ได้ทันทีไม่ต้องรอ baseline)
  4. สะสมข้อมูล ≥30 วัน แล้วเปิด baseline-dependent metrics
  5. เก็บ journal ควบคู่ ≥2-3 สัปดาห์ก่อนเปิด correlation engine
  6. correlation กับ training load ต้องการข้อมูล ≥30-60 วัน
  7. ต่อเข้า Telegram/Sheets

พูดง่าย ๆ คือไฟล์นี้เป็น **spec/design doc** ส่วน `sleep_analysis.py` คือ **implementation จริง** ที่เขียนตามสเปกนี้ (มีบางจุดต่างกันเล็กน้อย เช่นโค้ดจริงเพิ่ม error handling `try/except` และรองรับกรณีข้อมูลไม่ครบมากกว่าที่ระบุในเอกสาร)

---

## 5️⃣ `breath_analysis.py` — โมดูลวิเคราะห์การหายใจและการฟื้นฟู

ไฟล์นี้อ้างอิงสูตรจาก "breath-coach skill" โฟกัสที่การหายใจ ออกซิเจน และสถานะฟื้นฟูของร่างกาย:

| ฟังก์ชัน | หน้าที่ | เกณฑ์ |
|---|---|---|
| `analyze_respiratory_rate(rr)` | วิเคราะห์อัตราการหายใจ (breaths/min) | <12 = excellent (นักกีฬา), 12-18 = normal, 18-22 = fair, >22 = elevated (ควรฟื้นฟู) |
| `analyze_spo2(avg, min_val)` | วิเคราะห์ระดับออกซิเจนในเลือด | ≥95% = normal, 90-94% = low, <90% = critical |
| `recovery_status(recovery_pct, est_hours)` | สถานะความพร้อมฟื้นฟู | ≥80% = ready, 60-79% = moderate, <60% = low (ควรพัก) |
| `training_load_ratio(short_term, long_term)` | อัตราส่วน load ระยะสั้น/ยาว | 0.8-1.3 = optimal, >1.3 = overreaching, <0.8 = detraining |
| `interpret_vo2max(vo2max, age, gender)` | ตีความค่า VO2max ตามเพศ/อายุ (default 30-39 ปี) | มีเกณฑ์แยกชาย/หญิงชัดเจน |
| `breathing_efficiency_score(rr, spo2, hrv, hrv_baseline)` | คะแนนประสิทธิภาพการหายใจรวม (0-100) | สูตร weighted: respiratory 40% + spo2 30% + HRV 30% |

ทุกฟังก์ชันคืนค่าเป็น dict ที่มี `status`/`level`, `description` (ภาษาไทย) และ `unit` เพื่อให้ frontend เอาไปแสดงผลได้ตรง ๆ โดยไม่ต้องแปลผลเพิ่ม

---

## 6️⃣ `app.py` — Flask Web Server (โหมดรัน Local/Dynamic)

ไฟล์นี้คือ **ทางเลือกที่สองในการดูข้อมูล** (นอกจาก GitHub Pages แบบ static) โดยรันเป็นเว็บเซิร์ฟเวอร์ที่คำนวณผลวิเคราะห์แบบสด (on-the-fly) ทุกครั้งที่เรียก API แทนการอ่านจาก `data.json` ที่ export ไว้ล่วงหน้า

### Route ทั้งหมด

| Route | Method | หน้าที่ |
|---|---|---|
| `/` | GET | เสิร์ฟ `docs/index.html` |
| `/journal.html` | GET | เสิร์ฟ `docs/journal.html` |
| `/api/data` | GET | เสิร์ฟไฟล์ `docs/data.json` ตรง ๆ (ถ้ามี) |
| `/api/analysis` | GET | **หัวใจของ endpoint นี้** — ดึงข้อมูลทั้งหมดจาก DB มาประมวลผลผ่าน `sleep_analysis` + `breath_analysis` แบบเรียลไทม์ แล้วคืน JSON ก้อนใหญ่ |
| `/api/journal` | GET | คืน journal entries ทั้งหมด |
| `/api/journal` | POST | บันทึก journal entry ใหม่ (แปลง boolean field เป็น int ก่อนเก็บ) |
| `/api/sync` | POST | รัน `coros_daily_sync.py` เป็น subprocess ทันที (ส่ง env var COROS_EMAIL/PASSWORD ต่อให้) แล้วคืน stdout/stderr |
| `/api/stats` | GET | คืนสถิติ DB (จำนวน record ในแต่ละตาราง) |

### รายละเอียดของ `/api/analysis` (ซับซ้อนสุด)
1. ดึง `sleep_data`, `daily_health`, `activities` (limit 20), `journal_entries` จาก DB
2. Normalize sleep record ให้ตรงกับ schema ที่ `sleep_analysis.py` ต้องการ (map `duration_min` → `total_sleep_min`, ประมาณ `time_in_bed_min`)
3. รันฟังก์ชันวิเคราะห์ครบทุกกลุ่ม: `sleep_efficiency`, `stage_percentages`, `compute_baseline` (deep/rem/hrv/resting_hr), `recovery_score`, `calculate_sqi`, `generate_weekly_report`, `rank_journal_impacts` (ต้องมี journal ≥3 รายการ), `detect_anomalies`, `bedtime_consistency`, `rolling_average` (7 วัน)
4. รัน `breath_analysis` จาก daily_health (respiratory_rate, spo2_avg) และคำนวณ `breathing_efficiency_score` ของวันล่าสุด
5. รวมทุกอย่างเป็น JSON response เดียว ส่งกลับให้ frontend

### จุดที่ควรรู้
- ใช้ `sys.path.insert(0, SCRIPT_DIR)` เพื่อ import โมดูลข้างเคียง (`coros_db`, `sleep_analysis`, `breath_analysis`) แบบไม่ต้องติดตั้งเป็น package
- รันด้วย `python app.py [port]` (default port 8080)
- `debug=False` — ตั้งใจปิด debug mode เพื่อไม่ให้เผย stack trace ตอน deploy จริง

---

## 7️⃣ `export.py` — ตัวแปลง SQLite → JSON สำหรับ GitHub Pages

เพราะ GitHub Pages เป็น **static hosting** (รันเซิร์ฟเวอร์ Python ไม่ได้) ไฟล์นี้จึงทำหน้าที่ "แปลง" ข้อมูลจาก `coros_cache.db` ให้เป็นไฟล์ `docs/data.json` ที่ฝั่ง frontend (JavaScript) อ่านได้ตรง ๆ โดยไม่ต้องมี backend

### ขั้นตอนการทำงาน (`export()`)
1. อ่านจาก DB: `activities` (50 record ล่าสุด), `sleep_data`/`daily_health`/`journal_entries` (30 record ล่าสุด)
2. **Transform ชื่อฟิลด์**ให้ตรงกับที่ frontend คาดหวัง เช่น `calories` (ใน DB) → `calories_burned` (ใน JSON), แปลง `date` จากรูปแบบ `20260917` → `2026-09-17` ด้วย `fmt_date()`
3. แปลง journal boolean fields (เก็บเป็น 0/1 ใน DB) กลับเป็น `true`/`false` จริงด้วย `bool()`
4. `compute_metrics()` — คำนวณค่าเฉลี่ยสรุป (avg sleep efficiency, avg deep/rem %, avg duration, total steps) ไว้ล่วงหน้า เพื่อให้หน้า dashboard โหลดเร็วโดยไม่ต้องคำนวณฝั่ง JS
5. เขียนไฟล์ `docs/data.json` พร้อม `stats` (จำนวน record ของแต่ละหมวด + `last_updated` timestamp)

> เทียบกับ `/api/analysis` ใน `app.py`: `export.py` ให้ **ข้อมูลดิบ + สรุปพื้นฐาน** เท่านั้น (ไม่รัน recovery_score/SQI/anomaly detection เต็มรูปแบบ — ฟิลด์ `recovery_score`/`sqi` ใน `compute_metrics()` ถูกปล่อยเป็น `None` ไว้) ส่วนการวิเคราะห์เชิงลึกทั้งหมดต้องรันผ่าน `app.py` แบบ local เท่านั้น ตอนนี้หน้าเว็บ GitHub Pages (static) จึงเห็นได้แค่ข้อมูลพื้นฐาน+สรุป ไม่เห็นผลวิเคราะห์แบบละเอียดเหมือนตอนรัน Flask local

---

## 8️⃣ `fix_script.py` — สคริปต์แพตช์ครั้งเดียว (One-off Patch)

ไฟล์นี้ไม่ใช่ส่วนหนึ่งของ pipeline ที่รันประจำ แต่เป็น **สคริปต์ที่รันครั้งเดียวเพื่อแก้บั๊ก** ใน `docs/index.html`:

- ไล่หาบรรทัดใน `docs/index.html` ที่มีทั้งคำว่า `respiratory_rate`, `spo2`, และ `html +=` (แปลว่าเป็นโค้ด JS ที่ต่อ string HTML table แถวข้อมูลการหายใจ)
- แทนที่บรรทัดนั้นด้วยเวอร์ชันที่ปลอดภัยกว่า ใช้ **string concatenation แบบ manual** (เช่น `'<tr><td>' + b.date + '</td>'...`) แทนวิธีเดิมที่อาจพังเมื่อ `b.respiratory_rate` หรือ `b.spo2` เป็น `null`/`undefined` — โค้ดใหม่ใช้ ternary (`? :`) เช็คก่อนทุกจุด กัน error `Cannot read property of null`
- เขียนไฟล์ `docs/index.html` ทับกลับไปทันที

พูดง่าย ๆ คือ **"hotfix" ที่ผู้พัฒนาเขียนไว้ใช้แก้ปัญหา JS error ในหน้า breathing table ของ dashboard แบบเร่งด่วน** — ไม่ควรรันซ้ำเพราะจะไปหาสตริงเดิมที่ (อาจจะ) ถูกแก้ไปแล้วไม่เจอ

---

## 9️⃣ `README.md` — เอกสารภาพรวม

สรุปสั้น ๆ ของทั้งโปรเจกต์ ประกอบด้วย:
- ลิงก์ Live Dashboard (`https://aomeasy.github.io/coros-data-pipeline/`)
- แผนภาพ Architecture แบบย่อ (เหมือนที่สรุปไว้ด้านบนของเอกสารนี้)
- ตารางไฟล์หลัก 4 ไฟล์ (`coros_db.py`, `coros_daily_sync.py`, `docs/index.html`, `docs/data.json`)
- อธิบายว่า GitHub Actions จะ export `coros_cache.db` → `docs/data.json` ทุกครั้งที่ sync
- License: MIT

---

## 🔟 โฟลเดอร์ที่อ้างอิงจากโค้ด (อนุมานหน้าที่ได้ แม้เปิด raw ตรง ๆ ไม่ได้)

### `docs/` — หน้าเว็บ GitHub Pages
จากที่ตรวจสอบหน้า live dashboard (https://aomeasy.github.io/coros-data-pipeline/) พบว่าเป็น **Single Page Application** มีแท็บเมนู:
- Dashboard, Sleep, Recovery, Breathing, Journal, Activities, Weekly Report

ไฟล์ในนี้ที่ปรากฏชื่อในโค้ดที่อื่น:
- `docs/index.html` — หน้าหลักของ dashboard (มี JS ต่อ HTML table แบบ dynamic ตามที่ `fix_script.py` เข้าไปแก้)
- `docs/journal.html` — หน้าบันทึก journal (เชื่อมกับ `/api/journal` ใน `app.py`)
- `docs/data.json` — ข้อมูลที่ `export.py` สร้างขึ้น อ่านโดย JS ในหน้า `index.html` ตอนรันบน GitHub Pages (โหมด static ไม่มี backend)

### `templates/` 
โฟลเดอร์นี้ปรากฏใน repo แต่ไม่มีการอ้างอิงถึงโดยตรงใน Python ไฟล์ที่ตรวจสอบ (Flask app ใน `app.py` ใช้ `send_file` เสิร์ฟจาก `docs/` ไม่ได้ใช้ Flask template engine ผ่าน `render_template` จาก `templates/`) จึงคาดว่าเป็น **เทมเพลตสำรอง/ตัวช่วยออกแบบหน้าเว็บ** ที่อาจไม่ได้ใช้งานจริงใน production หรือใช้เป็น draft ก่อนย้ายไป `docs/`

### `.github/workflows/`
ไม่สามารถเปิด raw ได้ในตอนทำเอกสาร แต่ตาม README ระบุชัดว่า **"GitHub Actions exports `coros_cache.db` → `docs/data.json` on every sync"** และ `coros_daily_sync.py` มี comment ว่า "รันทุกวันผ่าน GitHub Actions" ดังนั้น workflow ในโฟลเดอร์นี้ควรมีลักษณะ:
- ตั้ง schedule แบบ cron (รันทุกวัน)
- ติดตั้ง Node.js (สำหรับ `npx coros-mcp`) + Python dependencies (`numpy` ที่ `sleep_analysis.py` ใช้)
- ตั้งค่า secrets `COROS_EMAIL` และ `COROS_PASSWORD` (ใช้ใน `coros_daily_sync.py`)
- รันลำดับ: `python coros_daily_sync.py` → `python export.py` → commit ไฟล์ `coros_cache.db` และ `docs/data.json` กลับเข้า repo (หรือ deploy ไปที่ branch/Pages)

### `coros_cache.db`
ไฟล์ SQLite ที่ **คอมมิตเข้า repo ตรง ๆ** (ไม่ได้อยู่ใน `.gitignore`) ซึ่งแปลว่าโปรเจกต์นี้ใช้ repo เองเป็นที่เก็บ "cache แบบถาวร" — ทุกครั้งที่ GitHub Actions รัน sync จะ commit ไฟล์นี้กลับเข้า repo ด้วย เพื่อให้ครั้งต่อไปที่ workflow รันมีข้อมูลเก่าอยู่ครบ (ไม่ต้องดึงประวัติทั้งหมดใหม่ทุกครั้ง)

---

## 🔑 สรุป Flow การทำงานแบบ End-to-End

1. **ทุกวัน** GitHub Actions trigger `coros_daily_sync.py`
2. สคริปต์ login เข้า COROS ผ่าน `coros-mcp` CLI แล้วดึงกิจกรรม 90 วัน + สุขภาพ 7 วันล่าสุด (เป็นข้อความ, parse ด้วย regex)
3. ข้อมูลที่ parse แล้วถูกเก็บผ่าน `coros_db.py` เข้า `coros_cache.db` (SQLite)
4. `export.py` อ่านจาก DB แปลงเป็น `docs/data.json` (พร้อมสรุปเมตริกพื้นฐาน)
5. Workflow commit `coros_cache.db` + `docs/data.json` กลับเข้า repo → GitHub Pages serve หน้า `docs/index.html` ที่อ่าน `data.json` แสดงผล
6. ถ้าผู้ใช้ต้องการดูผลวิเคราะห์เชิงลึก (recovery score, SQI, anomaly, journal correlation) ที่ static site ไม่มี ให้รัน `python app.py` แบบ local แทน — จะได้ endpoint `/api/analysis` ที่ประมวลผลผ่าน `sleep_analysis.py` + `breath_analysis.py` แบบเรียลไทม์ และยังสามารถบันทึก journal ผ่าน `docs/journal.html` → `/api/journal` ได้ด้วย

---

## 💡 ข้อสังเกตเชิงวิศวกรรมที่น่าสนใจ

- **ไม่พึ่ง AI/LLM ในการวิเคราะห์เลย** — ทุกสูตร (recovery score, SQI, anomaly detection, journal correlation) เป็น rule-based/สถิติล้วน ๆ ทำให้รันได้เร็ว ไม่มีค่าใช้จ่าย API และผลลัพธ์ทำนายซ้ำได้ (deterministic)
- **Static site กับ Dynamic server แยกกันชัดเจน**: `export.py` ทำสรุปพื้นฐานให้ static site เบา ๆ ส่วนการวิเคราะห์เชิงลึกสงวนไว้ให้ต้องรัน Flask local — เป็นการแลกเปลี่ยนระหว่างความสะดวก (ดูผ่านเว็บได้ทุกที่) กับความลึกของข้อมูล
- **การ parse ข้อมูลจาก text output ของ COROS-MCP** (ไม่ใช่ JSON ตรง ๆ) เป็นจุดที่เปราะบางที่สุดของระบบ เพราะพึ่งพา regex จับรูปแบบข้อความคงที่ — หาก COROS-MCP เปลี่ยน format ข้อความ จะกระทบ `coros_daily_sync.py` โดยตรง
- **Journal correlation ต้องมีข้อมูลสะสมพอสมควร** (≥3 record ต่อกลุ่มสำหรับ correlation, ≥30 วันสำหรับ baseline ที่มั่นใจได้) ทำให้ feature นี้จะ "ยังไม่มีข้อมูลเพียงพอ" ในช่วงเริ่มต้นใช้งาน
- ทุก threshold/weight ในสูตรวิเคราะห์ (เช่น recovery score weight 30/20/25/15%) เป็นค่าที่ผู้เขียนตั้งไว้เองแบบ **ยังไม่ผ่านการ calibrate ด้วยข้อมูลจริง** — เอกสาร `sleep analysis.md` ระบุไว้ตรง ๆ ว่าเป็นค่าตั้งต้นที่ควรปรับเมื่อมีข้อมูล ≥60 วัน
