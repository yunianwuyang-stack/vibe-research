/**
 * Vibe Research — Electron 主进程
 *
 * 职责：
 * 1. 启动内嵌 Python 后端（uvicorn）
 * 2. 等待后端 ready（轮询 /api/health）
 * 3. 创建 BrowserWindow 加载前端
 * 4. 托盘图标 + 关闭最小化到托盘
 * 5. 退出时杀掉 Python 子进程
 */

const { app, BrowserWindow, Tray, Menu, dialog, ipcMain, nativeImage } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');
const crypto = require('crypto');
const { resolveUserDataRoot } = require('./desktop-data');

app.setName('Vibe Research');
const {
  userDataRoot: CANONICAL_USER_DATA,
  defaultRoot: DEFAULT_USER_DATA,
  pointerFile: DATA_POINTER_FILE,
} = resolveUserDataRoot(app.getPath('appData'), process.env.VIBE_USER_DATA_ROOT || '');
fs.mkdirSync(CANONICAL_USER_DATA, { recursive: true });
app.setPath('userData', CANONICAL_USER_DATA);

// GUI/automation launches do not always keep Electron's inherited console
// pipes open.  Never let a closed stdout/stderr pipe crash the main process.
function ignoreBrokenPipe(stream) {
  if (!stream || typeof stream.on !== 'function') return;
  stream.on('error', () => {
    // There is intentionally no fallback console here: it may be backed by
    // this same failed stream. Logging must never become another crash path.
  });
}

function safeStreamWrite(stream, message) {
  if (!stream || stream.destroyed || stream.writableEnded || typeof stream.write !== 'function') return;
  try {
    stream.write(message, () => {
      // The callback consumes asynchronous write failures. Throwing here would
      // recreate an uncaught main-process error.
    });
  } catch (_) {
    // Deliberately ignore logging failures in the desktop main process.
  }
}

ignoreBrokenPipe(process.stdout);
ignoreBrokenPipe(process.stderr);

// 自动更新器
const { Updater } = require('./updater');

// ── 路径 ──
const IS_DEV = !app.isPackaged;
const APP_ARCHIVE_ROOT = path.join(process.resourcesPath, 'app.asar');
const APP_UNPACKED_ROOT = path.join(process.resourcesPath, 'app.asar.unpacked');
const APP_ROOT = IS_DEV ? __dirname : APP_ARCHIVE_ROOT;
const EXECUTABLE_APP_ROOT = IS_DEV ? __dirname : APP_UNPACKED_ROOT;
const RUNTIME_DIR = IS_DEV
  ? path.join(__dirname, 'runtime')
  : path.join(process.resourcesPath, 'runtime');

const PYTHON_EXE = path.join(RUNTIME_DIR, 'python', 'python.exe');
const BACKEND_DIR = path.join(EXECUTABLE_APP_ROOT, 'backend');
const APP_ICON = path.join(APP_ROOT, 'icon.ico');

const PORT = 18088;
const LOCAL_SESSION_TOKEN = crypto.randomBytes(32).toString('base64url');
const AUTOMATION_PORT = Number(process.env.VIBE_AUTOMATION_PORT || 0);
if (AUTOMATION_PORT) app.disableHardwareAcceleration();
let automationServer = null;

ipcMain.handle('local-session-token', () => LOCAL_SESSION_TOKEN);
ipcMain.handle('select-data-directory', async () => {
  const options = {
    title: '选择 Vibe Research 数据目录',
    defaultPath: CANONICAL_USER_DATA,
    buttonLabel: '选择此目录',
    properties: ['openDirectory', 'createDirectory'],
  };
  const result = mainWindow
    ? await dialog.showOpenDialog(mainWindow, options)
    : await dialog.showOpenDialog(options);
  return {
    canceled: result.canceled || result.filePaths.length === 0,
    path: result.canceled || result.filePaths.length === 0 ? undefined : path.resolve(result.filePaths[0]),
  };
});
// 本地交付版不参与远程更新，因此不会向前端发送更新事件或显示下载横幅。
const AUTO_UPDATE_ENABLED = false;

// ── 运行时完整性检查（应对杀毒软件误报删除 python.exe） ──

/**
 * 检查关键 runtime 文件是否完整。
 * Python embeddable 的 python.exe 没数字签名, 国内 Windows Defender / 360 / 火绒
 * 经常按行为规则识别为 "Trojan:Win32/Wacatac" 等误报并静默隔离。
 * 启动前如果文件丢了, 直接弹友好提示, 不要让用户看到神秘的 ENOENT。
 */
