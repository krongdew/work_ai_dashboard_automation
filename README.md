# Dashboard Factory

ระบบสร้าง **Dashboard อัตโนมัติจากไฟล์ Excel/CSV** สำหรับหน่วยงานที่บุคลากร
ไม่จำเป็นต้องมีทักษะด้านข้อมูล — แค่ **อัปโหลดไฟล์** ระบบจะทำความสะอาดข้อมูล
ที่ยุ่งเหยิงให้กลายเป็น master data ที่ถูกต้อง แล้ววางแผนและสร้าง dashboard
ที่คำนวณตัวเลขด้วย Python ทั้งหมด พร้อมตรวจ QA ก่อนนำไปใช้

หลักการสำคัญ: **AI วางแผนเท่านั้น — Python คำนวณตัวเลขทุกตัว** ตัวเลขบน dashboard
จึงตรวจสอบย้อนกลับได้ ไม่ได้มาจากการเดาของโมเดล

---

## ระบบทำอะไร (ภาพรวม)

```
อัปโหลดไฟล์เละ ──► ทำความสะอาด ──► Profile ──► AI วางแผน ──► Python คำนวณ+QA ──► ดู/แก้/ส่งออก
  (Excel/CSV)      (ต้นน้ำ)        (ไม่ใช้ AI)   (metadata)   (source of truth)    (dashboard)
```

| ขั้น | ทำอะไร | ใช้ AI? |
|---|---|---|
| **1. Upload** | รับไฟล์ Excel/CSV เข้า project | — |
| **2. ทำความสะอาด (ต้นน้ำ)** | forward-fill merge cell, รวม header หลายชั้น, กรอง total row, ตัด junk column, ล้าง Excel error (`#REF!`), trim ช่องว่าง — อัตโนมัติทุกไฟล์ | — |
| **3. Profile** | หา header จริง, แยก field role (measure/date/category/identifier), ตรวจ null/distinct/duplicate, แปลงวันเป็น พ.ศ. | ไม่ใช้ (deterministic) + AI เสริมตั้งชื่อคอลัมน์กำกวม |
| **4. AI Plan** | วางแผน KPI / charts / filters จาก **metadata เท่านั้น** (allowlist ของ field) | ✅ |
| **5. Python + QA** | คำนวณ KPI/กราฟจริงด้วย Python, ตรวจ QA 7 ด้าน, สร้าง `dashboard/index.html` | ไม่ใช้ (source of truth) |
| **6. View / Export** | ดู dashboard, สั่งแก้แผนเป็นภาษาไทย (Improve), ดาวน์โหลด DataLink Bundle | ✅ (เฉพาะตอนแก้แผน) |

**ความเป็นส่วนตัว:** ส่งให้ AI เฉพาะ metadata ที่ลดข้อมูลแล้ว (ชื่อ field, ชนิด,
บทบาท) — **ไม่ส่ง raw records, ไฟล์ต้นฉบับ, ค่า PII หรือ identifier** ขึ้น cloud
การคำนวณ การสร้าง dashboard และ QA ทำในเครื่องทั้งหมด

---

## หน้าจอผู้ใช้ (2 โหมด)

หลัง login (Google OAuth) ผู้ใช้สลับได้ 2 โหมดในเว็บเดียวกัน:

- **หน้าปกติ** — React SPA (Ant Design): สร้าง Dashboard, Dashboard ทั้งหมด,
  จัดการระบบ, คู่มือ
- **เมือง Workflow 3D** — ฉาก Three.js แบบ interactive แสดง workflow เป็นเมือง
  โรงงานการ์ตูน 6 อาคาร (Login → Upload → Profile → AI Plan → Python+QA →
  View/Export) พร้อมตัวละคร "Factory Buddies" เดินส่งงานระหว่างบ้าน และวงรอบ
  **Improve** (6→4→5→6) ที่ผ่านขั้นคำนวณ+QA เสมอ

---

## AI แบบ Hybrid (Local / Groq)

รองรับทั้งโมเดลในเครื่องและคลาวด์ สลับได้ที่ `.env`:

- **Local (LM Studio)** — รันผ่าน OpenAI-compatible server ในเครื่อง ไม่ต้องใช้ API
  key ไม่ต้องต่อเน็ต เหมาะกับข้อมูลที่ต้องอยู่ในองค์กร
