# COROS Data Pipeline — Professional Development Roadmap
### แผนพัฒนาสู่แพลตฟอร์มวิเคราะห์สุขภาพระดับ Whoop-grade

> อ้างอิงจากโค้ดปัจจุบันใน `aomeasy/coros-data-pipeline`:
> - Sync อัตโนมัติทุกเช้าผ่าน GitHub Actions (`coros_daily_sync.py`)
> - เก็บข้อมูลใน SQLite (`activities`, `sleep_data`, `daily_health`, `journal_entries`)
> - มี `sleep_analysis.py` (rule-based) ที่ทำ sleep efficiency, baseline z-score, recovery score, SQI, sleep debt, journal correlation, anomaly detection อยู่แล้ว — ถือว่า**แข็งแรงระดับ MVP ของฝั่ง Sleep**
> - มี `breath_analysis.py`, Flask `app.py` (`/api/analysis`, `/api/journal`, `/api/sync`) และ static dashboard บน GitHub Pages
>
> จุดที่ยังขาดเมื่อเทียบกับ Whoop/Oura ระดับ professional: **Strain/Load Engine, Training Readiness, Personalized Adaptive Baseline, Illness/Overtraining Detection แบบ multi-signal, Narrative AI Insight, Data Quality Layer, Testing/Observability** — แผนนี้ออกแบบมาเพื่ออุดช่องว่างเหล่านั้นทีละ phase โดยไม่ทุบของเดิมที่ทำงานอยู่แล้ว

---

## หลักการออกแบบ (Design Principles)

1. **Backward-compatible เสมอ** — ทุก phase ต้องรันคู่กับ `coros_daily_sync.py` เดิมได้ ไม่ทำให้ pipeline เช้าพัง
2. **Rule-based ก่อน ML ทีหลัง** — ยึดแนวทางเดิม (ไม่พึ่ง AI API สำหรับ core metric) แล้วค่อยเพิ่มชั้น AI สำหรับ "narrative" และ "personalization" เท่านั้น
3. **Baseline ต้องเป็น per-user, adaptive, และมี confidence interval** ไม่ใช่ threshold ตายตัว
4. **ทุก score ต้องอธิบายได้ (explainable)** — ห้ามเป็น black box เพราะผู้ใช้ต้องเชื่อใจตัวเลขเพื่อปรับพฤติกรรม
5. **แยก Data Layer / Analytics Layer / Presentation Layer ให้ชัด** เพื่อให้ทดสอบและสลับ frontend ได้ในอนาคต

---

## Phase 0 — Audit & Hardening ฐานราก (1 สัปดาห์)
**เป้าหมาย:** ปิดความเสี่ยงของระบบที่รันอัตโนมัติทุกวันอยู่แล้ว ก่อนต่อยอด feature ใหม่

- [ ] ตรวจสอบ error handling ใน `coros_daily_sync.py`: กรณี COROS API timeout / login หมดอายุ / rate limit → ต้อง retry + alert ไม่ใช่ fail เงียบ
- [ ] เพิ่ม **data validation layer**: เช็คว่าค่าที่ sync มาสมเหตุสมผล (เช่น HRV ไม่ติดลบ, sleep duration ไม่เกิน 16 ชม., SpO2 อยู่ในช่วง 70–100)
- [ ] เพิ่ม logging แบบมีโครงสร้าง (JSON log) พร้อม log level และเก็บ log การ sync แต่ละวันไว้ตรวจย้อนหลัง
- [ ] เขียน `schema_version` ใน SQLite + migration script เบื้องต้น เพื่อรองรับการเพิ่มคอลัมน์ใน phase ถัดไปโดยไม่พังของเก่า
- [ ] เพิ่ม unit test ชุดแรกให้ `sleep_analysis.py` (มี logic เยอะแล้วแต่ยังไม่มี test) ด้วย `pytest` — เริ่มจากฟังก์ชัน pure function: `sleep_efficiency`, `z_score`, `calculate_sqi`, `cumulative_sleep_debt`
- [ ] ตั้ง GitHub Actions ให้รัน test suite ทุกครั้งที่ push (CI ขั้นต่ำ)

**Deliverable:** pipeline เดิมยังรันทุกเช้าได้เหมือนเดิม + มี safety net (test, log, validation) รองรับการแก้โค้ดถี่ขึ้นใน phase ต่อไป