function verifyRuntime() {
  if (IS_DEV) return [];  // dev 模式跳过

  const checks = [
    { file: PYTHON_EXE,                                          name: 'python.exe',     minSize: 50 * 1024,  maxSize: 500 * 1024 },
    { file: path.join(RUNTIME_DIR, 'python', 'python311.dll'),   name: 'python311.dll',  minSize: 1024 * 1024 },
    { file: path.join(RUNTIME_DIR, 'python', 'python311.zip'),   name: 'python311.zip',  minSize: 1024 * 1024 },
    { file: path.join(RUNTIME_DIR, 'node',   'node.exe'),        name: 'node.exe',       minSize: 10 * 1024 * 1024 },
    { file: path.join(RUNTIME_DIR, 'agent-cli-manifest.json'),   name: 'agent-cli-manifest.json', minSize: 512 },
    { file: path.join(RUNTIME_DIR, 'node', 'node_modules', '@openai', 'codex', 'node_modules', '@openai', 'codex-win32-x64', 'vendor', 'x86_64-pc-windows-msvc', 'bin', 'codex.exe'), name: 'codex.exe', minSize: 100 * 1024 * 1024 },
    { file: path.join(RUNTIME_DIR, 'git', 'cmd', 'git.exe'),     name: 'git.exe',        minSize: 20 * 1024 },
    { file: path.join(RUNTIME_DIR, 'git', 'bin', 'bash.exe'),    name: 'bash.exe',       minSize: 20 * 1024 },
    { file: path.join(RUNTIME_DIR, 'pandoc', 'pandoc.exe'),      name: 'pandoc.exe',     minSize: 10 * 1024 * 1024 },
    { file: path.join(RUNTIME_DIR, 'draw.io', 'draw.io.exe'),    name: 'draw.io.exe',    minSize: 10 * 1024 * 1024 },
    { file: path.join(RUNTIME_DIR, 'texlive', 'texmfs', 'install', 'miktex', 'bin', 'x64', 'xelatex.exe'), name: 'xelatex.exe', minSize: 500 * 1024 },
    { file: path.join(RUNTIME_DIR, 'texlive', 'texmfs', 'install', 'miktex', 'bin', 'x64', 'pdflatex.exe'), name: 'pdflatex.exe', minSize: 500 * 1024 },
  ];
  const issues = [];
  for (const c of checks) {
    if (!fs.existsSync(c.file)) {
      issues.push({ file: c.file, name: c.name, reason: '文件不存在' });
      continue;
    }
    try {
      const sz = fs.statSync(c.file).size;
      if (c.minSize && sz < c.minSize) {
        issues.push({ file: c.file, name: c.name, reason: `文件大小异常 (${sz} 字节)` });
      } else if (c.maxSize && sz > c.maxSize) {
        issues.push({ file: c.file, name: c.name, reason: `文件大小异常 (${sz} 字节)` });
      }
    } catch (e) {
      issues.push({ file: c.file, name: c.name, reason: `无法读取 (${e.message})` });
    }
  }
  return issues;
}

/**
 * 把 verifyRuntime 的结果格式化成对用户友好的中文诊断对话框。
 * 重点是说明这是杀毒软件误报, 给出可操作的修复步骤, 而不是让用户对着 ENOENT 发懵。
 */
function showRuntimeIssueDialog(issues) {
  const installDir = path.dirname(process.execPath);
  const fileList = issues.map(i => `  • runtime\\${path.basename(path.dirname(i.file))}\\${i.name}  ${i.reason}`).join('\n');
  const detail = [
    '原因（最常见）：',
    'Windows Defender / 360 / 火绒等杀毒软件把内嵌的 python.exe 误报为木马并自动隔离。',
    '内嵌 Python 没有数字签名，部分杀毒软件按行为规则会误报，实际是安全的官方发行版。',
    '',
    '修复方法（任选其一）：',
    '',
    '【方法 1：恢复被隔离的文件 + 添加排除项】',
    '  1. 打开「Windows 安全中心」→「病毒和威胁防护」→「保护历史记录」',
    '     （或 360/火绒 → 隔离区/已处理威胁）',
    '  2. 找到 python.exe，选择「允许」/「恢复」',
    '  3. 进入「病毒和威胁防护设置」→「管理设置」→「添加或删除排除项」',
    `  4. 添加文件夹排除：${installDir}`,
    '  5. 重新启动 Vibe Research',
    '',
    '【方法 2：管理员 PowerShell 一键加白名单】',
    '  右键开始菜单 →「Windows PowerShell (管理员)」，粘贴执行：',
    `    Add-MpPreference -ExclusionPath "${installDir}"`,
    '  然后重新安装本程序。',
    '',
    '【方法 3：彻底重装】',
    '  先按方法 1 / 2 加排除项 → 卸载本程序 → 重新运行安装包。',
  ].join('\n');

  dialog.showMessageBoxSync({
    type: 'error',
    title: '启动失败：运行时文件被杀毒软件拦截',
    message: '检测到 ' + issues.length + ' 个关键运行时文件丢失或损坏：\n\n' + fileList,
    detail,
    buttons: ['退出'],
    defaultId: 0,
    noLink: true,
  });
}

let mainWindow = null;
let tray = null;
let pythonProcess = null;
let isQuitting = false;
let actualPort = PORT;  // 实际使用的端口（可能因占用而变）

// ── 端口检测 ──

