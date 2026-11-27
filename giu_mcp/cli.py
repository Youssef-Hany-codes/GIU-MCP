"""Command line: `giu-mcp` runs the MCP server; `giu-mcp login|logout|status|config` set it up."""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sys
from pathlib import Path

from . import __version__, credentials

CLIENTS = ["claude-code", "claude-desktop", "cursor", "vscode", "windsurf", "gemini", "codex", "json"]


def _launch_command() -> tuple[str, list[str]]:
    """How an AI app should start this server on this machine."""
    if any(part.startswith("archive-v") for part in Path(sys.executable).parts):
        return "uvx", ["giu-mcp"]  # running via `uvx giu-mcp`: its cache path isn't stable
    exe = shutil.which("giu-mcp")
    if exe and Path(exe).resolve().parent != Path(sys.executable).resolve().parent:
        return exe, []  # installed as a tool (pipx / uv tool): stable path on PATH
    return sys.executable, ["-m", "giu_mcp"]


def cmd_login(args) -> int:
    from .client import AuthError, GiuClient
    from .config import PORTAL_HOME, Settings
    from .portal import profile

    print("Sign in with the same GIU username and password you use for portal.giu-uni.de.")
    username = (args.username or input("GIU username: ")).strip()
    password = getpass.getpass("GIU password (hidden): ")
    if not username or not password:
        print("Username and password are both required.", file=sys.stderr)
        return 1
    settings = Settings(username, password, args.domain.strip(), Path.home(), 45.0, "login")
    if not args.no_verify:
        print("Checking with the portal…")
        try:
            client = GiuClient(settings)
            client.get(PORTAL_HOME)
            who = profile(client)
        except AuthError:
            print("GIU rejected that username/password. Nothing was saved.", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"Could not reach the portal ({e}). Use --no-verify to save anyway.", file=sys.stderr)
            return 1
        print(f"Signed in as {who['name'] or username}" + (f" ({who['student_id']})" if who["student_id"] else ""))
    where = credentials.save(username, password, args.domain.strip())
    if where == "keyring":
        print("Password saved in your operating system's credential store.")
    else:
        print(f"No OS credential store found: password saved in {credentials.config_dir() / 'account.json'} (readable by you only).")
    print("\nNext: add the server to your AI app. For the exact snippet, run:  giu-mcp config")
    return 0


def cmd_logout(args) -> int:
    print("Signed out: saved GIU account removed." if credentials.clear() else "No saved GIU account.")
    return 0


def cmd_status(args) -> int:
    from .client import AuthError, GiuClient
    from .config import ConfigError, load_settings
    from . import cms, portal

    print(f"giu-mcp {__version__}  |  config folder: {credentials.config_dir()}")
    try:
        settings = load_settings()
    except ConfigError as e:
        print(e)
        return 1
    print(f"Account: {settings.username}  (from {settings.source})")
    client = GiuClient(settings)
    try:
        who = portal.profile(client)
        print(f"Portal: OK, signed in as {who['name']} {who['student_id']}".rstrip())
        print(f"CMS:    OK, {len(cms.current_courses(client))} current course(s)")
    except AuthError as e:
        print(f"Sign-in failed: {e}\nRun `giu-mcp login` again.")
        return 1
    except Exception as e:
        print(f"Could not reach GIU: {e}")
        return 1
    print(f"Downloads go to: {settings.download_dir}")
    return 0


def cmd_config(args) -> int:
    command, cmd_args = _launch_command()
    server = {"command": command, "args": cmd_args}
    show = args.client or "all"

    def block(title: str, body: str) -> None:
        print(f"\n== {title}\n{body}")

    quoted = " ".join(f'"{x}"' if " " in x else x for x in [command, *cmd_args])
    if show in ("all", "claude-code"):
        block("Claude Code (run once in a terminal)", f"claude mcp add giu --scope user -- {quoted}")
    if show in ("all", "claude-desktop", "cursor", "windsurf", "gemini", "json"):
        where = {
            "claude-desktop": "Claude Desktop: Settings > Developer > Edit Config (claude_desktop_config.json)",
            "cursor": "Cursor: ~/.cursor/mcp.json",
            "windsurf": "Windsurf: ~/.codeium/windsurf/mcp_config.json",
            "gemini": "Gemini CLI: ~/.gemini/settings.json",
        }
        title = where.get(show) or "Claude Desktop, Cursor, Windsurf, Gemini CLI and most other apps (inside \"mcpServers\")"
        block(title, json.dumps({"mcpServers": {"giu": server}}, indent=2))
    if show in ("all", "vscode"):
        block("VS Code (.vscode/mcp.json, or 'MCP: Add Server')", json.dumps({"servers": {"giu": {"type": "stdio", **server}}}, indent=2))
    if show in ("all", "codex"):
        toml_args = ", ".join(json.dumps(a) for a in cmd_args)
        block("OpenAI Codex CLI (~/.codex/config.toml)", f"[mcp_servers.giu]\ncommand = {json.dumps(command)}\nargs = [{toml_args}]")
    print("\nRestart the app afterwards. The server reads the account saved by `giu-mcp login`.")
    return 0


def cmd_serve(args) -> int:
    if sys.stdin.isatty():
        print(
            "giu-mcp: starting the MCP server on stdio. AI apps launch this themselves;\n"
            "to set up instead, run `giu-mcp login` then `giu-mcp config`. Ctrl+C to stop.",
            file=sys.stderr,
        )
    from .server import main as serve

    serve()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="giu-mcp",
        description="MCP server for the GIU student portal and CMS. Run without a command to start the server.",
    )
    p.add_argument("--version", action="version", version=f"giu-mcp {__version__}")
    sub = p.add_subparsers(dest="cmd", metavar="command")
    sub.add_parser("serve", help="run the MCP server over stdio (the default)")
    lp = sub.add_parser("login", help="save your GIU username and password for the server")
    lp.add_argument("--username", help="GIU username (asked if omitted)")
    lp.add_argument("--domain", default="", help="Windows domain, only if sign-in fails without it")
    lp.add_argument("--no-verify", action="store_true", help="save without checking against the portal")
    sub.add_parser("logout", help="remove the saved account")
    sub.add_parser("status", help="check that the saved account can sign in")
    cp = sub.add_parser("config", help="print the snippet to add this server to an AI app")
    cp.add_argument("client", nargs="?", choices=CLIENTS, help="only this app (default: all)")
    args = p.parse_args(argv)
    handler = {"login": cmd_login, "logout": cmd_logout, "status": cmd_status, "config": cmd_config}.get(args.cmd, cmd_serve)
    try:
        return handler(args) or 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
