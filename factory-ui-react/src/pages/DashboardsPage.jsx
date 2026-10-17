import { useEffect, useMemo, useState } from 'react';
import { Row, Col, Card, Button, Tag, Input, Empty, Popconfirm, App, Space, Select, Segmented, Table } from 'antd';
import { DeleteOutlined, ExportOutlined, EditOutlined, AppstoreOutlined, TableOutlined, DownloadOutlined } from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import { api } from '../api.js';

const VISIBILITY_TH = {
  sub_unit: { label: 'เฉพาะหน่วยย่อย', color: 'purple' },
  org: { label: 'ทั้งหน่วยงาน', color: 'blue' },
  authenticated: { label: 'สาธารณะในองค์กร', color: 'green' },
};

export default function DashboardsPage() {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [q, setQ] = useState('');
  const [orgFilter, setOrgFilter] = useState(null);
  const [subFilter, setSubFilter] = useState(null);
  const [visFilter, setVisFilter] = useState(null);
  const [view, setView] = useState(() => localStorage.getItem('dashboards_view') || 'gallery');

  const load = () => api.get('/api/projects').then(setItems).catch((e) => message.error(e.message));
  useEffect(() => { load(); }, []);

  function setViewPersist(v) { setView(v); localStorage.setItem('dashboards_view', v); }

  async function remove(name) {
    try { await api.del(`/api/projects/${name}`); message.success(`ลบ ${name} แล้ว`); await load(); }
    catch (e) { message.error(e.message); }
  }

  // Build filter option lists from whatever the visible projects carry.
  const orgOptions = useMemo(() => {
    const m = new Map();
    items.forEach((i) => { if (i.org_id != null) m.set(i.org_id, i.org_name || `หน่วยงาน #${i.org_id}`); });
    return [...m].map(([value, label]) => ({ value, label }));
  }, [items]);
  const subOptions = useMemo(() => {
    const m = new Map();
    items.filter((i) => !orgFilter || i.org_id === orgFilter)
      .forEach((i) => { if (i.sub_unit_id != null) m.set(i.sub_unit_id, i.sub_unit_name || `หน่วยย่อย #${i.sub_unit_id}`); });
    return [...m].map(([value, label]) => ({ value, label }));
  }, [items, orgFilter]);

  const shown = items.filter((i) =>
    `${i.title} ${i.name}`.toLowerCase().includes(q.toLowerCase())
    && (orgFilter == null || i.org_id === orgFilter)
    && (subFilter == null || i.sub_unit_id === subFilter)
    && (visFilter == null || i.visibility === visFilter),
  );

  const actions = (item) => (
    <Space>
      {item.built && <Button size="small" type="primary" icon={<ExportOutlined />} href={`/api/projects/${item.name}/dashboard`} target="_blank">เปิด</Button>}
      {item.built && <Button size="small" icon={<EditOutlined />} onClick={() => navigate(`/?project=${encodeURIComponent(item.name)}&edit=1`)}>แก้ไข</Button>}
      {item.built && <Button size="small" icon={<DownloadOutlined />} href={`/api/projects/${item.name}/datalink-bundle`}>DataLink</Button>}
      <Popconfirm title="ลบโปรเจกต์นี้?" description="ลบแล้วกู้คืนไม่ได้" okText="ลบ" cancelText="ยกเลิก" okButtonProps={{ danger: true }} onConfirm={() => remove(item.name)}>
        <Button size="small" danger icon={<DeleteOutlined />}>ลบ</Button>
      </Popconfirm>
    </Space>
  );

  const columns = [
    {
      title: 'Dashboard', dataIndex: 'title', key: 'title',
      sorter: (a, b) => (a.title || a.name).localeCompare(b.title || b.name, 'th'),
      render: (_, item) => (
        <div>
          <div style={{ fontWeight: 600 }}>{item.title || item.name}</div>
          <div style={{ color: '#6B7280', fontSize: 12 }}>{item.name} · {item.input_files} ไฟล์</div>
        </div>
      ),
    },
    {
      title: 'หน่วยงาน', dataIndex: 'org_name', key: 'org_name',
      sorter: (a, b) => (a.org_name || '').localeCompare(b.org_name || '', 'th'),
      render: (v) => v ? <Tag>{v}</Tag> : <span style={{ color: '#aaa' }}>—</span>,
    },
    {
      title: 'หน่วยย่อย', dataIndex: 'sub_unit_name', key: 'sub_unit_name',
      render: (v) => v ? <Tag color="purple">{v}</Tag> : <span style={{ color: '#aaa' }}>—</span>,
    },
    {
      title: 'การมองเห็น', dataIndex: 'visibility', key: 'visibility',
      filters: Object.entries(VISIBILITY_TH).map(([value, v]) => ({ text: v.label, value })),
      onFilter: (value, item) => item.visibility === value,
      render: (v) => { const t = VISIBILITY_TH[v]; return t ? <Tag color={t.color}>{t.label}</Tag> : <span style={{ color: '#aaa' }}>—</span>; },
    },
    {
      title: 'QA', dataIndex: 'qa_status', key: 'qa_status', width: 90,
      render: (v) => v ? <Tag color={v === 'ready' ? 'green' : 'orange'}>{v.toUpperCase()}</Tag> : <span style={{ color: '#aaa' }}>—</span>,
    },
    { title: '', key: 'actions', align: 'right', render: (_, item) => actions(item) },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: 'auto' }}>
      <Space wrap style={{ marginBottom: 16, width: '100%', justifyContent: 'space-between' }}>
        <Space wrap>
          <Input.Search placeholder="ค้นหา dashboard" allowClear style={{ width: 240 }} onChange={(e) => setQ(e.target.value)} />
          <Select placeholder="หน่วยงาน" allowClear style={{ minWidth: 170 }} value={orgFilter}
            onChange={(v) => { setOrgFilter(v ?? null); setSubFilter(null); }} options={orgOptions} />
          <Select placeholder="หน่วยย่อย" allowClear style={{ minWidth: 170 }} value={subFilter}
            onChange={(v) => setSubFilter(v ?? null)} options={subOptions} disabled={subOptions.length === 0} />
          <Select placeholder="การมองเห็น" allowClear style={{ minWidth: 160 }} value={visFilter}
            onChange={(v) => setVisFilter(v ?? null)}
            options={Object.entries(VISIBILITY_TH).map(([value, v]) => ({ value, label: v.label }))} />
        </Space>
        <Segmented value={view} onChange={setViewPersist}
          options={[
            { value: 'gallery', icon: <AppstoreOutlined />, label: 'แกลเลอรี' },
            { value: 'table', icon: <TableOutlined />, label: 'ตาราง' },
          ]} />
      </Space>

      {shown.length === 0 ? (
        <Empty description="ยังไม่มี dashboard ที่ตรงเงื่อนไข" />
      ) : view === 'table' ? (
        <Table rowKey="name" size="middle" dataSource={shown} columns={columns}
          pagination={shown.length > 15 ? { pageSize: 15 } : false} scroll={{ x: 'max-content' }} />
      ) : (
        <Row gutter={[16, 16]}>
          {shown.map((item) => {
            const vis = VISIBILITY_TH[item.visibility];
            return (
              <Col xs={24} sm={12} lg={8} key={item.name}>
                <Card hoverable
                  styles={{ header: { borderTop: '3px solid #6C5CE7', borderRadius: '16px 16px 0 0' } }}
                  title={item.title || item.name}
                  extra={item.qa_status && <Tag color={item.qa_status === 'ready' ? 'green' : 'orange'}>{item.qa_status.toUpperCase()}</Tag>}>
                  <p style={{ color: '#6B7280', marginBottom: 8 }}>{item.name} · {item.input_files} ไฟล์</p>
                  <Space wrap style={{ marginBottom: 12 }}>
                    {item.org_name && <Tag>{item.org_name}</Tag>}
                    {item.sub_unit_name && <Tag color="purple">{item.sub_unit_name}</Tag>}
                    {vis && <Tag color={vis.color}>{vis.label}</Tag>}
                  </Space>
                  <div>{actions(item)}</div>
                </Card>
              </Col>
            );
          })}
        </Row>
      )}
    </div>
  );
}
