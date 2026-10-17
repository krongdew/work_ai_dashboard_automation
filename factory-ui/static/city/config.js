// ============================================================================
// Dashboard Factory — central workflow configuration (spec-aligned)
// Base city 30 x 20 units; Y is up; front of city faces +Z.
// Single source of truth: scene / buildings / animation / ui read from here.
// ============================================================================

export const PALETTE = {
  cream:         '#FAF6EE',   // background
  base:          '#B9DCC5',   // city ground
  baseEdge:      '#9FC7AE',   // base edge
  wall:          '#FFF0D6',   // building wall
  frame:         '#E5CFAD',   // door / window frame
  wallDark:      '#E5CFAD',   // (alias) used for posts/steps
  roofDefault:   '#69B8B6',   // general roof
  roofEdge:      '#559E9D',   // roof edge
  roofAiplan:    '#B49ADB',   // AI Plan roof
  roofAiplanEdge:'#947BC1',
  glass:         '#BBDCE6',   // window glass
  road:          '#BEC0C8',   // road
  roadLine:      '#FFF9EE',   // road edge + arrows
  belt:          '#737B85',   // conveyor belt
  beltWheel:     '#C9CDD1',   // belt wheels
  improve:       '#B498DC',   // improve path
  improveArrow:  '#795BA6',   // improve arrows
  lavenderDeep:  '#795BA6',   // (alias) improve arrows
  tree:          '#88BC91',
  treeTrunk:     '#B39975',
  robot:         '#FFF8EA',
  robotJoint:    '#B49ADB',
  screen:        '#344451',   // screen / eyes
  good:          '#78B78D',   // QA pass
  warn:          '#E8B663',   // warning
  error:         '#D98282',   // error
  idle:          '#9BA6B2',
  running:       '#7099B7',
  text:          '#344451',   // sign title
  white:         '#FFFFFF',
  signBg:        '#FFF4DF',   // sign face
  signEdge:      '#DFC9A8',   // sign border
  numCircle:     '#7099B7',   // step-number circle
};

// Matte material defaults required by the spec.
export const MAT = { roughness: 0.85, metalness: 0 };

// Per-building size: [width(x), depth(z), height(y)] — excludes the roof.
// pos: [x, z] centre on the city floor (floor top = Y 0). Front faces +Z.
export const STATIONS = [
  {
    id: 1, key: 'login', badge: '1', title: 'Login',
    pos: [-10, 5], size: [3.2, 3.0, 3.2], color: '#8EAFD3', roofKind: 'default', symbol: 'shield', buddy: { name: 'Gate', hat: 'cap', badge: 'shield', tool: 'key' },
    signName: 'LOGIN', signSub: null, signSmall: true,
    label: '1 · Login',
    details: {
      heading: 'เข้าสู่ระบบและตรวจสอบสิทธิ์',
      bullets: [
        'เข้าสู่ระบบและตรวจสอบสิทธิ์ผู้ใช้',
        'แยกสิทธิ์ตามองค์กร หน่วยงานย่อย และ visibility',
        'ทุก route ต้องตรวจสิทธิ์ที่ฝั่ง server',
      ],
      tag: null,
    },
  },
  {
    id: 2, key: 'upload', badge: '2', title: 'Project / Upload',
    pos: [-10, -4.5], size: [5.0, 3.8, 3.5], color: '#F0AF95', roofKind: 'default', symbol: 'folders', buddy: { name: 'Intake', hat: 'cap', badge: 'folder', tool: 'box' },
    signName: 'UPLOAD', signSub: null,
    label: '2 · Upload',
    details: {
      heading: 'รับไฟล์เข้าระบบ (Excel / CSV)',
      bullets: [
        'POST /api/projects',
        'สร้าง projects/<name>/{input, output, working}',
        'ผูก project_meta: org, sub_unit, visibility ตามผู้สร้าง',
        'POST /uploads',
        'บันทึกไฟล์ลง input พร้อมเติม suffix สุ่ม ไม่ทับไฟล์เดิม',
      ],
      tag: null,
    },
  },
  {
    id: 3, key: 'profile', badge: '3', title: 'Profile',
    pos: [0, -4.5], size: [5.0, 3.8, 3.5], color: '#9AC6AE', roofKind: 'default', symbol: 'magnifier', buddy: { name: 'Scout', hat: 'ears', badge: 'grid', tool: 'magnifier' },
    signName: 'PROFILE', signSub: 'NO AI',
    label: '3 · Profile',
    details: {
      heading: 'ตรวจโครงสร้างข้อมูล (ไม่ใช้ AI)',
      bullets: [
        'profile_project อ่านไฟล์ผ่าน load_sources',
        'detect_header_row หาแถวหัวตารางจริง',
        'วิเคราะห์ field_role: measure, date, category, identifier',
        'ตรวจ non_null, distinct, examples, date parsing และ duplicate rows',
        'สร้าง dataset-profile.json เป็นข้อมูลหลักที่ UI แสดงก่อนสร้าง Dashboard',
      ],
      tag: 'NO AI',
    },
  },
  {
    id: 4, key: 'aiplan', badge: '4', title: 'AI Plan',
    pos: [10, -4.5], size: [5.0, 3.8, 3.5], color: '#B49ADB', roofKind: 'aiplan', symbol: 'blueprint', buddy: { name: 'Planner', hat: 'antenna', badge: null, tool: 'tablet-plan' },
    signName: 'AI PLAN', signSub: 'METADATA ONLY',
    label: '4 · AI Plan',
    details: {
      heading: 'AI วางแผน KPI / charts / filters',
      bullets: [
        'suggest_spec ทำงานเป็น job พร้อม progress',
        'semantic_profile: โมเดล 20b',
        'get_normalization_plan: โมเดล 20b',
        'ai_calculation_bundle เลือกเครื่องมือคำนวณ: โมเดล 120b',
        'local_ai_spec วางแผน KPI, charts, filters: โมเดล 120b',
        'validation และ repair เมื่อแผนไม่ผ่าน',
        'uncovered_requirements ตรวจความครอบคลุม: โมเดล 20b',
        'สร้าง dashboard-spec.local-ai.json ให้ผู้ใช้ตรวจทานก่อน build',
        'AI ใช้ชื่อฟิลด์ได้เฉพาะใน allowlist',
        'ส่งให้ AI เฉพาะ metadata ผ่าน cloud_safe_profile — ไม่ส่งข้อมูลรายแถวขึ้น cloud',
        'AI วางแผนเท่านั้น ไม่คำนวณค่าตัวเลข',
      ],
      tag: 'METADATA ONLY',
    },
  },
  {
    id: 5, key: 'python', badge: '5', title: 'Python + QA',
    pos: [10, 5], size: [5.4, 3.8, 3.5], color: '#69B8B6', roofKind: 'default', symbol: 'chart', buddy: { name: 'Builder', hat: 'helmet', badge: 'gear', tool: 'tablet-qa' },
    signName: 'PYTHON + QA', signSub: 'CALCULATE', signLong: true,
    label: '5 · Python + QA',
    details: {
      heading: 'คำนวณจริงด้วย Python + ตรวจ QA',
      bullets: [
        'build_project อ่าน profile และ spec',
        're-profile เมื่อ schema เปลี่ยน',
        'prepare_analytical_records ใช้ normalization plan และแปลงวันเป็น พ.ศ.',
        'calculate_spec_results ใช้ Python/Pandas คำนวณ KPI และกราฟทุกตัว',
        'เขียน records.json / csv และคัดลอก logo',
        'render_dashboard_qa สร้าง dashboard/index.html',
        'ตรวจ QA 7 ด้าน: records, identifier exclusion, duplicates, missing, date parse, calc, normalization',
        'แสดงผล pass หรือ warning ตามผลตรวจ',
        'เขียน report และ run-manifest.json',
        'Python เป็น source of truth ของตัวเลขทุกตัว',
      ],
      tag: 'CALCULATE',
    },
  },
  {
    id: 6, key: 'view', badge: '6', title: 'View / Improve / Export',
    pos: [0, 5], size: [5.4, 3.8, 3.5], color: '#EDC16A', roofKind: 'default', symbol: 'screen', buddy: { name: 'Guide', hat: 'bow', badge: 'download', tool: 'tablet-chart' },
    signName: 'VIEW / EXPORT', signSub: null,
    label: '6 · View / Export',
    details: {
      heading: 'ดู แก้ไข และส่งออก Dashboard',
      bullets: [
        'เปิด /dashboard โดยตรวจ visibility',
        'ส่งคำสั่งภาษาไทยเพื่อแก้แผนผ่าน improve_spec',
        'AI 120b แก้ spec เดิม พร้อมเก็บ revision history',
        'Build และ QA ใหม่หลังแก้ไข',
        'ดาวน์โหลด DataLink Bundle: data.csv + spec + qa + manifest',
        'หน้ารวมกรอง org, sub_unit, visibility และจัดการสิทธิ์',
      ],
      tag: null,
    },
  },
];

