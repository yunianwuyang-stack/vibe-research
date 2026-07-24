const fs = require('fs');
const path = require('path');

function copyMissing(source, target) {
  if (!fs.existsSync(source)) return false;
  fs.mkdirSync(target, { recursive: true });
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const src = path.join(source, entry.name);
    const dst = path.join(target, entry.name);
    if (entry.isDirectory()) copyMissing(src, dst);
    else if (!fs.existsSync(dst)) fs.copyFileSync(src, dst);
  }
  return true;
}

function promoteProductDb(userDataRoot) {
  // Brand-canonical ledger name. Rename any pre-brand SQLite file once.
  // The legacy filename is only a migration source for existing installs.
  const dbDir = path.join(userDataRoot, 'db');
  const preferred = path.join(dbDir, 'vibe.db');
  const legacy = path.join(dbDir, 'aris.db');
  if (fs.existsSync(preferred) || !fs.existsSync(legacy)) return;
  try {
    fs.renameSync(legacy, preferred);
  } catch (_) {
    // Locked by another process — backend resolve_product_db_path also handles this.
  }
}

function prepareUserDataRoot(appData, canonicalName = 'Vibe Research') {
  const canonical = path.join(appData, canonicalName);
  const marker = path.join(canonical, 'migration-state.json');
  fs.mkdirSync(canonical, { recursive: true });
  if (fs.existsSync(marker)) {
    promoteProductDb(canonical);
    return canonical;
  }
  const sources = ['VibeResearch', 'vibe-research']
    .map(name => path.join(appData, name))
    .filter(source => path.resolve(source) !== path.resolve(canonical));
  const migrated = [];
  for (const source of sources) if (copyMissing(source, canonical)) migrated.push(source);
  promoteProductDb(canonical);
  fs.writeFileSync(marker, JSON.stringify({ schema: 1, policy: 'copy_missing_keep_source', migrated }, null, 2), 'utf8');
  return canonical;
}

function resolveUserDataRoot(appData, override = '') {
  const defaultRoot = prepareUserDataRoot(appData);
  // The pointer must live outside the selectable data root. Otherwise moving
  // the root would also move the only information needed to find it again.
  const pointerFile = path.join(appData, 'Vibe Research.data-location.json');
  let requested = override ? path.resolve(override) : defaultRoot;
  if (!override && fs.existsSync(pointerFile)) {
    try {
      const pointer = JSON.parse(fs.readFileSync(pointerFile, 'utf8'));
      if (pointer && pointer.schema === 1 && typeof pointer.data_dir === 'string' && path.isAbsolute(pointer.data_dir)) {
        requested = path.resolve(pointer.data_dir);
      }
    } catch (_) {
      requested = defaultRoot;
    }
  }
  try {
    fs.mkdirSync(requested, { recursive: true });
    fs.accessSync(requested, fs.constants.R_OK | fs.constants.W_OK);
  } catch (_) {
    requested = defaultRoot;
    fs.mkdirSync(requested, { recursive: true });
  }
  return { userDataRoot: requested, defaultRoot, pointerFile };
}

module.exports = { copyMissing, prepareUserDataRoot, resolveUserDataRoot };