function isPortAvailable(port) {
  return new Promise((resolve) => {
    const net = require('net');
    const server = net.createServer();
    server.once('error', () => resolve(false));
    server.once('listening', () => { server.close(); resolve(true); });
    server.listen(port, '127.0.0.1');
  });
}

async function findAvailablePort(startPort, maxTries = 10) {
  for (let i = 0; i < maxTries; i++) {
    const port = startPort + i;
    if (await isPortAvailable(port)) return port;
    console.log(`[Port] ${port} is occupied, trying next...`);
  }
  // Never terminate an unowned process. Ownership cannot be inferred from a PID.
  throw new Error(`No available loopback port in range ${startPort}-${startPort + maxTries - 1}`);
}

// ── MiKTeX 自动安装 ──

function getBundledTeXBin() {
  const candidates = [
    path.join(RUNTIME_DIR, 'texlive', 'texmfs', 'install', 'miktex', 'bin', 'x64'),
    path.join(RUNTIME_DIR, 'texlive', 'bin', 'windows'),
    path.join(RUNTIME_DIR, 'texlive', 'miktex', 'bin', 'x64'),
  ];
  return candidates.find(p => fs.existsSync(path.join(p, 'xelatex.exe'))) || null;
}

function getMiKTeXDir() {
  const candidates = [
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'MiKTeX'),
    'C:\\Program Files\\MiKTeX',
  ];
  for (const p of candidates) {
    const xelatex = path.join(p, 'miktex', 'bin', 'x64', 'xelatex.exe');
    if (fs.existsSync(xelatex)) return p;
  }
  return null;
}

async function ensureMiKTeX() {
  // 检查 xelatex 是否可用（不只是 MiKTeX 目录存在）
  const { execSync } = require('child_process');

  // The release includes an offline portable MiKTeX tree. Prefer it over a
  // machine-wide install and never launch the network bootstrapper when the
  // bundled compiler is healthy.
  const bundledTeXBin = getBundledTeXBin();
  if (bundledTeXBin) {
    console.log('[MiKTeX] Using bundled portable runtime:', bundledTeXBin);
    return;
  }
  
  // 先检查系统上有没有 xelatex
  let hasXelatex = false;
  try {
    execSync('where.exe xelatex', { stdio: 'ignore', timeout: 5000 });
    hasXelatex = true;
  } catch (e) {}
  
  if (!hasXelatex && getMiKTeXDir()) {
    // MiKTeX 装了但没有 xelatex，需要装 xetex 包
    const miktexDir = getMiKTeXDir();
    const miktexExe = path.join(miktexDir, 'miktex', 'bin', 'x64', 'miktex.exe');
    if (fs.existsSync(miktexExe)) {
      console.log('[MiKTeX] Installing xetex + Chinese packages...');
      const packages = ['xetex', 'ctex', 'xecjk', 'gbt7714', 'fontspec', 'booktabs', 'float', 'hyperref', 'amsmath', 'geometry', 'fancyhdr', 'caption', 'subcaption', 'multirow', 'listings', 'algorithm2e', 'pgfplots', 'xcolor', 'tcolorbox', 'biblatex', 'biber', 'natbib'];
      for (const pkg of packages) {
        try {
          execSync(`"${miktexExe}" packages install ${pkg}`, { stdio: 'ignore', timeout: 60000 });
        } catch (e) {} // 忽略已安装的包
      }
      console.log('[MiKTeX] Packages installed');
    }
    return;
  }
  
  if (hasXelatex) {
    console.log('[MiKTeX] xelatex already available');
    return;
  }

  // 没有 MiKTeX，用内嵌安装器安装
  const setupFile = path.join(RUNTIME_DIR, 'miktex-setup.exe');
  if (!fs.existsSync(setupFile)) {
    console.log('[MiKTeX] Installer not found at', setupFile);
    dialog.showMessageBox({
      type: 'warning',
      title: 'LaTeX 未安装',
      message: '未检测到 MiKTeX (LaTeX)，论文编译功能将不可用。\n请手动安装 MiKTeX: https://miktex.org/download',
    });
    return;
  }

  console.log('[MiKTeX] Installing from bundled installer (this may take several minutes)...');
  try {
    // MiKTeX 安装可能需要较长时间，给 15 分钟超时
    execSync(`"${setupFile}" --unattended --auto-install=yes --package-set=basic --paper-size=A4 --private`, {
      // A packaged GUI process may not own live console handles. Inheriting a
      // stale pipe makes native installer output capable of reproducing EPIPE.
      stdio: 'ignore',
      timeout: 900000,  // 15 分钟
    });
    console.log('[MiKTeX] Basic installation complete');
  } catch (e) {
    // 检查是否实际安装成功了（安装器可能返回非零退出码但实际装好了）
    if (getMiKTeXDir()) {
      console.log('[MiKTeX] Installation completed (installer returned non-zero but MiKTeX is present)');
    } else {
      console.error('[MiKTeX] Installation failed:', e.message);
      dialog.showMessageBox({
        type: 'warning',
        title: 'MiKTeX 安装失败',
        message: 'LaTeX 自动安装失败，论文编译功能可能不可用。\n请手动安装: https://miktex.org/download',
      });
      return;
    }
  }

  // 装完 basic 后，立刻装 xelatex 和中文包
  const newDir = getMiKTeXDir();
  if (newDir) {
    const miktexExe = path.join(newDir, 'miktex', 'bin', 'x64', 'miktex.exe');
    if (fs.existsSync(miktexExe)) {
      console.log('[MiKTeX] Installing xetex + Chinese packages...');
      const packages = ['xetex', 'ctex', 'xecjk', 'gbt7714', 'fontspec'];
      for (const pkg of packages) {
        try {
          execSync(`"${miktexExe}" packages install ${pkg}`, { stdio: 'ignore', timeout: 60000 });
        } catch (e) {}
      }
      // 启用自动安装缺失包
      const initexmf = path.join(newDir, 'miktex', 'bin', 'x64', 'initexmf.exe');
      try {
        execSync(`"${initexmf}" --set-config-value=[MPM]AutoInstall=1`, { stdio: 'ignore', timeout: 10000 });
      } catch (e) {}
      console.log('[MiKTeX] Full setup complete');
    }
  }
}

