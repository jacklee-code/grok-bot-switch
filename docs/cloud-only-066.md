# Grok Bot 0.66.0: verified cloud-only route for an isolated local Bot

As of 2026-10-05, the cloud adapter has been tested successfully with the **unmodified Windows Grok Bot 0.66.0 client** and cloud host **1494ebd**. A new isolated local Bot handled `/gs status` and completed a real custom-provider conversation after both desktop binaries were restored to their exact original hashes and the desktop routing allowlist was removed from its active location.

This supersedes the earlier assumption that this version combination always requires the Windows routing patch. It establishes a working route for the isolated local Bot. **It does not migrate or reroute existing Temporal Bots.**

## What was actually verified

The following observations were collected during the live desktop test, rather than inferred from the panel's installation indicator:

- `Grok Bot.exe` and `resources/app.asar` matched their pre-patch original SHA-256 checksums before launching the official client.
- The active desktop `grok-switch-local-agents.json` was moved out of the profile before launch. The client-side routing adapter was therefore absent both from the binaries and the active configuration.
- `/gs status` was entered through the official desktop UI. The cloud adapter recorded the matching command admission, the UI displayed the provider status, and the custom-provider request count remained 11.
- A fresh normal message was entered through that UI and its response contained the requested verification marker. The custom-provider log recorded two real `turn` requests with HTTP 200 during that conversation's execution.
- The cloud transcript publisher subsequently reported `publishedThroughSeq: 17` for the local Bot.
- This test did not add a host roster patch, create a server-owned identity for the local Bot, or change the original Temporal Bots.

A second live check removed only the cached last-roster and last-agent selection entries, left authentication untouched, and restarted the same original desktop binaries with no desktop routing manifest. The isolated Bot appeared in the refreshed roster. A newly submitted message then produced the visible response marker `GS-COLD-ROSTER-OK-9364`, confirmed from the screenshot and accessibility state. Its two custom-provider requests returned HTTP 200:

| Request ID | Recorded UTC timestamp |
| --- | --- |
| `93f13473-e6e4-45de-b63d-4ff165563473` | `17:27:33.681Z` |
| `35658081-68c0-4409-97e3-77180650f95e` | `17:27:39.444Z` |

This second check rules out dependence on those two old roster/selection cache entries for the tested exchange. It was **not** a fresh desktop profile, a new account login, a second computer, or an office-machine test. Other ordinary profile data and authentication were preserved.

A subsequent live tool check also used the original desktop UI. The Bot was asked to execute the harmless cloud Shell command `printf GS-STOCK-SHELL-OK-5746`. The native cloud audit recorded turn ID `0370fc18-6597-4a47-b3ab-d60c7066a3a8`, tool `shell_command`, target `box`, exit code `0`, and duration `96 ms`. The native `auto_review` policy recorded `allowed`, and a new desktop screenshot confirmed the resulting response marker `GS-STOCK-SHELL-OK-5746`. The accessibility snapshot was stale for that final reply; the screenshot supplied the visible-result confirmation.

That check establishes this one Shell-tool round trip through the original client and shows that the native review path was retained. It does not validate all tools or every approval outcome. An earlier Shell test from the initial deployment used a patched desktop client and remains separate historical evidence.

The two provider requests are request-level evidence, not a claim that two separate user messages were sent. The publisher checkpoint establishes that the host's publishing path ran; by itself it does not establish whether the desktop displayed the gateway copy or the server-store copy of the response.

## Why the original client can work

The original client still contains both gateway and Temporal routes. Its coordinator maintains each Bot's harness from the roster:

- An explicit `harness: "temporal"` selects the platform's server action for ordinary chat sends.
- An explicit `harness: "box"` selects the cloud computer's gateway.
- A missing harness preserves a previously known harness; when no previous value exists, it defaults to `box`.

The cloud adapter's isolated Bot has a fresh UUID, `harness: "box"`, no `serverId`, and a `grokSwitchLocal` marker. The existing adapter protects that identity from automatic registration and reconciliation. The original host summary normally omits the `box` harness field, but this fresh local ID has no existing Temporal ownership for the original client to preserve. Its normal send can therefore reach the cloud gateway without a desktop patch.

At the gateway, the cloud adapter admits only explicitly allowlisted isolated local Bots. It handles `/gs` commands before prompt wrapping, or runs the existing local model/tool runner against the configured external provider. It does not ask an official Grok model to relay the message to that provider.

### Reply display is a separate decision

The original client's send route and transcript read route are independent. When the global legacy server-transcript source is enabled, the client can send a Box turn to the gateway while reading its transcript from the platform store. In that state, it suppresses gateway transcript events.

