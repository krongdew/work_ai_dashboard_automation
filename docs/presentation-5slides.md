---
marp: true
theme: default
paginate: true
backgroundColor: "#F4F5F9"
color: "#1F2937"
style: |
  /* Minimal infographic theme — Mahidol institutional palette */
  section { font-family: "Prompt","Noto Sans Thai",sans-serif; padding: 56px 64px; }
  h1 { color: #0B2B5E; font-size: 2.1em; letter-spacing: -0.01em; }
  h2 { color: #263988; }
  strong { color: #0B2B5E; }
  a, .accent { color: #1AA9B8; }
  .gold { color: #b9821a; }
  table { font-size: 0.8em; border-collapse: collapse; }
  th { background: #0B2B5E; color: #fff; }
  td, th { border: 1px solid #D9DEE8; padding: 8px 12px; }
  .pill { background:#0B2B5E; color:#fff; border-radius:999px; padding:4px 14px; font-size:0.6em; font-weight:700; }
  .big { font-size: 1.6em; font-weight: 800; color:#0B2B5E; }
  section::after { color: #8a93a6; }
  .lead { background: linear-gradient(135deg,#0B2B5E,#6C5CE7); color:#fff; }
  .lead h1, .lead h2, .lead strong { color:#fff; }
---

<!-- _class: lead -->

# MULA Data Automation Factory
## ระบบผลิต Dashboard อัตโนมัติด้วย AI

<span class="pill">คณะศิลปศาสตร์ · มหาวิทยาลัยมหิดล</span>

เปลี่ยนไฟล์ข้อมูลที่ "เละ" และกระจัดกระจาย
ให้เป็น Dashboard ที่ถูกต้อง **ภายในไม่กี่นาที**

---

# 1. 🔴 Problem — ปัญหา

**ข้อมูลเยอะ · กระจัดกระจาย · ทำเป็น dashboard ยากและช้า**

- 🗂️ Data **silo** — Excel / Google Sheet หลายรูปแบบ ไม่มีแหล่งจริงแหล่งเดียว
- 🧩 ไฟล์จากระบบมหาวิทยาลัยมี **merge cell / header ไม่อยู่แถวแรก / ต้องกลับแถว-คอลัมน์**
- 🔁 ต้องดึงไฟล์ **หลายครั้ง** มาประกอบเป็นชุดเดียว
- ⏳ clean ไฟล์ + ทำ dashboard **ใช้เวลานานมาก** และข้อมูล **มักไม่ถูกต้อง**
- 🧑‍💻 IT มีงานหลายด้าน · บุคลากรสายอื่น **ไม่มีทักษะจัดการข้อมูล**

> แก่น: เวลาหมดไปกับการ **clean ไฟล์ให้ได้ master data** และ **สร้าง dashboard** ไม่ใช่การตัดสินใจ

---

# 2. 💡 Solution — แนวทางแก้

**ต่อยอดบน MULA DataLink** (Data Governance: รวมศูนย์ · เจ้าของข้อมูล · เข้ารหัส · สิทธิ์ตามบทบาท)

DataLink เก็บ/แบ่งสิทธิ์ได้ **แต่ยังต้องใช้คนทักษะสูง clean + สร้าง dashboard** → เติมช่องว่างด้วย **Automation Factory**

| | |
|---|---|
| 🎯 ใครก็สร้างได้ | บุคลากรที่ **ไม่มีความรู้ข้อมูล** ทำเองจากไฟล์ดิบ |
| ⏱️ เร็ว | วัน/สัปดาห์ → **นาที** |
| ✅ ถูกต้อง | **AI วางแผน · Python คำนวณ** (ไม่หลอน ตรวจสอบได้) |
| 🧹 ทนไฟล์เละ | ตรวจ header / ตีความคอลัมน์อัตโนมัติ |

---

# 3. 🤖 AI & Kiro — หัวใจของระบบ

**AI ใช้แบบมีขอบเขต — วางแผนเท่านั้น ไม่แตะตัวเลข**

```
ไฟล์ดิบ → Python หา header + master data
        → AI(เบา) ตีความคอลัมน์ไม่มีชื่อ (column_10 → "เดือน")
        → AI(ฉลาด) วางแผน KPI/กราฟ/ตัวกรอง
        → Python คำนวณจริง + QA + เรนเดอร์
```

- 🔒 **Grounded** — AI ใช้ได้เฉพาะฟิลด์จริง เสนอผิด = ปฏิเสธ+ซ่อมเอง
- 🙈 **Privacy** — ส่งขึ้น cloud แค่ metadata ไม่ส่งข้อมูลรายแถว
- ⚖️ **Model tiering + token pacing** — คุมต้นทุน ไม่ให้ล่ม · รองรับ Cloud & Local

**Kiro** = AI agent คู่พัฒนา ที่อ่านโค้ด ออกแบบ เขียน และทดสอบระบบนี้จริง → ทีมเล็กก็ทำ production ได้

---

# 4. ⚙️ Prototype — ทำได้แล้ว (Demo)

<span class="pill">LIVE</span>

- ✅ ตรวจ **header อัตโนมัติ** (รองรับ merge cell / header ลึก)
- ✅ **AI ตีความคอลัมน์ที่ไม่มีชื่อ** ให้ความหมาย
- ✅ แสดง **master data + คุณภาพข้อมูล** ให้ตรวจก่อนสร้าง
- ✅ สร้าง dashboard **3 รอบ** มี % ความคืบหน้าทุกขั้น
- ✅ **แก้ไขด้วยคำสั่งภาษาไทย** (เพิ่มกราฟ/ตัวกรอง/KPI/วิธีคำนวณ)
- ✅ **สิทธิ์ตามหน่วยงาน/หน่วยย่อย** + ส่งออก **DataLink Bundle**

> 🖥️ **เดโมสด:** อัปโหลดไฟล์เละ → ดู master data → สร้าง dashboard ในไม่กี่นาที

---

# 5. 🌟 Expected Impact — ผลที่คาดหวัง

| มิติ | ก่อน | หลัง |
|---|---|---|
| ⏱️ เวลา | ชั่วโมง–วัน | **นาที** |
| 🎓 ทักษะ | ต้องเชี่ยวชาญ | **ไม่ต้องก็ได้** |
| ✅ ความถูกต้อง | clean มือ | **คำนวณ+QA อัตโนมัติ** |
| 🔑 การเข้าถึง | รวมที่ IT | **ทุกหน่วยทำเองได้** |

**ขยายผล:** คณะศิลปศาสตร์ → ทุกส่วนงาน · เป็นมาตรฐาน dashboard ของ Data Governance ทั้งองค์กร

<div align="center">

**ให้ข้อมูลพร้อมใช้ โดยไม่ต้องเป็นผู้เชี่ยวชาญข้อมูล**

</div>
