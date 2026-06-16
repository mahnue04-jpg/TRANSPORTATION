#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..', '..');
const includeExt = new Set(['.js', '.py', '.json', '.yml', '.yaml', '.ps1', '.md']);
const skipDirs = new Set(['.git', 'node_modules', '.venv', 'project_snapshots', 'artifacts', '.runtime', 'backend/data', 'backend/logs']);

function shouldSkipDir(relativeDir) {
  const normalized = relativeDir.replace(/\\/g, '/');
  for (const item of skipDirs) {
    if (normalized === item || normalized.startsWith(item + '/')) {
      return true;
    }
  }
  return false;
}

function walk(dir, relBase, out) {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const rel = relBase ? `${relBase}/${entry.name}` : entry.name;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (shouldSkipDir(rel)) continue;
      walk(full, rel, out);
      continue;
    }
    if (!entry.isFile()) continue;
    const ext = path.extname(entry.name).toLowerCase();
    if (includeExt.has(ext)) {
      out.push({ rel, full });
    }
  }
}

const files = [];
walk(root, '', files);

const findings = [];
const conflictStartPattern = /^<{7}(?:\s|$)/;
const conflictMidPattern = /^={7}$/;
const conflictEndPattern = /^>{7}(?:\s|$)/;
for (const file of files) {
  const text = fs.readFileSync(file.full, 'utf8');
  const lines = text.split(/\r?\n/);
  let inConflict = false;
  for (let i = 0; i < lines.length; i += 1) {
    const lineNo = i + 1;
    const line = lines[i].trimStart();

    if (conflictStartPattern.test(line)) {
      inConflict = true;
      findings.push(`${file.rel}:${lineNo} merge-conflict marker`);
      continue;
    }

    if (inConflict && conflictMidPattern.test(line)) {
      findings.push(`${file.rel}:${lineNo} merge-conflict marker`);
      continue;
    }

    if (conflictEndPattern.test(line)) {
      findings.push(`${file.rel}:${lineNo} merge-conflict marker`);
      inConflict = false;
      continue;
    }

    if (inConflict && conflictStartPattern.test(line)) {
      findings.push(`${file.rel}:${lineNo} merge-conflict marker`);
    }
  }
}

if (findings.length > 0) {
  console.error('[lint] FAILED');
  for (const finding of findings.slice(0, 200)) {
    console.error(` - ${finding}`);
  }
  if (findings.length > 200) {
    console.error(` - ... ${findings.length - 200} more`);
  }
  process.exit(1);
}

console.log(`[lint] OK (${files.length} files checked)`);