// ── Python 后端 ──

function startBackend() {
  // 查找可用的 Python
  let pythonPath;
  let pythonArgs;
  if (fs.existsSync(PYTHON_EXE)) {
    pythonPath = PYTHON_EXE;
    pythonArgs = ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(actualPort), '--log-level', 'info'];
  } else {
    // 开发模式：按优先级查找可用 Python
    const candidates = [
      'C:\\Windows\\py.exe',                    // Windows Launcher
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python313', 'python.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python312', 'python.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'),
      path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python39', 'python.exe'),
    ];
    let found = false;
    for (const candidate of candidates) {
      if (candidate && fs.existsSync(candidate)) {
        if (candidate.endsWith('py.exe')) {
          pythonPath = candidate;
          pythonArgs = ['-3', '-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(actualPort), '--log-level', 'info'];
        } else {
          pythonPath = candidate;
          pythonArgs = ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(actualPort), '--log-level', 'info'];
        }
        found = true;
        break;
      }
    }
    if (!found) {
      pythonPath = 'python';
      pythonArgs = ['-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', String(actualPort), '--log-level', 'info'];
    }
  }

  const env = Object.assign({}, process.env, {
    VIBE_DESKTOP: '1',
    // Pass the exact runtime selected above.  Inferring a sibling directory
    // from backend/config.py is correct for packaged resources/app, but wrong
    // for source-mode Electron where the runtime lives inside the repository.
    VIBE_RUNTIME_ROOT: RUNTIME_DIR,
    VIBE_PACKAGED_RUNTIME: IS_DEV ? '0' : '1',
    API_PORT: String(actualPort),
    VIBE_LOCAL_SESSION_TOKEN: LOCAL_SESSION_TOKEN,
    VIBE_DESKTOP_ORIGIN: `http://127.0.0.1:${actualPort}`,
    VIBE_USER_DATA_ROOT: CANONICAL_USER_DATA,
    VIBE_DEFAULT_USER_DATA_ROOT: DEFAULT_USER_DATA,
    VIBE_DATA_POINTER_FILE: DATA_POINTER_FILE,
    PYTHONDONTWRITEBYTECODE: '1',
    // 强制 UTF-8 编码（防止 Git Bash 写中文文件时乱码）
    LANG: 'en_US.UTF-8',
    LC_ALL: 'en_US.UTF-8',
    PYTHONIOENCODING: 'utf-8',
    PYTHONUTF8: '1',
    PYTHONPATH: BACKEND_DIR,
  });

  // 把 runtime 工具链加入 PATH
  const extraPaths = [];
  const nodeDir = path.join(RUNTIME_DIR, 'node');
  if (fs.existsSync(nodeDir)) extraPaths.push(nodeDir);
  const pandocDir = path.join(RUNTIME_DIR, 'pandoc');
  if (fs.existsSync(pandocDir)) extraPaths.push(pandocDir);
  const drawioDir = path.join(RUNTIME_DIR, 'draw.io');
  if (fs.existsSync(drawioDir)) extraPaths.push(drawioDir);
  const texDirs = [
    path.join(RUNTIME_DIR, 'texlive', 'texmfs', 'install', 'miktex', 'bin', 'x64'),
    path.join(RUNTIME_DIR, 'texlive', 'bin', 'windows'),
    path.join(RUNTIME_DIR, 'texlive', 'miktex', 'bin', 'x64'),
  ];
  const texDir = texDirs.find(candidate => fs.existsSync(candidate));
  if (texDir) extraPaths.push(texDir);

  // Keep bundled Git Bash available to an optional user-managed Claude CLI.
  const gitBashPaths = [
    path.join(RUNTIME_DIR, 'git', 'bin', 'bash.exe'),
    'D:\\Git\\bin\\bash.exe',
    'C:\\Program Files\\Git\\bin\\bash.exe',
    'C:\\Program Files (x86)\\Git\\bin\\bash.exe',
  ];
  for (const bp of gitBashPaths) {
    if (fs.existsSync(bp)) {
      env.CLAUDE_CODE_GIT_BASH_PATH = bp;
      // 也把 git 的 cmd 和 bin 加入 PATH
      const gitBin = path.dirname(bp);
      extraPaths.push(gitBin);
      const gitCmd = path.join(path.dirname(gitBin), 'cmd');
      if (fs.existsSync(gitCmd)) extraPaths.push(gitCmd);
      console.log('[Backend] Git Bash:', bp);
      break;
    }
  }
  const pyDir = path.dirname(pythonPath);
  if (fs.existsSync(pyDir)) {
    extraPaths.push(pyDir);
    const scriptsDir = path.join(pyDir, 'Scripts');
    if (fs.existsSync(scriptsDir)) extraPaths.push(scriptsDir);
  }
  if (extraPaths.length) {
    env.PATH = extraPaths.join(';') + ';' + (env.PATH || '');
  }

  console.log('[Backend] Starting:', pythonPath, ...pythonArgs);
  console.log('[Backend] CWD:', BACKEND_DIR);

  pythonProcess = spawn(pythonPath, pythonArgs, {
    cwd: BACKEND_DIR,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  pythonProcess.stdout.on('data', (data) => {
    safeStreamWrite(process.stdout, `[Backend] ${data}`);
  });
  pythonProcess.stderr.on('data', (data) => {
    safeStreamWrite(process.stderr, `[Backend] ${data}`);
  });
  pythonProcess.on('exit', (code) => {
    console.log(`[Backend] Process exited with code ${code}`);
    if (!isQuitting) {
      dialog.showErrorBox('后端异常退出', `Python 后端进程退出（code=${code}）。\n请检查诊断信息或重启 Vibe Research。`);
    }
  });
}

function killBackend() {
  if (!pythonProcess) return;
  try {
    // Windows: taskkill /T 杀掉整个进程树
    const { execSync } = require('child_process');
    execSync(`taskkill /T /F /PID ${pythonProcess.pid}`, { stdio: 'ignore', shell: true });
  } catch (e) {
    try { pythonProcess.kill('SIGTERM'); } catch (_) {}
  }
  pythonProcess = null;
}

// ── 健康检查 ──

function waitForBackend(maxRetries = 60, interval = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const healthUrl = `http://127.0.0.1:${actualPort}/api/health`;
    const check = () => {
      attempts++;
      // The loopback backend rejects every request without the per-launch
      // session token.  Startup readiness is a real backend request too;
      // omitting this header made packaged Electron wait until timeout even
      // while uvicorn had started successfully.
      const req = http.get(healthUrl, {
        headers: { 'X-Vibe-Session-Token': LOCAL_SESSION_TOKEN },
      }, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else if (attempts < maxRetries) {
          setTimeout(check, interval);
        } else {
          reject(new Error(`Backend not ready after ${maxRetries} attempts`));
        }
      });
      req.on('error', () => {
        if (attempts < maxRetries) {
          setTimeout(check, interval);
        } else {
          reject(new Error(`Backend not ready after ${maxRetries} attempts`));
        }
      });
      req.setTimeout(2000, () => { req.destroy(); });
    };
    check();
  });
}

