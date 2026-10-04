'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { createHost066Runtime } = require('./runtime.cjs');
const transform = require('./transform.cjs');
const id = '11111111-1111-4111-8111-111111111111';
const other = '8cb39ff3-9dcd-482d-9b5c-ac5471d110b0';

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'gs-host066-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const manifestPath = () => path.join(root, 'local-agents.json');
  const profilePath = agent => path.join(root, agent + '.json');
  const writeManifest = value => fs.writeFileSync(manifestPath(), JSON.stringify(value));
  const writeProfile = value => fs.writeFileSync(profilePath(id), JSON.stringify(value));
  writeManifest({ version: 1, hostVersion: '1494ebd', agentIds: [id] });
  writeProfile({ name: 'Test', harness: 'box', grokSwitchLocal: { version: 1, hostVersion: '1494ebd' } });
  let route = 'external';
  const commands = [];
  const runtime = createHost066Runtime({ fs, manifestPath, profilePath, randomUUID: crypto.randomUUID,
    sha256: x => crypto.createHash('sha256').update(x).digest('hex'), routeKind: () => route,
    commandReply: text => { commands.push(text); return 'Active: **test-provider**'; } });
  const entries = [], records = new Map(), queue = [], observed = [], settlements = [], cancellations = [];
  const session = { id, db: { getTranscriptEntries: () => entries, getLastTurnSettlement: () => settlements.at(-1) } };
  const counts = new Map();
  const manager = {
    execution: { canExecute: true, isLocalWorkAllowed: true },
    sessions: { activeSession: session, ensureActionTarget: async () => {}, ensureLoaded: async () => {} },
    groupChat: { isGroupSession: () => false },
    runnerRegistry: { getRunner: () => ({ native: true }) },
    appendEntry: entry => { entries.push(entry); return { outcome: 'inserted' }; },
    sendPipeline: { nextTurnEpoch: () => entries.length },
    acceptanceLedger: {
      lookup: x => records.has(x.clientNonce) ? { outcome: 'found', record: records.get(x.clientNonce) } : { outcome: 'not-found' },
      admitSend(x) { const r = records.get(x.clientNonce); if (r && r.inputDigest !== x.inputDigest) throw Error('digest mismatch'); return { kind: r ? 'duplicate' : 'dispatch' }; },
      recordPending: x => records.set(x.clientNonce, { ...x, status: 'pending' }),
      markAccepted: x => { records.get(x.clientNonce).status = 'accepted'; },
      markRejected: x => { records.get(x.clientNonce).status = 'rejected'; }
    },
    runLifecycle: {
      inFlightRunCounts: counts,
      beginSessionRun: s => counts.set(s, (counts.get(s) ?? 0) + 1),
      endSessionRun: s => counts.set(s, (counts.get(s) ?? 0) - 1),
      enqueueExclusiveRun: (_id, fn, options) => { queue.push(fn); cancellations.push(options.onCancelled); return Promise.resolve(); }
    },
    turnRuntime: {
      async runTurn(s, runner, prompt, options, epoch) {
        observed.push({ s, runner, prompt, options, epoch, manual: runtime.isManualRun(id, 'turn'), automation: runtime.isManualRun(id, 'automation') });
        runtime.endRun(manager, s, options);
      }, settleClientTurn(s, clientNonce, outcome) { settlements.push({ clientNonce, outcome }); }
    }
  };
  const api = { sendPrompt: async x => ({ delegated: x.agentId }), createAgent: async () => ({ delegated: true }), promptAcceptanceStatus: async () => ({ delegated: true }), createAgentAutomation: async () => ({ delegated: true }) };
  for (const key of ['importAgentWorkflowText', 'importAgentWorkflowUrl', 'runAgentWorkflowNow']) api[key] = async () => ({ delegated: true });
  runtime.installGateway(api, manager, { nextEntryId: list => 'u-' + (list.length + 1), noConnectors: { mode: 'none' }, createSendMessageEntry: (entryId, message, timestampMs) => ({ kind: 'send-message', id: entryId, message, timestampMs }) });
  return { root, profilePath, writeManifest, writeProfile, runtime, manager, api, entries, records, queue, observed, counts, session, settlements, cancellations, commands, setRoute: x => route = x };
}

