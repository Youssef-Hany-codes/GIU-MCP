"""Per-user storage of GIU credentials.

The username (not secret) goes in <config dir>/account.json. The password goes in the
operating system's credential store via `keyring` (Windows Credential Manager, macOS
Keychain, Secret Service on Linux). Only when no store is available does it fall back
to that JSON file, readable by the current user only.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE = "giu-mcp"


def config_dir() -> Path:
    override = os.environ.get("GIU_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / SERVICE


def _account_file() -> Path:
    return config_dir() / "account.json"


def _keyring():
    """The keyring module if a real OS backend is available, else None."""
    try:
        import keyring
        from keyring.backends import fail

        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or "fail" in type(backend).__module__:
            return None
        return keyring
    except Exception:
        return None


@dataclass(frozen=True)
class StoredAccount:
    username: str
    password: str
    domain: str
    store: str  # "keyring" or "file"


def save(username: str, password: str, domain: str = "") -> str:
    """Store the account; returns where the password went ("keyring" or "file")."""
    path = _account_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"username": username, "domain": domain}
    kr = _keyring()
    if kr is not None:
        old = load()
        if old and old.store == "keyring" and old.username != username:
            _delete_keyring(old.username)
        kr.set_password(SERVICE, username, password)
        data["password_store"] = "keyring"
    else:
        data["password_store"] = "file"
        data["password"] = password
    _write_private(path, json.dumps(data, indent=2))
    return data["password_store"]


def load() -> StoredAccount | None:
    path = _account_file()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    username = data.get("username", "")
    if not username:
        return None
    if data.get("password_store") == "keyring":
        kr = _keyring()
        password = kr.get_password(SERVICE, username) if kr else None
        store = "keyring"
    else:
        password, store = data.get("password"), "file"
    if not password:
        return None
    return StoredAccount(username, password, data.get("domain", ""), store)


def clear() -> bool:
    """Forget the stored account. Returns True if there was one."""
    path = _account_file()
    existed = path.exists()
    old = load()
    if old and old.store == "keyring":
        _delete_keyring(old.username)
    if existed:
        path.unlink()
    return existed


def _delete_keyring(username: str) -> None:
    kr = _keyring()
    if kr is None:
        return
    try:
        kr.delete_password(SERVICE, username)
    except Exception:
        pass


def _write_private(path: Path, text: str) -> None:
    """Write a file only the current user can read (best effort on Windows, where the
    per-user AppData folder already restricts access)."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)
    if os.name != "nt":
        os.chmod(path, 0o600)