// ── 窗口 ──

function createWindow() {
  const isTrustedExternalUrl = (url) => {
    try {
      const parsed = new URL(url);
      return parsed.protocol === 'https:' && parsed.hostname !== '127.0.0.1' && parsed.hostname !== 'localhost';
    } catch (_) { return false; }
  };
  const isLocalPreviewUrl = (url) => {
    try {
      const parsed = new URL(url);
      const port = Number(parsed.port);
      return parsed.protocol === 'http:'
        && parsed.hostname === '127.0.0.1'
        && !parsed.username
        && !parsed.password
        && Number.isInteger(port)
        && port >= 19000
        && port <= 19099;
    } catch (_) { return false; }
  };
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    title: 'Vibe Research',
    icon: APP_ICON,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
    show: false,
  });

  // 禁用缓存，确保每次加载最新的前端文件
  mainWindow.webContents.session.clearCache();
  mainWindow.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  mainWindow.webContents.session.webRequest.onHeadersReceived((details, callback) => {
    callback({ responseHeaders: { ...details.responseHeaders, 'Content-Security-Policy': ["default-src 'self' http://127.0.0.1:*; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' http://127.0.0.1:*; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"] } });
  });

  mainWindow.loadURL(`http://127.0.0.1:${actualPort}`);

  // 外部链接用系统浏览器打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isTrustedExternalUrl(url) || isLocalPreviewUrl(url)) {
      require('electron').shell.openExternal(url);
      return { action: 'deny' };
    }
    return { action: 'deny' };
  });
  mainWindow.webContents.on('will-navigate', (e, url) => {
    if (!url.startsWith(`http://127.0.0.1:${actualPort}`)) {
      e.preventDefault();
      if (isTrustedExternalUrl(url) || isLocalPreviewUrl(url)) require('electron').shell.openExternal(url);
    }
  });

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  if (AUTOMATION_PORT > 0) startAutomationBridge();

  // 关闭时最小化到托盘
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
}

