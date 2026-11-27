"""Tell students when a newer GIU MCP is out.

Copies installed from a .mcpb file never update by themselves (Claude Desktop only
auto-updates directory extensions), so the server checks PyPI for the latest version,
at most once a day, in a background thread with a short timeout. Nothing about the
student is sent: it is a plain GET of https://pypi.org/pypi/giu-mcp/json.

The first tool result after a newer version is found carries an `update_notice` the AI
passes on, with the update steps for however this copy was installed.
Set GIU_NO_UPDATE_CHECK=1 to turn it off.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from pathlib import Path

import requests

from . import __version__
from .credentials import config_dir

PYPI_URL = "https://pypi.org/pypi/giu-mcp/json"
DOWNLOAD_URL = "https://github.com/Youssef-Hany-codes/GIU-MCP/releases/latest/download/giu-mcp.mcpb"
RELEASES_URL = "https://github.com/Youssef-Hany-codes/GIU-MCP/releases/latest"
CHECK_EVERY = 24 * 3600
TIMEOUT = 4


def install_kind() -> str:
    """How this copy runs: "extension", "uvx", "dev" (source checkout) or "installed"."""
    root = Path(__file__).resolve().parent.parent
    if (root / "manifest.json").exists() and (root / "server.py").exists():
        return "extension"
    if any(part.startswith("archive-v") for part in Path(sys.executable).parts):
        return "uvx"
    if (root / "pyproject.toml").exists() and (root / ".git").exists():
        return "dev"
    return "installed"


def _parse(v: str) -> tuple[int, ...] | None:
    """'0.10.2' -> (0, 10, 2); None for pre-releases or anything unexpected."""
    return tuple(int(x) for x in v.split(".")) if re.fullmatch(r"\d+(\.\d+)*", v or "") else None


def is_newer(latest: str, current: str) -> bool:
    a, b = _parse(latest), _parse(current)
    return bool(a and b and a > b)


def _cache_file() -> Path:
    return config_dir() / "update-check.json"


def latest_version(force: bool = False) -> str | None:
    """Latest version on PyPI, from a once-a-day cache unless `force`."""
    cache = _cache_file()
    try:
        data = json.loads(cache.read_text(encoding="utf-8"))
        if not force and time.time() - float(data.get("checked", 0)) < CHECK_EVERY:
            return data.get("latest")
    except (OSError, ValueError):
        pass
    try:
        resp = requests.get(PYPI_URL, timeout=TIMEOUT, headers={"User-Agent": f"giu-mcp/{__version__}"})
        resp.raise_for_status()
        latest = resp.json()["info"]["version"]
    except Exception:
        return None  # offline or PyPI unreachable: try again next start
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"checked": time.time(), "latest": latest}), encoding="utf-8")
    except OSError:
        pass
    return latest


def how_to_update(kind: str) -> str:
    if kind == "extension":
        return (
            f"Download the new giu-mcp.mcpb from {DOWNLOAD_URL} and install it in Claude Desktop via "
            "Settings > Desktop app > Extensions > Advanced settings > Install extension."
        )
    if kind == "uvx":
        return (
            "Restart the AI app: a setup that runs `uvx giu-mcp@latest` updates itself on start. "
            "If the setup runs plain `uvx giu-mcp`, change it to `uvx giu-mcp@latest` "
            "(or run `uvx --refresh giu-mcp --version` once)."
        )
    return f"Run `uv tool upgrade giu-mcp` or `pipx upgrade giu-mcp` (release notes: {RELEASES_URL}), then restart the AI app."


def notice_text(latest: str, current: str = __version__, kind: str | None = None) -> str:
    return (
        f"Tell the user: a newer version of GIU MCP is available ({latest}; they have {current}). "
        + how_to_update(kind or install_kind())
    )


class UpdateChecker:
    """Checks once in the background; hands out the notice once per server run."""

    def __init__(self) -> None:
        self._latest: str | None = None
        self._shown = False
        self._lock = threading.Lock()

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("GIU_NO_UPDATE_CHECK", "").strip().lower() not in {"1", "true", "yes"} and (
            install_kind() != "dev"
        )

    def start(self) -> None:
        if self.enabled():
            threading.Thread(target=self._check, name="giu-update-check", daemon=True).start()

    def _check(self) -> None:
        latest = latest_version()
        with self._lock:
            self._latest = latest

    def take_notice(self) -> str | None:
        """The notice text the first time it applies, then None."""
        with self._lock:
            if self._shown or not self._latest or not is_newer(self._latest, __version__):
                return None
            self._shown = True
            return notice_text(self._latest)


checker = UpdateChecker()
