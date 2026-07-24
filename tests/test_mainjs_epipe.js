'use strict';

/** Deterministic regression for Electron main-process closed console pipes. */
const assert = require('assert');
const { EventEmitter, once } = require('events');
const { Writable } = require('stream');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    if (!argv[index].startsWith('--')) continue;
    const key = argv[index].slice(2);
    result[key] = argv[index + 1] && !argv[index + 1].startsWith('--') ? argv[++index] : true;
  }
  return result;
}

function loadHelpers(sourcePath, useRealProcess = false) {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const marker = "const { Updater } = require('./updater');";
  const markerIndex = source.indexOf(marker);
  assert(markerIndex > 0, 'main.js helper boundary not found');

  const sourceDir = path.dirname(sourcePath);
  const dummyOut = new EventEmitter();
  const dummyErr = new EventEmitter();
  // Resolve relative requires against main.js, not the test file path.
  // Host require('./desktop-data') would otherwise look under tests/.
  // Electron is stubbed enough for the pre-Updater prefix: setName/getPath/
  // setPath run before the epipe helpers and must not throw.
  const electronStub = {
    app: {
      setName() {},
      getPath(name) {
        return path.join(sourceDir, '.epipe-test-user-data', String(name || 'appData'));
      },
      setPath() {},
      isPackaged: false,
    },
    BrowserWindow: class BrowserWindow {},
    Tray: class Tray {},
    Menu: { buildFromTemplate() { return {}; } },
    dialog: {},
    ipcMain: { handle() {} },
    nativeImage: { createFromPath() { return {}; } },
  };
  const hostProcess = useRealProcess
    ? process
    : {
        stdout: dummyOut,
        stderr: dummyErr,
        env: { ...(process.env || {}) },
        platform: process.platform,
        versions: process.versions || {},
      };
  const context = {
    require: (name) => {
      if (name === 'electron') return electronStub;
      if (name.startsWith('.')) return require(path.resolve(sourceDir, name));
      return require(name);
    },
    process: hostProcess,
    __dirname: sourceDir,
    console,
    Buffer,
    setTimeout,
    clearTimeout,
  };
  vm.createContext(context);
  vm.runInContext(
    `${source.slice(0, markerIndex)}\n` +
      'globalThis.__epipeHelpers = { ignoreBrokenPipe, safeStreamWrite };',
    context,
    { filename: sourcePath }
  );
  return { source, ...context.__epipeHelpers };
}

function failingWritable(code) {
  return new Writable({
    write(_chunk, _encoding, callback) {
      const error = new Error(code === 'EPIPE' ? 'broken pipe' : 'write failed');
      error.code = code;
      callback(error);
    },
  });
}

async function worker(sourcePath) {
  const { ignoreBrokenPipe, safeStreamWrite } = loadHelpers(sourcePath, true);
  // The prefix already registers these; repeated registration is harmless and
  // mirrors modules that may defensively initialize the streams more than once.
  ignoreBrokenPipe(process.stdout);
  ignoreBrokenPipe(process.stderr);
  process.stdout.write('READY\n', () => {});
  await new Promise((resolve) => setTimeout(resolve, 150));
  safeStreamWrite(process.stdout, 'backend stdout after parent close\n');
  safeStreamWrite(process.stderr, 'backend stderr after parent close\n');
  console.log('console stdout after parent close');
  console.error('console stderr after parent close');
  await new Promise((resolve) => setTimeout(resolve, 150));
}

async function parent(sourcePath, outputPath) {
  const { source, ignoreBrokenPipe, safeStreamWrite } = loadHelpers(sourcePath);

  assert.strictEqual((source.match(/process\.stdout\.write\s*\(/g) || []).length, 0,
    'backend output must not directly call process.stdout.write');
  assert.strictEqual((source.match(/process\.stderr\.write\s*\(/g) || []).length, 0,
    'backend output must not directly call process.stderr.write');
  assert(source.includes('safeStreamWrite(process.stdout, `[Backend] ${data}`)'),
    'backend stdout must use safeStreamWrite');
  assert(source.includes('safeStreamWrite(process.stderr, `[Backend] ${data}`)'),
    'backend stderr must use safeStreamWrite');
  assert(!/stdio\s*:\s*['"]inherit['"]/.test(source),
    'GUI subprocesses must not inherit possibly stale console handles');

  // Real Writable async EPIPE: both the callback error and emitted error event
  // are handled. This is the path try/catch alone cannot cover.
  const epipe = failingWritable('EPIPE');
  ignoreBrokenPipe(epipe);
  safeStreamWrite(epipe, 'payload');
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert(epipe.errored && epipe.errored.code === 'EPIPE');

  // A non-EPIPE stream failure also cannot become an uncaught logging crash.
  const eacces = failingWritable('EACCES');
  ignoreBrokenPipe(eacces);
  safeStreamWrite(eacces, 'payload');
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert(eacces.errored && eacces.errored.code === 'EACCES');

  let synchronousWrites = 0;
  const synchronousFailure = {
    destroyed: false,
    writableEnded: false,
    on() {},
    write() {
      synchronousWrites += 1;
      const error = new Error('broken pipe');
      error.code = 'EPIPE';
      throw error;
    },
  };
  assert.doesNotThrow(() => safeStreamWrite(synchronousFailure, 'payload'));
  assert.strictEqual(synchronousWrites, 1);

  let destroyedWrites = 0;
  safeStreamWrite({ destroyed: true, write() { destroyedWrites += 1; } }, 'payload');
  assert.strictEqual(destroyedWrites, 0, 'destroyed streams must be skipped');

  // OS-pipe boundary: close both parent-side pipes after READY, then make the
  // child execute the actual helpers plus console.log/console.error. It must
  // exit normally instead of raising the Electron-style uncaught EPIPE.
  const childEnv = { ...process.env };
  if (process.versions.electron) childEnv.ELECTRON_RUN_AS_NODE = '1';
  else delete childEnv.ELECTRON_RUN_AS_NODE;
  const child = spawn(process.execPath, [__filename, '--worker', '--source', sourcePath], {
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
    env: childEnv,
  });
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('worker READY timeout')), 5000);
    child.stdout.once('data', (chunk) => {
      if (!String(chunk).includes('READY')) return reject(new Error(`unexpected worker prelude: ${chunk}`));
      clearTimeout(timeout);
      child.stdout.destroy();
      child.stderr.destroy();
      resolve();
    });
    child.once('error', reject);
  });
  const [exitCode, signal] = await once(child, 'exit');
  assert.strictEqual(exitCode, 0, `closed-pipe worker failed (signal=${signal})`);

  const result = {
    source: sourcePath,
    direct_stdout_writes: 0,
    direct_stderr_writes: 0,
    inherited_stdio_paths: 0,
    async_epipe_handled: true,
    async_non_epipe_handled: true,
    sync_epipe_handled: true,
    destroyed_stream_skipped: true,
    real_closed_pipe_exit_code: exitCode,
    passed: true,
  };
  if (outputPath) {
    fs.mkdirSync(path.dirname(outputPath), { recursive: true });
    fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  }
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

const args = parseArgs(process.argv.slice(2));
const defaultSource = path.resolve(__dirname, '..', 'main.js');
const sourcePath = path.resolve(args.source || defaultSource);

(args.worker ? worker(sourcePath) : parent(sourcePath, args.output && path.resolve(args.output)))
  .catch((error) => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