function automationBlackPixelRatio(image) {
  const bitmap = image.toBitmap();
  if (!bitmap.length) return 1;
  let black = 0;
  let samples = 0;
  // NativeImage bitmaps are BGRA. Sampling every 16th pixel is enough to
  // distinguish real dark UI colors from Chromium's large pure-black tiles.
  for (let index = 0; index + 3 < bitmap.length; index += 64) {
    samples += 1;
    if (bitmap[index] < 3 && bitmap[index + 1] < 3 && bitmap[index + 2] < 3) black += 1;
  }
  return samples ? black / samples : 1;
}

async function captureAutomationScreenshot() {
  const contents = mainWindow.webContents;
  let bestImage = null;
  let bestBlackPixelRatio = Infinity;
  let attachedHere = false;
  let debuggerReady = contents.debugger.isAttached();
  if (!debuggerReady) {
    try {
      contents.debugger.attach('1.3');
      attachedHere = true;
      debuggerReady = true;
      await contents.debugger.sendCommand('Page.enable');
    } catch (_) {
      debuggerReady = false;
    }
  }
  try {
    for (let attempt = 0; attempt < 4; attempt += 1) {
      contents.invalidate();
      await new Promise((resolve) => setTimeout(resolve, 100 + attempt * 60));
      await contents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))', true);
      let candidate = null;
      if (debuggerReady && attempt % 2 === 0) {
        try {
          const frame = await contents.debugger.sendCommand('Page.captureScreenshot', {
            format: 'png',
            fromSurface: true,
            captureBeyondViewport: false,
            optimizeForSpeed: false,
          });
          candidate = nativeImage.createFromBuffer(Buffer.from(frame.data, 'base64'));
          if (candidate.isEmpty()) candidate = null;
        } catch (_) {
          candidate = null;
        }
      }
      if (!candidate) candidate = await contents.capturePage();
      const blackPixelRatio = automationBlackPixelRatio(candidate);
      if (!bestImage || blackPixelRatio < bestBlackPixelRatio) {
        bestImage = candidate;
        bestBlackPixelRatio = blackPixelRatio;
      }
      if (blackPixelRatio < 0.02) break;
    }
  } finally {
    if (attachedHere && contents.debugger.isAttached()) contents.debugger.detach();
  }
  return { image: bestImage, blackPixelRatio: bestBlackPixelRatio };
}

