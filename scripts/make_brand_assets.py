"""Regenerate every derived image from the logo files in assets/:

    extension/icon.png          512x512   Claude Desktop extension icon
    giu_mcp/icon.png            128x128   MCP server icon (sent to apps that display one)
    assets/social-preview.png   1280x640  GitHub link preview (upload it in the repo's
                                          Settings > General > Social preview)

    python scripts/make_brand_assets.py      (needs Pillow: pip install pillow)

To change the logo, replace the files in assets/ and run this again.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PNG = ROOT / "assets" / "png"


def resized(src: Path, size: int) -> Image.Image:
    return Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)


def save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, optimize=True)
    print(f"wrote {path.relative_to(ROOT)}  {img.size[0]}x{img.size[1]}  {path.stat().st_size // 1024} KB")


icon = PNG / "giu-mcp-icon-1024.png"
save(resized(icon, 512), ROOT / "extension" / "icon.png")
save(resized(icon, 128), ROOT / "giu_mcp" / "icon.png")

# Social preview: the horizontal logo centred on white, 1280x640 (GitHub's recommended size).
canvas = Image.new("RGBA", (1280, 640), (255, 255, 255, 255))
logo = Image.open(PNG / "giu-mcp-horizontal.png").convert("RGBA")
width = 1040
logo = logo.resize((width, round(logo.height * width / logo.width)), Image.LANCZOS)
canvas.alpha_composite(logo, ((1280 - logo.width) // 2, (640 - logo.height) // 2))
save(canvas.convert("RGB"), ROOT / "assets" / "social-preview.png")
