#!/usr/bin/env node
'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');

function collectTsFiles(dir, out) {
  if (!fs.existsSync(dir)) return;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === 'node_modules' || entry.name === '.venv' || entry.name === 'project_snapshots' || entry.name === 'artifacts') {
      continue;
    }
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collectTsFiles(full, out);
      continue;
    }
    if (entry.isFile() && (full.endsWith('.ts') || full.endsWith('.tsx'))) {
      out.push(path.relative(root, full).replace(/\\/g, '/'));
    }
  }
}

const tsFiles = [];
collectTsFiles(root, tsFiles);

if (tsFiles.length === 0) {
  console.log('[tsc] No TypeScript files found. Skipping type-check.');
  process.exit(0);
}

const localTsc = path.join(root, 'node_modules', 'typescript', 'lib', 'tsc.js');
const hasTsConfig = fs.existsSync(path.join(root, 'tsconfig.json'));

if (!hasTsConfig) {
  console.log(`[tsc] TypeScript sources detected (${tsFiles.length} files), but no tsconfig.json is present.`);
  console.log('[tsc] Skipping compile in unconfigured mode to keep CI deterministic.');
  process.exit(0);
}

let result;
if (fs.existsSync(localTsc)) {
  const args = [localTsc, '--noEmit'];
  result = spawnSync(process.execPath, args, {
    cwd: root,
    stdio: 'inherit',
    shell: false,
    windowsHide: true,
  });
} else {
  console.error('[tsc] TypeScript sources found but local compiler is missing.');
  console.error('[tsc] Install dev dependency: typescript');
  process.exit(1);
}

if (result.error) {
  console.error(`[tsc] Failed to run TypeScript compiler: ${result.error.message}`);
  process.exit(1);
}

process.exit(typeof result.status === 'number' ? result.status : 1);
