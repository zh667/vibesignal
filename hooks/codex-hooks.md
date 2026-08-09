# Wiring Codex Into the Signal Light

The signal light is agent-agnostic. Every state event carries an `--agent` tag, so
Codex drives the same light as Claude Code by calling:

```bash
vibesignal event --agent codex --state working --quiet
vibesignal event --agent codex --state blocked --quiet
```

`needs_input` is still accepted as an alias for `blocked`, so a v1 wrapper keeps
working.

## Quick Setup

One command wires everything, with the Codex-correct events and the absolute
path pinned (so a minimal hook `PATH` cannot break it):

```bash
vibesignal install-hooks --agent codex
```

It merges the per-turn hooks into `~/.codex/hooks.json`, preserving any hooks you
already have. It first detects Codex CLI and selects either the full five-Hook
mode or a four-Hook compatibility mode. Then trust the generated commands once
via `/hooks` in Codex CLI and restart Codex Desktop. The rest of this document
explains the mapping that command applies.

Codex CLI `0.147.0` is VibeSignal's currently verified `SessionEnd` baseline;
`0.142.3` is the verified floor for reviewing the four base Hooks. If the CLI is
missing or older than the full baseline, the command asks before installing the
exact tested release with `npm install -g @openai/codex@0.147.0`. Existing newer
versions are kept. Versions below `0.142.3` or unparseable versions do not get a
Hook configuration because the review path is unverified. `--yes` may be used
only after an outer installer has collected explicit consent; Hook review and
trust always remain manual.

The intended mapping mirrors the Claude Code side:

| Codex situation | State |
|-----------------|-------|
| A turn starts, Codex is working | `working` |
| Codex needs approval or input | `blocked` |
| A turn finishes and waits on you | `done` |

## Where to Hook In

Codex exposes a `notify` program in `~/.codex/config.toml`, and newer versions add
a hooks system. The `notify` program is called with a JSON argument when events
such as "turn complete" or "approval required" occur. Point it at a small wrapper
that maps the event to a `vibesignal` call.

Exact event names and the JSON shape vary by Codex version, so confirm them against
the Codex docs for your installed version (`codex --version`) before relying on the
mapping. The command form above is stable; only the event source differs.

A minimal wrapper (pseudocode, adjust the event keys to your Codex version):

```python
# codex-notify.py  (set as the notify program in ~/.codex/config.toml)
import json, subprocess, sys

event = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
kind = event.get("type", "")

state = "working"
if kind == "approval-requested":
    state = "blocked"
elif kind == "agent-turn-complete":
    state = "done"

subprocess.run([
    "vibesignal", "event", "--agent", "codex",
    "--state", state, "--session", event.get("session_id", "codex"),
])
```

## Per-Turn States via the Hooks System

Codex exposes a hooks system that fires on the same per-turn events Claude Code
uses, configured through `~/.codex/hooks.json`.
Map `UserPromptSubmit` and `PostToolUse` to `working`, `PermissionRequest` to
`blocked`, and `Stop` to `done` for the same live states as the Claude side. Trust the
hooks once via `/hooks` in a Codex session. Use `--quiet` for Codex hooks: some hook
types parse stdout as JSON, so normal human-readable status text causes an invalid
hook output error.

The tracked snippet is [`codex-hooks.snippet.json`](codex-hooks.snippet.json). Merge it
into `~/.codex/hooks.json`. If `vibesignal` is not on the hook shell's `PATH`, replace
the command prefix with an absolute interpreter form such as
`C:/Users/<you>/miniforge3/envs/py312/python.exe -m vibesignal`.

Keep [`codex-notify.py`](codex-notify.py) as a completion-only fallback for older Codex
builds or for environments where the hooks system is disabled.

## SessionEnd

VibeSignal has verified `SessionEnd` review with Codex CLI `0.147.0`. Full mode
wires it to `vibesignal end --agent codex --quiet`, so a closed session clears at
once. Verified CLI versions from `0.142.3` through `0.146.x` use compatibility
mode and omit this event; those sessions age out by their per-state lifetime
instead -- `done` through the 90-second fade, `working` after the 10-minute TTL,
and `blocked` or `error` at the 8-hour backstop.

This keeps the Claude Code and Codex paths on one light and one state store, which
satisfies the cross-agent requirement: the function works under role reversal or
when only one agent is present.
