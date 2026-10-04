'use strict';
const { createHost066Runtime } = require('./runtime.cjs');
const BEGIN = '// GROK_SWITCH_HOST_066_BEGIN';
const END = '// GROK_SWITCH_HOST_066_END';
const HOST_VERSION = '1494ebd';

function replaceOnce(source, before, after, label) {
  const index = source.indexOf(before);
  if (index < 0 || source.indexOf(before, index + before.length) >= 0) throw new Error('Unsupported host shape: ' + label + ' (expected exactly one anchor)');
  return source.slice(0, index) + after + source.slice(index + before.length);
}
function patches() {
  return [
    ['native superseded turn lifecycle', '          setTurnTraceAttributes(turnTrace, { "sand.outcome": "superseded" });\n          this.tm.runLifecycle.endSessionRun(session);',
      '          setTurnTraceAttributes(turnTrace, { "sand.outcome": "superseded" });\n          grokSwitchHost066.endRun(this.tm, session, options2);'],
    ['native completed turn lifecycle', '        this.tm.runLifecycle.endSessionRun(session);\n        if (this.tm.runLifecycle.persistedSpendRequestIds.get(session.id) === spendRequestId) {',
      '        grokSwitchHost066.endRun(this.tm, session, options2);\n        if (this.tm.runLifecycle.persistedSpendRequestIds.get(session.id) === spendRequestId) {'],
    ['preserve explicit profile marker', 'function writeProfileJson(path33, serialized) {\n  try {',
      'function writeProfileJson(path33, serialized) {\n  serialized = grokSwitchHost066.preserveProfileMarker(path33, serialized);\n  try {'],
    ['gateway', '  return wrapGatewayApiWithServerAgentProxy({\n    api,\n    proxy: deps.extensions.api("server-agent-proxy"),',
      '  grokSwitchHost066.installGateway(api, manager, { nextEntryId, createSendMessageEntry, noConnectors: NO_CONNECTORS });\n  return wrapGatewayApiWithServerAgentProxy({\n    api,\n    proxy: deps.extensions.api("server-agent-proxy"),'],
    ['manual-run-only gate', 'function gateBoxHarnessRuns(runner, args) {\n  const isRefused = () => {\n    if (!args.gate.isBlocked()) return false;',
      'function gateBoxHarnessRuns(runner, args) {\n  const isRefused = () => {\n    if (grokSwitchHost066.isManualRun(args.conversationId, args.currentSource())) return false;\n    if (!args.gate.isBlocked()) return false;'],
    ['identity mint protection', '  async mint(agentId, op, createIntent) {\n    if (this.deletedAgents.has(agentId)) return "no_profile";',
      '  async mint(agentId, op, createIntent) {\n    if (grokSwitchHost066.isIsolated(agentId)) return "already_bound";\n    if (this.deletedAgents.has(agentId)) return "no_profile";'],
    ['identity sync protection', '  async syncDownAgent(root, agent) {\n    if (this.deletedAgents.has(agent.handle)) return false;',
      '  async syncDownAgent(root, agent) {\n    if (grokSwitchHost066.isIsolated(agent.handle)) return false;\n    if (this.deletedAgents.has(agent.handle)) return false;'],
    ['automation sync exclusion', '      (agentId) => isBoxHostedForAutomationSync(args.readHosting(agentId))',
      '      (agentId) => !grokSwitchHost066.isIsolated(agentId) && isBoxHostedForAutomationSync(args.readHosting(agentId))']
  ];
}
function payload() {
  return BEGIN + '\nvar grokSwitchHost066 = (' + createHost066Runtime.toString() + ')({\n' +
    '  fs: require("node:fs"),\n' +
    '  manifestPath: () => (typeof GROK_SWITCH_DIR === "string" ? GROK_SWITCH_DIR : "/workspace/grok-switch") + "/local-agents.json",\n' +
    '  profilePath: (id) => getSandProfilePath(require("node:path").join(getSandAgentsRootDir(), id)),\n' +
    '  randomUUID: () => require("node:crypto").randomUUID(),\n' +
    '  sha256: (value) => require("node:crypto").createHash("sha256").update(value).digest("hex"),\n' +
    '  routeKind: () => grokSwitchResolveRoute().kind,\n' +
    '  commandReply: (text) => grokSwitchCommandReply(text),\n' +
    '  log: (line) => process.stderr.write(line + "\\n")\n' +
    '});\n' + END + '\n';
}
function apply(source, options = {}) {
  if (options.hostVersion !== HOST_VERSION) throw new Error('Only host 1494ebd is supported.');
  if (source.includes(BEGIN) || source.includes('grokSwitchHost066.')) throw new Error('Host compatibility patch is already present or partial.');
  if (!source.includes('(true ? "1494ebd" : null)') || !source.includes('function grokSwitchResolveRoute()')) throw new Error('Expected host 1494ebd with the Grok Switch inference patch installed.');
  // These structural guards prohibit applying the opt-in exception to a
  // different lifecycle or an already modified global gate.
  for (const guard of ['      isBlocked: () => true,', '  async runTurn(session, runner, prompt, options2, epoch) {', '  getRunner(session) {', '  async mintAgentSession(profile, origin, options2) {']) {
    replaceOnce(source, guard, guard, 'guard ' + guard.trim());
  }
  let result = source;
  for (const [label, before, after] of patches()) result = replaceOnce(result, before, after, label);
  result = replaceOnce(result, 'function createHostGatewayApi(deps) {', payload() + 'function createHostGatewayApi(deps) {', 'runtime insertion');
  return result;
}
function remove(source) {
  const start = source.indexOf(BEGIN);
  const stop = source.indexOf(END, start);
  if (start < 0 || stop < 0 || source.indexOf(BEGIN, start + BEGIN.length) >= 0) throw new Error('Expected exactly one complete compatibility patch.');
  let result = source.slice(0, start) + source.slice(stop + END.length + (source[stop + END.length] === '\n' ? 1 : 0));
  for (const [label, before, after] of patches().reverse()) result = replaceOnce(result, after, before, 'restore ' + label);
  return result;
}
module.exports = { apply, remove, HOST_VERSION, BEGIN, END, patches };