// city base + front sign (spec)
export const CITY = {
  base: { w: 30, d: 20, thickness: 0.6 },   // floor top at Y 0
  sign: { text: 'DASHBOARD FACTORY', size: [10, 1.1, 0.15], pos: [0, -0.25, 10.10] },
};

export const byId = Object.fromEntries(STATIONS.map((s) => [s.id, s]));

// Main production path: 1 → 2 → 3 → 4 → 5 → 6
export const MAIN_ROUTE = [1, 2, 3, 4, 5, 6];

// Improve loop (purple): 6 → 4 → 5 → 6 — never skips calculate/QA.
export const IMPROVE_ROUTE = [6, 4, 5, 6];

export const EDGES = [
  { from: 1, to: 2, kind: 'main' },
  { from: 2, to: 3, kind: 'main' },
  { from: 3, to: 4, kind: 'main' },
  { from: 4, to: 5, kind: 'main' },
  { from: 5, to: 6, kind: 'main' },
  { from: 6, to: 4, kind: 'improve' },
];

export const SIM_CAPTIONS = {
  1: 'ตรวจสิทธิ์ผู้ใช้…',
  2: 'อัปโหลดไฟล์ Excel/CSV…',
  3: 'ตรวจ header และ field role…',
  4: 'AI ร่างแผน KPI / charts…',
  5: 'Python คำนวณ + QA 7 ด้าน…',
  6: 'แสดง Dashboard พร้อมส่งออก',
};

export const IMPROVE_CAPTIONS = {
  6: 'ส่งคำสั่งแก้ไข (ภาษาไทย)…',
  4: 'AI แก้ spec + เก็บ revision…',
  5: 'คำนวณใหม่ + QA ซ้ำ…',
};

export const STATUS = {
  idle:    { color: PALETTE.idle,    icon: '○', label: 'พร้อมทำงาน' },
  running: { color: PALETTE.running, icon: '◐', label: 'กำลังทำงาน' },
  success: { color: PALETTE.good,    icon: '✓', label: 'สำเร็จ' },
  warning: { color: PALETTE.warn,    icon: '!', label: 'มีคำเตือน' },
  error:   { color: PALETTE.error,   icon: '✕', label: 'ผิดพลาด' },
};
