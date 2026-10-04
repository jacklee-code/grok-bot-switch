# Grok Bot 0.66 compatibility work

This is an experimental fork of [enderzcx/grok-bot-switch](https://github.com/enderzcx/grok-bot-switch), based on commit `2005450dc9980bc32ced742a46a1dbe3ed99bc38` (MIT). It is not an official Grok/xAI release.

## Why the original patch is insufficient

Grok Bot desktop 0.66.0 can route conversations to the platform Temporal harness. Those turns do not enter the Linux Box's `createHostInference` factory patched by Switch 0.8.5. Host build `1494ebd` additionally retires the old Box send entry and blocks Box runners. A successful API probe or a patched file therefore does not prove that a conversation uses the configured provider.

This fork detects that situation and reports it in both `status --json` and the panel. It automatically discovers the current `/opt/sand/sand-host/host-main.cjs` layout while respecting an explicit `GROK_SWITCH_HOST` override.

## Experimental route

The separate `experimental/host-066` and `experimental/client-066` tools stage compatibility candidates for an **explicitly configured, newly created local Bot**. They preserve the native routing of all other agents. They do not convert existing Temporal agents, copy their history, or enable their scheduled tasks.

The host adapter requires both an allowlist and a local profile marker. It uses the existing host runner and tool/permission handling for manual text turns. The desktop adapter sends and reads only those IDs through the Box gateway, keeping their transcript events separate from the platform stream.

The initial scope is manual plain-text main-chat turns. Attachments, existing-agent migration, groups, voice, scheduled tasks, subagent execution and cross-device use are not claimed as supported. These tools reject unknown host/client versions and unmatched code shapes. Neither tool distributes vendor application binaries.

## Version constraints

| Component | Required version |
| --- | --- |
| Windows Grok Bot | `0.66.0`, exact matching coordinator/bootstrap structure |
| Linux host | `1494ebd`, exact matching lifecycle structure |
| Fork bundle | `0.9.0-alpha.1` |

Local staging, source-shape verification and synthetic tests are separate from an actual desktop send/reply test. See the individual tool READMEs and the checked-in validation notes for the evidence available for a particular build. Do not treat a generated candidate as a successful deployment.

## Configuration

On the host, the opt-in manifest is `<GROK_SWITCH_DIR>/local-agents.json`, normally `/workspace/grok-switch/local-agents.json`. On Windows it is `grok-switch-local-agents.json` in the application's exact Electron `userData` profile. Both use:

```json
{
  "version": 1,
  "hostVersion": "1494ebd",
  "agentIds": ["11111111-1111-4111-8111-111111111111"]
}
```

The ID above is an example. Generate a fresh UUID v4; never add an existing Temporal Bot as a shortcut. The host creation adapter creates the matching local profile marker. Missing or invalid configuration never activates a broad routing override.

## Restore and updates

Keep the staged source backups and manifests outside the vendor installation. Stop the desktop before replacing its ASAR/EXE pair; verify the installed pair still matches the candidate before restoring. The desktop restore tool checks both files rather than overwriting an unrelated update.

Remove the host compatibility transform before running the ordinary Switch `restore` or updating its inference payload. The CLI refuses an ordinary restore/update while a host compatibility transform is present, preventing a half-uninstalled host. A vendor update requires fresh version/shape verification and another real chat test.

## Development

```sh
npm test
node --test experimental/host-066/*.test.cjs
node --test experimental/client-066/*.test.cjs
python -m unittest discover -s experimental/client-066 -p 'test_*.py'
```

Run the panel build separately with `npm ci && npm run build` in `panel/`, then run the root build to embed it. The host tests retain Linux credential-file permission checks; those POSIX bits are not asserted on Windows.

The ASAR staging helpers retain the attribution and MIT license from the Grok Switch Plus project in `experimental/client-066/ATTRIBUTION.md` and `LICENSE.upstream`.
