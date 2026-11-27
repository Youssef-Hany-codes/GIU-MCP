"""Map the GIU portal and CMS so parsers can be written against real pages.

Read-only: it only follows plain <a href> GET links on the two GIU hosts, never
submits forms or postbacks, skips anything that looks like an action (logout,
delete, register, pay, ...), and does not download files. Pages are saved under
.discovery/ (git-ignored: it holds your personal data).

    .venv\\Scripts\\python.exe scripts\\discover.py [--depth 2] [--max 120]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup  # noqa: E402

from giu_mcp.client import ALLOWED_HOSTS, AuthError, GiuClient  # noqa: E402
from giu_mcp.config import CMS_BASE, PORTAL_HOME, PROJECT_ROOT  # noqa: E402

OUT = PROJECT_ROOT / ".discovery"
RISKY = re.compile(
    r"log_?out|sign_?out|log_?off|delete|remove|drop|withdraw|register|enrol|"
    r"pay|submit|apply|cancel|password|reset|upload|edit|update|save|confirm|approve",
    re.I,
)
FILE_EXT = re.compile(r"\.(pdf|zip|rar|7z|pptx?|docx?|xlsx?|png|jpe?g|gif|mp4|mp3|txt|csv|ics)$", re.I)


def slug(url: str) -> str:
    p = urlparse(url)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", p.path.strip("/")) or "root"
    if p.query:
        base += "__" + hashlib.sha1(p.query.encode()).hexdigest()[:8]
    return f"{p.hostname}/{base[:150]}.html"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=2)
    ap.add_argument("--max", type=int, default=120)
    args = ap.parse_args()

    client = GiuClient()
    OUT.mkdir(exist_ok=True)
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(PORTAL_HOME, 0), (CMS_BASE + "/", 0)])
    index, files, skipped = [], set(), set()

    while queue and len(index) < args.max:
        url, depth = queue.popleft()
        url = urldefrag(url)[0]
        if url in seen:
            continue
        seen.add(url)
        try:
            page = client.get(url)
        except AuthError as e:
            print(f"AUTH FAILED on {url}: {e}")
            return 2
        except Exception as e:  # keep mapping the rest
            index.append({"url": url, "error": f"{type(e).__name__}: {e}"})
            print(f"  ERR  {url}  {e}")
            continue

        soup = BeautifulSoup(page.html, "lxml")
        title = (soup.title.get_text(" ", strip=True) if soup.title else "")[:100]
        path = OUT / slug(page.url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page.html, encoding="utf-8")
        entry = {
            "url": url,
            "final_url": page.url,
            "title": title,
            "file": str(path.relative_to(OUT)),
            "depth": depth,
            "tables": len(soup.find_all("table")),
            "forms_selects": len(soup.find_all("select")),
            "postbacks": len(re.findall(r"__doPostBack", page.html)),
        }
        index.append(entry)
        print(f"  {depth}  {page.url}  [{title}]  tables={entry['tables']} selects={entry['forms_selects']}")

        if depth >= args.depth:
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            nxt = urldefrag(urljoin(page.url, href))[0]
            host = urlparse(nxt).hostname
            if host not in ALLOWED_HOSTS:
                continue
            label = a.get_text(" ", strip=True)
            if FILE_EXT.search(urlparse(nxt).path):
                files.add(nxt)
                continue
            if RISKY.search(nxt) or RISKY.search(label):
                skipped.add(f"{label} -> {nxt}")
                continue
            if nxt not in seen:
                queue.append((nxt, depth + 1))

    (OUT / "index.json").write_text(
        json.dumps({"pages": index, "file_links": sorted(files), "skipped": sorted(skipped)}, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved {len(index)} pages, {len(files)} file links, {len(skipped)} skipped links to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
