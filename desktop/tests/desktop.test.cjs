const { test } = require('node:test');
const assert = require('node:assert/strict');
const { safeExternal, allowedNavigation, trayTemplate, desktopEntry } = require('../policy.cjs');
const { stopBackend, waitForBackend } = require('../backend.cjs');

test('external navigation allows only exact trusted HTTPS hosts', () => {
  assert.equal(safeExternal('https://www.namecheap.com/help-center/live-chat/'), true);
  for (const url of ['file:///etc/passwd', 'javascript:alert(1)', 'https://www.namecheap.com.attacker.example/', 'http://www.namecheap.com/', 'https://attacker.example/']) assert.equal(safeExternal(url), false);
});

test('renderer navigation stays on the application root', () => {
  assert.equal(allowedNavigation('http://127.0.0.1:12345/?compact=1', 'http://127.0.0.1:12345'), true);
  assert.equal(allowedNavigation('http://127.0.0.1:12345/api/settings/credentials', 'http://127.0.0.1:12345'), false);
  assert.equal(allowedNavigation('https://attacker.example/', 'http://127.0.0.1:12345'), false);
});

test('tray dispatches selected favorite and disconnect commands', () => {
  const calls = [];
  const items = trayTemplate({ connected: true, city: 'Melbourne', favorites: [{ id: 'profile-1', label: 'Chicago' }] }, command => calls.push(command));
  items.find(item => item.label === 'Disconnect').click();
  items.find(item => item.label === 'Favorites').submenu[0].click();
  assert.deepEqual(calls, ['disconnect', 'connect:profile-1']);
});

test('quit stops only the child backend owned by this instance', () => {
  let calls = 0;
  stopBackend(null);
  stopBackend({ exitCode: 0, kill: () => calls++ });
  stopBackend({ exitCode: null, kill: signal => { assert.equal(signal, 'SIGTERM'); calls++; } });
  assert.equal(calls, 1);
});

test('readiness requires matching backend instance identity', async () => {
  await assert.rejects(waitForBackend('http://localhost', 'expected', 20, async () => ({ ok: true, json: async () => ({ instance: 'someone-else' }) })), /start/);
  await waitForBackend('http://localhost', 'expected', 100, async () => ({ ok: true, json: async () => ({ instance: 'expected' }) }));
});

test('startup entry safely quotes paths containing spaces', () => {
  const entry = desktopEntry('/home/test/My VPN', '/usr/bin/node');
  assert.match(entry, /Exec="\/home\/test\/My VPN\/scripts\/start-desktop.sh" --background/);
  assert.match(entry, /Terminal=false/);
});

test('favorites and logs survive desktop restart independently of backend origin', () => {
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const { DesktopStore } = require('../store.cjs');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'northstar-store-'));
  try {
    const file = path.join(directory, 'state.json');
    new DesktopStore(file).write('vpn-favorites', ['country:US', 'profile-1']);
    new DesktopStore(file).write('vpn-events', ['Connected to Singapore']);
    const restarted = new DesktopStore(file);
    assert.deepEqual(restarted.read('vpn-favorites'), ['country:US', 'profile-1']);
    assert.deepEqual(restarted.read('vpn-events'), ['Connected to Singapore']);
    assert.throws(() => restarted.write('../arbitrary', ['bad']));
  } finally { fs.rmSync(directory, {recursive:true,force:true}); }
});
