# Codex Hook Capability Detection Design

## Goal

Make `vibesignal install-hooks --agent codex` safe for Codex Desktop-only users by detecting the installed Codex CLI, offering an explicit installation or upgrade to a known-good version, and selecting a compatible Hook set.

## Version Policy

- `0.147.0` is the minimum version VibeSignal has verified can display and trust `SessionEnd` in `/hooks`.
- `0.142.3` is the oldest version VibeSignal has verified can display and trust the four base Hooks.
- `0.147.0` is a verified baseline, not a claim about OpenAI's official minimum version.
- A missing or older CLI may be installed or upgraded only after explicit consent.
- An existing CLI at or above the baseline is retained. VibeSignal never downgrades it.
- A CLI below `0.142.3` or with an unparseable version is treated as lacking a verified review path, so no Hooks are written.

## Installation Flow

For Codex, the installer runs `codex --version` before changing `~/.codex/hooks.json`.

| Detected state | Action | Result |
| --- | --- | --- |
| CLI missing | Ask to install `@openai/codex@0.147.0` with npm | Consent enables full mode; refusal leaves Codex integration disabled |
| CLI below `0.142.3` | Ask to upgrade to `@openai/codex@0.147.0` | Consent enables full mode; refusal leaves Codex integration disabled |
| CLI from `0.142.3` through `0.146.x` | Ask to upgrade to `@openai/codex@0.147.0` | Consent enables full mode; refusal installs compatibility mode |
| CLI at or above `0.147.0` | Keep the installed CLI | Full mode |
| Version unknown | Do not modify the global CLI | Codex integration remains disabled |

Full mode installs `UserPromptSubmit`, `PostToolUse`, `PermissionRequest`, `Stop`, and `SessionEnd`. Compatibility mode omits `SessionEnd`; `Stop` and the existing state TTL provide cleanup.

The `--yes` option records explicit command-line consent for the npm install or upgrade. It does not trust Hooks for the user. After writing the configuration, VibeSignal tells the user to run Codex CLI, open `/hooks`, review the new commands, and trust them manually.

## Failure Handling

- If npm is unavailable for a missing CLI, no Codex Hooks are written and the command exits unsuccessfully with an actionable message.
- If an upgrade fails, VibeSignal detects the CLI again. It installs compatibility mode only if a CLI at or above `0.142.3` still works; otherwise no Hooks are written.
- If `codex --version` fails or cannot be parsed, VibeSignal does not mutate the global CLI and writes no Hooks.
- Existing non-VibeSignal Hooks remain untouched in both modes.

## Testing

Unit tests cover missing, old, supported, newer, and unparseable CLI versions; consent and refusal; exact npm package selection; install failures; full and compatibility Hook output; stale `SessionEnd` removal when converging to compatibility mode; and no downgrade of newer CLIs.
