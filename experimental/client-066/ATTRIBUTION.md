The ASAR parsing/repacking implementation in `asar.py` and the foundation of
`stage_client.py` / `verify_client.py` were adapted from
[grok-switch-plus](https://github.com/yuwenjie058-boop/grok-switch-plus),
`experimental/client-routing`, version `0.1.0-alpha.4`.

That project is based on enderzcx/grok-bot-switch and distributes those files
under the MIT license. Its supplied copyright and full permission notice are
retained in `LICENSE.upstream` (Copyright (c) 2026 enderzcx).

The 0.66.0 exact-anchor adapter, explicit allowlist runtime, tests, and rollback
staging added here are local modifications under this repository's MIT license.
Vendor application source, EXEs, ASAR archives, and user agent identifiers are
not included. Candidates must be built from the operator's own installation.
