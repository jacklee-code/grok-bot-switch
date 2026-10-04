import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import test from "node:test";
import vm from "node:vm";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const cliSource = fs.readFileSync(path.join(root, "src/cli.cjs"), "utf8");
const runtimeSource = fs.readFileSync(path.join(root, "src/runtime.cjs"), "utf8");
const require = createRequire(import.meta.url);
const modernPath = "/opt/sand/sand-host/host-main.cjs";
const legacyPath = "/home/box/sand-host/host-main.cjs";
// Original, synthetic contracts; no vendor bundle or private agent profile is
// distributed in the tests. The retired method deliberately has a factory too.
const legacyHost = `function createHostInference() { return {}; }`;
const retiredHost = `${legacyHost}
var SendPipeline = class {
  async sendPrompt(prompt, options) {
    this.tm.boxHarnessTurnGate.reportBlocked({ conversationId: options.agentId, entry: "send", source: "turn" });
    throw new SandBoxHarnessRetiredError();
  }
};
const boxHarnessTurnGate = { isBlocked: () => true, reportBlocked() {} };
`;
const adapterBlock = "// GROK_SWITCH_HOST_066_BEGIN\n// synthetic experimental adapter\n// GROK_SWITCH_HOST_066_END\n";
const localId = "4b766285-cfcf-4257-9533-60ad68755378";
const secondLocalId = "a8a6e3a3-229a-4d49-863b-dc49abf25ce1";
const localProfile = { harness: "box", grokSwitchLocal: { version: 1, hostVersion: "1494ebd" } };

function configureAdapter(f, ids = [localId]) {
  fs.writeFileSync(path.join(f.dir, "version"), "1494ebd\n");
  fs.writeFileSync(path.join(f.config, "local-agents.json"), JSON.stringify({ version: 1, hostVersion: "1494ebd", agentIds: ids }));
}

function fixture(t, source = legacyHost) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "grok-switch-compat-"));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const host = path.join(dir, "host-main.cjs");
  const agents = path.join(dir, "agents");
  const proc = path.join(dir, "proc");
  const config = path.join(dir, "config");
  fs.writeFileSync(host, source);
  for (const folder of [agents, proc, config]) fs.mkdirSync(folder);
  const env = {
    ...process.env,
    GROK_SWITCH_HOST: host,
    GROK_SWITCH_PROC: proc,
    GROK_SWITCH_AGENTS_ROOT: agents,
    GROK_SWITCH_SUPERVISOR_DIR: path.join(dir, "supervisor"),
    GROK_SWITCH_DIR: config,
  };
  const context = vm.createContext({
    require, module: { exports: {} }, __filename: path.join(root, "src/cli.cjs"),
    process: { ...process, env, stdout: { on() {}, write() {} }, stderr: { write() {} } }, console,
    GROK_SWITCH_DIR: config,
    GROK_SWITCH_CONFIG_PATH: path.join(config, "config.json"),
    GROK_SWITCH_LOG_PATH: path.join(config, "requests.log"),
  });
  vm.runInContext(runtimeSource, context, { filename: "runtime.cjs" });
  vm.runInContext(cliSource, context, { filename: "cli.cjs" });
  function profile(id, value) {
    const folder = path.join(agents, id);
    fs.mkdirSync(folder);
    fs.writeFileSync(path.join(folder, "profile.json"), typeof value === "string" ? value : JSON.stringify(value));
  }
  return { dir, host, agents, proc, config, env, context, profile };
}

function discoveryFs(paths, cmdlines = {}) {
  return {
    statSync(file) { if (!paths.includes(file)) throw new Error("missing"); return { isFile: () => true }; },
    readdirSync() { return Object.keys(cmdlines); },
    readFileSync(file) { return cmdlines[path.basename(path.dirname(file))]; },
  };
}

test("host discovery supports both layouts and explicit missing overrides", (t) => {
  const { context } = fixture(t);
  const detect = context.cliDetectHostPath;
  assert.equal(detect({}, discoveryFs([modernPath])), modernPath);
  assert.equal(detect({}, discoveryFs([legacyPath])), legacyPath);
  assert.equal(detect({}, discoveryFs([modernPath, legacyPath])), modernPath);
  assert.equal(detect({ GROK_SWITCH_HOST: "/chosen/missing.cjs" }, discoveryFs([modernPath])), "/chosen/missing.cjs");
  assert.equal(detect({}, discoveryFs([])), modernPath);
});

test("host discovery chooses the live legacy host over an unused modern install", (t) => {
  const { context } = fixture(t);
  const available = discoveryFs([modernPath, legacyPath], {
    101: `node\0${legacyPath}\0`,
    102: `sh\0-c\0cat ${modernPath}\0`,
  });
  assert.equal(context.cliDetectHostPath({}, available), legacyPath);
});