function startAutomationBridge() {
  if (automationServer || !mainWindow) return;
  const send = (response, status, value) => {
    const body = JSON.stringify(value); response.writeHead(status, {'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)}); response.end(body);
  };
  automationServer = http.createServer(async (request, response) => {
    if (!request.socket.remoteAddress?.includes('127.0.0.1') && request.socket.remoteAddress !== '::1') return send(response, 403, {error:'loopback only'});
    if (request.headers['x-vibe-automation-token'] !== LOCAL_SESSION_TOKEN) return send(response, 401, {error:'invalid automation token'});
    let body = ''; for await (const chunk of request) body += chunk;
    let input = {}; try { input = body ? JSON.parse(body) : {}; } catch { return send(response, 400, {error:'invalid json'}); }
    try {
      if (request.url === '/snapshot') {
        const value = await mainWindow.webContents.executeJavaScript(`({title:document.title,active:document.activeElement?.textContent||document.activeElement?.getAttribute('aria-label')||'',body:document.body.innerText,buttons:[...document.querySelectorAll('button')].map(x=>({text:x.innerText,disabled:x.disabled})),violations:[...document.querySelectorAll('img:not([alt]),button:not([aria-label])')].filter(x=>!x.textContent.trim()).map(x=>x.outerHTML.slice(0,120))})`, true);
        return send(response, 200, value);
      }
      if (request.url === '/screenshot') {
        const focusText = JSON.stringify(String(input.focusText || ''));
        const resetScroll = Boolean(input.resetScroll);
        await mainWindow.webContents.executeJavaScript(`(()=>{const wanted=${focusText};if(wanted){const nodes=[...document.querySelectorAll('#main-content *')].filter(x=>x.childElementCount===0&&x.textContent.includes(wanted)).sort((a,b)=>a.textContent.length-b.textContent.length);nodes[0]?.scrollIntoView({block:'center',inline:'nearest'});}else if(${resetScroll}){window.scrollTo({top:0,left:0,behavior:'auto'});}})()`, true);
        const { image, blackPixelRatio } = await captureAutomationScreenshot();
        return send(response, 200, {
          png: image.toPNG().toString('base64'),
          size: image.getSize(),
          blackPixelRatio,
        });
      }
      if (request.url === '/click') {
        const text = JSON.stringify(String(input.text || ''));
        const value = await mainWindow.webContents.executeJavaScript(`(()=>{const wanted=${text};const nodes=[...document.querySelectorAll('button,a,[role="button"]')];const node=nodes.find(x=>x.textContent.trim()===wanted)||nodes.find(x=>x.textContent.trim().includes(wanted));if(!node)return {ok:false,error:'not found',candidates:nodes.map(x=>x.textContent.trim()).filter(Boolean).slice(0,80)};node.click();return {ok:true};})()`, true);
        return send(response, value.ok ? 200 : 404, value);
      }
      if (request.url === '/fill') {
        const label = JSON.stringify(String(input.label || '')); const value = JSON.stringify(String(input.value ?? ''));
        const result = await mainWindow.webContents.executeJavaScript(`(()=>{const wanted=${label};const control=[...document.querySelectorAll('input,textarea,select')].find(x=>x.getAttribute('aria-label')===wanted||x.closest('label')?.childNodes[0]?.textContent.trim()===wanted);if(!control)return {ok:false,error:'not found'};const setter=Object.getOwnPropertyDescriptor(control instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:control instanceof HTMLSelectElement?HTMLSelectElement.prototype:HTMLInputElement.prototype,'value').set;setter.call(control,${value});control.dispatchEvent(new Event('input',{bubbles:true}));control.dispatchEvent(new Event('change',{bubbles:true}));return {ok:true};})()`, true);
        return send(response, result.ok ? 200 : 404, result);
      }
      if (request.url === '/key') { mainWindow.webContents.sendInputEvent({type:'keyDown',keyCode:String(input.key||'TAB')});mainWindow.webContents.sendInputEvent({type:'keyUp',keyCode:String(input.key||'TAB')});return send(response,200,{ok:true}); }
      if (request.url === '/quit') { send(response,200,{ok:true});isQuitting=true;setTimeout(()=>app.quit(),50);return; }
      return send(response,404,{error:'unknown endpoint'});
    } catch (error) { return send(response,500,{error:error.message}); }
  });
  automationServer.listen(AUTOMATION_PORT, '127.0.0.1', () => {
    const line = `VIBE_AUTOMATION_READY ${AUTOMATION_PORT} ${LOCAL_SESSION_TOKEN}\n`;
    safeStreamWrite(process.stdout, line);
    // Packaged GUI launches often lose inherited stdout. Persist a durable
    // readiness envelope under the active user-data root so dual-clean and
    // install harnesses can recover the loopback token without attaching a TTY.
    try {
      const readyPath = path.join(CANONICAL_USER_DATA, 'automation-ready.json');
      fs.writeFileSync(
        readyPath,
        JSON.stringify({
          schema: 1,
          port: AUTOMATION_PORT,
          token: LOCAL_SESSION_TOKEN,
          api_port: actualPort,
          user_data: CANONICAL_USER_DATA,
          ready_at: new Date().toISOString(),
        }, null, 2),
        'utf8',
      );
    } catch (_) {
      // Harness can still fall back to stdout when the file cannot be written.
    }
  });
}

// ── 托盘 ──

function createTray() {
  const iconPath = APP_ICON;
  // 如果 icon 不存在，跳过托盘
  if (!fs.existsSync(iconPath)) {
    console.log('[Tray] icon.ico not found, skipping tray');
    return;
  }

  tray = new Tray(iconPath);
  tray.setToolTip('Vibe Research — 研究证据工作台');

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);

  tray.setContextMenu(contextMenu);
  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── 生命周期 ──

app.on('ready', async () => {
  createTray();

  // ⛔ 启动前完整性检查：python.exe 等关键文件是否被杀毒软件误删/隔离
  const runtimeIssues = verifyRuntime();
  if (runtimeIssues.length > 0) {
    console.error('[Runtime] Integrity check failed:', runtimeIssues);
    showRuntimeIssueDialog(runtimeIssues);
    isQuitting = true;
    app.quit();
    return;
  }

  // 首次启动：自动安装 MiKTeX（如果系统上没有）
  try {
    await ensureMiKTeX();
  } catch (e) {
    console.error('[MiKTeX] Setup error:', e.message);
    // 不阻塞启动，编译功能可能不可用但其他功能正常
  }

  // 自动选择可用端口（避免端口占用导致启动失败）
  actualPort = await findAvailablePort(PORT);
  if (actualPort !== PORT) {
    console.log(`[Port] Default port ${PORT} occupied, using ${actualPort} instead`);
  } else {
    console.log(`[Port] Using port ${actualPort}`);
  }

  startBackend();

  try {
    await waitForBackend();
    console.log('[App] Backend is ready');
    createWindow();
    // 本地交付版禁用远程更新，避免显示更新下载横幅。
    if (AUTO_UPDATE_ENABLED) {
      setTimeout(() => initUpdater().catch(e => console.error('[Updater] init failed:', e)), 5000);
    }
  } catch (err) {
    dialog.showErrorBox('启动失败', `后端启动超时：${err.message}\n请检查 Python 运行时是否完整。`);
    isQuitting = true;
    killBackend();
    app.quit();
  }
});

// ============================================================
// 自动更新
// ============================================================
let updater = null;

async function initUpdater() {
  if (!AUTO_UPDATE_ENABLED) {
    console.log('[Updater] Disabled for this local build');
    return;
  }
  // 仅打包模式下启用更新 (开发模式不更新)
  if (IS_DEV) {
    console.log('[Updater] Dev mode, skip auto-update');
    return;
  }

  // 读取更新配置 (打包时随 app 分发, 也可以从 user_data 读用户自定义)
  let updateCfg = {
    server_url: '',  // 默认禁用；仅配置自有 HTTPS 更新服务后启用
    check_interval_hours: 6,
  };
  try {
    const cfgPath = path.join(APP_ROOT, 'updater-config.json');
    if (fs.existsSync(cfgPath)) {
      Object.assign(updateCfg, JSON.parse(fs.readFileSync(cfgPath, 'utf8')));
    }
  } catch (e) {
    console.warn('[Updater] config load failed:', e.message);
  }

  // 当前版本号 (从 package.json 读)
  let currentVersion = '1.0.0';
  try {
    const pkgPath = path.join(APP_ROOT, 'package.json');
    if (fs.existsSync(pkgPath)) {
      currentVersion = JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version || '1.0.0';
    }
  } catch {}

  // 安装目录 = process.resourcesPath 的父目录
  const installDir = path.dirname(process.resourcesPath);
  const userDataDir = app.getPath('userData');

  updater = new Updater({
    server_url: updateCfg.server_url,
    install_dir: installDir,
    current_version: currentVersion,
    check_interval_hours: updateCfg.check_interval_hours,
    user_data_dir: userDataDir,
  });

  // 静默检查
  try {
    const result = await updater.checkForUpdate();
    if (result.hasUpdate) {
      console.log(`[Updater] update available: v${result.version} (${result.changedFiles.length} files, ${(result.totalSize/1024/1024).toFixed(2)} MB)`);
      // 通知前端弹气泡
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update-available', {
          version: result.version,
          changelog: result.changelog,
          fileCount: result.changedFiles.length,
          totalSize: result.totalSize,
        });
      }
      // 缓存这次检查结果, 用户点更新时直接用
      updater._lastCheck = result;
    } else {
      console.log(`[Updater] no update: ${result.reason}`);
    }
  } catch (e) {
    console.error('[Updater] check error:', e);
  }
}