test('requires exact opt-in policy, local marker and no server identity', t => {
  const f = fixture(t);
  assert.equal(f.runtime.isLocal(id), true);
  assert.equal(f.runtime.isLocal(other), false);
  f.writeProfile({ harness: 'box', serverId: 'server-owned', grokSwitchLocal: { version: 1, hostVersion: '1494ebd' } });
  assert.equal(f.runtime.isLocal(id), false);
  assert.throws(() => f.api.sendPrompt({ agentId: id, prompt: 'hello' }), /ownership/);
  f.writeManifest({ version: 1, hostVersion: 'other', agentIds: [id] });
  assert.equal(f.runtime.declared(id), false);
});
test('ordinary agents delegate without interception', async t => {
  const f = fixture(t);
  assert.deepEqual(await f.api.sendPrompt({ agentId: other, prompt: 'hello' }), { delegated: other });
  assert.deepEqual(await f.api.createAgentAutomation({ id: other }), { delegated: true });
  assert.equal(f.entries.length, 0);
});
test('native runner, persisted echo, admission and lifecycle are connected', async t => {
  const f = fixture(t);
  assert.deepEqual(await f.api.sendPrompt({ agentId: id, prompt: 'hello', clientNonce: 'n1' }), { accepted: true });
  assert.equal(f.entries[0].clientNonce, 'n1');
  assert.equal(f.records.get('n1').status, 'accepted');
  assert.equal(f.runtime.isManualRun(id, 'turn'), false);
  await f.queue[0]();
  assert.equal(f.observed[0].manual, true);
  assert.equal(f.observed[0].automation, false);
  assert.equal(f.observed[0].runner.native, true);
  assert.equal(f.observed[0].options.messageId, f.entries[0].id);
  assert.equal(Object.keys(f.observed[0].options).includes('__grokSwitchHost066Lease'), false);
  assert.equal(f.runtime.isManualRun(id, 'turn'), false);
  assert.equal(f.counts.get(f.session), 0);
  assert.equal((await f.api.promptAcceptanceStatus({ agentId: id, clientNonce: 'n1', accountSlot: 'desktop' })).record.status, 'accepted');
});
test('nonce replay is idempotent and changed text cannot reuse the nonce', async t => {
  const f = fixture(t), args = { agentId: id, prompt: 'same', clientNonce: 'n1' };
  await Promise.all([f.api.sendPrompt(args), f.api.sendPrompt(args)]);
  assert.equal(f.entries.length, 1);
  assert.equal(f.queue.length, 1);
  await assert.rejects(f.api.sendPrompt({ ...args, prompt: 'different' }), /digest mismatch/);
});
test('unsupported rich operations and automations fail before model work', async t => {
  const f = fixture(t);
  for (const extra of [{ attachmentPaths: ['/tmp/a'] }, { replyToId: 'u1' }, { isFork: true }, { taskId: 'task' }, { sessionId: 'different' }, { initiator: 'automation' }]) {
    await assert.rejects(f.api.sendPrompt({ agentId: id, prompt: 'hello', ...extra }), /plain-text/);
  }
  assert.throws(() => f.api.createAgentAutomation({ id }), /disabled/);
  for (const key of ['importAgentWorkflowText', 'importAgentWorkflowUrl', 'runAgentWorkflowNow']) assert.throws(() => f.api[key]({ id }), /disabled/);
  assert.equal(f.entries.length, 0);
});
test('ownership revoked between admission and run cannot invoke a model', async t => {
  const f = fixture(t);
  await f.api.sendPrompt({ agentId: id, prompt: 'hello' });
  f.writeManifest({ version: 1, hostVersion: '1494ebd', agentIds: [] });
  await assert.rejects(f.queue[0](), /ownership/);
  assert.equal(f.observed.length, 0);
  assert.equal(f.counts.get(f.session), 0);
  assert.equal(f.settlements.at(-1).outcome, 'error');
});
test('one native run ending cannot decrement a later admitted turn', async t => {
  const f = fixture(t);
  let release;
  const paused = new Promise(resolve => { release = resolve; });
  f.manager.turnRuntime.runTurn = async (s, runner, prompt, options) => { await paused; f.runtime.endRun(f.manager, s, options); };
  await f.api.sendPrompt({ agentId: id, prompt: 'first', clientNonce: 'n1' });
  const running = f.queue[0]();
  await f.api.sendPrompt({ agentId: id, prompt: 'second', clientNonce: 'n2' });
  assert.equal(f.counts.get(f.session), 2);
  release(); await running;
  assert.equal(f.counts.get(f.session), 1);
  await f.queue[1]();
  assert.equal(f.counts.get(f.session), 0);
});
test('queue cancellation settles even when enqueue resolves normally', async t => {
  const f = fixture(t);
  f.manager.runLifecycle.enqueueExclusiveRun = async (_id, _fn, options) => { options.onCancelled(); };
  await f.api.sendPrompt({ agentId: id, prompt: 'hello', clientNonce: 'n1' });
  assert.equal(f.settlements.at(-1).outcome, 'cancelled');
  assert.equal(f.counts.get(f.session), 0);
});
test('native setup exceptions settle and balance the per-turn lease once', async t => {
  const f = fixture(t);
  f.manager.turnRuntime.runTurn = async () => { throw new Error('setup failure'); };
  await f.api.sendPrompt({ agentId: id, prompt: 'hello', clientNonce: 'n1' });
  await assert.rejects(f.queue[0](), /setup failure/);
  assert.equal(f.counts.get(f.session), 0);
  assert.deepEqual(f.settlements, [{ clientNonce: 'n1', outcome: 'error' }]);
});
test('external route is mandatory except local slash commands', async t => {
  const f = fixture(t); f.setRoute('official');
  await assert.rejects(f.api.sendPrompt({ agentId: id, prompt: 'hello' }), /external/);
  await f.api.sendPrompt({ agentId: id, prompt: '/gs status' });
  assert.equal(f.queue.length, 0);
  assert.equal(f.entries[1].message.content, 'Active: **test-provider**');
  assert.equal(f.settlements.at(-1).outcome, 'success');
});
test('raw slash commands bypass runner and native wrapped prompt, with nonce deduplication', async t => {
  const f = fixture(t);
  f.manager.runnerRegistry.getRunner = () => { throw new Error('must not build a runner'); };
  const args = { agentId: id, prompt: '/grok-switch STATUS', clientNonce: 'n1' };
  await f.api.sendPrompt(args);
  await f.api.sendPrompt(args);
  assert.equal(f.entries.length, 2);
  assert.deepEqual(f.commands, [args.prompt]);
  assert.equal(f.queue.length, 0);
  assert.equal(f.counts.size, 0);
});
test('official aliases stay local without changing global provider configuration', async t => {
  const f = fixture(t);
  for (const prompt of ['/gs official', '/gs off', '/gs grok']) await f.api.sendPrompt({ agentId: id, prompt });
  assert.equal(f.commands.length, 0);
  assert.equal(f.queue.length, 0);
  assert.equal(f.entries.length, 6);
  assert.match(f.entries[1].message.content, /existing official Bots/);
});
test('saved-provider selection and unknown command help are handled locally with nonce deduplication', async t => {
  const f = fixture(t);
  f.manager.runnerRegistry.getRunner = () => { throw new Error('must not build a runner'); };
  const selection = { agentId: id, prompt: '/gs use another', clientNonce: 'selection1' };
  await f.api.sendPrompt(selection);
  await f.api.sendPrompt(selection);
  await f.api.sendPrompt({ agentId: id, prompt: '/gs made-up', clientNonce: 'help1' });
  assert.deepEqual(f.commands, ['/gs use another', '/gs made-up']);
  assert.equal(f.entries.length, 4);
  assert.equal(f.queue.length, 0);
  assert.equal(f.counts.size, 0);
  assert.match(f.entries[3].message.content, /Compatibility note/);
});
test('marker survives native profile edits but rebinding is refused', t => {
  const f = fixture(t);
  const p = JSON.parse(f.runtime.preserveProfileMarker(f.profilePath(id), JSON.stringify({ name: 'renamed', harness: 'box' })));
  assert.equal(p.grokSwitchLocal.hostVersion, '1494ebd');
  assert.throws(() => f.runtime.preserveProfileMarker(f.profilePath(id), JSON.stringify({ harness: 'temporal', serverId: 'server' })), /rebind/);
});
test('removing the opt-in manifest disables execution but preserves identity isolation', t => {
  const f = fixture(t);
  f.writeManifest({ version: 1, hostVersion: '1494ebd', agentIds: [] });
  assert.equal(f.runtime.isLocal(id), false);
  assert.equal(f.runtime.isIsolated(id), true);
  assert.equal(f.runtime.isManualRun(id, 'turn'), false);
  assert.throws(() => f.api.createAgentAutomation({ id }), /disabled/);
  const p = JSON.parse(f.runtime.preserveProfileMarker(f.profilePath(id), JSON.stringify({ name: 'renamed', harness: 'box' })));
  assert.equal(p.grokSwitchLocal.hostVersion, '1494ebd');
});
test('transform is fail-closed and fully reversible against exact anchors', () => {
  const fixtureSource = ['(true ? "1494ebd" : null)', 'function grokSwitchResolveRoute()', '      isBlocked: () => true,', '  async runTurn(session, runner, prompt, options2, epoch) {', '  getRunner(session) {', '  async mintAgentSession(profile, origin, options2) {', 'function createHostGatewayApi(deps) {', ...transform.patches().map(p => p[1])].join('\n');
  const modified = transform.apply(fixtureSource, { hostVersion: '1494ebd' });
  assert.equal(transform.remove(modified), fixtureSource);
  assert.throws(() => transform.apply(modified, { hostVersion: '1494ebd' }), /already/);
  assert.throws(() => transform.apply(fixtureSource, { hostVersion: 'other' }), /1494ebd/);
  assert.throws(() => transform.apply(fixtureSource.replace('isBlocked: () => true', 'isBlocked: () => false'), { hostVersion: '1494ebd' }), /shape/);
  assert.throws(() => transform.apply(fixtureSource + '\nfunction createHostGatewayApi(deps) {', { hostVersion: '1494ebd' }), /shape/);
});