---

## Phase 1 — Personalized Adaptive Baseline Engine (1–2 สัปดาห์)
**เป้าหมาย:** ยกระดับจาก "baseline คงที่ 30 วันล่าสุด" (ของเดิมใน `compute_baseline`) ไปเป็นระบบ baseline ที่ฉลาดแบบที่ Whoop/Oura ใช้จริง

- [ ] เปลี่ยนจาก simple rolling mean/stdev → **Exponentially Weighted Moving Average (EWMA)** ที่ให้น้ำหนักข้อมูลล่าสุดมากกว่า พร้อม half-life ปรับได้ต่อ metric (เช่น RHR half-life 7 วัน, HRV half-life 14 วัน)
- [ ] เพิ่ม **minimum data requirement + confidence band**: ถ้าข้อมูล < 14 วัน ให้ label ว่า `baseline_confidence: "building"` และไม่ฟันธง status ที่รุนแรง (critical) จนกว่าจะมีข้อมูลพอ
- [ ] แยก baseline ตาม **context** เช่น HRV วันธรรมดา vs วันหลังแข่ง/หลัง hard training (ลด false alarm)
- [ ] เพิ่มการแปลง HRV แบบ **ln(RMSSD)** ก่อนคำนวณ z-score (มาตรฐานงานวิจัย sleep/HRV เพราะ HRV ดิบมีการกระจายแบบ log-normal ไม่ใช่ normal)
- [ ] เก็บ baseline history ลงตาราง `baselines_daily` (ไม่ compute ใหม่ทุกครั้งที่เรียก API) เพื่อให้ดู trend ของ baseline เองได้ (baseline drift = สัญญาณ fitness เปลี่ยนระยะยาว)

**Deliverable:** ทุก z-score / anomaly ใน `sleep_analysis.py` วิ่งบน baseline ที่แม่นยำและมี confidence ชัดเจนขึ้น ลด false positive ของ anomaly เดิม

---

## Phase 2 — Recovery Score v2 + Strain/Load Engine (2–3 สัปดาห์)
**เป้าหมาย:** นี่คือหัวใจของ "แบบ Whoop" — ตอนนี้มีแค่ Recovery ฝั่งเดียว ยังขาด **Strain** (ภาระที่ร่างกายได้รับ) ซึ่งต้องคู่กันเสมอ

### 2.1 Recovery Score v2
- [ ] Refactor `recovery_score()` เดิมให้ดึง weight (HRV 30% / RHR 20% / Sleep Perf 25% / Sleep Eff 15% / SpO2-Temp 10%) มาจาก config ที่ปรับได้ ไม่ hardcode
- [ ] เพิ่มสัญญาณ **Respiratory Rate trend** และ **Skin Temp deviation ต่อเนื่องหลายวัน** เป็น input จริง (ตอนนี้มี param แต่ยังไม่ได้ผูกจากข้อมูลจริงใน `app.py`)
- [ ] เพิ่ม **Training Load ล่าสุดเป็น input** ของ Recovery (ไม่ใช่แค่ผลลัพธ์) — โหลดหนักเมื่อวานควรลด recovery คาดการณ์ของวันนี้ก่อนแม้ยังไม่เห็นผลใน HRV

### 2.2 Strain Engine (ของใหม่ทั้งหมด)
- [ ] ออกแบบ **Day Strain (0–21 scale แบบ Whoop หรือจะกำหนด scale เองก็ได้)** จาก HR-zone time-in-zone ตลอดวัน (ไม่ใช่แค่ตอนออกกำลังกาย):
  - ดึง HR ต่อเนื่องทั้งวันจาก COROS (ถ้า API มี) → แบ่งเป็น 5 zone ตาม %HRmax
  - ใช้สูตรแบบ cumulative algorithmic (logarithmic, ยิ่งเวลาอยู่ zone สูงนานยิ่งเพิ่ม strain แบบเร่ง)
- [ ] เพิ่ม **Acute:Chronic Workload Ratio (ACWR)** = (ค่าเฉลี่ย 7 วัน) / (ค่าเฉลี่ย 28 วัน) — ตัวเลขมาตรฐานวงการกีฬาสำหรับเตือนความเสี่ยงบาดเจ็บ (ACWR > 1.5 = high risk)
- [ ] สร้างตาราง `daily_strain` เก็บ strain, TRIMP (Training Impulse), และ ACWR รายวัน
- [ ] เชื่อม Strain ↔ Recovery: แสดงเป็นคู่กันเสมอ (เหมือน Whoop ที่บอก "วันนี้ strain เท่านี้ recovery คุณรับไหวไหม")

