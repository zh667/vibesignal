"""Command-line entry point, invoked by agent hooks.

Usage:
  vibesignal event --agent claude --state working
  vibesignal status
  vibesignal clear [--agent A --session S]
  vibesignal off

The `event` command reads the session id from the hook's stdin JSON when
`--session` is not given, and always exits 0 so a hook can never block the agent.
The single-line stdin read is bounded by a short timeout, so it does not wait for
the hook runner to close the pipe and an open but dataless pipe cannot hang the
hook. The record -> resolve -> set-light -> cache critical section is held under a
cross-process lock so concurrent hooks cannot race the device.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading

from . import light, lock, store
from .resolve import State, resolve_color, resolve_per_session


def _default_stdin_timeout() -> float:
    # Hook stdin must be available within this window, or the event falls back to
    # the default session. Override for slower wrapper layers.
    raw = os.environ.get("VIBECODING_STDIN_TIMEOUT", "0.5")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.5


STDIN_TIMEOUT_SECONDS = _default_stdin_timeout()


def _read_hook_stdin(timeout: float = STDIN_TIMEOUT_SECONDS) -> dict:
    if sys.stdin is None or sys.stdin.isatty():
        return {}

    # Hook payloads are UTF-8 JSON. On Windows, Python may otherwise inherit a
    # Chinese console code page and turn paths such as "我的世界存档" into mojibake.
    reconfigure = getattr(sys.stdin, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

    result: "queue.Queue[str]" = queue.Queue(maxsize=1)

    def read_stdin() -> None:
        try:
            # Codex and Claude hooks send one JSON object. Reading one line lets
            # us proceed as soon as the payload arrives, even if the runner keeps
            # its stdin pipe open until after the hook process exits.
            raw = sys.stdin.readline()
        except Exception:
            raw = ""
        try:
            result.put_nowait(raw)
        except queue.Full:
            pass

    # Daemon thread: if stdin has no data, the read is abandoned at exit instead
    # of hanging the hook.
    threading.Thread(target=read_stdin, daemon=True).start()
    try:
        raw = result.get(timeout=timeout)
    except queue.Empty:
        return {}

    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _apply_light() -> tuple[str, list | None]:
    state, color = resolve_color()
    if color != store.get_last_color():
        # Cache the color only after the device accepts it, so a no-device run
        # does not poison the cache and suppress the first real write later.
        if light.set_color(color):
            store.set_last_color(color)
    return state, color


def cmd_event(args) -> int:
    try:
        hook = _read_hook_stdin()
        # Codex Desktop runs private background sessions for ambient suggestion
        # generation and safety checks. They have session ids and trigger global
        # hooks, but no user transcript, so they must not appear as coding tasks.
        # An explicit --session remains available for manual simulation.
        if args.agent == "codex" and args.session is None and not hook.get("transcript_path"):
            return 0
        session = args.session or hook.get("session_id") or "default"
        cwd = str(hook.get("cwd") or os.getcwd())
        project = args.project or os.path.basename(cwd.rstrip("/\\")) or None
        with lock.file_lock(store.lock_path()):
            store.record(agent=args.agent, session=session, state=args.state, project=project)
            state, color = _apply_light()
        # --quiet keeps stdout empty for hosts that parse hook stdout as JSON
        # (Codex rejects a plain status line from a PostToolUse hook).
        if not args.quiet:
            print(f"[vibesignal] {args.agent}/{session}: {args.state} -> {state} {color}")
    except Exception as exc:  # a VibeSignal bug must never break the agent
        print(f"[vibesignal] non-fatal: {exc}", file=sys.stderr)
    return 0


def cmd_status(args) -> int:
    # Use the resolver, not raw store.load_active, so `status` agrees with the
    # light and the panel: same per-state lifetime, blocked sorted first. Reading
    # the store directly would hide a long-blocked session the light still shows.
    rows = resolve_per_session()
    state, color = resolve_color()
    if args.json:
        sessions = [
            {key: row[key] for key in ("agent", "session", "project", "state", "ts")}
            for row in rows
        ]
        reconfigure = getattr(sys.stdout, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
        print(json.dumps({"aggregate": state, "sessions": sessions}, ensure_ascii=False))
        return 0
    print(f"aggregate: {state}  color: {color}  (last applied: {store.get_last_color()})")
    for r in rows:
        print(f"  {r['agent']}/{r['session']}: {r['state']} project={r['project']}")
    if not rows:
        print("  (no active sessions)")
    return 0


def cmd_clear(args) -> int:
    with lock.file_lock(store.lock_path()):
        store.clear(agent=args.agent, session=args.session)
        _apply_light()
    print("[vibesignal] cleared")
    return 0


def cmd_off(args) -> int:
    with lock.file_lock(store.lock_path()):
        store.clear()
        # Force the device off, but cache None only if the write was accepted,
        # mirroring _apply_light so a failed write is not recorded as applied.
        if light.set_color(None):
            store.set_last_color(None)
    print("[vibesignal] off")
    return 0


def cmd_end(args) -> int:
    # SessionEnd hook: clear just the ending session (id from hook stdin) so a
    # closed session leaves the panel at once instead of waiting out the TTL.
    try:
        hook = _read_hook_stdin()
        session = args.session or hook.get("session_id")
        if not session:
            # Unlike `event`, `end` must not fall back to "default": a SessionEnd
            # with no id would otherwise clear an unrelated default-bucket session.
            if not args.quiet:
                print(f"[vibesignal] end ignored for {args.agent}: no session id")
            return 0
        with lock.file_lock(store.lock_path()):
            store.clear(agent=args.agent, session=session)
            _apply_light()
        if not args.quiet:
            print(f"[vibesignal] ended {args.agent}/{session}")
    except Exception as exc:  # a VibeSignal bug must never break the agent
        print(f"[vibesignal] non-fatal: {exc}", file=sys.stderr)
    return 0


def cmd_watch(args) -> int:
    from . import panel
    return panel.watch(interval=args.interval, once=args.once)


def cmd_widget(args) -> int:
    from . import widget
    return widget.main(interval_ms=int(args.interval * 1000))


def cmd_install_launcher(args) -> int:
    from . import installer
    dest = installer.install_launcher()
    print(f"[vibesignal] installed launcher: {dest}")
    if sys.platform == "win32":
        print("Launch from the Start menu (type 'VibeSignal') or the Desktop shortcut.")
    else:
        print("Open via Spotlight ('VibeSignal'), or drag the .app to the Dock.")
    return 0


def cmd_uninstall_launcher(args) -> int:
    from . import installer
    removed = installer.uninstall_launcher()
    print(f"[vibesignal] {'removed launcher' if removed else 'no launcher found'}")
    return 0


def cmd_install_autostart(args) -> int:
    from . import installer
    launch_now = not getattr(args, "no_launch", False)
    dest = installer.install_autostart(launch_now=launch_now)
    if sys.platform == "win32":
        print(f"[vibesignal] installed autostart shortcut: {dest}")
        print("The widget starts now and at every future login." if launch_now
              else "The widget will start at the next login (run 'vibesignal widget' to start it now).")
    else:
        print(f"[vibesignal] installed autostart LaunchAgent: {dest}")
        print("Widget starts now (RunAtLoad=true) and at every future login." if launch_now
              else "Widget will start at the next login (run 'vibesignal widget &' to start it now).")
    if launch_now:
        print("Close any manually opened widget first to avoid duplicate processes.")
    print("Re-run after switching env to re-pin the path.")
    return 0


def cmd_uninstall_autostart(args) -> int:
    from . import installer
    removed = installer.uninstall_autostart()
    print(f"[vibesignal] {'removed autostart' if removed else 'no autostart found'}")
    return 0


def _confirm(prompt: str) -> bool:
    """Ask an EOF-safe, default-no confirmation question."""
    try:
        answer = input(f"{prompt} [y/N] ")
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.strip().lower() in {"y", "yes"}


def cmd_install_hooks(args) -> int:
    from . import installer

    include_session_end = True
    if args.agent == "codex":
        info = installer.detect_codex_cli()
        assume_yes = getattr(args, "yes", False)
        recommended = installer.RECOMMENDED_CODEX_CLI_VERSION
        npm_command = f"npm install -g @openai/codex@{recommended}"

        if info.path is None:
            print(
                "[vibesignal] Codex CLI was not found. It is needed to review "
                "and trust Codex Desktop Hooks, but not while the widget runs."
            )
            print(f"[vibesignal] Proposed command: {npm_command}")
            consent = assume_yes or _confirm(
                f"Install the verified Codex CLI {recommended} globally with npm?"
            )
            if not consent:
                print("[vibesignal] Codex Hook integration not enabled.")
                return 2
            try:
                info = installer.install_recommended_codex_cli()
            except installer.CodexCliInstallError as exc:
                print(f"[vibesignal] {exc}", file=sys.stderr)
                print("[vibesignal] Codex Hook integration not enabled.")
                return 2
        elif info.version is None:
            detected = info.raw_version or "version command failed"
            print(
                f"[vibesignal] Detected Codex CLI ({detected}), but its version "
                "could not be verified. The global CLI will not be changed."
            )
            print(
                "[vibesignal] Codex Hook integration not enabled because a "
                "verified /hooks review path is unavailable."
            )
            return 2
        elif not installer.codex_supports_session_end(info):
            detected = info.raw_version or ".".join(map(str, info.version))
            base_supported = installer.codex_supports_base_hooks(info)
            print(
                f"[vibesignal] Detected {detected}; VibeSignal has verified "
                f"SessionEnd review starting at Codex CLI {recommended}."
            )
            if not base_supported:
                base = ".".join(map(str, installer.MIN_VERIFIED_BASE_HOOKS_CLI))
                print(
                    "[vibesignal] This version is also below the oldest verified "
                    f"four-Hook review version ({base})."
                )
            print(f"[vibesignal] Proposed command: {npm_command}")
            consent = assume_yes or _confirm(
                f"Upgrade the global Codex CLI to {recommended} with npm?"
            )
            if consent:
                try:
                    info = installer.install_recommended_codex_cli()
                except installer.CodexCliInstallError as exc:
                    print(f"[vibesignal] {exc}", file=sys.stderr)
                    recovered = installer.detect_codex_cli()
                    if installer.codex_supports_session_end(recovered):
                        print(
                            "[vibesignal] The CLI remains usable at the full "
                            "Hook baseline; continuing in full mode."
                        )
                    elif installer.codex_supports_base_hooks(recovered):
                        print(
                            "[vibesignal] The existing CLI remains usable; "
                            "continuing without SessionEnd."
                        )
                        include_session_end = False
                    else:
                        print(
                            "[vibesignal] Codex Hook integration not enabled "
                            "because no verified /hooks review path remains."
                        )
                        return 2
            else:
                if not base_supported:
                    print(
                        "[vibesignal] Codex Hook integration not enabled because "
                        "this CLI is below the verified review baseline."
                    )
                    return 2
                include_session_end = False
        else:
            detected = info.raw_version or ".".join(map(str, info.version))
            print(f"[vibesignal] Detected {detected}; keeping the existing CLI.")

    path = installer.install_hooks(
        agent=args.agent, include_session_end=include_session_end
    )
    print(f"[vibesignal] wired {args.agent} hooks into {path}")
    if args.agent == "codex":
        if include_session_end:
            print("[vibesignal] Codex Hook mode: full mode (SessionEnd enabled).")
        else:
            print(
                "[vibesignal] Codex Hook mode: compatibility mode "
                "(four Hooks; Stop + TTL cleanup)."
            )
        print(
            "Run Codex CLI, enter /hooks, then review and trust the new Hooks "
            "yourself. Restart Codex Desktop and send a test prompt afterward."
        )
    else:
        print("Takes effect on the next Claude Code session (or a settings reload).")
    print("Re-run after switching env to re-pin the path.")
    return 0


def cmd_uninstall_hooks(args) -> int:
    from . import installer
    removed = installer.uninstall_hooks(agent=args.agent)
    print(f"[vibesignal] {'removed' if removed else 'no'} {args.agent} hooks")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vibesignal")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_event = sub.add_parser("event", help="record a session state and update the light")
    p_event.add_argument("--agent", required=True, help="agent name, e.g. claude or codex")
    p_event.add_argument(
        "--state", required=True,
        choices=[State.WORKING, State.BLOCKED, State.DONE, State.ERROR, State.IDLE, State.NEEDS_INPUT],
    )
    p_event.add_argument("--session", default=None, help="session id (else from hook stdin)")
    p_event.add_argument("--project", default=None, help="project tag (else from cwd)")
    p_event.add_argument("--quiet", action="store_true", help="suppress normal stdout for strict hook parsers")
    p_event.set_defaults(func=cmd_event)

    p_status = sub.add_parser("status", help="print active sessions and the resolved color")
    p_status.add_argument("--json", action="store_true", help="print one UTF-8 JSON snapshot")
    p_status.set_defaults(func=cmd_status)

    p_clear = sub.add_parser("clear", help="clear one or all sessions")
    p_clear.add_argument("--agent", default=None)
    p_clear.add_argument("--session", default=None)
    p_clear.set_defaults(func=cmd_clear)

    p_off = sub.add_parser("off", help="clear all sessions and turn the light off")
    p_off.set_defaults(func=cmd_off)

    p_end = sub.add_parser("end", help="clear one ended session (id from hook stdin)")
    p_end.add_argument("--agent", required=True, help="agent name, e.g. claude")
    p_end.add_argument("--session", default=None, help="session id (else from hook stdin)")
    p_end.add_argument("--quiet", action="store_true", help="suppress normal stdout for strict hook parsers")
    p_end.set_defaults(func=cmd_end)

    p_watch = sub.add_parser("watch", help="live multi-session panel (foreground viewer)")
    p_watch.add_argument("--interval", type=float, default=1.0, help="refresh seconds")
    p_watch.add_argument("--once", action="store_true", help="render once and exit")
    p_watch.set_defaults(func=cmd_watch)

    p_widget = sub.add_parser("widget", help="always-on-top floating GUI panel")
    p_widget.add_argument("--interval", type=float, default=1.0, help="refresh seconds")
    p_widget.set_defaults(func=cmd_widget)

    p_install_launcher = sub.add_parser(
        "install-launcher",
        help="install a one-click launcher (macOS .app, or Windows Start menu + Desktop shortcut)",
    )
    p_install_launcher.set_defaults(func=cmd_install_launcher)

    p_uninstall_launcher = sub.add_parser(
        "uninstall-launcher",
        help="remove the one-click launcher",
    )
    p_uninstall_launcher.set_defaults(func=cmd_uninstall_launcher)

    p_install_autostart = sub.add_parser(
        "install-autostart",
        help="install login autostart (macOS LaunchAgent, or Windows Startup shortcut) and start the widget now",
    )
    p_install_autostart.add_argument(
        "--no-launch", action="store_true",
        help="install the autostart entry but do not start the widget now (it starts at the next login)",
    )
    p_install_autostart.set_defaults(func=cmd_install_autostart)

    p_uninstall_autostart = sub.add_parser(
        "uninstall-autostart",
        help="remove login autostart",
    )
    p_uninstall_autostart.set_defaults(func=cmd_uninstall_autostart)

    p_install_hooks = sub.add_parser(
        "install-hooks",
        help="wire agent hooks into the settings file, absolute path pinned (all platforms)",
    )
    p_install_hooks.add_argument(
        "--agent", default="claude", choices=["claude", "codex"],
        help="which agent's settings file to wire (default: claude)",
    )
    p_install_hooks.add_argument(
        "--yes", action="store_true",
        help=(
            "consent to install or upgrade the verified Codex CLI version "
            "without an interactive prompt; Hook trust always remains manual"
        ),
    )
    p_install_hooks.set_defaults(func=cmd_install_hooks)

    p_uninstall_hooks = sub.add_parser(
        "uninstall-hooks",
        help="remove vibesignal hooks from an agent settings file",
    )
    p_uninstall_hooks.add_argument(
        "--agent", default="claude", choices=["claude", "codex"],
        help="which agent's settings file to clean (default: claude)",
    )
    p_uninstall_hooks.set_defaults(func=cmd_uninstall_hooks)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
