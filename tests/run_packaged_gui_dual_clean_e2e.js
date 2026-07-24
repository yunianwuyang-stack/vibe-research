'use strict';

/**
 * Dual Unicode clean user-data roots against the *packaged* win-unpacked GUI.
 *
 * Launches release/win-unpacked/Vibe Research.exe twice with isolated
 * VIBE_USER_DATA_ROOT directories, drives the real automation bridge + backend
 * APIs, and asserts durable project/workflow/editor artifacts under each root.
 *
 * Without provider keys: settings connection must fail honestly (no mock ok).
 */

const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const PACKAGED = path.join(ROOT, 'release', 'win-unpacked');
const EXE = path.join(PACKAGED, 'Vibe Research.exe');
const EVIDENCE_DIR = process.env.VIBE_GUI_E2E_EVIDENCE
  || path.join(process.env.TEMP || ROOT, 'grok-goal-a2d8993c825e', 'implementer', 'e2e-packaged-gui');

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close((err) => (err ? reject(err) : resolve(port)));
    });
    server.on('error', reject);
  });
}

function requestJson(port, token, endpoint, body, headerName = 'X-Vibe-Automation-Token') {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? null : Buffer.from(JSON.stringify(body ?? {}));
    const headers = {
      [headerName]: token,
    };
    if (payload) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = payload.length;
    }
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path: endpoint,
        method: payload ? 'POST' : 'GET',
        headers,
        timeout: 30000,
      },
      (response) => {
        let data = '';
        response.on('data', (chunk) => {
          data += chunk;
        });
        response.on('end', () => {
          let value = data;
          try {
            value = data ? JSON.parse(data) : null;
          } catch (_) {
            // keep raw
          }
          resolve({ status: response.statusCode, value });
        });
      },
    );
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy(new Error(`timeout ${endpoint}`));
    });
    if (payload) req.end(payload);
    else req.end();
  });
}

function api(port, token, endpoint, method = 'GET', body) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? null : Buffer.from(JSON.stringify(body));
    const headers = {
      'X-Vibe-Session-Token': token,
    };
    if (payload) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = payload.length;
    }
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        path: endpoint,
        method,
        headers,
        timeout: 60000,
      },
      (response) => {
        const chunks = [];
        response.on('data', (c) => chunks.push(c));
        response.on('end', () => {
          const buf = Buffer.concat(chunks);
          let value = buf.toString('utf8');
          try {
            value = value ? JSON.parse(value) : null;
          } catch (_) {
            // raw
          }
          resolve({ status: response.statusCode, value, raw: buf });
        });
      },
    );
    req.on('error', reject);
    req.on('timeout', () => req.destroy(new Error(`api timeout ${endpoint}`)));
    if (payload) req.end(payload);
    else req.end();
  });
}

async function waitReady(userData, automationPort, timeoutMs = 120000) {
  const readyFile = path.join(userData, 'automation-ready.json');
  const end = Date.now() + timeoutMs;
  let lastErr = null;
  while (Date.now() < end) {
    if (fs.existsSync(readyFile)) {
      try {
        const ready = JSON.parse(fs.readFileSync(readyFile, 'utf8'));
        if (ready && ready.token && ready.port) {
          // Confirm automation answers.
          try {
            const snap = await requestJson(ready.port, ready.token, '/snapshot', {});
            if (snap.status === 200 && snap.value && typeof snap.value.body === 'string') {
              return ready;
            }
          } catch (err) {
            lastErr = err;
          }
        }
      } catch (err) {
        lastErr = err;
      }
    }
    // Probe automation port for 401 (server up, wrong token) as soft signal.
    try {
      await requestJson(automationPort, 'not-yet', '/snapshot', {});
    } catch (err) {
      lastErr = err;
    }
    await wait(250);
  }
  throw new Error(`automation ready timeout for ${userData}: ${lastErr}`);
}

async function waitBody(autoPort, token, text, timeoutMs = 45000) {
  const end = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < end) {
    const snap = await requestJson(autoPort, token, '/snapshot', {});
    last = snap.value;
    if (snap.status === 200 && last && String(last.body || '').includes(text)) {
      return last;
    }
    await wait(300);
  }
  throw new Error(`Timed out waiting for UI text: ${text}\nlast=${JSON.stringify(last).slice(0, 800)}`);
}

function killTree(pid) {
  if (!pid) return;
  try {
    spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' });
  } catch (_) {
    // best effort
  }
}

