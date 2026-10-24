const fs = require('node:fs');
const path = require('node:path');
const limits = { 'vpn-favorites': 302, 'vpn-events': 80 };

class DesktopStore {
  constructor(file) {
    this.file = file;
    try { this.values = JSON.parse(fs.readFileSync(file, 'utf8')); }
    catch { this.values = {}; }
  }
  read(key) {
    const values = this.values[key];
    return Object.hasOwn(limits, key) && Array.isArray(values) && values.every(value => typeof value === 'string') ? values.slice(0, limits[key]) : null;
  }
  write(key, values) {
    if (!Object.hasOwn(limits, key) || !Array.isArray(values) || values.length > limits[key] || values.some(value => typeof value !== 'string' || value.length > 1024)) throw new Error('Invalid desktop data');
    this.values[key] = values;
    fs.mkdirSync(path.dirname(this.file), {recursive:true});
    fs.writeFileSync(`${this.file}.tmp`, JSON.stringify(this.values), {mode:0o600});
    fs.renameSync(`${this.file}.tmp`, this.file);
  }
  snapshot() { return Object.fromEntries(Object.keys(limits).map(key => [key, this.read(key)])); }
}
module.exports = { DesktopStore };