// IPC: 前端触发开始下载
ipcMain.handle('updater:start-download', async () => {
  if (!updater || !updater._lastCheck || !updater._lastCheck.hasUpdate) {
    return { ok: false, error: 'no update available' };
  }
  try {
    await updater.downloadUpdate(updater._lastCheck, (progress) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('update-progress', progress);
      }
    });
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message };
  }
});

// IPC: 前端触发应用更新 + 重启
ipcMain.handle('updater:apply-and-restart', async () => {
  if (!updater) return { ok: false, error: 'updater not initialized' };
  // 找当前 exe 路径
  const mainExePath = process.execPath;
  updater.applyUpdateAndRestart(mainExePath);
  // ⛔ 关键: 先把 backend Python 进程杀掉, 否则它会占用 resources/app/backend/*.pyc
  // 导致 robocopy 写入失败. (helper.bat 已有 2s 等待 + robocopy /R:3 重试,
  //  但能提前杀就不要等)
  isQuitting = true;
  killBackend();
  // 给 helper 一秒启动, 然后主进程退出 (helper 会等待 PID 消失再开始 robocopy)
  setTimeout(() => {
    app.quit();
  }, 800);
  return { ok: true };
});

// IPC: 前端取消下载
ipcMain.handle('updater:abort', async () => {
  if (updater) updater.abortDownload();
  return { ok: true };
});

// IPC: 前端跳过版本
ipcMain.handle('updater:skip-version', async (_e, version) => {
  if (updater) updater.skipVersion(version);
  return { ok: true };
});

// IPC: 前端拉取缓存的检查结果 (用户激活通过后调用, 不会重新查 manifest)
ipcMain.handle('updater:get-cached', async () => {
  if (!updater) return { hasUpdate: false, reason: 'updater not initialized' };
  return updater._lastCheck || { hasUpdate: false, reason: 'no check yet' };
});

// IPC: 前端手动检查更新
ipcMain.handle('updater:check-now', async () => {
  if (!updater) return { hasUpdate: false, reason: 'not initialized' };
  // 强制检查 (清除限流)
  const state = updater._loadState();
  state.last_check = 0;
  updater._saveState(state);
  const result = await updater.checkForUpdate();
  if (result.hasUpdate) updater._lastCheck = result;
  return result;
});

app.on('before-quit', () => {
  isQuitting = true;
  if (automationServer) { automationServer.close(); automationServer = null; }
  killBackend();
});

app.on('window-all-closed', () => {
  // macOS 上不退出（但本项目只针对 Windows）
  if (process.platform !== 'darwin') {
    // 不退出，保持托盘运行
  }
});

app.on('activate', () => {
  if (mainWindow) {
    mainWindow.show();
  }
});
