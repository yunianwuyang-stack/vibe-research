const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { prepareUserDataRoot } = require('../desktop-data');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'vibe-data-'));
fs.mkdirSync(path.join(root, 'VibeResearch', 'db'), { recursive: true });
fs.writeFileSync(path.join(root, 'VibeResearch', 'db', 'aris.db'), 'legacy');
const target = prepareUserDataRoot(root);
// Legacy aris.db is promoted to the branded vibe.db on first prepare.
assert.equal(fs.readFileSync(path.join(target, 'db', 'vibe.db'), 'utf8'), 'legacy');
assert.ok(!fs.existsSync(path.join(target, 'db', 'aris.db')));
assert.ok(fs.existsSync(path.join(root, 'VibeResearch', 'db', 'aris.db')));
fs.writeFileSync(path.join(target, 'db', 'vibe.db'), 'current');
prepareUserDataRoot(root);
assert.equal(fs.readFileSync(path.join(target, 'db', 'vibe.db'), 'utf8'), 'current');
console.log('desktop data migration is reversible and idempotent');
