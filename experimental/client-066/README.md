# Explicit local routing for the Windows 0.66.0 client

These experimental tools **stage and verify files only**. They never overwrite
an installed application, create an active profile config, restart a process,
send a message, or change a server record. The original client and two exact
source shapes must match **0.66.0**; other versions and ambiguous/already-patched
inputs are refused. Supply your own licensed installation. Do not distribute
generated vendor binaries or extracted application source.

This adapter requires a separately restored host compatibility path for host
build `1494ebd`. It cannot restore a retired host harness by itself. The host
must independently restrict local execution to newly created, explicit test
agents, verify `profile.grokSwitchLocal = {version:1,hostVersion:"1494ebd"}`,
require Box harness and no server identity, and preserve normal Temporal bots.
No existing conversation is automatically migrated.

## Candidate generation

Requires Python 3.10+ and Node.js 20+ on PATH. The implementation uses the Python
standard library. Node runs `--check` to parse the two modified CJS payloads;
it does not load or start the application.

```powershell
python experimental/client-066/stage_client.py --install-dir 'C:\Apps\Grok Bot' --output 'C:\Staging\client-066-candidate'
python experimental/client-066/verify_client.py --install-dir 'C:\Apps\Grok Bot' --staged-dir 'C:\Staging\client-066-candidate'
python experimental/client-066/exercise_client.py --install-dir 'C:\Apps\Grok Bot' --staged-dir 'C:\Staging\client-066-candidate'
```

`--output` must be a new directory outside the installation. Generation validates
every packed ASAR payload and its integrity blocks, preserves entry metadata,
and changes only `dist/electron-main/main-app.cjs` and
`dist/node-agent-coordinator/main.cjs`. The EXE changes only at its single exact
embedded ASAR header hash record; all other bytes, including Electron fuses,
remain identical. This is a consistency check, not verification of vendor
authenticity or preservation of its code signature.

The candidate contains `app.asar`, `Grok Bot.exe`, `manifest.json`, and the exact
source snapshot under `original/resources/app.asar` and `original/Grok Bot.exe`.
It is not a complete standalone installation: unpacked files are preserved as
archive references but are not copied or independently verified.

Verification checks all payloads, metadata, expected transforms, manifest,
exact EXE pairing, and stored original snapshot. Exit 0 means the candidate is
consistent with the supplied source. It does **not** prove live connectivity,
that the host compatibility runtime is installed, or that a UI round trip works.

`exercise_client.py` isolates the actual staged roster store, command mux and
transcript read mux in a Node VM with fake filesystem/transports. It verifies
mixed local/Temporal send, read and event routing without loading application
modules or making network calls. Its test UUIDs are synthetic.

## Explicit opt-in after separate deployment

The patched client reads this exact file in Electron's actual `userData`
directory at coordinator startup:

`grok-switch-local-agents.json`

```json
{
  "version": 1,
  "hostVersion": "1494ebd",
  "agentIds": ["11111111-1111-4111-8111-111111111111"]
}
```

The example ID is fictitious. Use only explicitly reviewed, newly created local
agent UUIDs that the matching host config also permits. No config, invalid JSON,
wrong version/build, extra fields, duplicate IDs, noncanonical UUIDs, oversized
files, symlinks or more than 32 entries yield an empty allowlist and native
routing. The client does not persist or infer ownership from roster rows.

The config is read **once per coordinator launch**. A full client restart is
required after changes. Removing the file and restarting disables the override.
Files remain scoped to the actual Electron profile; do not reuse a profile's
allowlist for another account or host. This schema does not contain account
credentials. The host remains responsible for validating local agent ownership.

Only listed IDs return `box` from the coordinator's harness map. They stay out
of server-required IDs and server tail subscriptions, and their send/read/tail
events use the gateway. All unlisted IDs retain the native route. The patch
does not change renderer roster data, creation preferences, scheduled tasks,
agent identities, or server ownership. The 0.66.0 automation bookkeeping stays
intact; it is not replaced by the 0.57.1 implementation.

## Rollback preparation

Preserve the entire candidate directory until live validation and any rollback
are complete. After a separate deployment, prepare an exact restoration pair:

```powershell
python experimental/client-066/rollback_client.py --install-dir 'C:\Apps\Grok Bot' --staged-dir 'C:\Staging\client-066-candidate' --output 'C:\Staging\client-066-rollback'
```

The tool verifies the original snapshot and candidate, then requires the current
installation to match that exact candidate. It refuses an updated, mixed or
already-original installation. It writes restoration files and their manifest
only to a new external directory. It does not copy them into the installation,
delete the active config, or restart the application. Actual replacement remains
a separate operator action with the client stopped.

## Tests

```powershell
python -m unittest discover -s experimental/client-066 -p test_*.py
node --test experimental/client-066/runtime.test.cjs
```

Synthetic fixtures cover archive integrity, refusal cases, pairing, rollback,
profile/config validation and exact anchors. They do not contain application
source or real agent IDs. See `ATTRIBUTION.md` and `LICENSE.upstream` for the
MIT-licensed ASAR/tool foundation adapted from grok-switch-plus.
