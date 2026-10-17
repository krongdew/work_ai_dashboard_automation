import { useEffect, useState } from 'react';
import { Layout, Menu, Button, Typography, Spin, Result, Tag, Grid, Drawer, App as AntApp } from 'antd';
import { AppstoreOutlined, PlusCircleOutlined, TeamOutlined, GoogleOutlined, LogoutOutlined, MenuOutlined, ReadOutlined, ApartmentOutlined, LayoutOutlined } from '@ant-design/icons';
import { Routes, Route, useNavigate, useLocation, Navigate } from 'react-router-dom';
import { api, setCsrf } from './api.js';
import { GOLD } from './theme.js';
import WorkspaceWizard from './pages/WorkspaceWizard.jsx';
import DashboardsPage from './pages/DashboardsPage.jsx';
import AdminPage from './pages/AdminPage.jsx';
import HelpPage from './pages/HelpPage.jsx';
import CityPage from './pages/CityPage.jsx';

const { Header, Sider, Content } = Layout;
const { useBreakpoint } = Grid;

function LoginScreen({ oauthConfigured, loginError }) {
  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#F4F5F9', padding: 16 }}>
      <div style={{ background: '#fff', borderTop: `4px solid ${GOLD}`, borderRadius: 8, padding: 'clamp(24px,5vw,48px)', maxWidth: 440, width: '100%', textAlign: 'center', boxShadow: '0 6px 24px #0b2b5e1a' }}>
        <Typography.Title level={3} style={{ color: '#0B2B5E', marginBottom: 4 }}>Dashboard Factory</Typography.Title>
        <Typography.Paragraph type="secondary">คณะศิลปศาสตร์ มหาวิทยาลัยมหิดล</Typography.Paragraph>
        {loginError && <Typography.Paragraph type="danger">{loginError}</Typography.Paragraph>}
        {oauthConfigured ? (
          <Button type="primary" size="large" icon={<GoogleOutlined />} href="/api/auth/google/login" block>
            เข้าสู่ระบบด้วย Google
          </Button>
        ) : (
          <Result status="warning" title="ยังไม่ได้ตั้งค่า Google OAuth"
            subTitle="ผู้ดูแลระบบต้องใส่ GOOGLE_CLIENT_ID และ GOOGLE_CLIENT_SECRET ใน .env ก่อน" />
        )}
        <Typography.Paragraph type="secondary" style={{ marginTop: 16, fontSize: 12 }}>
          อนุญาตเฉพาะอีเมล @mahidol.ac.th ที่ได้รับสิทธิ์แล้วเท่านั้น
        </Typography.Paragraph>
      </div>
    </div>
  );
}