**Deliverable:** ระบบมี "สองแกนหลัก" ครบแบบ Whoop คือ Recovery (พร้อมแค่ไหน) + Strain (ใช้ไปเท่าไหร่) ไม่ใช่แค่วิเคราะห์การนอนเดี่ยวๆ

---

## Phase 3 — Sleep Intelligence Deep Dive (2 สัปดาห์)
**เป้าหมาย:** ต่อยอด `sleep_analysis.py` ที่มีอยู่แล้วให้ลึกและ actionable กว่าเดิม

- [ ] ปรับ `calculate_sleep_need()` ให้เป็น **dynamic model จริง**: ผูกกับ strain สะสม 3 วันล่าสุด (ตอนนี้รับ param `training_load` แต่ยังไม่มี source ข้อมูลจริงจาก Phase 2)
- [ ] เพิ่ม **Nap tracking & integration** เข้า sleep debt calculation
- [ ] ขยาย `estimate_cycles()` ให้ใช้ raw stage-timeline จริงจาก COROS (ถ้า API ส่ง timeline ระดับนาทีได้) แทนการประมาณหยาบ
- [ ] เพิ่ม **Sleep Consistency แบบ circadian**: ไม่ใช่แค่ stdev ของเวลาเข้านอน แต่รวม wake time ด้วย และให้คะแนนแบบ weighted ต่อ 14 วันล่าสุด
- [ ] สร้าง **Sleep Coach Recommendation Engine**: กฎ if-then จาก anomaly + journal correlation ที่มีอยู่แล้ว เช่น
  - ถ้า `alcohol_units` correlate กับ deep sleep ลดลง > 10% → แสดงคำแนะนำเจาะจงคน
  - ถ้า bedtime consistency ต่ำ 3 วันติด → แนะนำ target bedtime ที่คำนวณจาก pattern ที่ดีที่สุดของผู้ใช้เอง
- [ ] ทำ **Weekly/Monthly Sleep Report แบบ PDF** (ต่อยอด `generate_weekly_report()` เดิมที่เป็น text) ให้เป็นรายงานกราฟิกจริง

**Deliverable:** Sleep module จาก "วิเคราะห์ค่า" กลายเป็น "โค้ชแนะนำพฤติกรรม" ที่อ้างอิงจากข้อมูลของผู้ใช้เองจริงๆ

---

## Phase 4 — Training & Performance Analytics (2–3 สัปดาห์)
**เป้าหมาย:** ใช้ข้อมูล `activities` ที่เก็บอยู่แล้วให้เกิดประโยชน์เชิงวิเคราะห์สมรรถภาพ ไม่ใช่แค่ log

- [ ] คำนวณ **CTL/ATL/TSB (Fitness/Fatigue/Form)** แบบ TrainingPeaks-style จาก training load รายวัน (EWMA 42 วัน / 7 วัน)
- [ ] Trend ของ **VO2max, Running Economy, Pace ที่ HR เดียวกัน** (aerobic decoupling) เพื่อดู fitness ดีขึ้นจริงไหมโดยไม่ต้องพึ่งแค่ตัวเลขที่ COROS สรุปมาให้
- [ ] **Race/Event Readiness Score**: รวม Recovery + Fitness (CTL) + Sleep debt สะสม ให้คะแนนความพร้อมก่อนแข่งหรือ hard session
- [ ] Correlate **Strain วันนี้ ↔ Performance วันถัดไป** (lag correlation คล้ายที่ `correlate_load_vs_sleep` ทำกับ deep sleep อยู่แล้ว แต่ขยายไปที่ pace/power)

**Deliverable:** จากระบบ "ดูแลสุขภาพ" ขยายเป็น "ระบบวางแผนการซ้อม" ที่บอกได้ว่าซ้อมหนักไปหรือเบาไปเทียบกับเป้าหมาย

---

## Phase 5 — Multi-Signal Illness & Overtraining Detection (1–2 สัปดาห์)
**เป้าหมาย:** อัปเกรด `detect_anomalies()` เดิม (เช็คทีละ metric) ให้เป็น **composite early-warning system**

