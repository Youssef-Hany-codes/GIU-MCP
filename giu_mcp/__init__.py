"""MCP server for the GIU student portal (portal.giu-uni.de) and CMS (cms.giu-uni.de)."""

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _version() -> str:
    """The version, set only in pyproject.toml.

    Read from pyproject.toml when it sits next to the package (a source checkout or the
    Claude Desktop extension), because an editable install's metadata goes stale;
    otherwise from the installed package's metadata.
    """
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
        if project.get("name") == "giu-mcp":
            return project["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        pass
    try:
        return version("giu-mcp")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _version()
