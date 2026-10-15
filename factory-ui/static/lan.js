/* LAN-only account UI. Existing local Factory remains available unchanged. */
(() => {
  const originalFetch = window.fetch.bind(window);
  let csrf = '';
  let mode = 'local';
  const raw = async (path, options = {}) => {
    const response = await originalFetch(path, {credentials: 'same-origin', ...options});
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'Request failed');
    return data;
  };
  const post = (path, body = {}, method = 'POST') => raw(path, {
    method, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(body)
  });

  async function signIn() {
    return new Promise(resolve => {
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:fixed;inset:0;background:#eef3fb;z-index:10000;display:grid;place-items:center;padding:20px';
      overlay.innerHTML = '<form class="box" style="width:min(420px,100%)"><h1>Factory LAN</h1><p>เข้าสู่ระบบเพื่อจัดการโปรเจคส่วนตัว</p><label>ชื่อผู้ใช้<input name="username" autocomplete="username" required maxlength="40"></label><label>รหัสผ่าน<input name="password" type="password" autocomplete="current-password" required maxlength="256"></label><p id="lanLoginError" role="alert"></p><button class="primary" type="submit">เข้าสู่ระบบ</button></form>';
      document.body.append(overlay);
      overlay.querySelector('form').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const button = form.querySelector('button');
        button.disabled = true;
        try {
          const user = await post('/api/auth/login', {username: form.elements.namedItem('username').value, password: form.elements.namedItem('password').value});
          form.elements.namedItem('password').value = '';
          overlay.remove();
          resolve(user);
        } catch (error) {
          overlay.querySelector('#lanLoginError').textContent = error.message;
        } finally { button.disabled = false; }
      };
    });
  }

  const ready = (async () => {
    const health = await raw('/api/health');
    mode = health.mode;
    if (mode !== 'lan') return;
    let user;
    try { user = await raw('/api/auth/me'); }
    catch (_) { user = await signIn(); }
    csrf = user.csrf;
    const box = document.createElement('section');
    box.className = 'box';
    box.style.marginBottom = '18px';
    box.innerHTML = '<h2>บัญชีและ AI ของฉัน</h2><p id="lanUsername"></p><p id="lanWorkerStatus" role="status">กำลังตรวจ Worker…</p><button class="secondary" id="lanPair">สร้างรหัสจับคู่ Worker (5 นาที)</button><a class="secondary" href="/api/worker-package" style="display:inline-block;text-decoration:none">ดาวน์โหลด Worker</a><button class="secondary" id="lanRevoke">ยกเลิก Worker</button><button class="secondary" id="lanLogout">ออกจากระบบ</button><textarea id="lanPairCode" readonly hidden aria-label="รหัสจับคู่ Worker"></textarea><p>เปิด LM Studio และ Worker บนเครื่องของคุณก่อนกดสร้าง Spec ข้อมูลต้นฉบับเก็บบนเครื่องส่วนกลาง</p>';
    document.querySelector('main').prepend(box);
    box.querySelector('#lanUsername').textContent = `ผู้ใช้: ${user.username} · โปรเจคนี้เข้าถึงได้เฉพาะบัญชีของคุณ`;
    document.querySelectorAll('.online').forEach(el => { el.textContent = '● LAN · Private workspace'; });
    const local = document.querySelector('.local');
    if (local) local.textContent = 'AI ประมวลผลที่เครื่องของเจ้าของบัญชีผ่าน Worker';
    let workers = [];
    const refresh = async () => {
      try {
        workers = await raw('/api/workers');
        const worker = workers[0];
        box.querySelector('#lanWorkerStatus').textContent = worker ? `${worker.online ? 'ออนไลน์' : 'ออฟไลน์'} · ${worker.model}` : 'ยังไม่ได้จับคู่ Worker';
        box.querySelector('#lanRevoke').disabled = !worker;
      } catch (_) { box.querySelector('#lanWorkerStatus').textContent = 'ตรวจ Worker ไม่สำเร็จ กรุณาเข้าสู่ระบบใหม่หาก session หมดอายุ'; }
    };
    box.querySelector('#lanPair').onclick = async () => {
      try {
        const result = await post('/api/workers/pairing');
        const field = box.querySelector('#lanPairCode');
        field.hidden = false; field.value = result.code; field.select();
        setTimeout(() => { field.value = ''; field.hidden = true; }, result.expires_in * 1000);
      } catch (error) { alert(error.message); }
    };
    box.querySelector('#lanRevoke').onclick = async () => {
      try { if (workers[0]) await post(`/api/workers/${workers[0].id}`, {}, 'DELETE'); await refresh(); }
      catch (error) { alert(error.message); }
    };
    box.querySelector('#lanLogout').onclick = async () => {
      try { await post('/api/auth/logout'); location.reload(); }
      catch (error) { alert(error.message); }
    };
    await refresh();
    setInterval(refresh, 10000);
  })();

  window.fetch = async (input, options = {}) => {
    await ready;
    const headers = new Headers(options.headers || {});
    if (mode === 'lan' && !['GET', 'HEAD'].includes((options.method || 'GET').toUpperCase())) headers.set('X-CSRF-Token', csrf);
    const response = await originalFetch(input, {...options, headers, credentials: 'same-origin'});
    if (mode === 'lan' && response.status === 401) location.reload();
    return response;
  };
})();