test("current patched PID cannot hide a retired Box path or Temporal profiles", (t) => {
  const f = fixture(t, retiredHost);
  f.profile("private-agent-id", { name: "Private bot", harness: "temporal", secret: "never-output-this" });
  const patched = retiredHost.replace("function createHostInference(", "// GROK_SWITCH_BEGIN 0.8.5\n// synthetic payload\n// GROK_SWITCH_END\nfunction __grokSwitchOriginalCreateHostInference(");
  fs.writeFileSync(f.host, patched);
  const now = Math.floor(Date.now() / 1000);
  fs.utimesSync(f.host, now - 120, now - 120);
  fs.mkdirSync(path.join(f.proc, "4242"));
  fs.writeFileSync(path.join(f.proc, "stat"), `btime ${now - 3600}\n`);
  fs.writeFileSync(path.join(f.proc, "4242", "cmdline"), `node\0${f.host}\0`);
  const fields = new Array(22).fill("0");
  fields[19] = "359900";
  fs.writeFileSync(path.join(f.proc, "4242", "stat"), `4242 (node) ${fields.join(" ")}`);
  const state = f.context.cliHostState();
  assert.equal(state.patched, true);
  assert.equal(state.runningCurrentBundle, true);
  assert.equal(state.executionCompatibility.status, "blocked");
  assert.equal(state.executionCompatibility.reason, "box-turn-retired");
  assert.equal(state.executionCompatibility.runtimeVerified, false);
  assert.equal(state.executionCompatibility.profiles.temporal, 1);
  const json = JSON.stringify(state);
  for (const privateValue of ["private-agent-id", "Private bot", "never-output-this"]) assert.ok(!json.includes(privateValue));
});

test("retirement evidence is an actual gate or retired send path, not a type name", (t) => {
  const { context } = fixture(t);
  const conditional = `${legacyHost}\nclass SandBoxHarnessRetiredError extends Error {}\nfunction send() { if (serverHosted) throw new SandBoxHarnessRetiredError(); return run(); }`;
  assert.equal(context.cliExecutionCompatibility(conditional, null).boxTurnRetired, false);
  const gateOnly = `${legacyHost}\nconst boxHarnessTurnGate = { isBlocked: () => true, reportBlocked() {} };`;
  assert.equal(context.cliExecutionCompatibility(gateOnly, null).reason, "box-turn-retired");
});

test("all Temporal profiles block routing claims, mixed profiles need per-chat verification", (t) => {
  const f = fixture(t);
  f.profile("one", { harness: "temporal" });
  assert.equal(f.context.cliHostState().executionCompatibility.reason, "temporal-routing");
  f.profile("two", { harness: "box" });
  let compat = f.context.cliHostState().executionCompatibility;
  assert.equal(compat.reason, "mixed-routing");
  assert.equal(compat.status, "unverified");
  assert.equal(compat.profiles.total, 2);
  f.profile("three", "invalid JSON");
  compat = f.context.cliHostState().executionCompatibility;
  assert.equal(compat.profiles.invalid, 1);
  assert.equal(compat.runtimeVerified, false);
});

test("missing and unfamiliar profiles or hosts never become verified compatible", (t) => {
  const f = fixture(t);
  let compat = f.context.cliHostState().executionCompatibility;
  assert.equal(compat.reason, "box-route-unverified");
  assert.equal(compat.runtimeVerified, false);
  f.profile("unknown", { harness: "future-harness" });
  f.profile("bad", "[");
  f.profile("temporal", { harness: "temporal" });
  compat = f.context.cliHostState().executionCompatibility;
  assert.equal(compat.reason, "mixed-routing");
  assert.equal(compat.profiles.unknown, 1);
  assert.equal(f.context.cliExecutionCompatibility("function unrelated() {}", null).inferenceFactoryPresent, false);
  fs.unlinkSync(f.host);
  assert.equal(f.context.cliHostState().executionCompatibility.reason, "host-missing");
});

test("profile discovery uses the host data root while exposing no host environment secrets", (t) => {
  const f = fixture(t);
  const dataRoot = path.join(f.dir, "actual-host-data");
  fs.mkdirSync(path.join(dataRoot, "agents", "private"), { recursive: true });
  fs.writeFileSync(path.join(dataRoot, "agents", "private", "profile.json"), '{"harness":"temporal"}');
  fs.mkdirSync(path.join(f.proc, "42"));
  fs.writeFileSync(path.join(f.proc, "42", "environ"), `SAND_DATA_ROOT=${dataRoot}\0UNRELATED_TOKEN=private-token\0`);
  delete f.env.GROK_SWITCH_AGENTS_ROOT;
  const state = f.context.cliAgentProfilesState({ pid: 42 });
  assert.equal(state.root, path.join(dataRoot, "agents"));
  assert.equal(state.temporal, 1);
  assert.ok(!JSON.stringify(state).includes("private-token"));
  f.env.GROK_SWITCH_AGENTS_ROOT = f.agents;
  assert.equal(f.context.cliAgentProfilesState({ pid: 42 }).root, f.agents);
});

