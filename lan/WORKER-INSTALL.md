# ติดตั้ง Factory Worker บนเครื่องเพื่อน (Windows)

Worker รับเฉพาะงาน AI ของบัญชีที่จับคู่ เรียก LM Studio บนเครื่องนี้ และส่งผล
JSON กลับเซิร์ฟเวอร์ ไม่ต้องเปิดพอร์ตขาเข้าและไม่ต้องมีไฟล์ข้อมูลต้นฉบับในเครื่อง

1. ติดตั้ง Python 3.11 ขึ้นไป และเลือก Add Python to PATH
2. เปิด LM Studio โหลดโมเดลที่ต้องการ และ Start Server ที่ `127.0.0.1:1234`
   ไม่ต้องเปิด Serve on Local Network ดูชื่อ Model Identifier ที่ API ใช้จริง
3. Login เว็บ Factory ด้วยบัญชีที่เจ้าของเซิร์ฟเวอร์สร้างให้
4. ดาวน์โหลด Worker จากหน้าเว็บ แล้วแตก ZIP ไปยังโฟลเดอร์ส่วนตัว เช่น
   `C:\Users\YourName\FactoryWorker` เปิด PowerShell ที่โฟลเดอร์นั้น

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. รับไฟล์ **root.crt** จากเจ้าของเซิร์ฟเวอร์ ตรวจสอบว่าเป็นใบรับรองที่เจ้าของ
   เครื่องส่งให้จริง ติดตั้งใน Current User → Trusted Root Certification
   Authorities เพื่อให้ browser เชื่อถือ HTTPS ไฟล์นี้เป็น public certificate;
   ไม่ต้องรับหรือส่ง private key ของเซิร์ฟเวอร์
6. ในเว็บ กด **สร้างรหัสจับคู่ Worker** รหัสใช้ครั้งเดียวภายใน 5 นาที

```powershell
.\.venv\Scripts\python.exe worker.py pair --server https://192.168.1.10:8443 --model "MODEL_IDENTIFIER" --ca-certificate .\root.crt
```

เปลี่ยน IP เป็นเครื่องเซิร์ฟเวอร์จริง และ MODEL_IDENTIFIER ให้ตรงกับ LM Studio
คำสั่งจะถามรหัสจับคู่โดยซ่อนข้อความ อย่าใส่รหัสใน command line หรือส่งให้ผู้อื่น

7. เริ่ม Worker และเปิดหน้าต่างนี้ไว้ระหว่างทำงาน

```powershell
.\.venv\Scripts\python.exe worker.py run
```

เว็บควรแสดง Worker ออนไลน์ เลือกหรือสร้างโปรเจค อัปโหลด → Profile → สร้าง Spec
→ สร้าง Dashboard หากปิด Worker งาน AI จะไม่สำเร็จ ให้เปิดใหม่แล้วสั่งอีกครั้ง
งานที่ขาดการติดต่อจะไม่ถูกส่งต่อให้บัญชีอื่น

ตั้งแต่ครั้งถัดไป เปิด LM Studio แล้วใช้คำสั่ง `worker.py run` ได้ทันที
หากเปลี่ยนโมเดล ให้จับคู่ใหม่ด้วย `--model` ใหม่ เซิร์ฟเวอร์จะยกเลิก Worker เก่า
หากต้องการใช้ config คนละไฟล์ ให้ระบุ `--config .\private-worker.json`
เหมือนกันทั้งคำสั่ง pair และ run

Token อยู่ที่ `%USERPROFILE%\.factory-worker\config.json` เก็บโฟลเดอร์นี้เป็นส่วนตัว
อย่าส่ง config ให้ใคร อย่าเก็บใน shared drive หรือ Git เพิกถอน Worker ได้จากเว็บ
ใช้ Ctrl+C เพื่อหยุด Worker การหยุดโปรแกรมไม่ใช่การเพิกถอนสิทธิ์

ข้อมูลต้นฉบับและ Dashboard อยู่ที่เครื่องส่วนกลาง Worker ได้รับ prompt ที่มี
metadata และผล aggregate แบบจำกัดเพื่อทำ AI inference; ข้อความที่คุณพิมพ์เอง
และค่าหมวดหมู่บางส่วนอาจอยู่ใน prompt เช่นเดียวกับ workflow Local AI เดิม

หากเชื่อมต่อไม่ได้ ให้ตรวจ IP, ใบรับรอง, วันเวลาเครื่อง, Firewall,
ชื่อโมเดล, การเปิด LM Studio Server และสถานะการจับคู่ อย่าปิดการตรวจ TLS
