import { useEffect, useState } from 'react';
import { Tabs, Table, Button, Input, Space, Select, Tag, Popconfirm, App, Card } from 'antd';
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import { api } from '../api.js';

function Orgs() {
  const { message } = App.useApp();
  const [orgs, setOrgs] = useState([]);
  const [name, setName] = useState('');
  const [subName, setSubName] = useState({});
  const load = () => api.get('/api/admin/organizations').then(setOrgs).catch((e) => message.error(e.message));
  useEffect(() => { load(); }, []);

  const addOrg = async () => { if (!name.trim()) return; try { await api.post('/api/admin/organizations', { name: name.trim() }); setName(''); load(); } catch (e) { message.error(e.message); } };
  const delOrg = async (id) => { try { await api.del(`/api/admin/organizations/${id}`); load(); } catch (e) { message.error(e.message); } };
  const addSub = async (orgId) => { const v = (subName[orgId] || '').trim(); if (!v) return; try { await api.post(`/api/admin/organizations/${orgId}/sub-units`, { name: v }); setSubName({ ...subName, [orgId]: '' }); load(); } catch (e) { message.error(e.message); } };
  const delSub = async (id) => { try { await api.del(`/api/admin/sub-units/${id}`); load(); } catch (e) { message.error(e.message); } };

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Space.Compact style={{ maxWidth: 420 }}>
        <Input placeholder="ชื่อหน่วยงานใหม่" value={name} onChange={(e) => setName(e.target.value)} onPressEnter={addOrg} />
        <Button type="primary" icon={<PlusOutlined />} onClick={addOrg}>เพิ่มหน่วยงาน</Button>
      </Space.Compact>
      {orgs.map((o) => (
        <Card key={o.id} size="small" title={o.name}
          extra={<Popconfirm title="ลบหน่วยงานนี้?" okText="ลบ" cancelText="ยกเลิก" onConfirm={() => delOrg(o.id)}><Button danger size="small" icon={<DeleteOutlined />}>ลบ</Button></Popconfirm>}>
          <Space wrap>
            {o.sub_units.map((s) => (
              <Tag key={s.id} closable onClose={() => delSub(s.id)}>{s.name}</Tag>
            ))}
          </Space>
          <Space.Compact style={{ marginTop: 8, maxWidth: 360 }}>
            <Input size="small" placeholder="เพิ่มหน่วยย่อย" value={subName[o.id] || ''} onChange={(e) => setSubName({ ...subName, [o.id]: e.target.value })} onPressEnter={() => addSub(o.id)} />
            <Button size="small" onClick={() => addSub(o.id)}>เพิ่ม</Button>
          </Space.Compact>
        </Card>
      ))}
    </Space>
  );
}

function Users() {
  const { message } = App.useApp();
  const [users, setUsers] = useState([]);
  const [orgs, setOrgs] = useState([]);
  const [email, setEmail] = useState('');
  const load = () => {
    api.get('/api/admin/users').then(setUsers).catch((e) => message.error(e.message));
    api.get('/api/admin/organizations').then(setOrgs).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const addUser = async () => { if (!email.trim()) return; try { await api.post('/api/admin/users', { email: email.trim() }); setEmail(''); load(); message.success('เพิ่มผู้ใช้แล้ว'); } catch (e) { message.error(e.message); } };
  const update = async (id, patch) => { try { await api.put(`/api/admin/users/${id}`, patch); load(); } catch (e) { message.error(e.message); } };
  const del = async (id) => { try { await api.del(`/api/admin/users/${id}`); load(); } catch (e) { message.error(e.message); } };

  const subUnitOptions = (orgId) => (orgs.find((o) => o.id === orgId)?.sub_units || []).map((s) => ({ value: s.id, label: s.name }));

  const columns = [
    { title: 'อีเมล', dataIndex: 'email' },
    { title: 'ชื่อ', dataIndex: 'full_name' },
    { title: 'บทบาท', dataIndex: 'role', render: (r, u) => (
      <Select size="small" value={r} style={{ width: 110 }} onChange={(v) => update(u.id, { role: v })}
        options={[{ value: 'member', label: 'สมาชิก' }, { value: 'admin', label: 'ผู้ดูแล' }]} /> ) },
    { title: 'หน่วยงาน', dataIndex: 'org_id', render: (v, u) => (
      <Select size="small" allowClear placeholder="—" value={v} style={{ width: 160 }} onChange={(val) => update(u.id, { org_id: val, sub_unit_id: null })}
        options={orgs.map((o) => ({ value: o.id, label: o.name }))} /> ) },
    { title: 'หน่วยย่อย', dataIndex: 'sub_unit_id', render: (v, u) => (
      <Select size="small" allowClear placeholder="—" value={v} style={{ width: 160 }} disabled={!u.org_id} onChange={(val) => update(u.id, { sub_unit_id: val })}
        options={subUnitOptions(u.org_id)} /> ) },
    { title: 'สถานะ', dataIndex: 'active', render: (a) => <Tag color={a ? 'green' : 'default'}>{a ? 'ใช้งาน' : 'ปิด'}</Tag> },
    { title: '', render: (_, u) => (
      <Popconfirm title="ปิดการใช้งานผู้ใช้นี้?" okText="ปิด" cancelText="ยกเลิก" onConfirm={() => del(u.id)}>
        <Button danger size="small" icon={<DeleteOutlined />} /></Popconfirm> ) },
  ];

  return (
    <Space direction="vertical" style={{ width: '100%' }} size="middle">
      <Space.Compact style={{ maxWidth: 480 }}>
        <Input placeholder="อีเมล @mahidol.ac.th" value={email} onChange={(e) => setEmail(e.target.value)} onPressEnter={addUser} />
        <Button type="primary" icon={<PlusOutlined />} onClick={addUser}>เพิ่มผู้ใช้</Button>
      </Space.Compact>
      <Table rowKey="id" dataSource={users} columns={columns} size="small" scroll={{ x: 'max-content' }} pagination={false} />
    </Space>
  );
}

export default function AdminPage() {
  return (
    <Card title="จัดการระบบ" style={{ maxWidth: 1100, margin: 'auto' }}>
      <Tabs items={[
        { key: 'users', label: 'ผู้ใช้', children: <Users /> },
        { key: 'orgs', label: 'หน่วยงาน & หน่วยย่อย', children: <Orgs /> },
      ]} />
    </Card>
  );
}
