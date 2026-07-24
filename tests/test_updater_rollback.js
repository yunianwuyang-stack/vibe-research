const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { Updater } = require('../updater');

function sha(value) { return crypto.createHash('sha256').update(value).digest('hex'); }
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vibe-upgrade-中文-'));
const user = path.join(root, 'user data');
fs.mkdirSync(path.join(root, 'resources', 'app'), { recursive: true });
fs.writeFileSync(path.join(root, 'resources', 'app', 'version.txt'), 'old');
const updater = new Updater({ install_dir: root, user_data_dir: user });
fs.mkdirSync(path.join(updater.updateStagingDir, 'resources', 'app'), { recursive: true });
fs.writeFileSync(path.join(updater.updateStagingDir, 'resources', 'app', 'version.txt'), 'new');
fs.writeFileSync(path.join(updater.updateStagingDir, '.manifest.json'), JSON.stringify({ files: [
  { rel: 'resources/app/version.txt', sha256: sha('not-new') }
] }));
const helper = path.join(root, 'apply update.ps1');
updater._writePowerShellHelper(helper, path.join(root, 'missing.exe'), 999999);
const result = spawnSync('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', helper], { encoding: 'utf8' });
assert.equal(result.status, 0, result.stderr);
assert.equal(fs.readFileSync(path.join(root, 'resources', 'app', 'version.txt'), 'utf8'), 'old');
assert.throws(() => updater._validateRelativePath('../escape'), /unsafe update path/);
console.log('updater restores backup after failed verification');

const successRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'vibe-upgrade-success-中文-'));
fs.mkdirSync(path.join(successRoot, 'resources', 'app'), { recursive: true });
fs.writeFileSync(path.join(successRoot, 'resources', 'app', 'version.txt'), 'old');
const successful = new Updater({ install_dir: successRoot, user_data_dir: successRoot });
fs.mkdirSync(path.join(successful.updateStagingDir, 'resources', 'app'), { recursive: true });
fs.writeFileSync(path.join(successful.updateStagingDir, 'resources', 'app', 'version.txt'), 'new');
fs.writeFileSync(path.join(successful.updateStagingDir, '.manifest.json'), JSON.stringify({ files: [
  { rel: 'resources/app/version.txt', sha256: sha('new') }
] }));
const successHelper = path.join(successRoot, 'apply update.ps1');
successful._writePowerShellHelper(successHelper, path.join(successRoot, 'missing.exe'), 999999);
const success = spawnSync('powershell.exe', ['-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', successHelper], { encoding: 'utf8' });
assert.equal(success.status, 0, success.stderr);
assert.equal(fs.readFileSync(path.join(successRoot, 'resources', 'app', 'version.txt'), 'utf8'), 'new');
assert.equal(fs.readFileSync(path.join(successful.backupDir, 'resources', 'app', 'version.txt'), 'utf8'), 'old');
console.log('updater applies verified update and retains rollback backup');
