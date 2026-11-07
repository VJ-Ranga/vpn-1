const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../..');

test('Windows ICO contains valid PNG images at every supported icon size', () => {
  const ico = fs.readFileSync(path.join(root, 'assets/northstar-vpn.ico'));
  assert.equal(ico.readUInt16LE(0), 0);
  assert.equal(ico.readUInt16LE(2), 1);
  const sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256];
  assert.equal(ico.readUInt16LE(4), sizes.length);
  sizes.forEach((size, index) => {
    const entry = 6 + index * 16;
    assert.equal(ico[entry] || 256, size);
    assert.equal(ico[entry + 1] || 256, size);
    const length = ico.readUInt32LE(entry + 8);
    const offset = ico.readUInt32LE(entry + 12);
    const image = ico.subarray(offset, offset + length);
    assert.equal(image.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
    assert.equal(image.readUInt32BE(16), size);
    assert.equal(image.readUInt32BE(20), size);
  });
});

test('Windows resources are branded even when code signing is unavailable', () => {
  const { build } = require('../../package.json');
  assert.equal(build.win.icon, 'assets/northstar-vpn.ico');
  assert.equal(build.win.signAndEditExecutable, true);
  assert.equal(build.win.signExecutable, false);
  assert.equal(build.nsis.installerIcon, build.win.icon);
  assert.equal(build.nsis.uninstallerIcon, build.win.icon);
  const main = fs.readFileSync(path.join(root, 'desktop/main.cjs'), 'utf8');
  assert.match(main, /setAppUserModelId\("org\.northstarvpn\.desktop"\)/);
  assert.match(main, /nativeImage\.createFromPath\(path\.join\(root, "assets", "northstar-vpn\.png"\)\)/);
});
