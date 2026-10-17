// Thin API client. Carries the CSRF token on state-changing requests.
let csrfToken = '';
export function setCsrf(token) { csrfToken = token || ''; }
export function getCsrf() { return csrfToken; }

async function request(method, url, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (method !== 'GET' && csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const resp = await fetch(url, {
    method,
    headers,
    credentials: 'same-origin',
    body: body ? JSON.stringify(body) : undefined,
  });
  const type = resp.headers.get('content-type') || '';
  const data = type.includes('application/json') ? await resp.json() : {};
  if (!resp.ok) throw new Error(data.error || `คำขอผิดพลาด (${resp.status})`);
  return data;
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body),
  put: (url, body) => request('PUT', url, body),
  patch: (url, body) => request('PATCH', url, body),
  del: (url) => request('DELETE', url),
};
