// Run from the repository: node data_factory/tests/test_lan_ui.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require(path.resolve(__dirname, '../../frontend/node_modules/jsdom'));
const html = fs.readFileSync(path.resolve(__dirname, '../factory-ui/static/index.html'), 'utf8');
const source = fs.readFileSync(path.resolve(__dirname, '../factory-ui/static/lan.js'), 'utf8');
const wait = () => new Promise(resolve => setTimeout(resolve, 30));

async function check(mode) {
  const dom = new JSDOM(html, {url: 'https://factory.test:8443', runScripts: 'outside-only'});
  const window = dom.window;
  const calls = [];
  let loggedIn = false;
  window.Headers = Headers;
  window.alert = message => { throw Error(message); };
  window.fetch = async (url, options = {}) => {
    calls.push({url, options});
    let data = {}, status = 200;
    if (url === '/api/health') data = {mode};
    else if (url === '/api/auth/me') { status = 401; data = {error: 'Please sign in'}; }
    else if (url === '/api/auth/login') { loggedIn = true; data = {username: 'alice', csrf: 'test-csrf', mode: 'lan'}; }
    else if (url === '/api/workers') data = [];
    else if (url === '/api/workers/pairing') data = {code: 'single-use-test-code', expires_in: 300};
    else if (url === '/api/projects') { assert.ok(mode === 'local' || loggedIn); data = []; }
    else if (url === '/api/calculation-rule-templates') data = {templates: []};
    return {ok: status < 400, status, statusText: '', headers: new Headers({'content-type': 'application/json'}), json: async () => data};
  };
  try {
    window.eval(source);
    const inline = [...window.document.querySelectorAll('script')].find(script => !script.src);
    window.eval(inline.textContent);
    await wait();
    if (mode === 'lan') {
      assert.equal(calls.filter(call => call.url === '/api/projects').length, 0);
      const form = window.document.querySelector('form');
      assert.ok(form, 'LAN mode shows login before API initialization');
      form.elements.namedItem('username').value = 'alice';
      form.elements.namedItem('password').value = 'private-test-password';
      form.dispatchEvent(new window.Event('submit', {bubbles: true, cancelable: true}));
      await wait();
      assert.match(window.document.querySelector('#lanUsername').textContent, /alice/);
      window.document.querySelector('#lanPair').click();
      await wait();
      assert.equal(window.document.querySelector('#lanPairCode').value, 'single-use-test-code');
      const pair = calls.find(call => call.url === '/api/workers/pairing');
      assert.equal(pair.options.headers['X-CSRF-Token'], 'test-csrf');
      await window.fetch('/api/projects', {method: 'POST', body: JSON.stringify({name: 'sample'})});
      const mutation = calls.filter(call => call.url === '/api/projects').at(-1);
      assert.equal(mutation.options.headers.get('X-CSRF-Token'), 'test-csrf');
    } else {
      assert.equal(window.document.querySelector('form'), null);
      assert.equal(calls.filter(call => call.url === '/api/auth/me').length, 0);
    }
    assert.ok(calls.some(call => call.url === '/api/projects'));
  } finally { window.close(); }
}

(async () => {
  await check('lan');
  await check('local');
  console.log('LAN login, CSRF, pairing UI and local-mode compatibility passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
