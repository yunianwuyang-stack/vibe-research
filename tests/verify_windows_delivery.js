const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'runtime-manifest.json'), 'utf8'));
const installer = path.join(root, 'release', manifest.installer.path);
const unpacked = path.join(root, 'release', 'win-unpacked', 'Vibe Research.exe');
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex').toUpperCase();
assert.equal(manifest.product, 'Vibe Research');
assert.equal(manifest.product_commit, spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).stdout.trim());
assert.equal(sha(installer), manifest.installer.sha256);
assert.equal(sha(unpacked), manifest.unpacked_executable.sha256);
assert.equal(manifest.installer.code_signing, 'NotSigned');
for (const rel of ['main.js', 'updater.js', 'desktop-data.js', 'backend/config.py']) {
  assert.equal(sha(path.join(root, rel)), sha(path.join(root, 'release', 'win-unpacked', 'resources', 'app', ...rel.split('/'))), rel);
}
const policy = spawnSync(process.execPath, [path.join(root, 'tests', 'test_installer_policy.js')], { cwd: root, encoding: 'utf8' });
assert.equal(policy.status, 0, policy.stderr);
const rollback = spawnSync(process.execPath, [path.join(root, 'tests', 'test_updater_rollback.js')], { cwd: root, encoding: 'utf8' });
assert.equal(rollback.status, 0, rollback.stderr);
console.log(JSON.stringify({ok:true,product_commit:manifest.product_commit,installer_sha256:manifest.installer.sha256,packaged_mapping:true,policy:true,rollback:true}));
