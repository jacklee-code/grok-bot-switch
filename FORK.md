# Grok Bot 0.66 compatibility work

This is an experimental fork of [enderzcx/grok-bot-switch](https://github.com/enderzcx/grok-bot-switch), based on commit `2005450dc9980bc32ced742a46a1dbe3ed99bc38` (MIT). It is not an official Grok/xAI release.

## Why the original patch is insufficient

Grok Bot desktop 0.66.0 can route conversations to the platform Temporal harness. Those turns do not enter the Linux Box's `createHostInference` factory patched by Switch 0.8.5. Host build `1494ebd` additionally retires the old Box send entry and blocks Box runners. A successful API probe or a patched file therefore does not prove that a conversation uses the configured provider.

This fork detects that situation and reports it in both `status --json` and the panel. It automatically discovers the current `/opt/sand/sand-host/host-main.cjs` layout while respecting an explicit `GROK_SWITCH_HOST` override.

## Recommended route: original desktop with the cloud adapter

The `experimental/host-066` adapter enables an **explicitly configured, newly created local Bot**. On 2026-10-05, real command and text-message exchanges succeeded with the **unmodified Windows 0.66.0 desktop**, after restoring both desktop binaries to their original hashes and removing the active desktop routing manifest. A second successful exchange after restarting with only the cached last-roster and last-agent selection entries moved aside produced `GS-COLD-ROSTER-OK-9364`.

This supersedes the earlier assumption that this version combination always needs both desktop and cloud patches. The second test retained authentication and other profile data: it was not a clean profile, a fresh login, or a test on another computer. See [the cloud-only route and its evidence](docs/cloud-only-066.md) for the routing and feature-gate limits.

The host adapter requires a cloud allowlist and a local Bot profile marker. It uses the existing host runner and tool/permission handling for manual text turns. The optional `experimental/client-066` adapter and [Windows patch/restore application](desktop-patcher/README.md) remain compatibility fallbacks for a separately diagnosed desktop-routing problem. Do not apply a desktop patch merely because the cloud adapter is installed.

Both approaches preserve the native routing of all other agents. The original nine Temporal Bots remain on their official routes; they are not converted, their history is not copied, and their scheduled tasks are not migrated. Their `/gs` text does not enter the isolated Bot's command handler.

The initial scope is manual plain-text main-chat turns. Attachments, existing-agent migration, groups, voice, scheduled tasks, subagent execution and cross-device use are not claimed as supported. The original-client test does not establish operation on an office computer or all feature-gate combinations. The earlier Shell-tool exchange used the patched desktop and remains separate evidence. These tools reject unknown host/client versions and unmatched code shapes. Neither tool distributes vendor application binaries.

Custom-provider main inference does not establish zero official weekly usage or continued operation after official limits are exhausted. Native review, authentication, storage, the cloud computer and other platform services can still participate. A weekly-quota before/after measurement has not been completed.

## Version constraints

| Component | Required version |
| --- | --- |
| Windows Grok Bot | `0.66.0`; original client verified on the tested installation, exact source matching required for the optional patch |
| Linux host | `1494ebd`, exact matching lifecycle structure |
| Fork bundle | `0.9.0-alpha.1` |

Local staging, source-shape verification and synthetic tests are separate from an actual desktop send/reply test. See the individual tool READMEs and the checked-in validation notes for the evidence available for a particular build. Do not treat a generated candidate as a successful deployment.

## Configuration

On the host, the required opt-in manifest is `<GROK_SWITCH_DIR>/local-agents.json`, normally `/workspace/grok-switch/local-agents.json`. The original desktop does **not** need a local routing manifest. Only when using the optional desktop patch, place the same IDs in `grok-switch-local-agents.json` in that application's exact Electron `userData` profile. The manifest format is:

```json
{
  "version": 1,
  "hostVersion": "1494ebd",
  "agentIds": ["11111111-1111-4111-8111-111111111111"]
}
```

The ID above is an example. Generate a fresh UUID v4; never add an existing Temporal Bot as a shortcut. The host creation adapter creates the matching local profile marker. Missing or invalid configuration never activates a broad routing override.

## Restore and updates

Keep the staged source backups and manifests outside the vendor installation. If a desktop patch was previously installed, restore its exact original ASAR/EXE pair before testing the cloud-only route. The [Windows patch/restore tool](desktop-patcher/README.md) can inspect the installation and import a verified legacy staging snapshot. It checks both files before restoring rather than overwriting an unrelated update. An already-original desktop needs no binary changes.

Remove the host compatibility transform before running the ordinary Switch `restore` or updating its inference payload. The CLI refuses an ordinary restore/update while a host compatibility transform is present, preventing a half-uninstalled host. A vendor update requires fresh version/shape verification and another real chat test.

## Development

```sh
npm test
node --test experimental/host-066/*.test.cjs
node --test experimental/client-066/*.test.cjs
python -m unittest discover -s experimental/client-066 -p 'test_*.py'
python -m unittest discover -s desktop-patcher/tests -p 'test_*.py'
```

See [the desktop tool's build instructions](desktop-patcher/README.md) and [`desktop-patcher/build.ps1`](desktop-patcher/build.ps1) for the portable Windows executable. Development tests and source-level GUI checks do not establish that a particular packaged EXE was validated; the final portable-build verification is recorded separately in [VALIDATION.md](VALIDATION.md).

Run the panel build separately with `npm ci && npm run build` in `panel/`, then run the root build to embed it. The host tests retain Linux credential-file permission checks; those POSIX bits are not asserted on Windows.

The ASAR staging helpers retain the attribution and MIT license from the Grok Switch Plus project in `experimental/client-066/ATTRIBUTION.md` and `LICENSE.upstream`.
