'use strict';

/**
 * Packaged Electron acceptance for the main-process broken-pipe regression.
 *
 * The original failure occurred when the Playwright/terminal parent closed the
 * Electron main process' inherited stdout/stderr pipes while the Python backend
 * was still producing output.  This test deliberately destroys both parent-side
 * streams, makes the backend emit another access log, and verifies that the UI
 * and health endpoint remain alive.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function parseArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith('--')) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) {
      result[key] = next;
      i += 1;
    } else {
      result[key] = true;
    }
  }
  return result;
}

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex').toUpperCase();
}

function requirePlaywright(explicitPath) {
  const codexRuntimeRoot = path.join(
    process.env.LOCALAPPDATA || '',
    'OpenAI', 'Codex', 'runtimes', 'cua_node'
  );
  const codexCandidates = fs.existsSync(codexRuntimeRoot)
    ? fs.readdirSync(codexRuntimeRoot, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => path.join(codexRuntimeRoot, entry.name, 'bin', 'node_modules', 'playwright'))
    : [];
  const candidates = [
    explicitPath,
    process.env.PLAYWRIGHT_MODULE,
    'playwright',
    ...codexCandidates,
  ].filter(Boolean);
  for (const candidate of candidates) {
    try {
      return require(candidate);
    } catch (_) {
      // Try the next configured/local Playwright module.
    }
  }
  throw new Error(`Playwright not found; tried: ${candidates.join(', ')}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const defaultSourceRoot = path.resolve(__dirname, '..');
  const defaultReleaseCandidates = [
    path.join(defaultSourceRoot, 'release', 'win-unpacked'),
    path.resolve(defaultSourceRoot, '..', 'Vibe-research构建版'),
  ];
  const defaultReleaseRoot = defaultReleaseCandidates.find((candidate) => (
    fs.existsSync(path.join(candidate, 'Vibe Research.exe'))
  )) || defaultSourceRoot;
  const appRoot = path.resolve(args['app-root'] || defaultReleaseRoot);
  const exePath = path.resolve(args.exe || path.join(appRoot, 'Vibe Research.exe'));
  const mainJsPath = path.resolve(
    args['main-js']
      || (fs.existsSync(path.join(appRoot, 'resources', 'app', 'main.js'))
        ? path.join(appRoot, 'resources', 'app', 'main.js')
        : path.join(appRoot, 'main.js'))
  );
  const outputPath = path.resolve(args.output || path.join(process.cwd(), 'electron_epipe_acceptance.json'));
  const screenshotPath = path.resolve(args.screenshot || path.join(path.dirname(outputPath), 'electron_epipe_acceptance.png'));

  if (!fs.existsSync(exePath)) throw new Error(`Packaged executable missing: ${exePath}`);
  if (!fs.existsSync(mainJsPath)) throw new Error(`Packaged main.js missing: ${mainJsPath}`);

  const sourceMainJsPath = args['source-main-js'] && path.resolve(args['source-main-js']);
  const releaseMainJsSource = fs.readFileSync(mainJsPath, 'utf8');
  const preconditions = {
    release_main_js_has_safe_stdout: releaseMainJsSource
      .includes('safeStreamWrite(process.stdout, `[Backend] ${data}`)'),
    release_main_js_has_safe_stderr: releaseMainJsSource
      .includes('safeStreamWrite(process.stderr, `[Backend] ${data}`)'),
    release_main_js_has_inherited_stdio: /stdio\s*:\s*['"]inherit['"]/.test(releaseMainJsSource),
    source_release_hash_match: sourceMainJsPath && fs.existsSync(sourceMainJsPath)
      ? sha256(sourceMainJsPath) === sha256(mainJsPath)
      : null,
  };

  if (args['precheck-only']) {
    const result = {
      timestamp: new Date().toISOString(),
      exe: exePath,
      main_js: mainJsPath,
      main_js_sha256: sha256(mainJsPath),
      source_main_js: sourceMainJsPath || null,
      preconditions,
      passed: preconditions.release_main_js_has_safe_stdout
        && preconditions.release_main_js_has_safe_stderr
        && !preconditions.release_main_js_has_inherited_stdio
        && preconditions.source_release_hash_match !== false,
    };
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
    if (!result.passed) process.exitCode = 1;
    return;
  }

  const { _electron: electron } = requirePlaywright(args.playwright);
  const startedAt = new Date().toISOString();
  let electronApp;
  let page;
  let child;
  let result;

  try {
    electronApp = await electron.launch({ executablePath: exePath, args: [] });
    child = electronApp.process();
    page = await electronApp.firstWindow({ timeout: 120000 });
    await page.waitForLoadState('domcontentloaded');
    await page.goto('http://127.0.0.1:18088/settings', { waitUntil: 'domcontentloaded', timeout: 30000 });

    const title = await page.title();
    const settingsInputs = await page.locator('input').count();
    const healthBefore = await page.evaluate(async () => {
      const response = await fetch('/api/health', { cache: 'no-store' });
      return { status: response.status, body: await response.json() };
    });

    // Capture the visible acceptance artifact before destroying the parent
    // streams; Chromium screenshot transport can itself be affected by teardown
    // timing, while the post-destroy liveness assertions below remain decisive.
    let screenshotError = null;
    try {
      await page.evaluate(() => {
        if (document.fonts && document.fonts.status !== 'loaded') {
          Object.defineProperty(document, 'fonts', {
            configurable: true,
            value: { status: 'loaded', ready: Promise.resolve() },
          });
        }
      });
      await page.screenshot({
        path: screenshotPath,
        animations: 'disabled',
        caret: 'hide',
        timeout: 10000,
      });
    } catch (error) {
      screenshotError = String(error);
    }

    // This reproduces the exact parent-side condition that used to make
    // process.stdout.write/process.stderr.write throw EPIPE in main.js.
    if (child.stdout && !child.stdout.destroyed) child.stdout.destroy();
    if (child.stderr && !child.stderr.destroyed) child.stderr.destroy();

    // Generate fresh Python stdout after both inherited pipes have closed.
    const healthAfter = await page.evaluate(async () => {
      const response = await fetch(`/api/health?epipe_probe=${Date.now()}`, { cache: 'no-store' });
      return { status: response.status, body: await response.json() };
    });
    // Send a malformed URL as an additional noisy-request probe.  The static
    // and unit checks cover safeStreamWrite(process.stderr) deterministically;
    // Uvicorn's exact stream choice for this request is version-dependent.
    let malformedRequestError = null;
    try {
      await page.evaluate(async () => {
        await fetch('http://127.0.0.1:18088/%', { cache: 'no-store' });
      });
    } catch (error) {
      malformedRequestError = String(error);
    }
    await page.waitForTimeout(250);
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForTimeout(1000);

    const aliveAfterPipeDestroy = child.exitCode === null && !child.killed && !page.isClosed();
    const urlAfterReload = page.url();
    const settingsInputsAfter = await page.locator('input').count();

    result = {
      timestamp: new Date().toISOString(),
      started_at: startedAt,
      exe: exePath,
      main_js: mainJsPath,
      main_js_sha256: sha256(mainJsPath),
      source_main_js: sourceMainJsPath || null,
      preconditions,
      title,
      url_after_reload: urlAfterReload,
      health_before: healthBefore,
      health_after_pipe_destroy: healthAfter,
      stderr_probe: {
        request: 'GET /% (malformed URL)',
        renderer_error: malformedRequestError,
        stream_observation: 'not asserted; deterministic stderr coverage is in the main.js unit probe',
      },
      stdout_destroyed: !child.stdout || child.stdout.destroyed,
      stderr_destroyed: !child.stderr || child.stderr.destroyed,
      alive_after_pipe_destroy: aliveAfterPipeDestroy,
      settings_inputs_before: settingsInputs,
      settings_inputs_after: settingsInputsAfter,
      child_exit_code_during_probe: child.exitCode,
      screenshot: screenshotError ? null : screenshotPath,
      screenshot_error: screenshotError,
      passed: healthBefore.status === 200
        && healthAfter.status === 200
        && aliveAfterPipeDestroy
        && settingsInputsAfter > 0
        && preconditions.release_main_js_has_safe_stdout
        && preconditions.release_main_js_has_safe_stderr
        && !preconditions.release_main_js_has_inherited_stdio
        && preconditions.source_release_hash_match !== false
        && !screenshotError,
    };
  } finally {
    if (electronApp) {
      try {
        await electronApp.close();
      } catch (_) {
        if (child && child.exitCode === null) child.kill();
      }
    }
  }

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (!result.passed) process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