test("CLI status JSON and text report incompatibility without mutating host or configuration", (t) => {
  const f = fixture(t, retiredHost);
  f.profile("one", { harness: "temporal" });
  const configPath = path.join(f.config, "config.json");
  const config = JSON.stringify({ active: null, providers: {} });
  fs.writeFileSync(configPath, config);
  // Exercise this turn's CLI source without overwriting the shared dist build.
  const script = path.join(f.dir, "status-cli.cjs");
  fs.writeFileSync(script, runtimeSource + "\n" + cliSource);
  const json = spawnSync(process.execPath, [script, "status", "--json"], { env: f.env, encoding: "utf8" });
  assert.equal(json.status, 0, json.stderr);
  const result = JSON.parse(json.stdout);
  assert.equal(result.executionCompatibility.reason, "box-turn-retired");
  assert.deepEqual(result.executionCompatibility, result.host.executionCompatibility);
  const plain = spawnSync(process.execPath, [script, "status"], { env: f.env, encoding: "utf8" });
  assert.equal(plain.status, 0, plain.stderr);
  assert.match(plain.stdout, /chat route\s+: box-turn-retired \(blocked\)/);
  assert.match(plain.stdout, /successful provider tests do not connect Temporal chats/);
  assert.equal(fs.readFileSync(f.host, "utf8"), retiredHost);
  assert.equal(fs.readFileSync(configPath, "utf8"), config);
  assert.equal(fs.existsSync(f.env.GROK_SWITCH_SUPERVISOR_DIR), false);
});

test("complete adapter and explicit local profile report only scoped unverified capability", (t) => {
  const f = fixture(t, retiredHost + adapterBlock);
  configureAdapter(f);
  f.profile(localId, localProfile);
  f.profile("existing-private-temporal-agent", { harness: "temporal", name: "private bot" });
  const compat = f.context.cliHostState().executionCompatibility;
  assert.equal(compat.reason, "scoped-local-adapter");
  assert.equal(compat.status, "unverified");
  assert.equal(compat.runtimeVerified, false);
  assert.equal(compat.boxTurnRetired, true);
  assert.equal(compat.profiles.temporal, 1);
  assert.equal(compat.adapter.manifestValid, true);
  assert.equal(compat.adapter.configuredAgents, 1);
  assert.equal(compat.adapter.eligibleAgents, 1);
  assert.match(compat.message, /Existing Temporal chats are unchanged/);
  assert.ok(!JSON.stringify(compat).includes(localId));
});

test("adapter marker alone, empty scope, mismatched host and malformed manifests retain blocked status", (t) => {
  const f = fixture(t, retiredHost + adapterBlock);
  f.profile(localId, localProfile);
  assert.equal(f.context.cliHostState().executionCompatibility.status, "blocked");
  configureAdapter(f, []);
  assert.equal(f.context.cliHostState().executionCompatibility.status, "blocked");
  configureAdapter(f);
  const manifestPath = path.join(f.config, "local-agents.json");
  for (const bad of [
    { version: 2, hostVersion: "1494ebd", agentIds: [localId] },
    { version: 1, hostVersion: "future-host", agentIds: [localId] },
    { version: 1, hostVersion: "1494ebd", agentIds: [localId, localId] },
    { version: 1, hostVersion: "1494ebd", agentIds: ["../../elsewhere"] },
    { version: 1, hostVersion: "1494ebd", agentIds: ["4b766285-cfcf-1257-9533-60ad68755378"] },
    { version: 1, hostVersion: "1494ebd", agentIds: Array.from({ length: 17 }, (_, n) => `${n.toString(16).padStart(8, "0")}-cfcf-4257-9533-60ad68755378`) },
    [], null,
  ]) {
    fs.writeFileSync(manifestPath, JSON.stringify(bad));
    const compat = f.context.cliHostState().executionCompatibility;
    assert.equal(compat.status, "blocked");
    assert.equal(compat.adapter.manifestValid, false);
  }
  configureAdapter(f);
  fs.writeFileSync(path.join(f.dir, "version"), "different-host");
  assert.equal(f.context.cliHostState().executionCompatibility.status, "blocked");
  fs.writeFileSync(path.join(f.dir, "version"), "1494ebd");
  for (const block of ["// GROK_SWITCH_HOST_066_BEGIN\n", "// GROK_SWITCH_HOST_066_END\n", adapterBlock + adapterBlock]) {
    fs.writeFileSync(f.host, retiredHost + block);
    assert.equal(f.context.cliHostState().executionCompatibility.status, "blocked");
  }
});

