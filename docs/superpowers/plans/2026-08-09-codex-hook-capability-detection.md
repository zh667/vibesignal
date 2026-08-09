# Codex Hook Capability Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect Codex CLI Hook capability and safely install either the full five-Hook configuration or the four-Hook compatibility configuration.

**Architecture:** Keep version detection and npm execution in `vibesignal/installer.py` as testable subprocess helpers. Keep consent and user-facing mode selection in `vibesignal/__main__.py`, then pass an explicit `include_session_end` flag into the existing convergent Hook merger.

**Tech Stack:** Python 3.11 standard library, argparse, subprocess, pytest

## Global Constraints

- The verified `SessionEnd` baseline is exactly `0.147.0`.
- The verified four-Hook review baseline is exactly `0.142.3`.
- Never silently install, upgrade, or downgrade the user's global Codex CLI.
- Never automate Hook trust or modify Codex's trust database.
- Preserve all foreign Hook handlers and existing command compatibility.

---

### Task 1: Codex CLI Detection And Exact Installation

**Files:**
- Modify: `vibesignal/installer.py`
- Test: `tests/test_installer.py`

**Interfaces:**
- Produces: `CodexCliInfo(path, version, raw_version)`, `detect_codex_cli()`, `codex_supports_session_end(info)`, and `install_recommended_codex_cli()`.
- `install_recommended_codex_cli()` invokes `npm install -g @openai/codex@0.147.0`, then detects and validates the result.

- [ ] **Step 1: Write failing detection tests**

Add tests that mock `shutil.which` and `subprocess.run`, asserting missing CLI, `codex-cli 0.142.3`, `codex-cli 0.147.0`, a newer version, and unparseable output are classified correctly.

- [ ] **Step 2: Run the detection tests and verify RED**

Run: `python -m pytest tests/test_installer.py -k "codex_cli or session_end_support" -v`

Expected: failures because the constants, data object, and helper functions do not exist.

- [ ] **Step 3: Implement detection and exact installation**

Use a compiled semantic-version regular expression, immutable version tuples, bounded subprocess timeouts, and a dedicated `CodexCliInstallError`. Resolve `codex` and `npm` with `shutil.which`; never use a shell command string.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest tests/test_installer.py -k "codex_cli or session_end_support" -v`

Expected: all selected tests pass.

### Task 2: Full And Compatibility Hook Specs

**Files:**
- Modify: `vibesignal/installer.py`
- Test: `tests/test_installer.py`

**Interfaces:**
- Changes: `agent_hooks_spec(args, agent, include_session_end=True)` and `install_hooks(agent="claude", include_session_end=True)`.
- Compatibility mode passes `include_session_end=False` for Codex only.

- [ ] **Step 1: Write failing compatibility tests**

Assert a Codex spec with `include_session_end=False` has exactly the four base events, and reinstalling compatibility mode removes a stale VibeSignal `SessionEnd` while preserving foreign handlers.

- [ ] **Step 2: Run the compatibility tests and verify RED**

Run: `python -m pytest tests/test_installer.py -k "compatibility or without_session_end" -v`

Expected: failure because the public functions do not accept the new flag.

- [ ] **Step 3: Thread the flag through the existing merger**

Build the current Codex dictionary, conditionally add `SessionEnd`, and leave Claude's six-event spec unchanged. Reuse `_merge_hooks` so changing modes remains idempotent and convergent.

- [ ] **Step 4: Run the compatibility tests and verify GREEN**

Run: `python -m pytest tests/test_installer.py -k "compatibility or without_session_end" -v`

Expected: all selected tests pass.

### Task 3: Consent-Driven CLI Workflow

**Files:**
- Modify: `vibesignal/__main__.py`
- Modify: `README.md`
- Test: `tests/test_main.py`

**Interfaces:**
- Adds: `install-hooks --yes` for explicit CLI install or upgrade consent.
- Changes: `cmd_install_hooks(args)` returns nonzero when a verified review path is unavailable; CLI versions from `0.142.3` through `0.146.x` may use compatibility mode when upgrade is declined or unavailable.

- [ ] **Step 1: Write failing command workflow tests**

Cover missing CLI refusal, missing CLI consent, old CLI refusal, old CLI consent, supported and newer CLIs, unknown versions, and failed npm installation. Assert both return codes and the `include_session_end` argument passed to `install_hooks`.

- [ ] **Step 2: Run the command tests and verify RED**

Run: `python -m pytest tests/test_main.py -k "install_hooks_codex" -v`

Expected: failures because the CLI does not inspect Codex versions or accept `--yes`.

- [ ] **Step 3: Implement consent, degradation, and messages**

Add an EOF-safe yes/no prompt, route Codex through the detector, and print the selected `full`, `compatibility`, or `not enabled` state. Always direct the user to review `/hooks` manually after a configuration is written.

- [ ] **Step 4: Document the behavior**

Update the Codex configuration section with the verified baseline, the exact npm package, compatibility behavior, `--yes`, and the manual trust boundary.

- [ ] **Step 5: Run focused and complete verification**

Run: `python -m pytest tests/test_installer.py tests/test_main.py -v`

Run: `python -m pytest`

Expected: all runnable tests pass; platform-dependent skips remain explicitly reported.

- [ ] **Step 6: Commit and push**

Commit the implementation and tests on `windows-codex-desktop-compat`, then push that branch to the configured fork remote.
