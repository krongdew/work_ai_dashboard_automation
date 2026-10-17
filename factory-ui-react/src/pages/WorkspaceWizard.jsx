import { useEffect, useRef, useState } from 'react';
import {
  Steps, Card, Select, Button, Upload, Input, Space, Typography, App, Result,
  Progress, Alert, Descriptions, Tag, List, Empty, Spin, Table, Statistic, Row, Col, Popconfirm,
} from 'antd';
import {
  UploadOutlined, BulbOutlined, BarChartOutlined, FilterOutlined,
  FileExcelOutlined, DatabaseOutlined, ReloadOutlined, CheckCircleOutlined, DeleteOutlined,
} from '@ant-design/icons';
import { api, getCsrf } from '../api.js';
import { useSearchParams } from 'react-router-dom';

const { Text } = Typography;

// Maps the chart "type" coming from the spec to a readable Thai label.
// The spec schema allows: bar | line | pie.
const CHART_TYPE_TH = {
  bar: 'กราฟแท่ง (เปรียบเทียบ)', line: 'กราฟเส้น (แนวโน้ม)', pie: 'กราฟวงกลม (สัดส่วน)',
  hbar: 'กราฟแท่งแนวนอน (จัดอันดับ)', table: 'ตาราง', kpi: 'ตัวเลขสรุป (KPI)',
  scatter: 'กราฟกระจาย (ความสัมพันธ์)', heatmap: 'ฮีตแมป',
};

// Field "role" from the deterministic profile -> readable Thai label + color.
const ROLE_TH = {
  measure: { label: 'ตัวเลข/ตัววัด', color: 'blue' },
  date: { label: 'วันที่', color: 'purple' },
  category: { label: 'หมวดหมู่', color: 'green' },
  identifier: { label: 'รหัส/ไอดี', color: 'red' },
  text: { label: 'ข้อความ', color: 'default' },
};

// Dashboard visibility tiers (match the backend's project_meta.visibility check).
const VISIBILITY_OPTS = [
  { value: 'sub_unit', label: 'เฉพาะหน่วยย่อย (sub-unit เดียวกัน)' },
  { value: 'org', label: 'ทั้งหน่วยงาน (org เดียวกัน)' },
  { value: 'authenticated', label: 'สาธารณะในองค์กร — ทุกคนที่ login ดูได้ (ข้ามหน่วย)' },
];
const VISIBILITY_TH = {
  sub_unit: 'เฉพาะหน่วยย่อย', org: 'ทั้งหน่วยงาน', authenticated: 'สาธารณะในองค์กร (ทุกคนที่ login)',
};

