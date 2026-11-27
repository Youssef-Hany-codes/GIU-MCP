"""Settings: where the credentials come from, plus a few tunables.

Credentials are looked up in this order, first match wins:
  1. GIU_USERNAME / GIU_PASSWORD environment variables (e.g. set in the AI app's MCP config)
  2. the account saved by `giu-mcp login` (password in the OS credential store)
  3. a .env file in the config folder, or in the project folder when run from a checkout
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from . import credentials

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PORTAL_BASE = "https://portal.giu-uni.de"
PORTAL_HOME = f"{PORTAL_BASE}/GIUb/EXTStudent/Home.aspx"
CMS_BASE = "https://cms.giu-uni.de"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    domain: str
    download_dir: Path
    timeout: float
    source: str = ""

    @property
    def ntlm_user(self) -> str:
        """Username in the form NTLM expects: DOMAIN\\user when a domain is set."""
        if self.domain and "\\" not in self.username and "@" not in self.username:
            return f"{self.domain}\\{self.username}"
        return self.username

    def __repr__(self) -> str:  # never print the password
        return f"Settings(username={self.username!r}, source={self.source!r})"


def env_files() -> list[Path]:
    files = [credentials.config_dir() / ".env"]
    if (PROJECT_ROOT / "pyproject.toml").exists():  # running from a source checkout
        files.append(PROJECT_ROOT / ".env")
    return files


def _setting(name: str, dotenv: dict) -> str:
    return (os.environ.get(name) or dotenv.get(name) or "").strip()


def load_settings() -> Settings:
    dotenv: dict[str, str] = {}
    dotenv_source = ""
    for f in reversed(env_files()):  # earlier files win
        if f.exists():
            values = {k: v for k, v in dotenv_values(f).items() if v}
            if values.get("GIU_USERNAME"):
                dotenv_source = str(f)
            dotenv.update(values)

    username = os.environ.get("GIU_USERNAME", "").strip()
    password = os.environ.get("GIU_PASSWORD", "")
    domain = os.environ.get("GIU_DOMAIN", "").strip()
    source = "environment variables"
    if not (username and password):
        stored = credentials.load()
        if stored:
            username, password, domain = stored.username, stored.password, stored.domain
            source = "OS credential store" if stored.store == "keyring" else str(credentials.config_dir() / "account.json")
        else:
            username, password = dotenv.get("GIU_USERNAME", "").strip(), dotenv.get("GIU_PASSWORD", "")
            domain = dotenv.get("GIU_DOMAIN", "").strip()
            source = dotenv_source
    if not username or not password:
        raise ConfigError(
            "No GIU account is set up. Open a terminal and run:  giu-mcp login\n"
            "(or set GIU_USERNAME and GIU_PASSWORD in this AI app's MCP server config)."
        )

    download_dir = _setting("GIU_DOWNLOAD_DIR", dotenv) or str(Path.home() / "Downloads" / "GIU")
    return Settings(
        username=username,
        password=password,
        domain=domain or _setting("GIU_DOMAIN", dotenv),
        download_dir=Path(download_dir).expanduser(),
        timeout=float(_setting("GIU_TIMEOUT", dotenv) or 45),
        source=source,
    )