export default function App() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [health, setHealth] = useState(null);
  const [drawer, setDrawer] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const screens = useBreakpoint();
  const isMobile = !screens.md;

  const loginError = new URLSearchParams(location.search).get('login_error');

  useEffect(() => {
    Promise.all([
      api.get('/api/me').catch(() => ({ authenticated: false })),
      api.get('/api/health').catch(() => null),
    ]).then(([meData, healthData]) => {
      setMe(meData);
      setHealth(healthData);
      if (meData?.csrf) setCsrf(meData.csrf);
      setLoading(false);
    });
  }, []);

  if (loading) return <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }}><Spin size="large" /></div>;
  if (!me?.authenticated) return <LoginScreen oauthConfigured={me?.oauth_configured} loginError={loginError} />;

  const providerLabel = { local: 'Local AI (LM Studio)', groq: 'Groq Cloud', worker: 'LAN Worker' }[health?.ai_provider] || 'ไม่ทราบ';

  const cityMode = location.pathname === '/city';
  function toggleView() {
    if (cityMode) {
      const back = localStorage.getItem('dfx:lastClassic') || '/';
      localStorage.setItem('dfx:viewMode', 'classic');
      navigate(back);
    } else {
      localStorage.setItem('dfx:lastClassic', location.pathname);
      localStorage.setItem('dfx:viewMode', 'city');
      navigate('/city');
    }
  }

  const items = [
    { key: '/', icon: <PlusCircleOutlined />, label: 'สร้าง Dashboard' },
    { key: '/dashboards', icon: <AppstoreOutlined />, label: 'Dashboard ทั้งหมด' },
    { key: '/city', icon: <ApartmentOutlined />, label: 'เมือง Workflow (3D)' },
    ...(me.is_admin ? [{ key: '/admin', icon: <TeamOutlined />, label: 'จัดการระบบ' }] : []),
    { key: '/help', icon: <ReadOutlined />, label: 'คู่มือการใช้งาน' },
  ];

  const menu = (
    <Menu mode="inline" theme="light" selectedKeys={[location.pathname]} items={items}
      onClick={({ key }) => { navigate(key); setDrawer(false); }} style={{ borderInlineEnd: 'none', padding: '8px', fontWeight: 500 }} />
  );

  const brand = (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '18px 20px 10px' }}>
      <div style={{ width: 34, height: 34, borderRadius: 10, background: 'linear-gradient(135deg,#0B2B5E,#263988)', color: GOLD, display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: 18 }}>✧</div>
      <div style={{ lineHeight: 1.15 }}>
        <div style={{ fontWeight: 700, color: '#0B2B5E', fontSize: 14 }}>Dashboard Factory</div>
        <div style={{ fontSize: 11, color: '#8a93a6' }}>คณะศิลปศาสตร์ ม.มหิดล</div>
      </div>
    </div>
  );

  async function logout() { await api.post('/api/auth/logout'); window.location.href = '/'; }

  return (
    <AntApp>
      <Layout style={{ minHeight: '100vh' }}>
        <Header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: `3px solid ${GOLD}`, paddingInline: 'clamp(12px,3vw,24px)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, color: '#fff' }}>
            {isMobile && <Button type="text" icon={<MenuOutlined />} style={{ color: '#fff' }} onClick={() => setDrawer(true)} />}
            <strong style={{ letterSpacing: '.01em' }}>✧ Dashboard Factory</strong>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Button size="small" icon={cityMode ? <LayoutOutlined /> : <ApartmentOutlined />} onClick={toggleView}
              style={{ borderRadius: 8, fontWeight: 600 }}>
              {cityMode ? 'หน้าปกติ' : 'เมือง 3D'}
            </Button>
            <Tag color="gold" style={{ borderRadius: 999, margin: 0 }}>AI: {providerLabel}</Tag>
            {!isMobile && <span style={{ color: '#fff', fontSize: 13, opacity: .9 }}>{me.email}{me.is_admin ? ' (admin)' : ''}</span>}
            <Button size="small" icon={<LogoutOutlined />} onClick={logout} style={{ borderRadius: 8 }}>ออก</Button>
          </div>
        </Header>
        <Layout>
          {isMobile ? (
            <Drawer open={drawer} onClose={() => setDrawer(false)} placement="left" width={248} styles={{ body: { padding: 0 } }}>{brand}{menu}</Drawer>
          ) : (
            <Sider width={236} breakpoint="md" collapsedWidth={0} style={{ borderRight: '1px solid #e3e8f0' }}>{brand}{menu}</Sider>
          )}
          <Content style={{ margin: 'clamp(12px,3vw,24px)', padding: 'clamp(14px,2vw,22px)', background: 'transparent' }}>
            <Routes>
              <Route path="/" element={<WorkspaceWizard me={me} />} />
              <Route path="/dashboards" element={<DashboardsPage me={me} />} />
              <Route path="/admin" element={me.is_admin ? <AdminPage /> : <Navigate to="/" />} />
              <Route path="/help" element={<HelpPage />} />
              <Route path="/city" element={<CityPage />} />
            </Routes>
          </Content>
        </Layout>
      </Layout>
    </AntApp>
  );
}
