'use strict';

// Synthetic fixtures only. No application profile, user ID, or vendor source is read.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, 'local-routing.cjs'), 'utf8');
const context = { require };
vm.runInNewContext(source, context, { filename: 'local-routing.cjs' });
const read = context.__gs066ReadAllowlist;
const ID_A = '11111111-1111-4111-8111-111111111111';
const ID_B = '22222222-2222-4222-8222-222222222222';
const valid = agentIds => ({ version: 1, hostVersion: '1494ebd', agentIds });
const values = set => Array.from(set).sort();

function profile(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'gs066-config-test-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return directory;
}

function write(directory, data) {
  fs.writeFileSync(path.join(directory, 'grok-switch-local-agents.json'),
    typeof data === 'string' ? data : JSON.stringify(data));
}

test('explicit lower-case UUIDs enable only those agents', t => {
  const directory = profile(t);
  write(directory, valid([ID_A, ID_B]));
  assert.deepEqual(values(read(directory)), [ID_A, ID_B]);
  assert.equal(read(directory).has('33333333-3333-4333-8333-333333333333'), false);
});

test('an empty explicit allowlist remains disabled', t => {
  const directory = profile(t);
  write(directory, valid([]));
  assert.deepEqual(values(read(directory)), []);
});

test('missing or malformed configuration fails closed', t => {
  const directory = profile(t);
  assert.deepEqual(values(read(directory)), []);
  for (const malformed of ['', '{', 'null', '[]', 'true', '42', '"value"']) {
    write(directory, malformed);
    assert.deepEqual(values(read(directory)), [], malformed);
  }
});

for (const [label, mutation] of [
  ['missing schema version', data => delete data.version],
  ['old schema version', data => data.version = 0],
  ['future schema version', data => data.version = 2],
  ['string schema version', data => data.version = '1'],
  ['missing host version', data => delete data.hostVersion],
  ['different host version', data => data.hostVersion = '0000000'],
  ['non-string host version', data => data.hostVersion = 1494],
  ['missing agent IDs', data => delete data.agentIds],
  ['non-array agent IDs', data => data.agentIds = ID_A],
  ['unknown settings', data => data.autoLearn = true],
  ['null ID', data => data.agentIds = [null]],
  ['number ID', data => data.agentIds = [1]],
  ['wildcard ID', data => data.agentIds = ['*']],
  ['non-UUID ID', data => data.agentIds = ['not-an-agent']],
  ['uppercase UUID', data => data.agentIds = ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'.toUpperCase()]],
  ['UUID with whitespace', data => data.agentIds = [' ' + ID_A]],
  ['duplicate IDs', data => data.agentIds = [ID_A, ID_A]],
  ['mixed valid and invalid IDs', data => data.agentIds = [ID_A, 'invalid']],
]) {
  test(`${label} rejects the whole allowlist`, t => {
    const directory = profile(t);
    const data = valid([ID_A]);
    mutation(data);
    write(directory, data);
    assert.deepEqual(values(read(directory)), []);
  });
}

test('32 explicit UUIDs are accepted; 33 are rejected', t => {
  const directory = profile(t);
  const ids = Array.from({ length: 33 }, (_, i) =>
    `${(i + 1).toString(16).padStart(8, '0')}-aaaa-4aaa-8aaa-aaaaaaaaaaaa`);
  write(directory, valid(ids.slice(0, 32)));
  assert.equal(read(directory).size, 32);
  write(directory, valid(ids));
  assert.deepEqual(values(read(directory)), []);
});

test('32768-byte configuration is accepted; larger configuration is rejected', t => {
  const directory = profile(t);
  const data = JSON.stringify(valid([ID_A]));
  write(directory, data + ' '.repeat(32768 - Buffer.byteLength(data)));
  assert.deepEqual(values(read(directory)), [ID_A]);
  write(directory, data + ' '.repeat(32769 - Buffer.byteLength(data)));
  assert.deepEqual(values(read(directory)), []);
});

test('relative, empty and non-string profiles never read the filesystem', () => {
  const fail = new Proxy({}, { get() { throw new Error('filesystem touched'); } });
  for (const directory of [undefined, null, 1, {}, '', 'relative-profile']) {
    assert.deepEqual(values(read(directory, fail, path)), []);
  }
});

test('symlinks, directories and unreadable files fail closed', () => {
  const directory = path.resolve(os.tmpdir(), 'synthetic-profile');
  for (const flags of [
    { file: true, symlink: true, size: 10 },
    { file: false, symlink: false, size: 10 },
    { file: true, symlink: false, size: 32769 },
  ]) {
    let attemptedRead = false;
    const fakeFs = {
      lstatSync: () => ({ isFile: () => flags.file, isSymbolicLink: () => flags.symlink, size: flags.size }),
      readFileSync: () => { attemptedRead = true; return JSON.stringify(valid([ID_A])); },
    };
    assert.deepEqual(values(read(directory, fakeFs, path)), []);
    assert.equal(attemptedRead, false);
  }
  for (const throwingMethod of ['lstatSync', 'readFileSync']) {
    const fakeFs = {
      lstatSync: () => ({ isFile: () => true, isSymbolicLink: () => false, size: 10 }),
      readFileSync: () => JSON.stringify(valid([ID_A])),
      [throwingMethod]: () => { throw new Error('synthetic access failure'); },
    };
    assert.deepEqual(values(read(directory, fakeFs, path)), []);
  }
});

test('profile separation and loaded-set stability prevent cross-profile adoption', t => {
  const a = profile(t);
  const b = profile(t);
  write(a, valid([ID_A]));
  write(b, valid([ID_B]));
  const loadedA = read(a);
  assert.deepEqual(values(loadedA), [ID_A]);
  assert.deepEqual(values(read(b)), [ID_B]);
  write(a, valid([ID_B]));
  assert.deepEqual(values(loadedA), [ID_A]);
  assert.deepEqual(values(read(a)), [ID_B]);
});
