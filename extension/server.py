"""Entry point for the Claude Desktop extension. The app runs it with `uv run`, passing the
GIU username/password from the extension's settings form as GIU_USERNAME / GIU_PASSWORD."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from giu_mcp.server import main  # noqa: E402

main()
