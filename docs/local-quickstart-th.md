# ติดตั้ง Dashboard Factory จาก Git บนเครื่องตัวเอง

สำหรับเพื่อนที่ต้องการอัปโหลดข้อมูล สร้าง Dashboard และใช้ Local AI ของตัวเอง
ทุกอย่างรันบนเครื่องเพื่อน ไม่ต้องติดตั้งระบบ LAN, Worker, HTTPS หรือเปิด Firewall
และไม่ต้องรัน Angular, NestJS, PostgreSQL หรือระบบ DataLink ส่วนกลาง

## 1. ติดตั้งโปรแกรมครั้งแรก

- Python 3.11 ขึ้นไป: https://www.python.org/downloads/ เลือก **Add Python to PATH**
- Git: https://git-scm.com/downloads
- LM Studio: https://lmstudio.ai/download

ปิดแล้วเปิด PowerShell ใหม่ ตรวจด้วย `python --version` และ `git --version`
ถ้า Windows เปิด Microsoft Store แทน Python ให้ตรวจ PATH/การติดตั้ง Python ก่อน

## 2. ดาวน์โหลดโค้ด

เปิด PowerShell ในโฟลเดอร์ที่ต้องการเก็บโปรแกรม เช่น Documents แล้วใช้:

```powershell
git clone https://github.com/krongkwanbua/data_agentic_private.git
Set-Location data_agentic_private
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

หาก repository เป็น private เจ้าของต้องเชิญบัญชี GitHub ของเพื่อนก่อน
ไม่ต้องคัดลอก `.venv` จากเครื่องคนอื่น ให้สร้างใหม่ตามคำสั่งข้างบน
ถ้าใช้ GitHub → Code → Download ZIP ให้แตก ZIP แล้วเปิด PowerShell ในโฟลเดอร์
ที่มี `requirements.txt` จากนั้นเริ่มที่คำสั่ง `python -m venv .venv`

**สำหรับเจ้าของโปรเจค:** Factory เป็น Git repository แยกใน `data_factory/`
ต้อง commit/push โค้ดและคู่มือฉบับนี้ใน repository นั้นก่อน เพื่อนจึงจะดาวน์โหลด
เวอร์ชันที่แก้ภาษาแล้วได้ การแก้ไฟล์บนเครื่องอย่างเดียวยังไม่ทำให้ GitHub อัปเดต
ตรวจ diff และเลือกเฉพาะ source/docs ที่ต้องการ อย่ารวม `.env`, `.venv`, `.lan`,
ข้อมูลนำเข้า หรือ output ของโปรเจคส่วนตัวไปด้วย

## 3. เปิดโมเดลใน LM Studio

1. ค้นหา `Qwen3.5-14B-A3B-Claude-4.6-Opus-Reasoning-Distilled-reap`
2. เลือกไฟล์ **GGUF Q4_K_M** ตัวอย่างไฟล์มีขนาดประมาณ 8.7 GB:
   https://huggingface.co/brunopio/Qwen3.5-14B-A3B-Claude-4.6-Opus-Reasoning-Distilled-reap-Q4_K_M-GGUF/tree/main
3. สำหรับ RAM 16 GB เริ่มที่ **Context Length = 8192**, **Parallel = 1**
   และโหลดโมเดลเพียงตัวเดียว เปิดโปรแกรมอื่นให้น้อยที่สุด
4. ไปหน้า Developer และ **Start Server** ที่ `127.0.0.1:1234`
5. คัดลอก **Model Identifier** ที่ API แสดง เพื่อใช้ในขั้นตอนถัดไป

ไม่ต้องเปิด Serve on Local Network หากเครื่องมีการ์ดจอแยกให้เริ่มจากการเลือก
GPU offload อัตโนมัติของ LM Studio หากมีเฉพาะการ์ดจอออนบอร์ด หน่วยความจำ GPU
อาจแชร์ RAM จึงไม่นับว่าเป็นหน่วยความจำเพิ่มอีกก้อนหนึ่ง

## 4. ตั้งค่า Factory ครั้งแรก

จากโฟลเดอร์เดิม สร้าง `.env` เฉพาะกรณียังไม่มีไฟล์:

```powershell
Copy-Item local-ai\.env.example .env
notepad .env
```

ตั้งค่าหลักดังนี้ โดยแทน `MODEL_IDENTIFIER` ด้วยค่าที่คัดลอกจาก LM Studio:

```dotenv
FACTORY_MODE=local
AI_PROVIDER=local
LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
LMSTUDIO_MODEL=MODEL_IDENTIFIER
LMSTUDIO_API_KEY=lm-studio
LMSTUDIO_TIMEOUT=720
LMSTUDIO_MAX_TOKENS=2048
```

`LMSTUDIO_MAX_TOKENS` จำกัดความยาวคำตอบ ไม่ใช่ context ทั้งหมด โมเดลต้องมีพื้นที่
สำหรับ prompt และคำตอบรวมกัน ค่า 2048 เป็นจุดเริ่มสำหรับ spec ขนาดเล็กเท่านั้น
หากสร้างกราฟหลายตัวแล้ว JSON ถูกตัด ให้ลอง 4096 และเพิ่ม context เป็น 16384
หลังตรวจ memory estimate ของเครื่องแล้ว ถ้าหน่วยความจำไม่พอให้ลดจำนวน KPI/กราฟ
หรือใช้โมเดลเล็กลง การลด context จนใส่ prompt ไม่ครบไม่ใช่วิธีแก้ที่ใช้งานได้

หาก LM Studio ตั้ง API key ไว้ ให้ใส่ key นั้นแทน `lm-studio` ใน `.env`
ไม่ต้องมี Groq API key สำหรับโหมด Local และไม่ต้องส่ง `.env` ให้คนอื่น

## 5. ทดสอบและเปิดเว็บ

เปิด LM Studio Server ไว้ แล้วรัน:

```powershell
.\.venv\Scripts\python.exe local-ai\test_lmstudio.py
.\.venv\Scripts\python.exe factory-ui\app.py
```

เปิด browser ไปที่ **http://127.0.0.1:5050** และเก็บหน้าต่าง PowerShell ไว้
ไม่ต้อง Activate virtual environment เพราะคำสั่งใช้ Python ใน `.venv` โดยตรง

ลำดับใช้งาน:

1. สร้างโปรเจคใหม่ด้วยชื่อภาษาอังกฤษ เช่น `my-dashboard`
2. อัปโหลด Excel/CSV ของตัวเอง
3. กดวิเคราะห์ข้อมูลและสร้าง Profile
4. กดสร้างคำสั่งแนะนำจากข้อมูล หรือพิมพ์ความต้องการเอง
5. กดสร้าง Spec ตรวจ KPI/กราฟ/สูตร แล้วกดสร้าง Dashboard
6. เปิด Dashboard และตรวจ QA กับข้อมูลจริงก่อนนำไปใช้

ไฟล์แต่ละคนเก็บที่ `projects/<ชื่อโปรเจค>/` ในเครื่องตัวเอง ผลลัพธ์หน้าเว็บอยู่
ที่ `output/dashboard/index.html` ภายในโปรเจคนั้น โปรเจคชื่อเดียวกันบนคนละเครื่อง
ไม่มีการ sync หรือใช้ข้อมูลร่วมกันโดยอัตโนมัติ

## 6. เปิดใช้ครั้งต่อไป

1. เปิด LM Studio โหลดโมเดล และ Start Server
2. เปิด PowerShell ในโฟลเดอร์ Factory แล้วรัน:

```powershell
.\.venv\Scripts\python.exe factory-ui\app.py
```

3. เปิด http://127.0.0.1:5050 ใช้ Ctrl+C ใน PowerShell เพื่อหยุด Factory

## RAM 16 GB รันโมเดลนี้ไหวไหม

**มีโอกาสรันได้ด้วย Q4_K_M แต่หน่วยความจำค่อนข้างตึง ไม่รับประกันความเร็ว**

ไฟล์โมเดลประมาณ 8.7 GB ไม่ใช่หน่วยความจำทั้งหมดที่ใช้จริง ยังมี KV cache,
runtime, Windows, browser และการอ่าน Excel/สร้าง Dashboard ด้วย Factory
ผลประเมินบนเครื่องพัฒนาเมื่อ 15 ตุลาคม 2026 ด้วยโมเดลที่ติดตั้งอยู่, context
8192, parallel 1, GPU offload 0% คือหน่วยความจำรวมประมาณ **8.61 GiB**
เป็นเพียงผล estimate บนเครื่องพัฒนา ไม่ใช่ผลทดสอบบนเครื่อง RAM 16 GB ของเพื่อน
และไม่ได้รวม RAM ของ Windows กับ Factory

ให้ประเมินบนเครื่องเพื่อนก่อนโหลด (หากติดตั้ง `lms` CLI แล้ว):

```powershell
lms ls
lms load MODEL_KEY --context-length 8192 --parallel 1 --gpu off --estimate-only
```

แทน MODEL_KEY ด้วยชื่อที่ `lms ls` แสดง คำสั่งนี้ไม่โหลดโมเดลจริง หากจะใช้ GPU
offload ให้ประเมินใหม่โดยตัด `--gpu off` ออก รายละเอียด:
https://lmstudio.ai/docs/cli/local-models/load

หลังโหลด ให้ดู Task Manager ขณะสร้าง Spec และขณะ Build ถ้าหน่วยความจำเกือบเต็ม
และเครื่องเริ่มใช้ดิสก์หนัก/ช้ามาก แสดงว่าเหลือ headroom ไม่พอ การตั้ง context
262144 ตามค่าสูงสุดของโมเดลไม่เหมาะเป็นค่าเริ่มสำหรับเครื่องนี้

ทางเลือกเมื่อไม่ไหวคือใช้ Qwen3-8B Q4_K_M ซึ่งไฟล์ในเครื่องพัฒนามีขนาดประมาณ
5.03 GB แต่ยังต้องตรวจคุณภาพ JSON, สูตรและความตรงโจทย์แยกต่างหาก หรือเพิ่ม RAM
เป็น 32 GB เพื่อมีพื้นที่สำหรับข้อมูลและโปรแกรมอื่นมากขึ้น ทั้งหมดนี้เป็นข้อเสนอ
เชิงประมาณจากขนาดโมเดลและ workflow ไม่ใช่ benchmark ของเครื่องเพื่อน

## ผลลัพธ์และค่าใช้จ่ายเหมือนกันไหม

- ความสามารถของ Factory เหมือนกันเมื่อใช้โค้ดเวอร์ชันเดียวกัน แต่ข้อมูลแยกเครื่อง
- ตัวเลขควรตรงกันเมื่อข้อมูล สูตร ตัวกรอง และขั้นตอนแปลงข้อมูลตรงกัน
- แม้ใช้โมเดลเดียวกัน AI อาจเสนอข้อความหรือกราฟต่างกันได้ ไม่รับประกันผลเหมือน
  ทุกครั้ง โดยเฉพาะเมื่อ quantization, prompt, model/runtime หรือค่าตั้งต่างกัน
- การอนุมานแบบ Local ไม่เรียกเก็บค่าโทเคนผ่าน Groq เพราะไม่ได้ใช้ provider นั้น
  แต่ยังใช้ทรัพยากรเครื่อง พื้นที่จัดเก็บ ไฟฟ้า และอินเทอร์เน็ตตอนดาวน์โหลด

## อัปเดตเวอร์ชัน

หยุด Factory ก่อน ตรวจ `git status` และสำรองงานของตัวเอง จากนั้น:

```powershell
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

