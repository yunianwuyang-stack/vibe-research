/**
 * 客户端自动更新器 (调用方: main.js)
 *
 * 工作流程:
 * 1. 启动 5 秒后, 静默 GET <server>/manifest.json
 * 2. 对比本地版本 + 文件 hash, 找出需要更新的文件
 * 3. 通过 IPC 通知前端弹气泡 "v1.0.1 可用"
 * 4. 用户点"立即更新" → 下载到 resources/app.update/
 * 5. 用户点"重启" → 启动 update-helper.exe (NSIS 自带), Vibe Research 退出
 * 6. update-helper 把 app.update 覆盖到 app/, 启动 Vibe Research
 *
 * 关键安全:
 * - 每个文件下载后校验 sha256, 不匹配丢弃
 * - manifest.json 大小限制 5MB (防 DoS)
 * - 下载有 retry + 进度
 * - 替换失败自动回滚 (保留 app.bak/ 一份)
 *
 * 范围: 全覆盖 resources/app/ + runtime/
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const crypto = require('crypto');
const { spawn } = require('child_process');

// Keep update metadata bounded before it can influence filesystem or network
// operations.  These limits are intentionally higher than the current bundle
// size, while preventing malformed values (for example NaN) from disabling
// the per-download size guard.
const MAX_MANIFEST_FILES = 10000;
const MAX_UPDATE_FILE_SIZE = 2 * 1024 * 1024 * 1024;
const MAX_UPDATE_TOTAL_SIZE = 4 * 1024 * 1024 * 1024;

// 默认配置 (打包时被 main.js 覆盖)
const DEFAULT_CONFIG = {
  server_url: '',                            // disabled unless an owned HTTPS endpoint is configured
  install_dir: null,                         // 安装根目录 (含 resources/app/, runtime/)
  current_version: '1.0.0',                  // 当前版本 (从 package.json 读)
  check_interval_hours: 6,                   // 多少小时检查一次
  user_data_dir: null,                       // 存最后检查时间 / 跳过版本
};

class Updater {
  constructor(config) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.installDir = this.config.install_dir;
    this.appDir = path.join(this.installDir, 'resources', 'app');
    this.runtimeDir = path.join(this.installDir, 'runtime');
    this.updateStagingDir = path.join(this.installDir, '.app.update');
    this.backupDir = path.join(this.installDir, '.app.bak');
    this.statePath = path.join(this.config.user_data_dir, 'updater-state.json');
    this.aborted = false;
    this.downloadProgress = { current: 0, total: 0, file: '' };

    // 启动时清理上次更新失败 / 中断留下的 staging 残留 (可能占几十 MB 磁盘空间)
    // 也清理上次的 vbs / bat (避免脏文件影响下次更新)
    this._cleanupStaleArtifacts();
  }

  _cleanupStaleArtifacts() {
    try {
      if (this.installDir && fs.existsSync(this.updateStagingDir)) {
        this._rmrf(this.updateStagingDir);
      }
      const vbsPath = path.join(this.installDir, 'update-helper-launcher.vbs');
      const batPath = path.join(this.installDir, 'update-helper.bat');
      const ps1Path = path.join(this.installDir, 'update-helper.ps1');
      if (fs.existsSync(vbsPath)) { try { fs.unlinkSync(vbsPath); } catch {} }
      if (fs.existsSync(batPath)) { try { fs.unlinkSync(batPath); } catch {} }
      if (fs.existsSync(ps1Path)) { try { fs.unlinkSync(ps1Path); } catch {} }
    } catch (e) {
      console.warn('[updater] cleanup stale artifacts failed:', e.message);
    }
  }

  // ============================================================
  // 状态持久化
  // ============================================================
  _loadState() {
    try {
      return JSON.parse(fs.readFileSync(this.statePath, 'utf8'));
    } catch {
      return { last_check: 0, skipped_version: null };
    }
  }

  _saveState(state) {
    try {
      fs.mkdirSync(path.dirname(this.statePath), { recursive: true });
      fs.writeFileSync(this.statePath, JSON.stringify(state));
    } catch (e) {
      console.error('[updater] save state failed:', e);
    }
  }

  // ============================================================
  // HTTP 请求
  // ============================================================
  _fetchJson(url, maxBytes = 5 * 1024 * 1024) {
    return new Promise((resolve, reject) => {
      if (!url.startsWith('https://')) { reject(new Error('HTTPS is required for updater requests')); return; }
      const lib = https;
      const req = lib.get(url, (res) => {
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        let received = 0;
        let body = '';
        res.on('data', (chunk) => {
          received += chunk.length;
          if (received > maxBytes) {
            req.destroy();
            reject(new Error('manifest too big'));
            return;
          }
          body += chunk;
        });
        res.on('end', () => {
          try {
            resolve(JSON.parse(body));
          } catch (e) {
            reject(new Error(`bad JSON: ${e.message}`));
          }
        });
      });
      req.on('error', reject);
      req.setTimeout(10000, () => req.destroy(new Error('manifest timeout')));
    });
  }

  _downloadFile(url, destPath, expectedSha, expectedSize, onProgress) {
    return new Promise((resolve, reject) => {
      if (!url.startsWith('https://')) { reject(new Error('HTTPS is required for updater requests')); return; }
      const lib = https;
      fs.mkdirSync(path.dirname(destPath), { recursive: true });
      const tmpPath = destPath + '.tmp';
      const file = fs.createWriteStream(tmpPath);
      const hash = crypto.createHash('sha256');
      let received = 0;

      const req = lib.get(url, (res) => {
        if (res.statusCode !== 200) {
          file.destroy();
          fs.unlink(tmpPath, () => {});
          reject(new Error(`HTTP ${res.statusCode} ${url}`));
          return;
        }

        // 防 DoS: 不允许超过 expectedSize 太多
        const maxSize = Math.max(expectedSize * 2, 1024 * 1024);

        res.on('data', (chunk) => {
          received += chunk.length;
          if (received > maxSize) {
            req.destroy();
            file.destroy();
            fs.unlink(tmpPath, () => {});
            reject(new Error('size exceeded'));
            return;
          }
          hash.update(chunk);
          if (onProgress) onProgress(chunk.length);
        });

        res.pipe(file);

        file.on('finish', () => {
          file.close(() => {
            const actualSha = hash.digest('hex');
            if (actualSha !== String(expectedSha).toLowerCase()) {
              fs.unlink(tmpPath, () => {});
              reject(new Error(`sha256 mismatch: expected ${expectedSha}, got ${actualSha}`));
              return;
            }
            try {
              fs.renameSync(tmpPath, destPath);
              resolve();
            } catch (e) {
              reject(e);
            }
          });
        });
      });

      req.on('error', (e) => {
        file.destroy();
        fs.unlink(tmpPath, () => {});
        reject(e);
      });
      req.setTimeout(60000, () => req.destroy(new Error('download timeout')));
    });
  }

  // ============================================================
  // 计算本地文件 hash (相对 installDir)
  // ============================================================
  _computeLocalSha(rel) {
    const full = path.join(this.installDir, rel.replace(/\//g, path.sep));
    if (!fs.existsSync(full)) return null;
    try {
      const data = fs.readFileSync(full);
      return crypto.createHash('sha256').update(data).digest('hex');
    } catch {
      return null;
    }
  }

  // ============================================================
  // 主流程: 检查更新
  // ============================================================
  async checkForUpdate() {
    if (!this.config.server_url) return { hasUpdate: false, reason: 'disabled' };
    const state = this._loadState();
    const now = Date.now();

    // 间隔限流
    const intervalMs = this.config.check_interval_hours * 3600 * 1000;
    if (now - state.last_check < intervalMs) {
      return { hasUpdate: false, reason: 'rate-limited' };
    }

    state.last_check = now;
    this._saveState(state);

    let manifest;
    try {
      // ⛔ 绕过 CDN/nginx 缓存: 加 ?_t=timestamp
      // 否则 nginx 默认对 .json 缓存可能让客户端看到旧 manifest, 永远不更新
      const url = `${this.config.server_url}/manifest.json?_t=${now}`;
      manifest = await this._fetchJson(url);
    } catch (e) {
      return { hasUpdate: false, reason: `fetch failed: ${e.message}` };
    }

    if (!this._validateManifest(manifest)) {
      return { hasUpdate: false, reason: 'bad manifest' };
    }

    // 用户跳过过这个版本就不弹了
    if (state.skipped_version === manifest.version) {
      return { hasUpdate: false, reason: 'user skipped' };
    }

    // 版本号比较 (语义化)
    if (this._compareVersion(manifest.version, this.config.current_version) <= 0) {
      return { hasUpdate: false, reason: 'up to date' };
    }

    // 找出本地缺失或 hash 不一致的文件
    const changedFiles = [];
    let totalSize = 0;
    for (const f of manifest.files) {
      const localSha = this._computeLocalSha(f.rel);
      if (localSha !== f.sha256) {
        changedFiles.push(f);
        totalSize += f.size;
      }
    }

    // 本地所有文件都已同步, 说明上次更新已落地, 只是 package.json 没写新 version,
    // 不应再弹气泡 (否则点了立即更新后下载 0 文件、瞬间 ready, 用户重启后还是老版本, 进入死循环)
    if (changedFiles.length === 0) {
      return { hasUpdate: false, reason: 'all files in sync (already updated)' };
    }

    return {
      hasUpdate: true,
      version: manifest.version,
      changelog: manifest.changelog || '',
      changedFiles,
      totalSize,
      manifest,
    };
  }

  // 语义化版本比较: 1.0.1 > 1.0.0 → 1; equal → 0; less → -1
  _compareVersion(a, b) {
    const pa = a.split('.').map(n => parseInt(n, 10) || 0);
    const pb = b.split('.').map(n => parseInt(n, 10) || 0);
    const len = Math.max(pa.length, pb.length);
    for (let i = 0; i < len; i++) {
      const na = pa[i] || 0;
      const nb = pb[i] || 0;
      if (na > nb) return 1;
      if (na < nb) return -1;
    }
    return 0;
  }

  // ============================================================
  // 下载所有变化文件到 staging
  // ============================================================
  async downloadUpdate(updateInfo, onProgress) {
    this.aborted = false;

    if (!updateInfo || !this._validateManifest(updateInfo.manifest)) {
      throw new Error('bad manifest');
    }
    if (!Array.isArray(updateInfo.changedFiles) || updateInfo.changedFiles.length > MAX_MANIFEST_FILES) {
      throw new Error('bad update file list');
    }
    const manifestFiles = new Map(updateInfo.manifest.files.map(file => [file.rel, file]));
    const changedPaths = new Set();
    let changedTotal = 0;
    for (const file of updateInfo.changedFiles) {
      const declared = file && manifestFiles.get(file.rel);
      if (!this._validateFileEntry(file) || changedPaths.has(file.rel) || !declared ||
          file.sha256.toLowerCase() !== declared.sha256.toLowerCase() || file.size !== declared.size) {
        throw new Error('bad update file entry');
      }
      changedPaths.add(file.rel);
      changedTotal += file.size;
      if (!Number.isSafeInteger(changedTotal) || changedTotal > MAX_UPDATE_TOTAL_SIZE) {
        throw new Error('update file list too large');
      }
    }

    // 清理旧 staging
    if (fs.existsSync(this.updateStagingDir)) {
      this._rmrf(this.updateStagingDir);
    }
    fs.mkdirSync(this.updateStagingDir, { recursive: true });

    let downloaded = 0;
    const total = updateInfo.totalSize;
    this.downloadProgress = { current: 0, total, file: '' };

    for (const f of updateInfo.changedFiles) {
      if (this.aborted) throw new Error('aborted');

      if (!this._validateFileEntry(f)) throw new Error('bad update file entry');

      this.downloadProgress.file = f.rel;
      const destPath = path.join(this.updateStagingDir, f.rel.replace(/\//g, path.sep));
      const url = `${this.config.server_url}/files/${f.sha256.substring(0, 2)}/${f.sha256}.bin`;

      // 重试 3 次
      let lastErr;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          await this._downloadFile(url, destPath, f.sha256, f.size, (chunk) => {
            this.downloadProgress.current = downloaded + chunk;
            if (onProgress) onProgress(this.downloadProgress);
          });
          downloaded += f.size;
          this.downloadProgress.current = downloaded;
          if (onProgress) onProgress(this.downloadProgress);
          lastErr = null;
          break;
        } catch (e) {
          lastErr = e;
          await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
        }
      }
      if (lastErr) {
        throw new Error(`下载 ${f.rel} 失败: ${lastErr.message}`);
      }
    }

    // 保存 manifest 到 staging (apply 时校验)
    fs.writeFileSync(
      path.join(this.updateStagingDir, '.manifest.json'),
      JSON.stringify({ ...updateInfo.manifest, required_files: [...changedPaths] })
    );

    return { ok: true, downloaded };
  }

  abortDownload() {
    this.aborted = true;
  }

  // ============================================================
  // 启动 update-helper 应用更新 (在 Vibe Research 退出后跑)
  // 用 vbs 壳启动, wscript.exe 是 GUI 子系统进程, 完全静默 (无黑框).
  // 历史 bug: 之前用 cmd /c batPath, 即使 windowsHide:true + detached, Windows 仍会弹一个 cmd 窗口
  //          (因为 cmd 是 console 子系统, 用户体验差)
  // ============================================================
  applyUpdateAndRestart(mainExePath) {
    const helperBat = path.join(this.installDir, 'update-helper.bat');
    const helperVbs = path.join(this.installDir, 'update-helper-launcher.vbs');
    const helperPs1 = path.join(this.installDir, 'update-helper.ps1');

    this._writePowerShellHelper(helperPs1, mainExePath);
    this._writeFallbackBat(helperBat, helperPs1);
    this._writeVbsLauncher(helperVbs, helperBat);

    spawn('wscript', [helperVbs], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
    }).unref();
  }

  _validateRelativePath(rel) {
    if (typeof rel !== 'string' || !rel || rel.includes('\0') || path.isAbsolute(rel)) {
      throw new Error(`unsafe update path: ${rel}`);
    }
    const normalized = path.posix.normalize(rel.replace(/\\/g, '/'));
    if (normalized === '.' || normalized === '..' || normalized.startsWith('../') || normalized.endsWith('/')) {
      throw new Error(`unsafe update path: ${rel}`);
    }
    return normalized;
  }

  _validateFileEntry(file) {
    if (!file || typeof file !== 'object' || Array.isArray(file)) return false;
    if (typeof file.rel !== 'string') return false;
    let normalized;
    try {
      normalized = this._validateRelativePath(file.rel);
    } catch (_) {
      return false;
    }
    // Reject aliases such as ./app.js or a\\b.  The same canonical spelling
    // must be used by the downloader and the PowerShell apply helper.
    if (file.rel !== normalized) return false;
    if (typeof file.sha256 !== 'string' || !/^[a-f0-9]{64}$/i.test(file.sha256)) return false;
    if (!Number.isSafeInteger(file.size) || file.size < 0 || file.size > MAX_UPDATE_FILE_SIZE) return false;
    return true;
  }

  _validateManifest(manifest) {
    if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) return false;
    if (typeof manifest.version !== 'string' || manifest.version.length === 0 || manifest.version.length > 64) return false;
    if (!Array.isArray(manifest.files) || manifest.files.length > MAX_MANIFEST_FILES) return false;
    const paths = new Set();
    let total = 0;
    for (const file of manifest.files) {
      if (!this._validateFileEntry(file) || paths.has(file.rel)) return false;
      paths.add(file.rel);
      total += file.size;
      if (!Number.isSafeInteger(total) || total > MAX_UPDATE_TOTAL_SIZE) return false;
    }
    return true;
  }

  _psLiteral(value) {
    return `'${String(value).replace(/'/g, "''")}'`;
  }

  _writePowerShellHelper(ps1Path, mainExePath, parentPid = process.pid) {
    const content = `
$ErrorActionPreference = 'Stop'
$install = ${this._psLiteral(this.installDir)}
$staging = ${this._psLiteral(this.updateStagingDir)}
$backup = ${this._psLiteral(this.backupDir)}
$mainExe = ${this._psLiteral(mainExePath)}
$parentPid = ${parentPid}
$log = Join-Path $env:TEMP 'vibe-research-update.log'
function Log([string]$message) { Add-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] $message" -Encoding UTF8 }
function Restore-Backup {
  Log 'restoring backup'
  if ($manifest -and $manifest.files) {
    foreach ($file in $manifest.files) {
      $rel = ([string]$file.rel).Replace('/', '\\')
      if ([IO.Path]::IsPathRooted($rel) -or $rel.Split('\\') -contains '..') { continue }
      $dest = Join-Path $install $rel
      Remove-Item -LiteralPath $dest -Force -ErrorAction SilentlyContinue
    }
  }
  if (Test-Path -LiteralPath $backup) {
    Get-ChildItem -LiteralPath $backup -Recurse -File | ForEach-Object {
      $rel = $_.FullName.Substring($backup.Length).TrimStart('\\')
      $dest = Join-Path $install $rel
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
      Copy-Item -LiteralPath $_.FullName -Destination $dest -Force
    }
  }
}
Set-Content -LiteralPath $log -Value "[$(Get-Date -Format o)] update-helper start" -Encoding UTF8
try {
  try { Wait-Process -Id $parentPid -Timeout 30 -ErrorAction Stop } catch { Stop-Process -Id $parentPid -Force -ErrorAction SilentlyContinue }
  $manifestPath = Join-Path $staging '.manifest.json'
  $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($manifest.required_files) {
    foreach ($requiredRel in @($manifest.required_files)) {
      $rel = ([string]$requiredRel).Replace('/', '\\')
      if ([IO.Path]::IsPathRooted($rel) -or $rel.Split('\\') -contains '..') { throw "unsafe required update path: $rel" }
      $source = Join-Path $staging $rel
      if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw "missing staged update file: $rel" }
    }
  }
  Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $backup | Out-Null
  foreach ($file in $manifest.files) {
    $rel = ([string]$file.rel).Replace('/', '\\')
    if ([IO.Path]::IsPathRooted($rel) -or $rel.Split('\\') -contains '..') { throw "unsafe update path: $rel" }
    $source = Join-Path $staging $rel
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
    $current = Join-Path $install $rel
    if (Test-Path -LiteralPath $current -PathType Leaf) {
      $saved = Join-Path $backup $rel
      New-Item -ItemType Directory -Force -Path (Split-Path -Parent $saved) | Out-Null
      Copy-Item -LiteralPath $current -Destination $saved -Force
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $current) | Out-Null
    Copy-Item -LiteralPath $source -Destination $current -Force
  }
  foreach ($file in $manifest.files) {
    $rel = ([string]$file.rel).Replace('/', '\\')
    $source = Join-Path $staging $rel
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { continue }
    $current = Join-Path $install $rel
    $actual = (Get-FileHash -LiteralPath $current -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne ([string]$file.sha256).ToLowerInvariant()) { throw "post-apply hash mismatch: $rel" }
  }
  Log 'update applied and verified'
} catch {
  Log "apply failed: $($_.Exception.Message)"
  Restore-Backup
  Log 'rollback completed'
} finally {
  Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $mainExe) { Start-Process -FilePath $mainExe }
}
`;
    // Windows PowerShell 5.1 interprets BOM-less scripts using the active ANSI
    // code page, corrupting Unicode install paths. UTF-8 BOM is deterministic.
    fs.writeFileSync(ps1Path, Buffer.concat([Buffer.from([0xEF, 0xBB, 0xBF]), Buffer.from(content, 'utf8')]));
  }

  // wscript 壳: 完全无窗口启动 cmd /c batPath
  // - UTF-16 LE BOM 编码: wscript 才能正确识别中文路径
  // - 用 Chr(34) 拼接双引号: VBScript 最稳的引号转义方式
  _writeVbsLauncher(vbsPath, batPath) {
    // 在 VBS 字符串内, 不要含双引号 (用 & q 拼接)
    // 但 batPath 里可能含 " (用户装到含 " 的路径? 极少, 但保险起见用 chr 拼)
    // 最简单: 把 batPath 拆分, 任何 " 都换成 chr(34) 拼接
    const escapedForVbs = batPath
      .split('"')
      .map(s => `"${s}"`)
      .join(' & q & ');
    const content =
      'Set sh = CreateObject("WScript.Shell")\r\n' +
      'q = Chr(34)\r\n' +
      `sh.Run "cmd /c " & q & ${escapedForVbs} & q, 0, False\r\n`;
    // 写 UTF-16 LE + BOM (wscript 才能正确识别中文路径)
    const utf16Buf = Buffer.from(content, 'utf16le');
    const bom = Buffer.from([0xFF, 0xFE]);
    fs.writeFileSync(vbsPath, Buffer.concat([bom, utf16Buf]));
  }

  _writeFallbackBat(batPath, helperPs1) {
    const lines = [
      '@echo off',
      'chcp 65001 >nul',
      `powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "${helperPs1}"`,
      'exit /b %ERRORLEVEL%',
    ];
    const bom = Buffer.from([0xEF, 0xBB, 0xBF]);
    fs.writeFileSync(batPath, Buffer.concat([bom, Buffer.from(lines.join('\r\n'), 'utf8')]));
  }

  _rmrf(p) {
    if (!fs.existsSync(p)) return;
    for (const entry of fs.readdirSync(p, { withFileTypes: true })) {
      const sub = path.join(p, entry.name);
      if (entry.isDirectory()) this._rmrf(sub);
      else fs.unlinkSync(sub);
    }
    fs.rmdirSync(p);
  }

  skipVersion(version) {
    const state = this._loadState();
    state.skipped_version = version;
    this._saveState(state);
  }
}

module.exports = { Updater };
