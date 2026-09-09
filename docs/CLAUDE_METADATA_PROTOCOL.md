# Claude metadata compatibility evidence

This is a static inspection record for the v0.4.1 change, made on 2026-09-09. It covers locally installed official **Windows x64** VS Code extension packages, not a live account, a Mac binary, or a guarantee about future releases. No Claude process, inference request, private transcript, or credential file was used for this inspection. No provider binaries are distributed here.

Separately, the updated adapter successfully retrieved quota from the installed Windows Claude 2.1.266 client while the policy version mismatch remained active. That observation does not establish Mac account/Keychain behavior or future compatibility.

## Inspected artifacts

Paths below are relative to each `anthropic.claude-code-<version>-win32-x64` extension directory. The package manifests identify publisher `Anthropic` and the matching version. Offsets are zero-based byte positions in the embedded readable source of `resources/native-binary/claude.exe`.

| Version | Native file bytes | SHA-256 |
| --- | ---: | --- |
| 2.1.263 | 218746016 | `0b35df94c1307004f07b738390bfef8dfca5e9af29aaf6517f305bf086b95b03` |
| 2.1.266 | 218971808 | `d2c5f7b3b6a12819097ceb6efbce2a390157166003fcaee32dbde0e6d7b45ef7` |

| Inspected path | 2.1.263 offset | 2.1.266 offset | Finding |
| --- | ---: | ---: | --- |
| `skip_behaviors` request schema | 183260691 | 184586633 | Both describe skipping the recent-transcript scan for callers that need plan rate limits. |
| `get_usage` dispatch | 203810405 | 204313689 | An explicit true value disables behavioral collection in both versions. |
| Usage response builder | 197087304 | 197894134 | Both obtain plan utilization and return session counters, rate limits, and a null behaviors value when collection is disabled. |
| Initialization response builder | 203872805 | 204376496 | Both return control metadata including account source fields. Version 2.1.266 adds workspace-trust handling; the app does not send that option. |
| Safe-mode option definition | 195060157 | 196534244 | The option and its customization-disabling intent remain present. Authentication and managed policy remain applicable. |

The extension's own experimental usage wrapper is also present in both `extension.js` files (request offsets 2290149 and 2293164). The interface explicitly identifies itself as experimental. This record supports attempting the existing control exchange with 2.1.266; it does not establish a stable API contract.

## Compatibility boundary

The app requires an identified stable version at least 2.1.263, without an upper version pin. It sends exactly the fixed initialization and usage controls, with transcript analysis disabled, and never sends a prompt. Every read validates the response envelope and quota schema. Unexpected message types, behavioral analysis data, malformed or incomplete quota windows, output overflow, and timeouts fail without an AI fallback. Only global five-hour and weekly utilization/reset data and a salted pseudonymous scope may leave the adapter.

Checking for words in a binary would not prove their runtime meaning and would depend on packaging and bytecode layout. The app therefore does not scan binaries or start an extra help/capability process on each poll. A successful future-version exchange establishes only that the observed response meets the supported contract; it cannot prove every startup behavior is unchanged.

Safe mode is not a general isolation boundary. The [official CLI reference](https://code.claude.com/docs/en/cli-reference) documents that authentication and administrator-managed settings, including managed hooks, can still apply. The app uses the installed client's authentication and does not bypass those settings. This limitation also existed with the exact 2.1.263 pin.

Policy retirement is separate: a changed client still invalidates old additional instructions even when quota metadata remains compatible. No AI review is required to restore compatible quota reads.

Fixture regression checks should cover old/unparseable versions rejected before launch, identical controls for newer versions, no usage request after failed initialization, malformed/unexpected responses, cleanup, cache migration, and successful quota reads while old policy remains disabled. Fixture results and static inspection do not establish Mac account/Keychain behavior or completed release-package validation.
