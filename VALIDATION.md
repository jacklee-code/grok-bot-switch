# Validation: 0.9.0-alpha.1

Checked on 2026-10-05 with Windows Grok Bot `0.66.0` and Linux host `1494ebd`.
This is evidence for one explicitly configured new local Bot, not compatibility
with all versions or a migration of existing Temporal agents.

## Live checks

- Installed the host and desktop candidates after keeping the exact original
  files, checksums, and scoped configuration backups.
- The desktop displayed the new local test Bot alongside the existing Temporal
  Bots. A message sent from the real desktop received the unique requested echo
  `GS066-UI-OK-7429` in the real desktop transcript. The transcript request ID
  matched an HTTP 200 `kind: "turn"` request to the selected external provider.
- `/gs status` was submitted from the desktop after the raw-input command fix.
  It returned the configured provider and model locally. The upstream request
  count stayed unchanged across this command.
- A second desktop message requested the harmless cloud-shell command
  `printf GS066-SHELL-OK-8153`. The native audit recorded target `box`, exit code
  `0`, and successful shell execution under the native `auto_review` policy.
  The expected output was visible in the desktop transcript.
- The existing nine agents retained their original `harness` and `serverId`
  routing metadata. They were not migrated or added to the local allowlist.

The first exploratory `/gs status` before the raw-input fix reached the model.
That exposed the 0.66 prompt wrapper incompatibility; it was corrected before
the final command verification. Model self-identification is not used as proof
of routing.

## Automated and offline checks

- Root protocol/runtime/CLI suite: **64 passed, 1 skipped** on the Windows
  development machine and Linux host. The skip is the original optional test
  requiring a separately supplied old host fixture.
- Host/client Node compatibility suites: **42 passed**.
- Client archive/config Python tests: **31 passed**.
- The actual staged client routing functions passed **19 checks** in an inert
  VM using fake transports. No app modules or network requests were executed
  by that exercise.
- All **582 packed client ASAR entries** passed integrity checks. Only the two
  intended CJS files changed; the EXE changed only in its exact embedded ASAR
  header integrity record. Electron fuse bytes were preserved.
- The actual host candidate passed `node --check` and exact transformation
  removal back to its original input bytes.
- Panel TypeScript/Vite build and repository whitespace checks passed.

## Limits

Manual text turns, local control commands, native text delivery, and a harmless
shell call have live evidence. Attachments, groups, voice, subagents, connected
services, scheduling, existing-agent migration, cross-device use and other
client/host builds are not validated. Workflow and automation entry points for
the isolated Bot are blocked by the adapter.

`/gs use <saved-provider>` is supported. `/gs official`, `/gs off` and `/gs grok`
return an explanation without changing the global provider: this isolated
local identity cannot be converted into a platform Temporal identity. Existing
official Bots continue on their original routes.

Runtime status intentionally reports scoped capability as `unverified`; static
file/manifest checks cannot certify a current desktop round trip. This dated
record documents the live verification separately. A vendor upgrade requires
new shape checks and live validation.
