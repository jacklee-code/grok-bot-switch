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

## Follow-up: original desktop and cloud-only route, 2026-10-05

The alpha.1 evidence above is retained as a historical record of the original
deployment, which used both desktop and cloud patches. The follow-up below
**supersedes the assumption that a desktop patch is necessary** for the tested
Windows `0.66.0` / Linux host `1494ebd` combination. It does not invalidate the
earlier observations or extend them to unrelated Bots and computers.

- Both desktop binaries were restored to their exact pre-patch SHA-256 hashes,
  and `grok-switch-local-agents.json` was moved out of its active profile
  location. The cloud adapter remained installed.
- `/gs status` submitted through the original desktop produced the matching
  cloud command admission and a visible status reply without increasing the
  external provider's request count.
- A fresh ordinary message through that original desktop received a visible
  verification response, with corresponding external-provider `turn` requests
  returning HTTP 200.
- The test was repeated after moving only the cached `roster.last-roster` and
  `selection.last-agent` entries aside, then restarting the original desktop.
  The isolated Bot appeared in the refreshed roster and a newly submitted
  message produced the visible marker **`GS-COLD-ROSTER-OK-9364`**, confirmed in
  the screenshot and accessibility state. Both associated provider requests
  returned HTTP 200.
- Authentication and other profile data were preserved. This cache-refresh
  test was **not** a clean profile, a new login, another computer, or an office
  installation. It establishes independence from those two old cache entries
  for the tested exchange, not independence from all client state.
- The original nine Temporal Bots retained their official routes. No existing
  Bot, history, server identity or schedule was migrated. The original-client
  checks cover the control command and ordinary text. A further stock-client
  test executed `printf GS-STOCK-SHELL-OK-5746` through the native cloud Shell:
  target `box`, exit `0`, 96 ms, with native policy `auto_review` allowed. The
  new response marker was visible in the desktop screenshot. This establishes
  that specific Shell round trip; the earlier Shell test remains separate
  patched-desktop evidence, and other tools or approval outcomes are untested.

The detailed routing analysis, request evidence, cached feature-gate values,
and second-computer acceptance steps are in
[docs/cloud-only-066.md](docs/cloud-only-066.md). Prefer this original-desktop
route. The optional desktop patch and profile manifest are only needed when
choosing that fallback for a separately diagnosed client-routing problem.

No before/after official weekly-quota measurement was made. External main
inference is confirmed for the isolated Bot, but zero official usage, operation
after quota exhaustion, all feature-gate combinations, and office-machine
operation are not established.

### Desktop patch/restore fallback: development evidence

The new [desktop tool](desktop-patcher/README.md) supplies a Traditional Chinese
GUI and CLI for inspection, scoped patching, exact restoration, and importing
a verified alpha.1 staging snapshot. It includes installation/profile discovery,
strict Scope parsing, one elevation attempt when needed, preservation of the
original profile, and managed backup verification.

The Windows development run passed **44 tests** in
`desktop-patcher/tests`, including transaction/restore refusal cases and
entry-point checks for elevation retry, restart intent, and profile selection.
A hidden Tk construction check and temporary-directory CLI inspection check
also completed without changing the installed application. These are source
and fixture checks, not a claim about the final portable executable.

The final Windows portable EXE was built with Python 3.12.6, PyInstaller 6.20.0
and bundled Node.js 24.15.0. Its SHA-256 is
`7ac108b93db4a0fb4d32d04c927baead66772bbc5d7e7afe5577815e9094b666`.
Four packaged CLI checks completed successfully against this exact artifact:

- Inspect the actual stock installation: `original`, version `0.66.0`.
- Dry-run a patch against that installation and profile using a synthetic
  scope: no application writes, no state directory, no stopped processes.
- Patch a separate copy of the actual stock EXE/ASAR with an empty fixture
  profile: `ours` with the exact requested synthetic scope.
- Restore that fixture: `original`; both original file hashes and the
  previously absent scope were restored exactly.

A fifth packaged check supplied an actual temporary NTFS junction to the CLI
dry-run entry point. It was refused with `unsafe_path`; target files remained
unchanged and neither the state directory nor profile scope was created.
Windows CI had exposed short/long filename identity differences in the first
candidate. Version 0.1.1 canonicalizes identities while retaining the selected
mutation paths for reparse checks. Real 8.3 aliases and a short-name temporary
root were used to reproduce that environment; the source tests include the
PowerShell identity check and CLI junction refusal.

The real installation's hashes, sizes, timestamps, scope and running process
IDs remained unchanged throughout those packaged checks. The final GUI was
also launched and visually inspected: it discovered the actual installation
and profile, reported the official original state, and displayed the
cloud-first guidance and fallback Patch/Restore controls without clipping.
Actual mutation was tested through the CLI on the isolated copy; no live UAC
or office-machine operation is claimed. See the
[build instructions](desktop-patcher/README.md) and
[`build.ps1`](desktop-patcher/build.ps1).
