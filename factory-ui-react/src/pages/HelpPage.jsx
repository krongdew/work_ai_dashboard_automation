import { useEffect, useState } from 'react';
import { Card, Typography, Spin } from 'antd';

export default function HelpPage() {
  const [text, setText] = useState(null);
  useEffect(() => {
    fetch('/api/manual', { credentials: 'same-origin' })
      .then((r) => r.text()).then(setText).catch(() => setText('ไม่สามารถโหลดคู่มือได้'));
  }, []);
  return (
    <Card title="คู่มือการใช้งานระบบ" style={{ maxWidth: 900, margin: 'auto' }}>
      {text === null ? <Spin /> : (
        <Typography>
          <pre style={{ whiteSpace: 'pre-wrap', fontFamily: "Prompt, 'Noto Sans Thai', sans-serif", margin: 0 }}>{text}</pre>
        </Typography>
      )}
    </Card>
  );
}