- **Groq Cloud** — เร็ว เหมาะกับงานวางแผนที่ต้องการโมเดลใหญ่ (`openai/gpt-oss-120b`,
  fallback `llama-3.3-70b-versatile`)

```dotenv
# ใช้โมเดลในเครื่อง (LM Studio)
AI_PROVIDER=local
LMSTUDIO_MODEL=qwen2.5-3b-instruct-mlx

# หรือใช้ Groq
AI_PROVIDER=groq
GROQ_API_KEY=your_groq_key
```

ระบบจะบันทึก `generated_by` ใน spec เป็น `local-ai` หรือ `groq-ai` เพื่อบอกแหล่งที่มา
เมื่อต้นน้ำสะอาดดีพอ โมเดล local ขนาดเล็กก็วางแผน dashboard ได้โดยไม่ต้องพึ่งคลาวด์

---

## ติดตั้งและรัน

ต้องมี **Python 3.11+** และ (ถ้าจะแก้ frontend) **Node.js 20+**

```bash
# 1) backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 2) สร้าง .env จากตัวอย่าง แล้วตั้งค่า AI_PROVIDER
cp local-ai/.env.example .env      # หรือสร้างเองตามหัวข้อ Hybrid ด้านบน

# 3) (ถ้าใช้ local) ติดตั้ง dependency ฝั่ง local-ai แล้วทดสอบ LM Studio
python -m pip install -r local-ai/requirements.txt
python local-ai/test_lmstudio.py

# 4) รัน Factory
python factory-ui/app.py
```

เปิด **http://127.0.0.1:5050** → login → สร้าง/เลือก project → อัปโหลดไฟล์ →
ตรวจโครงสร้าง (Profile) → สร้าง Dashboard → ดูผล / Improve / Export

### แก้ไข frontend (ถ้าต้องการ)

React SPA + เมือง 3D อยู่ที่ `factory-ui-react/` build ลงที่ Flask static dir:

```bash
cd factory-ui-react
npm install
npm run build        # -> factory-ui/static/dist/  (Flask เสิร์ฟให้อัตโนมัติ)
npm run dev          # โหมดพัฒนา (proxy ไป :5050)
```

---

## โครงสร้างโปรเจกต์

```
factory-ui/            Flask backend (pipeline + API + เสิร์ฟ SPA)
  app.py               ต้นน้ำ (ทำความสะอาด) + profile + AI plan + build + QA
  static/city/         เมือง Workflow 3D (standalone Three.js)
factory-ui-react/      React SPA (Ant Design) — หน้าปกติ + ฝังเมือง 3D (/city)
local-ai/              ไคลเอนต์ LM Studio + schema + ตัวอย่าง .env
rules/                 data / qa / dashboard / analysis rules
docs/                  คู่มือติดตั้งภาษาไทย, AI calculation workflow ฯลฯ
projects/              ⚠️ ข้อมูลจริงของแต่ละ project — ไม่ commit (เหลือแค่ _template)
```

> **ข้อมูลใน `projects/` เป็นข้อมูลจริง ไม่ถูก track ใน git** (ดู `.gitignore`)
> เก็บเฉพาะ `projects/README.md` และ `projects/_template/` เป็นโครงไว้เท่านั้น
> ห้ามนำข้อมูลดิบที่อ่อนไหวขึ้น public repository

---

## QA และความถูกต้อง

ก่อนใช้งาน ระบบตรวจ QA 7 ด้าน (records, identifier exclusion, duplicates,
missing, date parse, calculation, normalization) และเขียนผลที่
`projects/<project>/output/qa/qa-report.json` — หากมี critical error สถานะจะเป็น
`NOT READY` ไม่ควรใช้ตัวเลขตัดสินใจจนกว่าจะตรวจข้อมูลต้นทาง

สรุปปี วันที่ และตัวกรองบน dashboard แสดงเป็น **พ.ศ.** เสมอ

---

## เอกสารเพิ่มเติม

- [คู่มือติดตั้งแบบง่าย (ภาษาไทย)](docs/local-quickstart-th.md)
- [AI Calculation Workflow](docs/ai-calculation-workflow.md)
- [คู่มือผู้ใช้ (ภาษาไทย)](docs/user-manual-th.md)
