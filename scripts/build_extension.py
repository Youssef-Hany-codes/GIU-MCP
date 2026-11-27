"""Build the Claude Desktop extension: dist/giu-mcp-<version>.mcpb

    python scripts/build_extension.py

Needs `uv` (pip install uv) to write the lockfile, and Node.js for the official packer
(`npx @anthropic-ai/mcpb`). The extension uses the "uv" server type: Claude Desktop installs
Python and the dependencies itself, so students need nothing pre-installed.

Only an allow-list of files is copied into the extension (never .env, .discovery/, .venv/),
and the tool/prompt lists in manifest.json are generated from the server itself.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "dist" / "extension"
MCPB = "@anthropic-ai/mcpb@2.1.2"
REPO = "https://github.com/Youssef-Hany-codes/GIU-MCP"

sys.path.insert(0, str(ROOT))


def run(cmd: list[str], **kw) -> None:
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True, shell=(sys.platform == "win32" and cmd[0] == "npx"), **kw)


def first_line(text: str | None) -> str:
    return " ".join((text or "").strip().split("\n\n")[0].split())


async def capabilities() -> tuple[list[dict], list[dict]]:
    from giu_mcp.server import mcp

    tools = [{"name": t.name, "description": first_line(t.description)} for t in await mcp.list_tools()]
    prompts = []
    for p in await mcp.list_prompts():
        args = [a.name for a in p.arguments or []]
        rendered = await mcp.get_prompt(p.name, {a: f"${{arguments.{a}}}" for a in args})
        prompts.append(
            {
                "name": p.name,
                "description": p.description,
                "arguments": args,
                "text": rendered.messages[0].content.text,
            }
        )
    return tools, prompts


def manifest(version: str, tools: list[dict], prompts: list[dict]) -> dict:
    return {
        "manifest_version": "0.4",
        "name": "giu-mcp",
        "display_name": "GIU MCP",
        "version": version,
        "description": "Your own GIU student portal and CMS: schedule, grades, transcript, attendance, exam seats and course materials.",
        "long_description": (
            "Unofficial, student-made extension for the German International University. It signs in to "
            "portal.giu-uni.de and cms.giu-uni.de as you and reads your schedule, grades, transcript, "
            "attendance, exam seats, course announcements and course files. It is read-only: it never submits, "
            "registers, evaluates, uploads or pays anything. Your password is stored securely by the app and is "
            "only ever sent to those two GIU sites. Free for non-commercial use (PolyForm Noncommercial 1.0.0)."
        ),
        "author": {"name": "Youssef-Hany-codes", "url": "https://github.com/Youssef-Hany-codes"},
        "repository": {"type": "git", "url": REPO},
        "homepage": REPO,
        "documentation": f"{REPO}#readme",
        "support": f"{REPO}/issues",
        "icon": "icon.png",
        "server": {
            "type": "uv",
            "entry_point": "server.py",
            "mcp_config": {
                "command": "uv",
                "args": ["run", "--directory", "${__dirname}", "server.py"],
                "env": {
                    "GIU_USERNAME": "${user_config.username}",
                    "GIU_PASSWORD": "${user_config.password}",
                    "GIU_DOWNLOAD_DIR": "${user_config.download_dir}",
                },
            },
        },
        "tools": tools,
        "prompts": prompts,
        "keywords": ["giu", "german international university", "student portal", "cms", "grades", "schedule"],
        "license": "PolyForm-Noncommercial-1.0.0",
        "privacy_policies": [f"{REPO}#your-account-and-your-data-stay-with-you"],
        "compatibility": {"platforms": ["darwin", "win32", "linux"], "runtimes": {"python": ">=3.11"}},
        "user_config": {
            "username": {
                "type": "string",
                "title": "GIU username",
                "description": "The username you type in the portal's sign-in box (e.g. firstname.lastname).",
                "required": True,
            },
            "password": {
                "type": "string",
                "title": "GIU password",
                "description": "Stored securely by the app. Only ever sent to portal.giu-uni.de and cms.giu-uni.de.",
                "sensitive": True,
                "required": True,
            },
            "download_dir": {
                "type": "directory",
                "title": "Download folder (optional)",
                "description": "Where course files are saved. Leave empty for Downloads/GIU.",
                "required": False,
            },
        },
    }


def stage(version: str, tools: list[dict], prompts: list[dict]) -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "giu_mcp").mkdir(parents=True)
    for f in sorted((ROOT / "giu_mcp").glob("*.py")) + [ROOT / "giu_mcp" / "icon.png"]:
        shutil.copy2(f, STAGE / "giu_mcp" / f.name)
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, STAGE / name)
    shutil.copy2(ROOT / "extension" / "server.py", STAGE / "server.py")
    shutil.copy2(ROOT / "extension" / "icon.png", STAGE / "icon.png")
    (STAGE / ".mcpbignore").write_text(".venv/\n__pycache__/\n*.pyc\n*.egg-info/\nserver/lib/\nserver/venv/\n")
    (STAGE / "manifest.json").write_text(json.dumps(manifest(version, tools, prompts), indent=2) + "\n", encoding="utf-8")


def main() -> int:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    print(f"Building giu-mcp {version} extension")
    tools, prompts = asyncio.run(capabilities())
    print(f"  {len(tools)} tools, {len(prompts)} prompts")
    stage(version, tools, prompts)

    uv = shutil.which("uv") or str(Path(sys.executable).parent / "uv")
    run([uv, "lock", "--directory", str(STAGE), "--quiet"])  # pinned, cross-platform dependency set

    out = ROOT / "dist" / f"giu-mcp-{version}.mcpb"
    out.unlink(missing_ok=True)
    run(["npx", "-y", MCPB, "validate", str(STAGE / "manifest.json")])
    run(["npx", "-y", MCPB, "pack", str(STAGE), str(out)])
    print(f"\nBuilt {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
