# Dashboard Factory

Multi-project AI dashboard automation for VS Code + GitHub Copilot Agent.

## เริ่มใช้งานบนเครื่องตัวเอง

สำหรับผู้ใช้ที่ดาวน์โหลดจาก Git แล้วต้องการใช้เว็บ Factory กับ LM Studio
บนเครื่องของตัวเอง อ่าน [คู่มือติดตั้งแบบง่ายภาษาไทย](docs/local-quickstart-th.md)
มีขั้นตอนติดตั้งครั้งแรก การเปิดใช้ครั้งถัดไป และคำแนะนำสำหรับเครื่อง RAM 16 GB

## เปิดใช้ระบบ

### Local AI (LM Studio)

Dashboard specification generator ใช้ LM Studio ผ่าน OpenAI-compatible local
server ได้โดยไม่ต้องใช้ Groq API key หรือส่ง metadata ออกนอกเครื่อง

1. ใน LM Studio โหลด `Qwen/Qwen3-8B-GGUF` แบบ `Q4_K_M` แล้วไปที่
	**Developer > Start Server** โดยใช้พอร์ต `1234`.
2. สร้าง `data_factory/.env` จาก `local-ai/.env.example` แล้วตั้งค่า
	`AI_PROVIDER=local` และ `LMSTUDIO_MODEL` ให้ตรงกับชื่อที่หน้า
	**Developer > Models** แสดง.
3. ติดตั้ง dependency และทดสอบการเชื่อมต่อ:

```powershell
Set-Location D:\pactices\MULA_DataLink_php\data_factory
.\.venv\Scripts\Activate.ps1
python -m pip install -r local-ai\requirements.txt
python local-ai\test_lmstudio.py
```

เมื่อผลทดสอบแสดง `Local AI response received` ให้สร้าง specification ได้ดังนี้:

```powershell
python local-ai\generate_dashboard_spec.py `
  --profile projects\CASS\output\metadata\dataset-profile.json `
  --output projects\CASS\output\metadata\dashboard-spec.local-ai.json
```

ไม่จำเป็นต้องกำหนด `GROQ_API_KEY` เมื่อใช้ workflow นี้. รักษา `.env` ไว้นอก Git
และตรวจผลลัพธ์ `.local-ai.json` กับข้อมูลจริงก่อนนำไปใช้.

เมื่อสร้าง spec ผ่าน Factory UI ระบบจะสร้าง
`semantic-profile.local-ai.json` เพิ่มจาก `dataset-profile.json` ด้วย AI ใช้เฉพาะ
metadata ที่ลดข้อมูลแล้วเพื่อเสนอความหมายของคอลัมน์ หน่วย และแนวทาง aggregation;
ผลนี้เป็นคำแนะนำและต้องผ่าน data rules กับการตรวจ field ของระบบก่อนใช้สร้าง KPI
หรือกราฟ เมื่อ Data Profile เปลี่ยน ระบบจะสร้าง Semantic Profile ใหม่อัตโนมัติ.

การสร้างและแก้ไข dashboard ใช้ AI workflow เดียวกันทั้ง Local AI และ Groq: AI ขอ
ผล aggregate แบบจำกัดจากเครื่อง, Python คำนวณจากข้อมูลจริง, แล้ว AI ใช้ผลนั้นสร้าง
หรือแก้ specification. ตั้งค่าปีการศึกษา รูปแบบรหัสนักศึกษา GPAX risk และคำสั่ง
การคำนวณต่อ project ได้จากหน้าจอ **กฎการคำนวณ**. ดูโครงสร้าง, วิธีแก้ dashboard,
และแผนการพัฒนาต่อที่ [AI Calculation Workflow](docs/ai-calculation-workflow.md).

หน้าจอ **Metric Rule Library** มี template สำหรับอัตราสำเร็จการศึกษา กำไร
อัตราส่วน และสัดส่วนหมวดหมู่. ต้องระบุ field mapping, บันทึกเป็น draft และให้ผู้
ตรวจสอบอนุมัติก่อน; ระบบใช้เฉพาะกฎที่ approved และเก็บ snapshot version ไว้ใน
`output/metadata/calculation-rule-versions/` ของ project.

ก่อนสร้าง dashboard ระบบสร้าง analytical copy โดยไม่แก้ไฟล์ต้นฉบับ และใช้ AI เสนอ
mapping สำหรับ category/date value ที่ซ้ำกันอย่างชัดเจน เช่น `ช` -> `ชาย`. Mapping
ที่ไม่แน่ใจจะเป็น Notice ใน QA แทนการปรับข้อมูลเอง; สรุปปี วันที่ และตัวกรองบน
dashboard แสดงเป็น พ.ศ. เสมอ.

### สลับ Local AI และ Groq

กำหนด provider ที่ `data_factory/.env` แล้ว restart Factory UI ทุกครั้งที่เปลี่ยนค่า:

```dotenv
# ใช้โมเดลใน LM Studio
AI_PROVIDER=local

# หรือใช้ Groq
AI_PROVIDER=groq
GROQ_API_KEY=your_groq_key
```

ค่าอื่นของทั้งสอง provider เก็บไว้ใน `.env` เดียวกันได้; ระบบจะอ่านเฉพาะค่าของ
provider ที่เลือก และจะบันทึก `generated_by` ใน dashboard specification เป็น
`local-ai` หรือ `groq-ai` เพื่อบอกแหล่งที่สร้างผลลัพธ์.

