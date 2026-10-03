#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { readFileSync, renameSync, writeFileSync, openSync, fsyncSync, closeSync } from 'node:fs';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import process from 'node:process';

import { executeCrossRuntimeChallenge } from '../dist/replication/cross-runtime-engine.js';

const [manifestArgument, dataRootArgument, packageRootArgument, outputArgument] = process.argv.slice(2);
if (!manifestArgument || !dataRootArgument || !packageRootArgument || !outputArgument) {
  throw new Error('Usage: cross-runtime-verify.mjs MANIFEST DATA_ROOT PACKAGE_ROOT OUTPUT');
}

function sha256(bytes) {
  return `sha256:${createHash('sha256').update(bytes).digest('hex')}`;
}

function stable(value) {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function safeChild(root, candidate, label) {
  const rootPath = resolve(root);
  const child = resolve(candidate);
  const rel = relative(rootPath, child);
  if (rel === '' || (!rel.startsWith(`..${sep}`) && rel !== '..' && !isAbsolute(rel))) return child;
  throw new Error(`${label} escapes its declared root.`);
}

function parseCsv(text, seriesId) {
  const rows = [];
  let row = [];
  let field = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ',') { row.push(field); field = ''; }
    else if (char === '\n') { row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = ''; }
    else field += char;
  }
  if (quoted) throw new Error(`Unclosed CSV quote in ${seriesId}.`);
  if (field !== '' || row.length > 0) { row.push(field.replace(/\r$/, '')); rows.push(row); }
  const nonEmpty = rows.filter((values) => values.some((value) => value !== ''));
  const header = nonEmpty.shift();
  if (JSON.stringify(header) !== JSON.stringify(['period_start_date', 'value', 'realtime_start_date'])) {
    throw new Error(`Canonical CSV schema changed for ${seriesId}.`);
  }
  return nonEmpty.map((values, index) => {
    if (values.length !== 3) throw new Error(`Malformed CSV row ${index + 2} for ${seriesId}.`);
    const value = Number(values[1]);
    if (!Number.isFinite(value) || value <= 0) throw new Error(`Invalid canonical value for ${seriesId}.`);
    return { period_start_date: values[0], value, realtime_start_date: values[2] };
  });
}

const dataRoot = resolve(dataRootArgument);
const packageRoot = resolve(packageRootArgument);
const manifestPath = safeChild(dataRoot, manifestArgument, 'Challenge manifest');
const outputPath = safeChild(dataRoot, outputArgument, 'Result output');
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'));
const payload = { ...manifest };
delete payload.challenge_id;
delete payload.challenge_fingerprint;
delete payload.created_at;
const computedChallengeFingerprint = sha256(Buffer.from(stable(payload), 'utf8'));
if (computedChallengeFingerprint !== manifest.challenge_fingerprint) throw new Error('Challenge fingerprint mismatch.');
if (manifest.challenge_id !== `XRV-${computedChallengeFingerprint.slice('sha256:'.length, 'sha256:'.length + 16)}`) {
  throw new Error('Challenge id is not derived from its fingerprint.');
}
if (manifest.production_status !== 'RESEARCH_ONLY' || manifest.automatic_promotion_authorized !== false) {
  throw new Error('Challenge production/promotion lock is not intact.');
}

for (const item of manifest.engine_files ?? []) {
  const sourcePath = safeChild(packageRoot, resolve(packageRoot, String(item.relative_path ?? '')), 'Engine source');
  if (sha256(readFileSync(sourcePath)) !== item.sha256) throw new Error(`Engine source fingerprint mismatch: ${item.relative_path}`);
}

const series = {};
for (const [seriesId, item] of Object.entries(manifest.canonical_files ?? {})) {
  const sourcePath = safeChild(dataRoot, resolve(dataRoot, String(item.relative_path ?? '')), 'Canonical series');
  const bytes = readFileSync(sourcePath);
  if (sha256(bytes) !== item.sha256) throw new Error(`Canonical file fingerprint mismatch: ${seriesId}`);
  const parsed = parseCsv(bytes.toString('utf8'), seriesId);
  if (parsed.length !== Number(item.row_count)) throw new Error(`Canonical row count mismatch: ${seriesId}`);
  series[seriesId] = parsed;
}

const result = executeCrossRuntimeChallenge(manifest, series);
result.node_version = process.version;
result.runtime_platform = `${process.platform}-${process.arch}`;
const encoded = `${JSON.stringify(result, null, 2)}\n`;
const temporary = `${outputPath}.tmp-${process.pid}`;
writeFileSync(temporary, encoded, { encoding: 'utf8', flag: 'wx' });
const descriptor = openSync(temporary, 'r');
try { fsyncSync(descriptor); } finally { closeSync(descriptor); }
renameSync(temporary, outputPath);
const directory = openSync(dirname(outputPath), 'r');
try { fsyncSync(directory); } finally { closeSync(directory); }
process.stdout.write(JSON.stringify({
  challenge_id: manifest.challenge_id,
  result_count: result.result_count,
  output_sha256: sha256(Buffer.from(encoded, 'utf8')),
}));