- [ ] สร้าง **Illness Risk Score**: รวมสัญญาณพร้อมกัน (RHR สูงผิดปกติ + HRV ต่ำ + skin temp สูง + respiratory rate สูง) — ถ้าเกิดพร้อมกัน ≥ 3 สัญญาณ ความเชื่อมั่นสูงกว่าเช็คทีละตัว มาก (ลด false positive)
- [ ] สร้าง **Overtraining/Non-functional Overreaching Flag**: ACWR สูงต่อเนื่อง + HRV แนวโน้มลดระยะยาว (ไม่ใช่แค่วันเดียว) + Recovery ต่ำติดกัน ≥ 4 วัน
- [ ] เพิ่ม **alert channel**: ส่งแจ้งเตือนผ่าน LINE Notify / Telegram Bot / Email เมื่อ risk score เกิน threshold (ให้เลือก config ได้)
- [ ] เก็บ log การแจ้งเตือนไว้ตรวจสอบย้อนหลังว่าระบบแม่นแค่ไหน (สร้าง feedback loop เพื่อ tune threshold)

**Deliverable:** ระบบเตือนล่วงหน้าที่แม่นยำขึ้นกว่าการเช็คทีละ metric และแจ้งเตือนถึงมือถือได้จริง ไม่ต้องเปิดเว็บดู

---

## Phase 6 — Narrative AI Insight Layer (1–2 สัปดาห์)
**เป้าหมาย:** เพิ่มชั้น AI *บนสุด* ของระบบ rule-based เดิม (ไม่แทนที่) เพื่อแปลตัวเลขเป็นภาษาคน

- [ ] ใช้ Claude API (ผ่าน Anthropic API) สร้าง **Daily Narrative Summary**: ป้อนผลลัพธ์ทั้งหมดจาก Recovery/Strain/Sleep/Anomaly (เป็น structured JSON ที่ระบบ rule-based สร้างไว้แล้ว) ให้ AI เรียบเรียงเป็นข้อความอ่านง่าย พร้อมคำแนะนำเชิงปฏิบัติ 1–2 ข้อ
- [ ] **สำคัญ:** AI ห้ามคำนวณตัวเลขเอง (ป้องกัน hallucination) — มีหน้าที่แค่ "อธิบาย" ผลลัพธ์ที่ rule-based engine คำนวณมาแล้วเท่านั้น
- [ ] เพิ่ม **Weekly Coaching Digest**: สรุปแนวโน้ม 7/30 วัน พร้อมจุดที่ดีขึ้น/แย่ลง และปัจจัยจาก journal ที่มีผลมากที่สุด (ต่อยอด `rank_journal_impacts`)
- [ ] ทำ cache ผลลัพธ์ AI ไว้ (ไม่เรียก API ซ้ำถ้าข้อมูลไม่เปลี่ยน) เพื่อคุมต้นทุน

**Deliverable:** Dashboard พูดภาษาคนได้ ไม่ใช่แค่ตัวเลข/กราฟ — จุดขายหลักที่ทำให้ต่างจาก dashboard ทั่วไป

---

## Phase 7 — Dashboard & UX Overhaul (2–3 สัปดาห์)
**เป้าหมาย:** ยกระดับ `docs/index.html` ให้สื่อสารข้อมูลเชิงลึกที่สร้างมาทั้งหมดได้จริง

- [ ] ออกแบบหน้า **Today View** แบบ Whoop: Recovery ring (สี green/yellow/red) + Strain ring คู่กันตรงกลางจอ
- [ ] เพิ่ม **Trend view** แบบ interactive (7/30/90 วัน) สำหรับ HRV, RHR, Sleep Performance, Strain, CTL/ATL/TSB — ใช้ไลบรารี chart ที่ smooth และรองรับ mobile
- [ ] หน้า **Insight Feed**: รวม anomaly, AI narrative, journal correlation เป็น timeline เดียว อ่านง่ายแบบ social feed
- [ ] ปรับให้ mobile-first (ปัจจุบันเป็น static GitHub Pages — ตรวจสอบ responsive ให้ใช้งานบนมือถือได้ลื่นเพราะเป็นที่ที่คนดูข้อมูลสุขภาพบ่อยที่สุด)
- [ ] เพิ่ม dark mode (เข้ากับ theme สุขภาพ/กีฬา)

