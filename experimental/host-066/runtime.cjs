'use strict';

// This factory is also embedded verbatim in the supported host bundle. Keep all
// dependencies explicit: no host imports, account credentials or model defaults.
function createHost066Runtime(deps) {
  const version = '1494ebd';
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  const manualTurns = new Set();
  const admissions = new Map();
  const creations = new Map();
  function policy() {
    try {
      const value = JSON.parse(deps.fs.readFileSync(deps.manifestPath(), 'utf8'));
      if (value.version !== 1 || value.hostVersion !== version || !Array.isArray(value.agentIds) ||
          value.agentIds.length > 16 || value.agentIds.some(id => typeof id !== 'string' || !uuid.test(id)) ||
          new Set(value.agentIds).size !== value.agentIds.length) return null;
      return value;
    } catch (_) { return null; }
  }
  function declared(id) { return typeof id === 'string' && uuid.test(id) && !!policy()?.agentIds.includes(id); }
  function profile(id) {
    if (!uuid.test(String(id))) return null;
    try { return JSON.parse(deps.fs.readFileSync(deps.profilePath(id), 'utf8')); } catch (_) { return null; }
  }
  function markedProfile(p) {
    return !!p && p.harness === 'box' && p.serverId == null &&
      p.grokSwitchLocal?.version === 1 && p.grokSwitchLocal?.hostVersion === version;
  }
  // The marker only reserves the isolated identity against background migration.
  // Positive execution permission additionally requires the current manifest.
  function isIsolated(id) { return markedProfile(profile(id)); }
  function isLocal(id) { return declared(id) && isIsolated(id); }
  function requireLocal(id) {
    if (!isLocal(id)) throw new Error('Grok Switch local compatibility refused: missing allowlist, marker, or local ownership.');
  }
  function isManualRun(id, source) { return source === 'turn' && manualTurns.has(id) && isLocal(id); }
  function endRun(manager, session, options) {
    const lease = options?.__grokSwitchHost066Lease;
    if (lease?.session === session) lease.end();
    else manager.runLifecycle.endSessionRun(session);
  }
  function preserveProfileMarker(path, serialized) {
    let current;
    try { current = JSON.parse(deps.fs.readFileSync(path, 'utf8')); } catch (_) { return serialized; }
    if (!markedProfile(current)) return serialized;
    const next = JSON.parse(serialized);
    if (next.serverId != null || next.harness !== 'box') throw new Error('Refusing to rebind an isolated local Bot.');
    next.grokSwitchLocal = { version: 1, hostVersion: version };
    return JSON.stringify(next, null, 2) + '\n';
  }
  function log(message) { deps.log?.('[grok-switch:host-066] ' + message); }
  function commandOf(text) {
    const match = /^\s*\/(?:gs|grok-switch)(?:\s+|$)([\s\S]*)$/i.exec(text);
    if (!match) return null;
    const action = (match[1].trim().split(/\s+/)[0] || 'help').toLowerCase();
    return { action, blockedOfficial: ['official', 'off', 'grok'].includes(action) };
  }
  function localCreationRequested(args) {
    return declared(args.clientNonce) && args.harness === 'box' && args.creationRoute?.kind === 'box';
  }
  function markProfile(id) {
    const path = deps.profilePath(id);
    const p = JSON.parse(deps.fs.readFileSync(path, 'utf8'));
    if (p.serverId != null || (p.harness != null && p.harness !== 'box')) throw new Error('Refusing to claim a server-owned Bot.');
    p.harness = 'box';
    p.grokSwitchLocal = { version: 1, hostVersion: version };
    const temporary = path + '.grok-switch-local.tmp';
    deps.fs.writeFileSync(temporary, JSON.stringify(p, null, 2) + '\n', { mode: 0o600 });
    deps.fs.renameSync(temporary, path);
  }
  function installGateway(api, manager, helpers) {
    const originalCreate = api.createAgent;
    const originalSend = api.sendPrompt;
    const originalStatus = api.promptAcceptanceStatus;
    api.createAgent = function(args) {
      if (!localCreationRequested(args)) return originalCreate(args);
      const id = args.clientNonce;
      if (creations.has(id)) return creations.get(id);
      const operation = (async () => {
        if (deps.fs.existsSync(deps.profilePath(id))) {
          requireLocal(id);
          const transcript = await manager.switchAgent(id);
          const agent = (await manager.listAgents()).find(item => item.id === id);
          if (!agent) throw new Error('The existing local Bot is missing from the roster.');
          return { agent, transcript };
        }
        if (args.templateId != null || args.purpose != null || args.isAutomatic === true) throw new Error('Local compatibility only creates a plain, manual test Bot.');
        const result = await manager.createAgent({ name: args.name, description: args.description ?? '' }, 'user', {
          agentId: id, harness: 'box', isIntroductionSuppressed: true,
          configureAgentDir: () => markProfile(id)
        });
        requireLocal(id);
        log('created isolated local Bot ' + id);
        return result;
      })();
      creations.set(id, operation);
      operation.catch(() => creations.delete(id));
      return operation;
    };
    api.promptAcceptanceStatus = function(args) {
      if (!isLocal(args.agentId)) return originalStatus(args);
      return manager.acceptanceLedger.lookup({ accountSlot: 'host', clientNonce: args.clientNonce });
    };
    api.sendPrompt = function(args) {
      if (declared(args.agentId)) requireLocal(args.agentId);
      if (!isLocal(args.agentId)) return originalSend(args);
      const id = args.agentId;
      const operation = (admissions.get(id) ?? Promise.resolve()).catch(() => {}).then(() => admit(args));
      admissions.set(id, operation);
      operation.finally(() => { if (admissions.get(id) === operation) admissions.delete(id); }).catch(() => {});
      return operation;
    };
    async function admit(args) {
      const id = args.agentId;
      requireLocal(id);
      if (typeof args.prompt !== 'string' || args.prompt.trim().length === 0) throw new Error('A nonempty text message is required.');
      const command = commandOf(args.prompt);
      if ((args.attachmentPaths?.length ?? 0) > 0 || (args.attachmentNames?.length ?? 0) > 0 || args.replyToId != null ||
          args.isFork === true || (args.sessionId != null && args.sessionId !== '') || args.taskId != null ||
          args.automationWriteProvenance != null || (args.initiator != null && args.initiator !== 'user')) {
        throw new Error('Host 0.66 compatibility currently supports manual plain-text main-chat turns only.');
      }
      if (manager.disposed || (!command && (!manager.execution.canExecute || !manager.execution.isLocalWorkAllowed))) throw new Error('The host is not ready for a local turn.');
      if (!command && deps.routeKind() !== 'external') throw new Error('Select an external Grok Switch provider before using this local Bot.');
      const nonce = typeof args.clientNonce === 'string' && args.clientNonce.length > 0 ? args.clientNonce : deps.randomUUID();
      const digest = deps.sha256(JSON.stringify({ agentId: id, prompt: args.prompt, richText: args.richText ?? '', machineId: args.machineId ?? '' }));
      const identity = { accountSlot: 'host', clientNonce: nonce, inputDigest: digest, agentId: id };
      const admission = manager.acceptanceLedger.admitSend(identity);
      if (admission.kind === 'duplicate') return { accepted: true };
      await manager.sessions.ensureActionTarget(id);
      await manager.sessions.ensureLoaded();
      requireLocal(id);
      const session = manager.sessions.activeSession;
      if (!session || session.id !== id || manager.groupChat.isGroupSession(session)) throw new Error('The local Bot session could not be opened.');
      const entry = {
        kind: 'message', id: helpers.nextEntryId(session.db.getTranscriptEntries(), 'user-message'), role: 'user',
        content: args.prompt, isStreaming: false, timestampMs: Date.now(), clientNonce: nonce,
        ...(args.richText == null ? {} : { richText: args.richText })
      };
      manager.acceptanceLedger.recordPending({ ...identity, echoEntryId: entry.id });
      const appended = manager.appendEntry(entry);
      if (appended?.outcome !== 'inserted') {
        manager.acceptanceLedger.markRejected({ ...identity, rejectionCode: 'local-transcript-write-failed' });
        throw new Error('The message could not be saved locally; no model request was sent.');
      }
      if (command) {
        let reply;
        if (command.blockedOfficial) {
          reply = 'This isolated local Bot supports `/gs status`, `/gs list`, `/gs help`, and `/gs use <saved-provider>`. For official Grok, open one of your existing official Bots. This local identity cannot migrate into the official Temporal service or use the retired official BOX harness; the global provider configuration was not changed.';
        } else {
          try { reply = deps.commandReply(args.prompt); }
          catch (error) { reply = 'grok-switch: command failed: ' + String(error?.message ?? error); }
          if (!['status', 'list', 'ls', 'use'].includes(command.action)) reply += '\n\nCompatibility note: `/gs official` is unavailable for this isolated local Bot. Open an existing official Bot instead; it does not change this Bot\'s identity.';
        }
        const replyEntry = helpers.createSendMessageEntry(helpers.nextEntryId(session.db.getTranscriptEntries(), 'send-message'), { type: 'text', content: reply }, Date.now());
        if (manager.appendEntry(replyEntry)?.outcome !== 'inserted') {
          manager.acceptanceLedger.markRejected({ ...identity, rejectionCode: 'local-command-reply-write-failed' });
          manager.turnRuntime.settleClientTurn(session, nonce, 'error');
          throw new Error('The local command reply could not be saved; no model request was sent.');
        }
        manager.acceptanceLedger.markAccepted(identity);
        manager.turnRuntime.settleClientTurn(session, nonce, 'success');
        await manager.roster?.emitAgentUpdate(id);
        log('handled local command ' + command.action + ' for ' + id + ' nonce=' + nonce);
        return { accepted: true };
      }
      let runner;
      try { runner = manager.runnerRegistry.getRunner(session); }
      catch (error) {
        manager.acceptanceLedger.markRejected({ ...identity, rejectionCode: 'local-runner-setup-failed' });
        manager.turnRuntime.settleClientTurn(session, nonce, 'error');
        throw error;
      }
      const epoch = manager.sendPipeline.nextTurnEpoch(session);
      const options = {
        selectedImages: [], selectedVideos: [], attachedFilePaths: [], connectorScope: helpers.noConnectors,
        clientNonce: nonce, messageId: entry.id, richText: args.richText, senderMachineId: args.machineId,
        recentUserMessages: [{ id: entry.id, text: args.prompt }], queueStartEpochMs: Date.now(), queueStartPerfMs: performance.now()
      };
      manager.runLifecycle.beginSessionRun(session, { initiationMessageId: entry.id, initiatedAtMs: entry.timestampMs });
      let ended = false;
      const lease = {
        session,
        end() { if (!ended) { ended = true; manager.runLifecycle.endSessionRun(session); } },
        settle(outcome) {
          if (session.db.getLastTurnSettlement?.()?.clientNonce !== nonce) manager.turnRuntime.settleClientTurn(session, nonce, outcome);
        }
      };
      Object.defineProperty(options, '__grokSwitchHost066Lease', { value: lease });
      let queued;
      try { queued = manager.runLifecycle.enqueueExclusiveRun(id, async () => {
        try {
          requireLocal(id);
          if (deps.routeKind() !== 'external') throw new Error('The external provider changed before the local turn started.');
          manualTurns.add(id);
          await manager.turnRuntime.runTurn(session, runner, args.prompt, options, epoch);
        } catch (error) {
          lease.settle('error');
          throw error;
        } finally {
          manualTurns.delete(id);
          // The two native runTurn end sites also call this per-turn lease.
          // A later admission therefore cannot cause a second decrement.
          lease.end();
        }
      }, { lane: 'user', source: 'turn', onCancelled: () => { lease.settle('cancelled'); lease.end(); } }); }
      catch (error) {
        lease.settle('error'); lease.end();
        manager.acceptanceLedger.markRejected({ ...identity, rejectionCode: 'local-queue-failed' });
        throw error;
      }
      Promise.resolve(queued).catch(error => {
        log('turn failed for ' + id + ': ' + String(error?.message ?? error));
        lease.settle('error'); lease.end();
      });
      manager.acceptanceLedger.markAccepted(identity);
      log('accepted local turn for ' + id + ' nonce=' + nonce);
      return { accepted: true };
    }
    const noAutomation = ['createAgentAutomation', 'updateAgentAutomation', 'runAgentAutomationNow', 'setAgentAutomationEnabled', 'createAgentWorkflow', 'updateAgentWorkflow', 'importAgentWorkflowText', 'importAgentWorkflowUrl', 'runAgentWorkflowNow'];
    for (const name of noAutomation) {
      if (typeof api[name] !== 'function') continue;
      const original = api[name];
      api[name] = function(args) {
        if (isIsolated(args.id ?? args.agentId)) throw new Error('Automations and workflows are disabled for the isolated compatibility Bot.');
        return original(args);
      };
    }
    return api;
  }
  return { policy, declared, profile, isLocal, isIsolated, isManualRun, endRun, preserveProfileMarker, installGateway };
}

module.exports = { createHost066Runtime };