function humanSize(bytes) {
  if (!bytes && bytes !== 0) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function WorkspaceWizard() {
  const { message } = App.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const [step, setStep] = useState(0);
  const [projects, setProjects] = useState([]);
  const [current, setCurrent] = useState(null);
  const [newName, setNewName] = useState('');
  const [instruction, setInstruction] = useState('');
  const [suggestions, setSuggestions] = useState([]);  // clickable dashboard prompt ideas
  const [busy, setBusy] = useState(false);
  const [buildResult, setBuildResult] = useState(null);

  // Existing project detail (uploaded files + previously-generated profile).
  const [detail, setDetail] = useState(null);     // { inputs, profile, built, ... }
  const [detailBusy, setDetailBusy] = useState(false);

  // Master-data profile shown for review before AI analysis / build.
  const [profileData, setProfileData] = useState(null);

  // Org / sub-unit / visibility for a new dashboard.
  const [orgOptions, setOrgOptions] = useState({ is_admin: false, organizations: [], sub_units: [], org_id: null, sub_unit_id: null });
  const [orgId, setOrgId] = useState(null);
  const [subUnitId, setSubUnitId] = useState(null);
  const [visibility, setVisibility] = useState('org');

  // Analysis (AI planning) state: live percent + Thai stage, then the resulting spec.
  const [analyzing, setAnalyzing] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [analysis, setAnalysis] = useState(null); // the dashboard-spec the AI produced
  const pollRef = useRef(null);

  // Edit / improve state (post-build revision).
  const [editInstruction, setEditInstruction] = useState('');
  const [improving, setImproving] = useState(false);
  const improvePollRef = useRef(null);

  const load = () => api.get('/api/projects').then(setProjects).catch((e) => message.error(e.message));
  useEffect(() => {
    load();
    api.get('/api/org-options')
      .then((o) => { setOrgOptions(o); setOrgId(o.org_id ?? null); setSubUnitId(o.sub_unit_id ?? null); })
      .catch(() => {}); // non-fatal: LAN mode or no orgs
    return () => clearInterval(pollRef.current);
  }, []);

  useEffect(() => () => clearInterval(improvePollRef.current), []);

  // Deep-link from the dashboards list: ?project=<name>&edit=1 jumps straight
  // into the edit step for an already-built dashboard.
  useEffect(() => {
    const proj = searchParams.get('project');
    if (!proj || searchParams.get('edit') !== '1') return;
    (async () => {
      try {
        const d = await api.get(`/api/projects/${proj}`);
        setCurrent(proj);
        setDetail(d);
        if (d.profile) setProfileData(d.profile);
        setAnalysis(d.spec || null); // show the current plan as the edit baseline
        setStep(6);
      } catch (e) { message.error(e.message); }
      finally { setSearchParams({}, { replace: true }); } // clear the params
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function resetAnalysis() {
    clearInterval(pollRef.current);
    setAnalyzing(false); setProgress(0); setStage(''); setAnalysis(null);
  }

  // Load a project's detail (uploaded files + existing profile) so the upload step
  // can show "you already have files" and offer reuse / edit.
  async function selectProject(name) {
    setCurrent(name); resetAnalysis(); setProfileData(null); setDetail(null);
    setStep(1);
    setDetailBusy(true);
    try {
      const d = await api.get(`/api/projects/${name}`);
      setDetail(d);
      if (d.profile) setProfileData(d.profile);
    } catch (e) { message.error(e.message); }
    finally { setDetailBusy(false); }
  }

  async function refreshDetail() {
    if (!current) return;
    try { const d = await api.get(`/api/projects/${current}`); setDetail(d); if (d.profile) setProfileData(d.profile); }
    catch (e) { message.error(e.message); }
  }

  // Delete one uploaded file, then refresh the list. Invalidates any stale profile.
  async function deleteFile(filename) {
    try {
      const r = await api.del(`/api/projects/${current}/uploads/${encodeURIComponent(filename)}`);
      setDetail((d) => ({ ...(d || {}), inputs: r.files || [] }));
      // The profile no longer matches the files on disk — force a re-profile.
      setProfileData(null);
      message.success(`ลบ ${filename} แล้ว`);
    } catch (e) { message.error(e.message); }
  }

  // Change an existing dashboard's visibility (and sub-unit) via PATCH.
  async function changeVisibility(newVisibility, newSubUnitId) {
    try {
      const meta = await api.patch(`/api/projects/${current}/meta`, {
        visibility: newVisibility,
        sub_unit_id: newSubUnitId ?? null,
      });
      setDetail((d) => ({ ...(d || {}), meta }));
      message.success('อัปเดตสิทธิ์การมองเห็นแล้ว');
    } catch (e) { message.error(e.message); }
  }

  async function createProject() {
    if (!newName.trim()) return;
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(newName.trim())) {
      message.warning('ชื่อโปรเจกต์ใช้ได้เฉพาะ ภาษาอังกฤษ ตัวเลข ขีด (-) และขีดล่าง (_) เท่านั้น ห้ามเว้นวรรคหรือภาษาไทย');
      return;
    }
    try {
      const nm = newName.trim();
      await api.post('/api/projects', {
        name: nm,
        visibility,
        org_id: orgOptions.is_admin ? orgId : undefined,
        sub_unit_id: subUnitId,
      });
      setCurrent(nm); setNewName(''); setDetail({ inputs: [], profile: null }); setProfileData(null);
      await load(); setStep(1);
      message.success('สร้างโปรเจกต์แล้ว');
    } catch (e) { message.error(e.message); }
  }

  // Deterministic structural profiling (fast, no AI). Produces the master-data profile,
  // then advances to the master-data PREVIEW step.
  async function profile() {
    setBusy(true); setAnalyzing(true); setProgress(20); setStage('รอบ 1/3 — ตรวจโครงสร้างข้อมูล');
    try {
      const job = await api.post(`/api/projects/${current}/profile-jobs`, {});
      pollJob(job.job_id,
        (result) => {
          setProfileData(result.profile); setAnalyzing(false); setBusy(false); setStep(3);
          message.success('ตรวจโครงสร้างเสร็จ — ดูข้อมูลที่ได้ด้านล่าง (AI กำลังตีความคอลัมน์ที่ไม่มีชื่อต่อในพื้นหลัง)');
          enrichInBackground();
        },
        (err) => { setAnalyzing(false); setBusy(false); message.error(`ตรวจโครงสร้างไม่สำเร็จ: ${err}`); });
    } catch (e) { setAnalyzing(false); setBusy(false); message.error(e.message); }
  }

  // Non-blocking AI enrichment: interprets only column_N fields AFTER the preview
  // is already shown. Updates the table's "AI ตีความ" column when it finishes.
  const [enriching, setEnriching] = useState(false);
  async function enrichInBackground() {
    setEnriching(true);
    try {
      const job = await api.post(`/api/projects/${current}/enrich-jobs`, {});
      pollJob(job.job_id,
        (result) => { setProfileData(result.profile); setEnriching(false); message.success('AI ตีความคอลัมน์เสร็จแล้ว'); },
        () => { setEnriching(false); }); // non-fatal: leave profile as-is on failure
    } catch { setEnriching(false); }
  }

  // Step 4: run the AI analysis job and poll it so we can show % + what it is doing.
  async function runAnalysis() {
    resetAnalysis();
    setAnalyzing(true); setStage('กำลังเริ่มงาน AI'); setProgress(0);
    try {
      const { job_id } = await api.post(`/api/projects/${current}/suggest-jobs`, { instruction: instruction.trim() });
      pollRef.current = setInterval(async () => {
        try {
          const job = await api.get(`/api/ai-jobs/${job_id}`);
          setProgress(job.percent || 0);
          if (job.stage) setStage(job.stage);
          if (job.status === 'completed') {
            clearInterval(pollRef.current);
            setProgress(100); setAnalysis(job.result); setAnalyzing(false);
            message.success('วิเคราะห์ด้วย AI เสร็จ — ตรวจผลก่อนสร้าง Dashboard');
          } else if (job.status === 'failed') {
            clearInterval(pollRef.current);
            setAnalyzing(false);
            message.error(job.error || 'วิเคราะห์ด้วย AI ไม่สำเร็จ');
          }
        } catch (e) {
          clearInterval(pollRef.current); setAnalyzing(false);
          message.error(e.message);
        }
      }, 1200);
    } catch (e) {
      setAnalyzing(false);
      message.error(e.message);
    }
  }

  // Build in two rounds to stay under the per-minute token limit:
  // Round 2 (master data, light model) -> short pause -> Round 3 (dashboard, smart model).
  function pollJob(jobId, onDone, onFail) {
    const timer = setInterval(async () => {
      try {
        const job = await api.get(`/api/ai-jobs/${jobId}`);
        setProgress(job.percent || 0);
        if (job.stage) setStage(job.stage);
        if (job.status === 'completed') { clearInterval(timer); onDone(job.result); }
        else if (job.status === 'failed') { clearInterval(timer); onFail(job.error || 'ไม่สำเร็จ'); }
      } catch (e) { clearInterval(timer); onFail(e.message); }
    }, 1200);
    return timer;
  }

  async function build() {
    setBusy(true); setAnalyzing(true); setProgress(10); setStage('รอบ 2/3 — กำลังสร้าง master data ที่ถูกต้อง');
    try {
      const md = await api.post(`/api/projects/${current}/master-data-jobs`, {});
      pollJob(md.job_id, async () => {
        // The backend token-pacer now spaces AI calls under the limit automatically,
        // so no fixed wait is needed here — go straight to the planning round.
        setStage('รอบ 3/3 — กำลังวางแผนและสร้าง Dashboard'); setProgress(60);
        const db = await api.post(`/api/projects/${current}/dashboard-jobs`, {});
        pollJob(db.job_id,
          (result) => { setBuildResult(result); setAnalyzing(false); setBusy(false); setStep(5); },
          (err) => { setAnalyzing(false); setBusy(false); message.error(`สร้าง Dashboard ไม่สำเร็จ: ${err}`); });
      }, (err) => { setAnalyzing(false); setBusy(false); message.error(`สร้าง master data ไม่สำเร็จ: ${err}`); });
    } catch (e) { setAnalyzing(false); setBusy(false); message.error(e.message); }
  }

  // Edit an already-built dashboard: send a Thai instruction to /improve-jobs,
  // poll for progress, then rebuild so the change shows on the dashboard.
  async function runImprove(instructionText) {
    const text = (instructionText ?? editInstruction).trim();
    if (!text) { message.warning('พิมพ์คำสั่งแก้ไขก่อน'); return; }
    clearInterval(improvePollRef.current);
    setImproving(true); setStage('AI กำลังแก้ไขแผน dashboard'); setProgress(10);
    try {
      const { job_id } = await api.post(`/api/projects/${current}/improve-jobs`, { instruction: text });
      improvePollRef.current = setInterval(async () => {
        try {
          const job = await api.get(`/api/ai-jobs/${job_id}`);
          setProgress(job.percent || 10);
          if (job.stage) setStage(job.stage);
          if (job.status === 'completed') {
            clearInterval(improvePollRef.current);
            setProgress(100); setAnalysis(job.result); setImproving(false); setEditInstruction('');
            message.success('แก้ไขแผนเสร็จ — กด “สร้าง Dashboard ใหม่” เพื่อให้มีผล');
          } else if (job.status === 'failed') {
            clearInterval(improvePollRef.current); setImproving(false);
            message.error(job.error || 'แก้ไขไม่สำเร็จ');
          }
        } catch (e) { clearInterval(improvePollRef.current); setImproving(false); message.error(e.message); }
      }, 1200);
    } catch (e) { setImproving(false); message.error(e.message); }
  }

  const uploadProps = {
    name: 'files', multiple: true, action: `/api/projects/${current}/uploads`, withCredentials: true,
    accept: '.xlsx,.xlsm,.csv',
    headers: { 'X-CSRF-Token': getCsrf() },
    showUploadList: true,
    onChange(info) {
      if (info.file.status === 'done') {
        message.success(`อัปโหลด ${info.file.name} แล้ว`);
        refreshDetail();
      } else if (info.file.status === 'error') {
        message.error(`อัปโหลด ${info.file.name} ไม่สำเร็จ`);
      }
    },
  };

  const kpis = analysis?.kpis || [];
  const charts = analysis?.charts || [];
  const filters = analysis?.filters || [];
  const insights = analysis?.insight_questions || [];

  const existingFiles = detail?.inputs || [];
  const hasFiles = existingFiles.length > 0;

  // ---- Master-data preview table (from the deterministic profile) ----
  const fieldColumns = [
    { title: 'ฟิลด์', dataIndex: 'name', key: 'name', render: (v) => <Text strong>{v}</Text> },
    {
      title: 'AI ตีความ', key: 'ai', width: 200,
      render: (_, f) => f.inferred_label
        ? <div><Tag color="geekblue">{f.inferred_label}</Tag><div style={{ fontSize: 11, color: '#8a93a6' }}>{f.inferred_meaning}</div></div>
        : <span style={{ color: '#ccc' }}>—</span>,
    },
    {
      title: 'บทบาท', dataIndex: 'role', key: 'role', width: 120,
      render: (r) => { const t = ROLE_TH[r] || { label: r, color: 'default' }; return <Tag color={t.color}>{t.label}</Tag>; },
    },
    { title: 'ชนิด', dataIndex: 'type', key: 'type', width: 90 },
    { title: 'ไม่ว่าง', dataIndex: 'non_null', key: 'non_null', width: 80, align: 'right' },
    { title: 'ค่าไม่ซ้ำ', dataIndex: 'distinct', key: 'distinct', width: 90, align: 'right' },
    {
      title: 'ตัวอย่างข้อมูล', dataIndex: 'examples', key: 'examples',
      render: (ex) => <Space size={[4, 4]} wrap>{(ex || []).slice(0, 5).map((e, i) => <Tag key={i}>{String(e)}</Tag>)}</Space>,
    },
  ];

  return (
    <Card
      title={<span style={{ color: '#fff', fontWeight: 700 }}>✧ สร้าง Dashboard ทีละขั้นตอน</span>}
      style={{ maxWidth: 1040, margin: 'auto', borderRadius: 16, overflow: 'hidden', boxShadow: '0 6px 24px rgba(11,43,94,.08)' }}
      styles={{ header: { background: 'linear-gradient(135deg,#0B2B5E,#6C5CE7)', borderBottom: 0 } }}>
      <Steps current={step} responsive size="small" style={{ marginBottom: 24 }}
        items={[
          { title: 'เลือกโปรเจกต์' },
          { title: 'อัปโหลด/เลือกไฟล์' },
          { title: 'ตรวจโครงสร้าง' },
          { title: 'ดูข้อมูลที่ได้' },
          { title: 'วิเคราะห์ด้วย AI' },
          { title: 'เสร็จสิ้น' },
        ]} />

      {step === 0 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text>เลือกโปรเจกต์ที่มีอยู่ หรือสร้างใหม่</Text>
          <Select style={{ width: '100%' }} placeholder="เลือกโปรเจกต์" value={current}
            onChange={selectProject}
            options={projects.map((p) => ({ value: p.name, label: p.name + (p.built ? ' (สร้างแล้ว)' : '') }))} />
          <Space.Compact style={{ width: '100%' }}>
            <Input placeholder="ชื่อโปรเจกต์ใหม่ (อังกฤษ/ตัวเลข เช่น student-2567)" value={newName}
              onChange={(e) => setNewName(e.target.value)} onPressEnter={createProject}
              status={newName && !/^[A-Za-z0-9_-]*$/.test(newName) ? 'error' : ''} />
            <Button type="primary" onClick={createProject}>สร้าง</Button>
          </Space.Compact>
          <Text type="secondary" style={{ fontSize: 12 }}>
            ใช้ได้เฉพาะภาษาอังกฤษ ตัวเลข ขีด (-) และขีดล่าง (_) เท่านั้น ห้ามเว้นวรรคหรือภาษาไทย
          </Text>

          <Card size="small" title="สิทธิ์การมองเห็นของ Dashboard ใหม่">
            <Space direction="vertical" style={{ width: '100%' }} size="small">
              {orgOptions.is_admin && (
                <div>
                  <Text type="secondary" style={{ fontSize: 12 }}>หน่วยงาน (admin เท่านั้น)</Text>
                  <Select style={{ width: '100%' }} placeholder="เลือกหน่วยงาน" value={orgId}
                    onChange={(v) => { setOrgId(v); setSubUnitId(null); }} allowClear
                    options={orgOptions.organizations.map((o) => ({ value: o.id, label: o.name }))} />
                </div>
              )}
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>หน่วยย่อย (sub-unit) — ไม่บังคับ</Text>
                <Select style={{ width: '100%' }} placeholder="เลือกหน่วยย่อย (ถ้ามี)" value={subUnitId}
                  onChange={setSubUnitId} allowClear
                  options={orgOptions.sub_units
                    .filter((s) => !orgOptions.is_admin || !orgId || s.org_id === orgId)
                    .map((s) => ({ value: s.id, label: s.name }))} />
              </div>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>ใครเห็น Dashboard นี้ได้</Text>
                <Select style={{ width: '100%' }} value={visibility} onChange={setVisibility}
                  options={VISIBILITY_OPTS} />
              </div>
              <Text type="secondary" style={{ fontSize: 12 }}>
                “สาธารณะในองค์กร” = ทุกคนที่ login เข้าระบบดูได้ (ข้ามหน่วยงาน) ไม่ใช่เปิดสู่อินเทอร์เน็ตสาธารณะ
              </Text>
            </Space>
          </Card>
        </Space>
      )}

      {step === 1 && current && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text>ไฟล์ข้อมูลของโปรเจกต์ <b>{current}</b></Text>

          {detailBusy && <Spin />}

          {!detailBusy && hasFiles && (
            <Card size="small"
              title={<Space><CheckCircleOutlined style={{ color: 'var(--ant-color-success, #52c41a)' }} />มีไฟล์อยู่แล้ว {existingFiles.length} ไฟล์</Space>}
              extra={<Button size="small" icon={<ReloadOutlined />} onClick={refreshDetail}>รีเฟรช</Button>}>
              <List size="small" dataSource={existingFiles}
                renderItem={(f) => (
                  <List.Item
                    actions={[
                      <Popconfirm key="del" title="ลบไฟล์นี้?" description={f.name}
                        okText="ลบ" cancelText="ยกเลิก" okButtonProps={{ danger: true }}
                        onConfirm={() => deleteFile(f.name)}>
                        <Button size="small" danger type="text" icon={<DeleteOutlined />}>ลบ</Button>
                      </Popconfirm>,
                    ]}>
                    <Space><FileExcelOutlined style={{ color: 'var(--ant-color-success, #52c41a)' }} /><Text>{f.name}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>{humanSize(f.size)}</Text></Space>
                  </List.Item>
                )} />
              <Alert style={{ marginTop: 8 }} type="info" showIcon
                message="ใช้ไฟล์เดิมวิเคราะห์ใหม่ได้เลย หรือจะอัปโหลดไฟล์เพิ่ม/แทนที่ก็ได้ (ไฟล์ชื่อซ้ำจะถูกเก็บเป็นไฟล์ใหม่ ไม่ทับของเดิม)" />
            </Card>
          )}

          {!detailBusy && !hasFiles && (
            <Alert type="warning" showIcon message="ยังไม่มีไฟล์ในโปรเจกต์นี้ — อัปโหลด Excel/CSV ก่อน" />
          )}

          <Card size="small" title={hasFiles ? 'อัปโหลดไฟล์เพิ่ม / แทนที่ (ถ้าต้องการแก้ไข)' : 'อัปโหลดไฟล์ Excel/CSV'}>
            <Upload {...uploadProps}><Button icon={<UploadOutlined />}>เลือกไฟล์</Button></Upload>
          </Card>

          {detail?.meta && (
            <Card size="small" title="สิทธิ์การมองเห็นของ Dashboard นี้">
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                <Text type="secondary" style={{ fontSize: 12 }}>
                  ปัจจุบัน: <b>{VISIBILITY_TH[detail.meta.visibility] || detail.meta.visibility}</b>
                </Text>
                <Select style={{ width: '100%' }} value={detail.meta.visibility}
                  onChange={(v) => changeVisibility(v, detail.meta.sub_unit_id)}
                  options={VISIBILITY_OPTS} />
                {orgOptions.sub_units.length > 0 && (
                  <Select style={{ width: '100%' }} placeholder="หน่วยย่อย (sub-unit)" allowClear
                    value={detail.meta.sub_unit_id}
                    onChange={(v) => changeVisibility(detail.meta.visibility, v)}
                    options={orgOptions.sub_units
                      .filter((s) => !orgOptions.is_admin || !detail.meta.org_id || s.org_id === detail.meta.org_id)
                      .map((s) => ({ value: s.id, label: s.name }))} />
                )}
              </Space>
            </Card>
          )}

          <Space wrap>
            <Button type="primary" disabled={!hasFiles} onClick={() => setStep(2)}>
              {hasFiles ? 'ใช้ไฟล์เหล่านี้ → ตรวจโครงสร้าง' : 'อัปโหลดไฟล์ก่อน'}
            </Button>
          </Space>
        </Space>
      )}

      {step === 2 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text>ตรวจโครงสร้างข้อมูล (ไม่แก้ไฟล์ต้นฉบับ) — ระบุชนิดฟิลด์ วันที่ ตัวเลข และมิติต่าง ๆ พร้อมให้ AI ช่วยตีความความหมายของคอลัมน์ แล้วแสดงหน้าตาข้อมูลที่ได้ให้ดูก่อน</Text>
          {!analyzing && (
            <Space wrap>
              <Button type="primary" loading={busy} icon={<DatabaseOutlined />} onClick={profile}>เริ่มตรวจโครงสร้างข้อมูล</Button>
              <Button type="link" onClick={() => setStep(1)}>ย้อนกลับไปจัดการไฟล์</Button>
            </Space>
          )}
          {analyzing && (
            <Card size="small" style={{ background: 'var(--ant-color-fill-quaternary, #fafafa)' }}>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space><Spin size="small" /><Text strong>{stage || 'กำลังตรวจโครงสร้าง…'}</Text></Space>
                <Progress percent={progress} status="active" />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  รอบ 1: Python อ่านโครงสร้าง + AI (ตัวเบา) ช่วยตีความความหมายของคอลัมน์ (รวมคอลัมน์ที่ไม่มีชื่อ)
                </Text>
              </Space>
            </Card>
          )}
        </Space>
      )}

      {/* Master-data PREVIEW: "หน้าตา data ที่ได้" from the deterministic profile */}
      {step === 3 && profileData && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert type="success" showIcon
            message="นี่คือหน้าตาข้อมูลที่ระบบอ่านได้ (master data) — ตรวจความถูกต้องก่อนวิเคราะห์/สร้าง Dashboard" />

          <Row gutter={16}>
            <Col xs={12} sm={6}><Card size="small"><Statistic title="จำนวนแถว (records)" value={profileData.records ?? 0} /></Card></Col>
            <Col xs={12} sm={6}><Card size="small"><Statistic title="จำนวนฟิลด์" value={(profileData.fields || []).length} /></Card></Col>
            <Col xs={12} sm={6}><Card size="small"><Statistic title="ไฟล์ต้นทาง" value={(profileData.input_files || []).length} /></Card></Col>
            <Col xs={12} sm={6}><Card size="small"><Statistic title="แถวซ้ำ" value={profileData.quality?.exact_duplicate_rows ?? 0} /></Card></Col>
          </Row>

          {(profileData.input_files || []).length > 0 && (
            <Space wrap>
              <Text type="secondary">จากไฟล์:</Text>
              {profileData.input_files.map((f, i) => <Tag key={i} icon={<FileExcelOutlined />}>{f}</Tag>)}
            </Space>
          )}

          <Card size="small" title={<Space><DatabaseOutlined />ฟิลด์ข้อมูล ({(profileData.fields || []).length}){enriching && <Tag color="processing"><Spin size="small" style={{ marginInlineEnd: 6 }} />AI กำลังตีความคอลัมน์…</Tag>}</Space>}>
            <Table
              size="small"
              rowKey="name"
              dataSource={profileData.fields || []}
              columns={fieldColumns}
              pagination={(profileData.fields || []).length > 12 ? { pageSize: 12, size: 'small' } : false}
              scroll={{ x: 'max-content' }}
            />
          </Card>

          {profileData.quality && (
            <Alert type="info" showIcon
              message="คุณภาพข้อมูล"
              description={
                <ul style={{ margin: 0, paddingInlineStart: 18 }}>
                  <li>แถวซ้ำกันทั้งแถว: {profileData.quality.exact_duplicate_rows ?? 0}</li>
                  {Object.entries(profileData.quality.missing_values || {})
                    .filter(([, n]) => n > 0)
                    .slice(0, 6)
                    .map(([k, n]) => <li key={k}>ค่าว่างในฟิลด์ <b>{k}</b>: {n}</li>)}
                  {Object.entries(profileData.quality.date_parsing || {}).map(([k, v]) =>
                    <li key={k}>วันที่ <b>{k}</b>: แปลงได้ {v.parsed}, แปลงไม่ได้ {v.unparsed}</li>)}
                </ul>
              } />
          )}

          <Space wrap>
            <Button type="primary" icon={<BulbOutlined />} onClick={async () => {
              setStep(4);
              try {
                const r = await api.get(`/api/projects/${current}/prompt-suggestions`);
                setSuggestions(r.suggestions || []);
              } catch { setSuggestions([]); }
            }} disabled={enriching} loading={enriching}>
              {enriching ? 'รอ AI ตีความคอลัมน์ให้เสร็จก่อน…' : 'ถูกต้องแล้ว → ไปวิเคราะห์ด้วย AI'}
            </Button>
            <Button onClick={() => setStep(1)} disabled={enriching}>ไปแก้ไข/เพิ่มไฟล์</Button>
            <Button onClick={profile} loading={busy} disabled={enriching} icon={<ReloadOutlined />}>ตรวจโครงสร้างใหม่</Button>
          </Space>
          {enriching && (
            <Text type="secondary" style={{ fontSize: 12 }}>
              AI กำลังตีความชื่อคอลัมน์ที่ไม่มีชื่อ — ปุ่มถัดไปจะกดได้เมื่อเสร็จ (กันไม่ให้สั่งงาน AI ซ้อนกัน)
            </Text>
          )}
        </Space>
      )}

      {step === 3 && !profileData && (
        <Empty description="ยังไม่มีผลตรวจโครงสร้าง — กลับไปกด “เริ่มตรวจโครงสร้างข้อมูล”">
          <Button onClick={() => setStep(2)}>ย้อนกลับ</Button>
        </Empty>
      )}

      {step === 4 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Text>ใส่คำสั่ง/ความต้องการ (ถ้ามี) แล้วให้ AI วิเคราะห์และวางแผน dashboard — ระบบจะแสดงผลการวิเคราะห์ให้ตรวจก่อนสร้างจริง</Text>

          {suggestions.length > 0 && !analysis && !analyzing && (
            <Card size="small" title="💡 ไอเดีย dashboard จากข้อมูลของคุณ — กดเลือกได้เลย (ไม่ต้องพิมพ์เอง)"
              style={{ background: 'var(--ant-color-fill-quaternary, #fafafa)' }}>
              <Space direction="vertical" style={{ width: '100%' }} size="small">
                {suggestions.map((s, i) => (
                  <Button key={i} block style={{ textAlign: 'left', height: 'auto', whiteSpace: 'normal', padding: '8px 12px' }}
                    onClick={() => setInstruction(s.prompt)}>
                    <Space direction="vertical" size={0} style={{ width: '100%' }}>
                      <Text strong>{s.title}</Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>{s.prompt}</Text>
                    </Space>
                  </Button>
                ))}
                <Text type="secondary" style={{ fontSize: 12 }}>กดแล้วคำสั่งจะไปอยู่ในช่องด้านล่าง ปรับแก้ได้ หรือกด “วิเคราะห์ด้วย AI” ได้เลย</Text>
              </Space>
            </Card>
          )}

          <Input.TextArea rows={3}
            placeholder="เช่น แสดงจำนวนนักศึกษาตามสาขา และอัตราคงอยู่รายปี"
            value={instruction} onChange={(e) => setInstruction(e.target.value)} disabled={analyzing} />

          {!analysis && !analyzing && (
            <Space wrap>
              <Button type="primary" icon={<BulbOutlined />} onClick={runAnalysis}>วิเคราะห์ด้วย AI</Button>
              <Button type="link" onClick={() => setStep(3)}>ย้อนกลับไปดูข้อมูลที่ได้</Button>
            </Space>
          )}

          {analyzing && (
            <Card size="small" style={{ background: 'var(--ant-color-fill-quaternary, #fafafa)' }}>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space><Spin size="small" /><Text strong>{stage || 'กำลังทำงาน…'}</Text></Space>
                <Progress percent={progress} status="active" />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  AI กำลังอ่านเฉพาะ metadata ของข้อมูล (ไม่ส่งข้อมูลรายแถว) เพื่อวางแผน KPI กราฟ และตัวกรอง
                </Text>
              </Space>
            </Card>
          )}

          {analysis && (
            <>
              <Alert type="success" showIcon
                message="ผลการวิเคราะห์พร้อมแล้ว — ตรวจรายละเอียดด้านล่าง แล้วกด “สร้าง Dashboard”" />

              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="ชื่อ Dashboard">{analysis.dashboard_title || current}</Descriptions.Item>
                {analysis.audience && <Descriptions.Item label="กลุ่มผู้ใช้">{analysis.audience}</Descriptions.Item>}
                {analysis.purpose && <Descriptions.Item label="วัตถุประสงค์">{analysis.purpose}</Descriptions.Item>}
                {analysis.generated_by && <Descriptions.Item label="วิเคราะห์โดย"><Tag color="gold">{analysis.generated_by}</Tag></Descriptions.Item>}
              </Descriptions>

              <Card size="small" title={<Space><BulbOutlined />KPI ที่จะแสดง ({kpis.length})</Space>}>
                {kpis.length ? (
                  <List size="small" dataSource={kpis}
                    renderItem={(k) => (
                      <List.Item>
                        <List.Item.Meta
                          title={k.name || k.title || k.metric}
                          description={[
                            k.metric && `ค่า: ${k.metric}`,
                            k.aggregation && `รวมแบบ: ${k.aggregation}`,
                            k.formula && `สูตร: ${k.formula}`,
                            (k.source_fields || k.source) && `ฟิลด์: ${[].concat(k.source_fields || k.source).join(', ')}`,
                            k.limitations && `ข้อจำกัด: ${k.limitations}`,
                          ].filter(Boolean).join(' · ')} />
                      </List.Item>
                    )} />
                ) : <Empty description="ไม่มี KPI" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>

              <Card size="small" title={<Space><BarChartOutlined />กราฟ/ตาราง ({charts.length})</Space>}>
                {charts.length ? (
                  <List size="small" dataSource={charts}
                    renderItem={(c) => (
                      <List.Item>
                        <List.Item.Meta
                          title={<Space wrap><span>{c.title || c.name}</span><Tag>{CHART_TYPE_TH[c.type] || c.type}</Tag></Space>}
                          description={[
                            c.dimension && `มิติ: ${c.dimension}`,
                            c.metric && `ค่า: ${c.metric}`,
                            c.aggregation && `รวมแบบ: ${c.aggregation}`,
                            c.limitations && `ข้อจำกัด: ${c.limitations}`,
                          ].filter(Boolean).join(' · ')} />
                      </List.Item>
                    )} />
                ) : <Empty description="ไม่มีกราฟ" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>

              {filters.length > 0 && (
                <Card size="small" title={<Space><FilterOutlined />ตัวกรอง ({filters.length})</Space>}>
                  <Space wrap>{filters.map((f, i) => <Tag key={i}>{f.label || f.field || f}</Tag>)}</Space>
                </Card>
              )}

              {insights.length > 0 && (
                <Alert type="info" showIcon icon={<BulbOutlined />}
                  message="คำถามเชิงวิเคราะห์ที่ dashboard นี้จะตอบ"
                  description={<ul style={{ margin: 0, paddingInlineStart: 18 }}>{insights.map((w, i) => <li key={i}>{w}</li>)}</ul>} />
              )}

              <Space wrap>
                <Button type="primary" loading={busy} icon={<BarChartOutlined />} onClick={build}>สร้าง Dashboard</Button>
                <Button onClick={runAnalysis} disabled={busy}>วิเคราะห์ใหม่</Button>
                <Button type="link" onClick={() => setStep(3)} disabled={busy}>ย้อนกลับไปดูข้อมูลที่ได้</Button>
              </Space>
            </>
          )}
        </Space>
      )}

      {step === 5 && buildResult && (
        <Result status={buildResult.qa?.status === 'pass' ? 'success' : 'warning'}
          title={`สร้าง Dashboard สำเร็จ · QA: ${(buildResult.qa?.status || '').toUpperCase()}`}
          subTitle={`${buildResult.records ?? 0} records`}
          extra={[
            <Button type="primary" key="open" href={`/api/projects/${current}/dashboard`} target="_blank">เปิด Dashboard</Button>,
            <Button key="edit" icon={<BulbOutlined />} onClick={() => { setAnalysis(null); setStep(6); }}>แก้ไข Dashboard</Button>,
            <Button key="datalink" href={`/api/projects/${current}/datalink-bundle`}>ดาวน์โหลด DataLink Bundle</Button>,
            <Button key="again" onClick={() => { resetAnalysis(); setProfileData(null); setDetail(null); setStep(0); setBuildResult(null); }}>สร้างอันใหม่</Button>,
          ]} />
      )}

      {step === 6 && (
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Alert type="info" showIcon
            message="สั่งแก้ไข Dashboard ด้วยภาษาไทย"
            description="เลือกคำสั่งลัด หรือพิมพ์เอง ระบบจะให้ AI แก้แผน (spec) ก่อน แล้วค่อยกดสร้างใหม่ให้มีผล — เก็บประวัติย้อนกลับได้" />

          <Card size="small" title="คำสั่งลัด">
            <Space direction="vertical" style={{ width: '100%' }} size={6}>
              {[
                ['เพิ่มตัวกรอง', 'เพิ่มตัวกรองที่เป็นประโยชน์กับ dashboard นี้ โดยใช้เฉพาะฟิลด์ที่มีในข้อมูล'],
                ['เปลี่ยนประเภทกราฟ', 'ปรับประเภทกราฟให้เหมาะกับข้อมูลแต่ละอัน เช่น แนวโน้มใช้กราฟเส้น เปรียบเทียบใช้กราฟแท่ง สัดส่วนใช้กราฟวงกลม'],
                ['เพิ่มกราฟ/วิเคราะห์เพิ่ม', 'เพิ่มกราฟวิเคราะห์ที่มีประโยชน์เพิ่มเติม โดยใช้เฉพาะฟิลด์ที่มีในข้อมูลและระบุข้อจำกัด'],
                ['เพิ่ม KPI ลูกศรขึ้น-ลง', 'เพิ่ม KPI การ์ดที่มีการเปรียบเทียบปีปัจจุบันกับปีก่อนหน้า พร้อมลูกศรขึ้น-ลง (comparison latest_year_vs_previous_year)'],
                ['แก้วิธีการคำนวณ', 'ปรับวิธีการคำนวณของ KPI/กราฟ ระบุตัวตั้ง ตัวหาร และช่วงเวลาให้ชัดเจน ถ้าสูตรไม่อยู่ใน Python ให้เสนอเป็น metric contract'],
              ].map(([label, preset]) => (
                <Button key={label} block style={{ textAlign: 'left' }} disabled={improving || busy}
                  onClick={() => { setEditInstruction(preset); runImprove(preset); }}>{label}</Button>
              ))}
            </Space>
          </Card>

          <Input.TextArea rows={3} placeholder="หรือพิมพ์คำสั่งแก้ไขเอง เช่น เพิ่มกราฟแท่งจำนวนนักศึกษาตามชั้นปี และตัวกรองสาขา"
            value={editInstruction} onChange={(e) => setEditInstruction(e.target.value)} disabled={improving} />

          {improving && (
            <Card size="small" style={{ background: 'var(--ant-color-fill-quaternary, #fafafa)' }}>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space><Spin size="small" /><Text strong>{stage || 'กำลังแก้ไข…'}</Text></Space>
                <Progress percent={progress} status="active" />
              </Space>
            </Card>
          )}

          {analysis && !improving && (
            <>
              <Alert type="success" showIcon message="แก้ไขแผนเสร็จแล้ว — ตรวจด้านล่าง แล้วกด “สร้าง Dashboard ใหม่”" />
              <Card size="small" title={<Space><BulbOutlined />KPI ({kpis.length})</Space>}>
                {kpis.length ? <List size="small" dataSource={kpis}
                  renderItem={(k) => <List.Item>{k.name || k.metric}{k.comparison?.enabled ? <Tag color="blue" style={{ marginInlineStart: 8 }}>มีลูกศรเทียบปี</Tag> : null}</List.Item>} />
                  : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>
              <Card size="small" title={<Space><BarChartOutlined />กราฟ ({charts.length})</Space>}>
                {charts.length ? <List size="small" dataSource={charts}
                  renderItem={(c) => <List.Item><Space wrap>{c.title || c.name}<Tag>{CHART_TYPE_TH[c.type] || c.type}</Tag></Space></List.Item>} />
                  : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />}
              </Card>
              {filters.length > 0 && (
                <Card size="small" title={<Space><FilterOutlined />ตัวกรอง ({filters.length})</Space>}>
                  <Space wrap>{filters.map((f, i) => <Tag key={i}>{f.label || f.field || f}</Tag>)}</Space>
                </Card>
              )}
            </>
          )}

          <Space wrap>
            <Button type="primary" icon={<BarChartOutlined />} loading={busy}
              onClick={async () => { await build(); }}>สร้าง Dashboard ใหม่</Button>
            <Button onClick={() => runImprove()} disabled={improving || busy || !editInstruction.trim()}>ส่งคำสั่งที่พิมพ์เอง</Button>
            <Button type="link" href={`/api/projects/${current}/dashboard`} target="_blank">เปิด Dashboard ปัจจุบัน</Button>
            {buildResult && <Button type="link" onClick={() => setStep(5)}>กลับหน้าผลลัพธ์</Button>}
          </Space>
        </Space>
      )}
    </Card>
  );
}
