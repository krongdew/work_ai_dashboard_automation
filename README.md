# Dashboard Factory

Multi-project AI dashboard automation for VS Code + GitHub Copilot Agent.

## เปิดใช้ระบบ

1. สร้าง Groq API key แล้วกำหนด `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b` และ `GROQ_FALLBACK_MODEL=llama-3.3-70b-versatile` ใน environment หรือ `.env` ที่ไม่ commit.
2. เปิด Terminal ที่โฟลเดอร์ repository และรัน:

```bash
source .venv/bin/activate
python factory-ui/app.py
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
4. เมื่อผลลัพธ์พร้อมเผยแพร่ ให้ push dashboard ที่สร้างใหม่:

```bash
git add projects/CASS
git commit -m "Update CASS dashboard data"
git push
```

GitHub Pages จะ deploy อัตโนมัติหลัง push ไฟล์ dashboard

มาตรฐานที่ระบบสร้างให้:
- Mahidol Faculty theme และตรามหาวิทยาลัยใน header
- animation ตอนเปิดหน้า โดยรองรับการลดการเคลื่อนไหวของระบบ
- คลิกแท่งกราฟเพื่อ cross-filter KPI, กราฟ และตาราง แล้วล้างได้
- เลือกปีงบประมาณเพื่อดู KPI เทียบปีก่อนด้วยลูกศรและเปอร์เซ็นต์
- แยก 3 แท็บ: บริการมีรายได้, บริการวิชาการแบบไม่ได้รายได้, และเปรียบเทียบงบประมาณ
# data_agentic_private
