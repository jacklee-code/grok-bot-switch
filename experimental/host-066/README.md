# Host 1494ebd: isolated local text turns

This opt-in adapter restores a manual send entry for **new, explicitly allowlisted local Bots** using the existing host runner, transcript database, turn lifecycle, and tool permission handling. It does not migrate existing Temporal conversations or enable their schedules.

Use it together with the Windows 0.66.0 client adapter. Neither side alone establishes a desktop chat path. The API provider must already be configured in Grok Switch; the adapter refuses ordinary turns while the external provider is inactive. Control commands are handled from the original gateway input before the host adds its prompt wrappers, without starting a model runner.

## Stage a candidate

First stage the fork's ordinary inference patch on a **copy** of the host, using isolated `GROK_SWITCH_HOST`, `GROK_SWITCH_DIR` and `GROK_SWITCH_SUPERVISOR_DIR` paths. Then:

```sh
node experimental/host-066/stage-host.cjs \
  --input /staging/inference-patched-host.cjs \
  --output /staging/compatible-host.cjs \
  --host-version 1494ebd --operation apply
```

The command refuses unsupported versions, missing or ambiguous anchors, existing patches, and existing output paths. It checks syntax and proves exact removal before writing the candidate and SHA256 manifest. It never replaces a running installation, creates a Bot, or requests a restart.

Deployment is a separate operation: preserve the exact current host and Switch bundle, verify the installed source checksum still matches the staged input, install the candidate with the original owner's permissions, and request an idle restart through the native supervisor. Preserve the existing API configuration and stock `.grok-switch.orig` backup.

## New local Bot

Write `<GROK_SWITCH_DIR>/local-agents.json`, normally `/workspace/grok-switch/local-agents.json`:

```json
{"version":1,"hostVersion":"1494ebd","agentIds":["11111111-1111-4111-8111-111111111111"]}
```

Generate a fresh UUID v4 instead of using the illustrative ID. The host permits at most 16 unique IDs. Use the same explicit ID in the desktop profile's `grok-switch-local-agents.json`, and restart the desktop after setting its manifest.

To create the isolated Bot, call the authenticated native gateway `createAgent` method with:

```json
{
  "clientNonce":"11111111-1111-4111-8111-111111111111",
  "harness":"box",
  "creationRoute":{"kind":"box"},
  "name":"Switch local test",
  "description":"A new isolated Bot for custom-provider validation."
}
```

Only this reserved manifest ID and Box creation shape use the adapter. It rejects an existing server identity, creates the native local session, and stores `profile.grokSwitchLocal = {version:1,hostVersion:"1494ebd"}`. Other creation requests use the unmodified gateway. Do not add an existing agent ID or hand-edit its ownership to satisfy these checks.

## Scope and verification

Initial support is manual plain-text main-chat turns. Attachments, reply threads, forks, task chats, workflow/automation imports and runs are refused. Groups, voice, connected services, subagents and cross-device use are not validated. The native runner and its permission/auto-review machinery remain responsible for any tool call.

Verify both `/gs status` and a harmless normal message from the actual desktop UI. A provider probe, patched PID, configured allowlist or direct gateway test alone does not establish the full UI path. Check the resulting provider request log and the visible desktop response. Keep original Temporal agent routing unchanged during validation.

## Disable and restore

Removing the host manifest stops new local execution while the installed adapter keeps marked local Bots excluded from identity backfill and automation sync. The client reads its manifest once per launch, so stop/restart it when changing its configuration.

For complete removal, first stop new input and wait for active turns to finish. Stop the host and move **only the newly created local test Bot directory** to a recoverable backup outside the native `agents` directory before removing the adapter. Otherwise native identity backfill may register the leftover local profile with the server.

Stage adapter removal with the same tool and `--operation remove`, restore the desktop using its exact verified backup pair, then restore the ordinary inference patch if desired. Ordinary Switch `restore` and version-changing updates refuse while this adapter is present, preventing a half-uninstalled host.

## Tests

```sh
node --test experimental/host-066/runtime.test.cjs
```

Tests cover manifest/profile ownership, native runner wiring, idempotent nonce replay, per-turn lifecycle accounting under concurrent admissions, cancellation, early failures, workflow exclusion and marker preservation. They use synthetic dependencies; separately staging a real bundle validates anchors and syntax without executing that bundle.