The cloud host already contains a native `TranscriptEntryPublisher`. When box-store synchronization is enabled, it uploads local, non-Temporal transcript mutations using `CommitGrokBotTranscriptEntries`. This is an existing route by which Box transcripts can be available to an original client reading from the server store.

During this investigation, the tested desktop's cached feature-gate evaluation had all of the following set to `false`:

- `sand_transcript_server_tail`
- `sand_transcript_store_first`
- `sand_transcript_store_read`

These values were read without changing them, using the bundled Statsig key-hashing implementation. This is evidence about that machine's cached evaluation, not a direct capture of every runtime evaluation or a guarantee of future rollout values. With the legacy server-tail gate disabled, the original coordinator can continue consuming gateway transcript events for a local Bot while still requiring server transcripts for its known Temporal Bots. The observed successful UI exchange is consistent with that route.

Consequently, the live result does **not** prove that all feature-gate combinations, other accounts, future official updates, or a second computer will behave identically. A second-computer check must use its actual original client and confirm both command and ordinary-message replies. Do not force feature flags or alter authentication merely to make the check pass.

## Why existing Temporal Bots are different

An existing Temporal Bot is also present in the platform's authoritative roster. The original client reads that roster directly and restores Temporal routing for those IDs. The cloud host's identity reconciliation also mirrors server ownership into local profiles.

Changing only the cloud profile or emitting a `box` roster hint for an existing Temporal ID is not a verified migration. A later server roster refresh can restore the Temporal route, and transcript generations, histories, scheduled work, groups, and permissions still belong to that server-owned identity. The adapter therefore refuses to claim an existing server-bound Bot.

The original nine Temporal Bots in this deployment remain on their official routes. Their `/gs` text is not handled by the local adapter. They have not been migrated, duplicated into replacement identities, or given new scheduling behavior by this cloud-only verification.

## Scope and quota

Current cloud-adapter support is manual plain-text main-chat turns for explicitly allowlisted new local Bots. `/gs status`, `/gs list`, `/gs help`, and `/gs use <saved-provider>` are local commands. `/gs official` does not convert a local identity into a Temporal identity; use an existing official Bot for official Grok.

The adapter retains the native runner and tool-permission mechanisms. This cloud-only live verification covers the control command, ordinary text conversation including the roster-cache refresh, and the specific harmless Shell-tool round trip described above. Other tools and approval outcomes have not been established by that single Shell check. Attachments, reply threads, forks, task conversations, groups, voice, connectors, subagents, schedules, and cross-device operation require their own validation and are not established by this test. Some unsupported input forms are deliberately rejected by the adapter.

The custom provider performs the local Bot's main inference. This does **not** establish zero official weekly usage, continued operation after official account limits are exhausted, or independence from all platform services. Native safety review, the cloud computer, storage, authentication, telemetry, and other services may still be involved. No weekly-quota before/after measurement was completed as part of this result.

## Deployment and acceptance

1. Keep the desktop installation original. Preserve and verify its exact original binary pair if a previous experimental patch was installed.
2. Install the ordinary Switch inference integration and the version-matched cloud adapter, with backups and exact staging checks as described in [the host adapter guide](../experimental/host-066/README.md).
3. Reserve a fresh UUID in the **cloud** manifest and create the isolated local Bot using the documented native gateway request. Do not add existing Temporal IDs or manually remove their ownership fields.
4. Open that Bot in the original desktop client. Send `/gs status`; verify the matching cloud command record and that no custom-provider inference request was made.
5. Send a fresh harmless message. Verify the visible reply and correlate the corresponding custom-provider `turn` request(s), not panel `test` requests.
6. Repeat after a normal desktop restart and roster refresh. When moving to another computer, repeat these same checks there instead of assuming that the first machine's gate and routing state applies.

A panel showing “patch ready”, a direct gateway request, an external provider probe, a publisher checkpoint, or a routing unit test alone is insufficient to claim end-to-end desktop success.

Keep the optional Windows patch/restore tooling as a fallback for a separately diagnosed client-routing problem. A desktop patch should not be applied merely because the cloud adapter is installed; the original-client route has now been observed working in this version combination.

## Source checks supporting the diagnosis

The investigation evaluated the original 0.66.0 coordinator's actual `YB`, `KD`, and transcript read functions in an isolated Node VM with inert transports. Eight assertions passed with zero network calls. They confirmed that:

- A missing harness preserves previously known Temporal ownership.
- An explicit Box roster selects the gateway for `sendPrompt`.
- A globally active server-tail source suppresses Box gateway transcript events and serves Box transcript reads from the server store.
- A later Temporal roster update restores the Temporal send route.

These tests explain the routing choices. The official-client live exchange above supplies the separate evidence that the isolated local route actually worked on the tested installation.
