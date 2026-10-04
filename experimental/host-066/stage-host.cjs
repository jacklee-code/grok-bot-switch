#!/usr/bin/env node
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const childProcess = require('node:child_process');
const transform = require('./transform.cjs');

function stage(options) {
  const input = path.resolve(options.input);
  const output = path.resolve(options.output);
  const manifest = output + '.manifest.json';
  if (input === output) throw new Error('Input and output must be different paths; staging never edits the installed host.');
  if (fs.existsSync(output) || fs.existsSync(manifest)) throw new Error('Output or manifest already exists; choose a fresh staging path.');
  if (options.hostVersion !== transform.HOST_VERSION) throw new Error('Only host 1494ebd is supported.');
  if (options.operation !== 'apply' && options.operation !== 'remove') throw new Error('Operation must be apply or remove.');
  const source = fs.readFileSync(input, 'utf8');
  const candidate = options.operation === 'apply' ? transform.apply(source, options) : transform.remove(source);
  if (options.operation === 'apply' && transform.remove(candidate) !== source) throw new Error('The reversibility proof failed.');
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const temporary = output + '.' + process.pid + '.staging.cjs';
  try {
    fs.writeFileSync(temporary, candidate, { flag: 'wx', mode: 0o600 });
    childProcess.execFileSync(process.execPath, ['--check', temporary], { encoding: 'utf8', stdio: 'pipe', windowsHide: true });
    const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
    const report = {
      schemaVersion: 1, operation: options.operation, hostVersion: transform.HOST_VERSION,
      input, output, inputSha256: sha256(source), outputSha256: sha256(candidate),
      syntaxCheck: 'passed', reversible: options.operation === 'apply', installed: false,
      localAgentManifest: 'Separate opt-in local-agents.json is required; this staging operation does not create or enable any Bot.'
    };
    fs.writeFileSync(manifest, JSON.stringify(report, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    fs.renameSync(temporary, output);
    return report;
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}
function parseArgs(argv) {
  const accepted = new Set(['--input', '--output', '--host-version', '--operation']);
  const result = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    if (!accepted.has(key) || typeof argv[i + 1] !== 'string' || argv[i + 1].startsWith('--')) throw new Error('Usage: stage-host.cjs --input SOURCE --output NEW_CANDIDATE --host-version 1494ebd --operation apply|remove');
    const property = key === '--host-version' ? 'hostVersion' : key.slice(2);
    if (property in result) throw new Error('Duplicate option: ' + key);
    result[property] = argv[i + 1];
  }
  if (!result.input || !result.output || !result.hostVersion || !result.operation) throw new Error('All four options are required.');
  return result;
}
if (require.main === module) {
  try { process.stdout.write(JSON.stringify(stage(parseArgs(process.argv.slice(2))), null, 2) + '\n'); }
  catch (error) { process.stderr.write('Staging refused: ' + error.message + '\n'); process.exitCode = 1; }
}
module.exports = { stage, parseArgs };
