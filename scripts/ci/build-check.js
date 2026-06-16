#!/usr/bin/env node
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const nodeExe = process.execPath;
const pythonExe = fs.existsSync(path.join(root, '.venv', 'Scripts', 'python.exe'))
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : 'python';

function run(cmd, args, label) {
  const res = spawnSync(cmd, args, {
    cwd: root,
    stdio: 'inherit',
    shell: false,
    windowsHide: true,
  });
  if (res.error) {
    console.error(`[build] ${label} failed to start: ${res.error.message}`);
    return 1;
  }
  return typeof res.status === 'number' ? res.status : 1;
}

function collectJsFiles(dir, out) {
  if (!fs.existsSync(dir)) return;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === 'node_modules' || entry.name === '.venv' || entry.name === 'project_snapshots' || entry.name === 'artifacts') {
      continue;
    }
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collectJsFiles(full, out);
      continue;
    }
    if (entry.isFile() && full.endsWith('.js')) {
      out.push(full);
    }
  }
}

console.log('[build] Python compile check...');
const pyStatus = run(pythonExe, ['-m', 'compileall', '-q', 'backend/app', 'scripts'], 'python compileall');
if (pyStatus !== 0) {
  process.exit(pyStatus);
}

console.log('[build] JavaScript parse check...');
const jsFiles = [];
collectJsFiles(path.join(root, 'backend', 'static'), jsFiles);
collectJsFiles(path.join(root, 'scripts'), jsFiles);

for (const file of jsFiles) {
  const status = run(nodeExe, ['--check', file], `node --check ${file}`);
  if (status !== 0) {
    process.exit(status);
  }
}

console.log(`[build] OK (${jsFiles.length} JS files parsed)`);