**Deliverable:** UI ที่สื่อสาร insight เชิงลึกทั้งหมดได้ในแวบเดียว ไม่ต้องไล่อ่าน JSON

---

## Phase 8 — Data Platform Maturity & Observability (1–2 สัปดาห์, ต่อเนื่อง)
**เป้าหมาย:** ทำให้ระบบดูแลตัวเองได้ระยะยาวโดยไม่ต้องคอยเช็คมือ

- [ ] เพิ่ม **data completeness dashboard**: แสดงว่าวันไหน sync พลาด/ข้อมูล field ไหนหาย เพื่อไม่ให้ analysis เพี้ยนแบบไม่รู้ตัว
- [ ] ทำ **backup อัตโนมัติของ `coros_cache.db`** (เช่น commit เป็น artifact หรือ sync ไป cloud storage) กัน DB เสียหาย
- [ ] เพิ่ม test coverage ให้ครอบคลุม `breath_analysis.py`, `coros_db.py`, และ API endpoints ใน `app.py` (integration test)
- [ ] เขียน **ADR (Architecture Decision Records)** สั้นๆ ทุกครั้งที่ตัดสินใจเชิงสถาปัตยกรรมใหญ่ เพื่อให้กลับมาอ่านทวนได้ภายหลัง
- [ ] อัปเดต README ให้มี architecture diagram ใหม่ที่รวม Strain Engine, AI Layer, Alert system เข้าไปด้วย

**Deliverable:** โปรเจคที่ maintain ได้ระยะยาวคนเดียว ไม่ต้องกลัว "แก้ตรงนี้แล้วพังตรงโน้น"

---

## ภาพรวม Timeline (โดยประมาณ)

| Phase | หัวข้อ | ระยะเวลาโดยประมาณ | Priority |
|---|---|---|---|
| 0 | Audit & Hardening | 1 สัปดาห์ | 🔴 ต้องทำก่อน |
| 1 | Adaptive Baseline Engine | 1–2 สัปดาห์ | 🔴 สูง |
| 2 | Recovery v2 + Strain Engine | 2–3 สัปดาห์ | 🔴 สูงสุด (หัวใจของ "แบบ Whoop") |
| 3 | Sleep Intelligence Deep Dive | 2 สัปดาห์ | 🟠 สูง |
| 4 | Training & Performance Analytics | 2–3 สัปดาห์ | 🟡 กลาง |
| 5 | Illness/Overtraining Detection | 1–2 สัปดาห์ | 🟠 สูง |
| 6 | Narrative AI Insight | 1–2 สัปดาห์ | 🟡 กลาง |
| 7 | Dashboard & UX Overhaul | 2–3 สัปดาห์ | 🟠 สูง |
| 8 | Platform Maturity | ต่อเนื่อง | 🟢 ทำคู่ขนานตลอด |

**รวม MVP "professional-grade" ถึงประมาณ Phase 5:** ราว 8–12 สัปดาห์ทำงานแบบ part-time

---

## Metric Glossary (อ้างอิงเร็ว)

| Metric | ความหมาย | ใช้ที่ Phase |
|---|---|---|
| HRV (lnRMSSD) | ความแปรปรวนของจังหวะหัวใจ, log-transform เพื่อ normal distribution | 1, 2 |
| RHR | Resting Heart Rate | 1, 2 |
| SQI | Sleep Quality Index (0–100) | มีอยู่แล้ว, ปรับใน 3 |
| ACWR | Acute:Chronic Workload Ratio — ตัวชี้วัดความเสี่ยงบาดเจ็บจากโหลดที่เพิ่มเร็วเกินไป | 2, 4 |
| CTL/ATL/TSB | Chronic/Acute Training Load, Training Stress Balance (Fitness/Fatigue/Form) | 4 |
| Day Strain | ภาระสะสมทั้งวันจาก time-in-HR-zone | 2 |
| Recovery Score | ความพร้อมของร่างกายวันนี้ (composite, มีอยู่แล้ว) | ปรับใน 2 |

---

*เอกสารนี้เป็น living document — แนะนำให้ทบทวนทุกจบ phase และปรับ timeline ตามเวลาที่ใช้จริง*