ถ้า Git แจ้งว่ามีไฟล์แก้ไขหรือ branch แยก ให้ตรวจและจัดการการแก้ไขก่อน ไม่ใช้คำสั่ง
reset/ลบไฟล์เพื่อฝืนอัปเดตโดยไม่สำรอง `.env` และข้อมูลของตัวเองไม่ควรถูก commit

## แก้ปัญหาเบื้องต้น

| อาการ | วิธีตรวจ |
|---|---|
| เชื่อม LM Studio ไม่ได้ | เปิด Developer Server ตรวจพอร์ต 1234 และ BASE_URL |
| ไม่พบโมเดล | คัดลอก Model Identifier ที่ API แสดงใหม่และ restart Factory |
| Context ไม่พอ | ตรวจจำนวน token ของ prompt ลดขนาดงาน หรือเพิ่ม context หลังตรวจ memory estimate |
| JSON ไม่ครบ | เพิ่ม MAX_TOKENS และเผื่อ context สำหรับ prompt รวมกับคำตอบ |
| ช้าหรือ RAM เต็ม | เปิดโมเดลเดียว ปิดโปรแกรมอื่น ลดขนาดงาน หรือเปลี่ยนโมเดลเล็กลง |
| Import `lan_service`/`output_language` ไม่ได้ | โค้ดดาวน์โหลดมาไม่ครบหรือคนละเวอร์ชัน ให้ตรวจ Git commit |
| ภาษาอื่นหลุด | ใช้เวอร์ชันที่มี output-language validation และสร้าง Spec ใหม่ |

คู่มือนี้ใช้โหมด Local ที่รับเฉพาะ loopback ใช้ Flask debug server เพื่อพัฒนาและ
ใช้งานส่วนตัว หากภายหลังต้องเปิดรับคนอื่นผ่านเครือข่ายให้ใช้โหมด LAN พร้อม
บัญชีและ HTTPS ตามคู่มือ LAN แทนการเปลี่ยน host ของ debug server