test("server-bound, Temporal and mismarked agents cannot gain local adapter eligibility", (t) => {
  const f = fixture(t, retiredHost + adapterBlock);
  configureAdapter(f);
  f.profile(localId, localProfile);
  const profilePath = path.join(f.agents, localId, "profile.json");
  for (const invalid of [
    { ...localProfile, harness: "temporal" },
    { ...localProfile, serverId: "private-server" },
    { harness: "box" },
    { harness: "box", grokSwitchLocal: { version: 2, hostVersion: "1494ebd" } },
    { harness: "box", grokSwitchLocal: { version: 1, hostVersion: "different-host" } },
  ]) {
    fs.writeFileSync(profilePath, JSON.stringify(invalid));
    const compat = f.context.cliHostState().executionCompatibility;
    assert.equal(compat.reason, "box-turn-retired");
    assert.equal(compat.adapter.eligibleAgents, 0);
    assert.equal(compat.adapter.ineligibleAgents, 1);
  }
  configureAdapter(f, [localId, secondLocalId]);
  f.profile(secondLocalId, localProfile);
  const mixed = f.context.cliHostState().executionCompatibility;
  assert.equal(mixed.reason, "scoped-local-adapter");
  assert.equal(mixed.adapter.configuredAgents, 2);
  assert.equal(mixed.adapter.eligibleAgents, 1);
  assert.equal(mixed.adapter.ineligibleAgents, 1);
});

test("restore refuses complete or partial host adapters without changing bundle or backup", (t) => {
  const f = fixture(t);
  const backup = f.host + ".grok-switch.orig";
  const configPath = path.join(f.config, "config.json");
  const config = JSON.stringify({ active: "test-provider", providers: { "test-provider": { model: "test", apiKey: "private-value" } } });
  fs.writeFileSync(configPath, config);
  fs.writeFileSync(backup, "original backup");
  for (const markers of [adapterBlock, "// GROK_SWITCH_HOST_066_BEGIN\n", "// GROK_SWITCH_HOST_066_END\n", adapterBlock + adapterBlock]) {
    const original = retiredHost + markers;
    fs.writeFileSync(f.host, original);
    assert.throws(() => f.context.cliUnpatch(), /Remove the adapter using experimental\/host-066 transform\.remove before running restore/);
    assert.throws(() => f.context.cliCommandRestore(), /Remove the adapter using experimental\/host-066 transform\.remove before running restore/);
    assert.equal(fs.readFileSync(f.host, "utf8"), original);
    assert.equal(fs.readFileSync(backup, "utf8"), "original backup");
    assert.equal(fs.readFileSync(configPath, "utf8"), config);
    assert.equal(fs.existsSync(f.env.GROK_SWITCH_SUPERVISOR_DIR), false);
  }
});

test("ordinary patch updates refuse an adapter while unchanged versions remain untouched", (t) => {
  const f = fixture(t);
  const backup = f.host + ".grok-switch.orig";
  fs.writeFileSync(backup, "original backup");
  const base = retiredHost.replace("function createHostInference(", "// GROK_SWITCH_BEGIN 0.8.5\n// synthetic payload\n// GROK_SWITCH_END\nfunction __grokSwitchOriginalCreateHostInference(");
  fs.writeFileSync(f.host, base + adapterBlock);
  f.context.CLI_VERSION = "0.8.5";
  assert.equal(f.context.cliEnsurePatched(), "unchanged");
  f.context.CLI_VERSION = "next-version";
  assert.throws(() => f.context.cliEnsurePatched(), /Remove the adapter.*before updating the inference patch/);
  assert.equal(fs.readFileSync(f.host, "utf8"), base + adapterBlock);
  for (const markers of ["// GROK_SWITCH_HOST_066_BEGIN\n", "// GROK_SWITCH_HOST_066_END\n", adapterBlock + adapterBlock]) {
    fs.writeFileSync(f.host, base + markers);
    f.context.CLI_VERSION = "0.8.5";
    assert.throws(() => f.context.cliEnsurePatched(), /incomplete or duplicate experimental host-066 adapter markers/);
    assert.equal(fs.readFileSync(f.host, "utf8"), base + markers);
  }
  assert.equal(fs.readFileSync(backup, "utf8"), "original backup");
});