### Groq API

1. สร้าง Groq API key แล้วกำหนด `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b` และ `GROQ_FALLBACK_MODEL=llama-3.3-70b-versatile` ใน environment หรือ `.env` ที่ไม่ commit.
2. ติดตั้ง Python 3.11+ และเลือกตัวเลือก **Add Python to PATH** ระหว่างติดตั้ง. เปิด Terminal ที่โฟลเดอร์ repository, สร้าง virtual environment และติดตั้ง dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python factory-ui/app.py
```

บน macOS หรือ Linux ใช้:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python factory-ui/app.py

deactivate
Set-Location D:\pactices\MULA_DataLink_php\data_factory
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python factory-ui\app.py
```

3. เปิด `http://127.0.0.1:5050` แล้วสร้างหรือเลือก project, อัปโหลดข้อมูล,
	กด Profile, Groq AI Suggest/Improve และ Build Dashboard ตามลำดับ.

ระบบสร้างหรือปรับ dashboard spec ผ่าน **Groq API** โดยค่าเริ่มต้นใช้ `openai/gpt-oss-120b` และ fallback เป็น `llama-3.3-70b-versatile`.
ระบบส่งเฉพาะ metadata ที่ลดข้อมูลแล้ว: ไม่ส่ง source files, raw records, example values,
identifier หรือ field PII. การคำนวณ KPI, การสร้าง dashboard และ QA ทำในเครื่องทั้งหมด.
API key อยู่ใน environment หรือ `.env` เท่านั้น และห้าม commit ลง repository.

Workflow:
1. Create or select a project.
2. Put Excel/CSV files into `projects/<project>/input/`.
3. Put optional `config.json` and `dashboard-request.md` in the project folder.
4. Ask Copilot Agent to run the dashboard automation.
5. Final dashboard is written to `projects/<project>/output/dashboard/`.

Do not put sensitive raw data into a public repository.

สร้าง dashboard ใหม่จาก projects/sales/input/sales.xlsx
ใช้ dashboard-automation skill
วิเคราะห์ข้อมูล ออกแบบ dashboard สร้าง dashboard และทำ QA ให้ครบ

อัปเดต dashboard sales จากข้อมูลใหม่ใน projects/sales/input
วิเคราะห์ข้อมูลใหม่ สร้าง dashboard ใหม่ และตรวจสอบ KPI

คำสั่งที่ใช้บ่อย
ดู Dashboard ทั้งหมด
แสดง dashboard ทั้งหมดใน projects
สร้างใหม่
สร้าง dashboard ใหม่จากไฟล์นี้
วิเคราะห์
วิเคราะห์ข้อมูลของ dashboard sales
อัปเดต
อัปเดต dashboard sales จากข้อมูลใหม่
ตรวจสอบ
ตรวจสอบ dashboard sales และทำ QA
เตรียม Publish
เตรียม dashboard sales สำหรับ publish


อัปเดต dashboard CASS จากข้อมูลใหม่ใน projects/CASS/input
วิเคราะห์ข้อมูลใหม่ สร้าง dashboard ใหม่ และตรวจสอบ KPI

## อัปเดต CASS รอบถัดไป

1. วางไฟล์ Excel หรือ CSV ใหม่ใน `projects/CASS/input/` โดยไม่แก้ไฟล์เก่า
	หากต้องการให้ข้อมูลใหม่แทนชุดเดิม ให้ย้ายไฟล์เดิมออกจากโฟลเดอร์ก่อน
	สำหรับ Tab 1 และ Tab 3 ให้ใช้ไฟล์ทะเบียนคุมงบประมาณของแต่ละปี; ระบบคำนวณกำไรเป็น `รายรับ - ค่าใช้จ่ายรวม` จากแต่ละรายการ
2. สั่ง Copilot Agent ด้วยข้อความนี้:

```text
ใช้ dashboard-automation skill
อัปเดต dashboard CASS จากข้อมูลใหม่ใน projects/CASS/input
วิเคราะห์ข้อมูลใหม่ สร้าง dashboard ใหม่ และตรวจสอบ KPI ให้ครบ
```

3. ตรวจสถานะใน `projects/CASS/output/qa/qa-report.json`
	หากมี critical error จะเป็น `NOT READY` และไม่ควรใช้ตัวเลขตัดสินใจ
	จนกว่าจะตรวจสอบข้อมูลต้นทาง
4. รันคำสั่งนี้เพื่อสร้าง DataLink Bundle และ Publish Package ของ HTML output เดิม:

```powershell
python projects\CASS\working\create_datalink_bundle.py
```

5. ใน DataLink Dashboard Library ให้นำเข้า `projects/CASS/output/CASS-DataLink-Bundle.zip`, อนุมัติ Dataset และอนุมัติ Dashboard version ใหม่ก่อนเปิดใช้งาน. Bundle มี HTML output เดิมอยู่แล้ว จึงแสดง tab, chart, filter และธีม CASS ครบโดยไม่ต้องนำเข้า Publish Package เพิ่ม.
6. เมื่อผลลัพธ์พร้อมเผยแพร่ ให้ push dashboard ที่สร้างใหม่:

```bash
git add projects/CASS
git commit -m "Update CASS dashboard data"
git push
```

GitHub Pages จะ deploy อัตโนมัติหลัง push ไฟล์ dashboard

มาตรฐานที่ระบบสร้างให้:
# data_agentic_private
