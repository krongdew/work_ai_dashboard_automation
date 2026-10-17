# Dashboard Factory — เมือง Workflow 3D

หน้าเว็บ 3D แบบ interactive (Three.js) แสดง workflow ของระบบสร้าง Dashboard
เป็นเมืองโรงงานการ์ตูน low-poly 6 อาคาร เชื่อมด้วยถนน/สายพานพร้อมลูกศรทิศทาง
และเส้นทาง **Improve** สีม่วง (6 → 4 → 5 → 6) ที่ผ่านขั้นคำนวณ + QA เสมอ

เป็นหน้า **standalone** แยกจาก Factory backend และ React SPA — ไม่ยุ่งกับ pipeline เดิม

## โครงสร้าง (แยก scene / buildings / config / animation / ui)

```
factory-ui/static/city/
├── index.html      หน้าเพจ + styles (overlay, bottom-sheet มือถือ, reduced-motion)
├── config.js       ⭐ configuration กลาง: สถานี, เส้นทาง, สี, ข้อความ (แก้ที่เดียว)
├── buildings.js    component อาคาร/ต้นไม้/หุ่นยนต์/กล่อง (geometry+material ใช้ซ้ำ)
├── scene.js        renderer, OrthographicCamera isometric, ไฟ+เงา, ถนน, raycast, resize, dispose
├── animation.js    render loop, hover, สถานะ, จำลอง workflow (state machine), Improve loop
├── ui.js           HTML overlay: tooltip, แผงรายละเอียด, ปุ่มควบคุม, + BackendAdapter (stub)
└── main.js         เชื่อมทุกส่วน + จัดการ event + teardown
```

## วิธีรัน

ต้องเสิร์ฟผ่าน HTTP (ES modules โหลดผ่าน `file://` ไม่ได้) — bind localhost เท่านั้น:

```bash
cd /Users/krongkwansmac/.kiro/crew/workspace/data_agentic_private
python3 -m http.server 5055 --bind 127.0.0.1 --directory factory-ui/static
```

เปิดเบราว์เซอร์: **http://127.0.0.1:5055/city/**

Three.js โหลดจาก CDN (unpkg) — ต้องมีเน็ตครั้งแรก ไม่ต้อง `npm install` ไม่ต้อง build

> หากรวมเข้ากับ Factory (Flask) ภายหลัง: โฟลเดอร์นี้อยู่ใน `factory-ui/static/` อยู่แล้ว
> เพิ่ม route เสิร์ฟ `static/city/index.html` ได้ทันที

## การใช้งาน

- **ชี้เมาส์** ที่อาคาร → อาคารยกขึ้น + tooltip ภาษาไทย
- **คลิก** อาคาร → เปิดแผงรายละเอียดด้านข้าง (มือถือ = bottom sheet)
- **ลาก** เพื่อหมุน (จำกัดมุม), **scroll** ซูม (จำกัดระยะ), ปุ่ม **คืนมุมกล้อง**
- ปุ่ม **จำลอง Workflow** → กล่องข้อมูลเลื่อน 1→2→3→4→5→6 ทีละขั้น
- ปุ่ม **จำลอง Improve** → เส้นทางม่วง 6→4→5→6 (ผ่านคำนวณ+QA ก่อนกลับ 6)
- ปุ่ม **หยุดชั่วคราว / เริ่มใหม่**
- รองรับ `prefers-reduced-motion` (ปิด animation ลื่น ๆ ใช้การข้ามขั้นแทน)

## หมายเหตุสำคัญ

- โหมดปัจจุบันเป็น **สาธิต (demo) ข้อมูลจำลอง** — มี badge บอกชัดบนหน้าจอ
- `ui.js › BackendAdapter` เป็น **seam เดียว** สำหรับต่อ backend จริงภายหลัง
  ตอนนี้เป็น stub ที่ **ไม่เรียก endpoint ใด ๆ** และไม่แกล้งว่างานจริงสำเร็จ
- ไม่มีระบบ login / ประมวลผลข้อมูลจริง — การจำลองขับด้วย state machine ไม่ใช่ timer ที่อ้างผลจริง