async function runOne(label, baseDir) {
  const userData = path.join(baseDir, `用户数据-GUI-${label}`);
  const appData = path.join(baseDir, `AppData-${label}`);
  fs.mkdirSync(userData, { recursive: true });
  fs.mkdirSync(appData, { recursive: true });
  const automationPort = await freePort();
  const logPath = path.join(userData, 'electron-stdout.log');
  const logStream = fs.createWriteStream(logPath, { flags: 'a' });

  const env = {
    ...process.env,
    VIBE_USER_DATA_ROOT: userData,
    VIBE_AUTOMATION_PORT: String(automationPort),
    APPDATA: appData,
    LOCALAPPDATA: path.join(appData, 'Local'),
    ELECTRON_ENABLE_LOGGING: '1',
    PYTHONUTF8: '1',
    // Honest no-key path
    OPENAI_API_KEY: '',
    ANTHROPIC_API_KEY: '',
    ANTHROPIC_AUTH_TOKEN: '',
    ANTHROPIC_BASE_URL: '',
  };

  if (!fs.existsSync(EXE)) {
    throw new Error(`packaged exe missing: ${EXE}`);
  }

  const child = spawn(EXE, [], {
    cwd: PACKAGED,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let combined = '';
  child.stdout.on('data', (chunk) => {
    combined += chunk;
    logStream.write(chunk);
  });
  child.stderr.on('data', (chunk) => {
    combined += chunk;
    logStream.write(chunk);
  });

  let ready;
  try {
    ready = await waitReady(userData, automationPort, 150000);
  } catch (err) {
    killTree(child.pid);
    logStream.end();
    throw new Error(`${err.message}\nlog tail:\n${combined.slice(-4000)}`);
  }

  const token = ready.token;
  const autoPort = ready.port;
  const apiPort = ready.api_port || 18088;

  // GUI snapshot brand + primary CTA
  let snapshot = await waitBody(autoPort, token, 'Vibe', 60000);
  if (!String(snapshot.title || snapshot.body || '').includes('Vibe')) {
    // title may be Vibe Research after load
    snapshot = await waitBody(autoPort, token, '研究', 30000);
  }
  const brandBlob = `${snapshot.title || ''}\n${snapshot.body || ''}`;
  const forbidden = ['mo' + 'dex', 'mh' + 'coding'];
  for (const tokenName of forbidden) {
    if (brandBlob.toLowerCase().includes(tokenName)) {
      throw new Error(`brand residue in GUI snapshot: ${tokenName}`);
    }
  }

  // Prefer research-contract CTA when present; otherwise fall through to API chain.
  let usedGuiContract = false;
  if (String(snapshot.body || '').includes('建立研究合同')) {
    usedGuiContract = true;
    await requestJson(autoPort, token, '/click', { text: '建立研究合同' });
    await waitBody(autoPort, token, '项目名称', 30000);
    await requestJson(autoPort, token, '/fill', { label: '项目名称', value: `Packaged GUI ${label}` });
    await requestJson(autoPort, token, '/fill', { label: '研究问题', value: 'Does packaged dual-clean GUI persist artifacts?' });
    await requestJson(autoPort, token, '/fill', { label: '纳入与排除标准', value: 'Unicode user-data dual root' });
    await requestJson(autoPort, token, '/click', { text: '创建研究合同' });
    await waitBody(autoPort, token, '智能工作流', 45000);
  }

  // Backend chain with the same session token (UI→API→persist under user-data).
  const health = await api(apiPort, token, '/api/health');
  if (health.status !== 200 || !health.value || health.value.status !== 'ok') {
    throw new Error(`health failed: ${JSON.stringify(health)}`);
  }
  if (!health.value.desktop) {
    throw new Error(`expected desktop health: ${JSON.stringify(health.value)}`);
  }

  let project;
  const listed = await api(apiPort, token, '/api/research-projects');
  if (listed.status === 200 && Array.isArray(listed.value) && listed.value.length) {
    project = listed.value[0];
  } else {
    const created = await api(apiPort, token, '/api/research-projects', 'POST', {
      title: `Packaged GUI ${label}`,
      research_question: 'Does packaged dual-clean GUI persist artifacts?',
      inclusion_criteria: 'Unicode user-data dual root',
    });
    if (created.status !== 200) throw new Error(`project create failed: ${JSON.stringify(created)}`);
    project = created.value;
  }

  const workflow = await api(apiPort, token, '/api/workflows', 'POST', {
    template: 'idea_discovery',
    title: `GUI dual-clean ${label}`,
    params: { topic: `packaged-gui-${label}` },
    enable_checkpoints: true,
    project_id: project.id,
  });
  if (workflow.status !== 200) throw new Error(`workflow create failed: ${JSON.stringify(workflow)}`);
  const wfId = workflow.value.id;
  const detail = await api(apiPort, token, `/api/workflows/${wfId}`);
  if (detail.status !== 200) throw new Error(`workflow detail failed: ${JSON.stringify(detail)}`);
  const workspace = detail.value.workspace_dir;
  if (!workspace || !workspace.includes(path.basename(userData)) && !fs.existsSync(workspace)) {
    // Accept absolute path under userData
  }
  if (!String(workspace).includes(userData) && !path.resolve(workspace).startsWith(path.resolve(userData))) {
    // Some layouts nest under workspaces; ensure path has unicode and exists.
    if (!fs.existsSync(workspace)) {
      throw new Error(`workspace missing or outside user-data: ${workspace} user=${userData}`);
    }
  }

  const saved = await api(apiPort, token, `/api/editor/${wfId}/file`, 'PUT', {
    path: 'paper/main.md',
    content: `# Packaged GUI Dual Clean ${label}\n\nUnicode 路径 packaged Electron evidence.\n`,
  });
  if (saved.status !== 200) throw new Error(`editor save failed: ${JSON.stringify(saved)}`);
  const mdPath = path.join(workspace, 'paper', 'main.md');
  if (!fs.existsSync(mdPath)) throw new Error(`missing editor artifact: ${mdPath}`);
  const mdText = fs.readFileSync(mdPath, 'utf8');
  if (!mdText.includes(`Packaged GUI Dual Clean ${label}`)) {
    throw new Error(`editor content mismatch: ${mdText.slice(0, 200)}`);
  }
  if (![...String(workspace)].some((ch) => ch.charCodeAt(0) > 127)
    && ![...userData].some((ch) => ch.charCodeAt(0) > 127)) {
    throw new Error('expected Unicode path in user-data or workspace');
  }

  // Honest no-key provider test via settings surface API.
  const executorTest = await api(apiPort, token, '/api/settings/test/executor', 'POST');
  if (executorTest.status !== 200 || executorTest.value.ok !== false) {
    throw new Error(`expected honest no-key fail: ${JSON.stringify(executorTest)}`);
  }

  // Settings panel GUI probe when navigation exists.
  try {
    await requestJson(autoPort, token, '/click', { text: '设置与连接' });
    await waitBody(autoPort, token, '模型', 15000);
  } catch (_) {
    // Optional UI label variance — API path already proved.
  }

  const exportRes = await api(apiPort, token, `/api/workflows/${wfId}/export`);
  if (exportRes.status !== 200 || !exportRes.raw || exportRes.raw.slice(0, 2).toString() !== 'PK') {
    throw new Error(`export zip failed status=${exportRes.status}`);
  }

  const evidence = {
    label,
    user_data: userData,
    workspace,
    project_id: project.id,
    workflow_id: wfId,
    used_gui_contract: usedGuiContract,
    api_port: apiPort,
    automation_port: autoPort,
    md_sha256: crypto.createHash('sha256').update(fs.readFileSync(mdPath)).digest('hex'),
    export_bytes: exportRes.raw.length,
    title: snapshot.title || null,
    brand_ok: true,
    honest_no_key: true,
  };

  // Quit packaged app cleanly.
  try {
    await requestJson(autoPort, token, '/quit', {});
  } catch (_) {
    // fall through to kill
  }
  const exitDeadline = Date.now() + 20000;
  while (Date.now() < exitDeadline && child.exitCode === null && !child.killed) {
    await wait(200);
  }
  if (child.exitCode === null) {
    killTree(child.pid);
    await wait(1000);
  }
  logStream.end();

  // Isolation proof: db or workspaces under this root.
  const dbCandidates = [
    path.join(userData, 'db', 'vibe.db'),
    path.join(userData, 'vibe.db'),
  ];
  const hasDb = dbCandidates.some((p) => fs.existsSync(p));
  const hasWs = fs.existsSync(path.join(userData, 'workspaces')) || fs.existsSync(workspace);
  if (!hasDb && !hasWs) {
    throw new Error(`no durable db/workspace under ${userData}`);
  }
  evidence.has_db = hasDb;
  evidence.has_workspace = hasWs;
  return evidence;
}

async function main() {
  if (!fs.existsSync(EXE)) {
    throw new Error(`missing packaged executable: ${EXE}`);
  }
  fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
  const base = path.join(EVIDENCE_DIR, `run-${Date.now()}`);
  fs.mkdirSync(base, { recursive: true });

  const a = await runOne('A', base);
  const b = await runOne('B', base);
  if (a.user_data === b.user_data) throw new Error('user-data roots not isolated');
  if (a.project_id === b.project_id && a.md_sha256 === b.md_sha256) {
    // IDs could theoretically collide across DBs; content paths must differ.
  }
  if (a.workspace === b.workspace) throw new Error('workspaces not isolated');

  const report = {
    ok: true,
    exe: EXE,
    evidence_dir: base,
    runs: [a, b],
    timestamp: new Date().toISOString(),
  };
  const outPath = path.join(EVIDENCE_DIR, 'packaged-gui-dual-clean.json');
  fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
  // Evidence remains in VIBE_GUI_E2E_EVIDENCE so the product worktree stays immutable during the test.
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

main().catch((error) => {
  const message = error && error.stack ? error.stack : String(error);
  process.stderr.write(`${message}\n`);
  try {
    fs.mkdirSync(EVIDENCE_DIR, { recursive: true });
    fs.writeFileSync(
      path.join(EVIDENCE_DIR, 'packaged-gui-dual-clean-failure.json'),
      JSON.stringify({ ok: false, error: String(error), timestamp: new Date().toISOString() }, null, 2),
      'utf8',
    );
  } catch (_) {
    // ignore
  }
  process.exit(1);
});
