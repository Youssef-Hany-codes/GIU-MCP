"""Scrapers for the course management system, cms.giu-uni.de/apps/student/. Read-only."""

from __future__ import annotations

import io
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

from bs4 import Tag

from .client import GiuClient, GiuError, safe_filename
from .config import CMS_BASE
from .util import clean, match_one, norm_code, table_rows, text_of

APP = f"{CMS_BASE}/apps/student/"
LABEL_RE = re.compile(r"^\(\|([^|]+)\|\)\s*(.*?)\s*\((\d+)\)$")
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


# --------------------------------------------------------------------------- courses
def parse_label(label: str) -> tuple[str, str, str]:
    """'(|MATH304|) Mathematics III (3020)' -> ('MATH304', 'Mathematics III', '3020')."""
    m = LABEL_RE.match(clean(label))
    return (norm_code(m.group(1)), m.group(2), m.group(3)) if m else ("", clean(label), "")


def _course(label: str, season_id: str, season: str, active: str) -> dict:
    code, name, cid = parse_label(label)
    return {"code": code, "name": name, "course_id": cid, "season_id": season_id, "season": season, "active": active}


def current_courses(client: GiuClient) -> list[dict]:
    soup = client.get(APP + "HomePageStn.aspx", ttl=300).soup
    table = soup.find(id=re.compile(r"GridViewcourses$"))
    out = []
    for r in table_rows(table)[1:]:
        if len(r) >= 6 and r[1]:
            c = _course(r[1], r[5], r[3], r[2])
            c["course_id"] = c["course_id"] or r[4]
            out.append(c)
    return out


def all_courses(client: GiuClient) -> list[dict]:
    soup = client.get(APP + "ViewAllCourseStn.aspx", ttl=300).soup
    season_names = {c["season_id"]: c["season"] for c in current_courses(client)}
    out = []
    for table in soup.find_all("table", id=re.compile(r"GridView1_\d+$")):
        head = table.find_previous(
            lambda el: "menu-header-title" in (el.get("class") or []) and re.search(r"Season", text_of(el))
        )
        m = re.search(r"Season\s*:\s*(\d+)\s*,\s*Title:\s*(.+)", text_of(head))
        for r in table_rows(table)[1:]:
            if len(r) >= 5 and r[1]:
                sid = r[4]
                season = m.group(2).strip() if m and m.group(1) == sid else season_names.get(sid, text_of(head))
                out.append(_course(r[1], sid, season, r[2]))
    out.sort(key=lambda c: int(c["season_id"] or 0), reverse=True)
    return out


def resolve_course(client: GiuClient, query: str, season_id: str | None = None) -> dict:
    keys = lambda c: [c["code"], c["name"], c["course_id"]]  # noqa: E731
    if not season_id:
        try:
            return match_one(query, current_courses(client), keys, "current course")
        except ValueError:
            pass  # fall back to every season, newest first
    pool = [c for c in all_courses(client) if not season_id or c["season_id"] == str(season_id)]
    if not pool:
        raise ValueError(f"No courses found for season {season_id}")
    hits = [c for c in pool if query.strip() == c["course_id"]]
    if hits:
        return hits[0]
    # Same course can appear in several seasons: keep the newest one per course id.
    newest: dict[str, dict] = {}
    for c in pool:
        newest.setdefault(c["code"] or c["course_id"], c)
    return match_one(query, list(newest.values()), keys, "course")


# --------------------------------------------------------------------------- course page
def _section_text(week: Tag, label: str) -> str:
    strong = week.find("strong", string=re.compile(rf"^\s*{label}\s*$"))
    if not strong:
        return ""
    p = strong.find_parent("div").find_next_sibling("p")
    return text_of(p)


def _rich_text(el: Tag | None) -> str:
    """Text of an announcement, keeping link targets that the visible text hides."""
    if el is None:
        return ""
    text = clean(el.get_text("\n", strip=True).replace("\n", " \n "))
    text = re.sub(r" ?\n ?", "\n", text)
    for a in el.find_all("a", href=True):
        if a["href"] not in text and a["href"].startswith("http"):
            text += f"\n[{text_of(a) or 'link'}]({a['href']})"
    return text.strip()


def _items(week: Tag, week_label: str) -> list[dict]:
    items = []
    for head in week.find_all("div", id=re.compile(r"^content\d+$")):
        title_el = head.find("strong")
        title = text_of(title_el)
        rest = clean(head.get_text(" ", strip=True)[len(title_el.get_text(" ", strip=True)) :]) if title_el else ""
        kind = rest.strip()[1:-1].strip() if rest.startswith("(") and rest.endswith(")") else rest
        m = re.match(r"^(\d+)\s*-\s*(.*)$", title)
        body = head.find_parent(class_="card-body") or head.parent
        link = body.find("a", class_="contentbtn")
        vod = body.find("input", class_="vodbutton")
        href = (link.get("href") if link else None) or (vod.get("data-url") if vod else None)
        btn = link or vod
        desc = head.find_next_sibling("div")
        items.append(
            {
                "content_id": int((btn.get("data-contentid") if btn else None) or head["id"][7:]),
                "number": int(m.group(1)) if m else None,
                "title": m.group(2) if m else title,
                "type": kind,
                "description": text_of(desc) if desc and not desc.find(["a", "input"]) else "",
                "url": urljoin(CMS_BASE, href) if href else None,
                "is_video": kind.lower() == "vod" or PurePosixPath(urlparse(href or "").path).suffix.lower() in VIDEO_EXT,
                "seen": (btn.get("data-seen") if btn else "no") != "no",
                "week": week_label,
            }
        )
    return items


def course_page(client: GiuClient, course: dict) -> dict:
    url = f"{APP}CourseViewStn.aspx?id={course['course_id']}&sid={course['season_id']}"
    soup = client.get(url, ttl=120).soup
    lbl = lambda s: text_of(soup.find(id=f"ContentPlaceHolderright_ContentPlaceHoldercontent_{s}"))  # noqa: E731
    weeks = []
    for w in soup.select(".weeksdata"):
        label = re.sub(r"^Week:\s*", "", text_of(w.find("h2")))
        weeks.append(
            {
                "week": label,
                "announcement": _section_text(w, "Announcement"),
                "description": _section_text(w, "Description"),
                "items": _items(w, label),
            }
        )
    return {
        "code": course["code"],
        "course": course["name"] or lbl("LabelCourseName"),
        "course_id": course["course_id"],
        "season_id": course["season_id"],
        "season": lbl("LabelseasonName") or course.get("season", ""),
        "url": url,
        "announcement": _rich_text(soup.find(id="ContentPlaceHolderright_ContentPlaceHoldercontent_desc")),
        "total_weeks": lbl("Labeltotalweeks"),
        "unseen_items": lbl("Labelunseencontent"),
        "weeks": weeks,
    }


def course_content(
    client: GiuClient,
    course: str,
    season_id: str | None = None,
    latest_weeks: int | None = None,
    content_type: str | None = None,
    unseen_only: bool = False,
) -> dict:
    data = course_page(client, resolve_course(client, course, season_id))
    weeks = data["weeks"][:latest_weeks] if latest_weeks else data["weeks"]
    if content_type or unseen_only:
        ct = (content_type or "").lower()
        weeks = [
            {**w, "items": [i for i in w["items"] if (not ct or ct in i["type"].lower()) and (not unseen_only or not i["seen"])]}
            for w in weeks
        ]
        weeks = [w for w in weeks if w["items"]]
    data["weeks"] = weeks
    return data


def _find_items(page: dict, content_ids, week, content_type, include_videos) -> list[dict]:
    items = [i for w in page["weeks"] for i in w["items"] if i["url"]]
    if content_ids:
        wanted = {int(x) for x in content_ids}
        items = [i for i in items if i["content_id"] in wanted]
        missing = wanted - {i["content_id"] for i in items}
        if missing:
            raise ValueError(f"Content id(s) {sorted(missing)} not found in {page['code']}")
        return items
    if week:
        items = [i for i in items if week.strip().lower() in i["week"].lower()]
    if content_type:
        items = [i for i in items if content_type.lower() in i["type"].lower()]
    if not include_videos:
        items = [i for i in items if not i["is_video"]]
    return items


# --------------------------------------------------------------------------- dashboard
def whats_new(client: GiuClient) -> dict:
    soup = client.get(APP + "HomePageStn.aspx", ttl=60).soup
    counts = []
    for r in table_rows(soup.find(id=re.compile(r"GridViewunseen$")))[1:]:
        if len(r) >= 2 and r[0]:
            code, name, _ = parse_label(r[0])
            unseen, _, total = r[1].partition("/")
            counts.append({"code": code, "course": name, "unseen": int(unseen or 0), "total": int(total or 0)})
    recent = []
    for r in table_rows(soup.find(id=re.compile(r"GridViewunseencontent$")))[1:]:
        if len(r) >= 5 and r[0]:
            code, name, _ = parse_label(r[0])
            recent.append({"code": code, "course": name, "title": r[1], "type": r[2], "posted": r[3], "by": r[4]})
    return {"unseen_per_course": counts, "latest_unseen": recent}


def notifications(client: GiuClient, limit: int = 30) -> list[dict]:
    soup = client.get(APP + "AllNotification.aspx", ttl=60).soup
    out = []
    for r in table_rows(soup.find(id=re.compile(r"grv_CourseContentCount$")))[1:]:
        if len(r) >= 9 and r[1]:
            code, name, _ = parse_label(r[6])
            out.append(
                {"title": r[1], "kind": r[2], "details": r[3], "date": r[4], "by": r[5], "code": code, "course": name, "id": r[8]}
            )
    return out[:limit] if limit else out


# --------------------------------------------------------------------------- files
def _check_upload_url(url: str) -> str:
    full = urljoin(CMS_BASE, url)
    p = urlparse(full)
    if p.hostname != "cms.giu-uni.de" or not p.path.lower().startswith("/uploads/"):
        raise ValueError("Only CMS course files (https://cms.giu-uni.de/Uploads/...) can be fetched")
    return full


def _nice_name(item: dict) -> str:
    ext = PurePosixPath(unquote(urlparse(item["url"]).path)).suffix
    num = f"{item['number']:02d} - " if item.get("number") is not None else ""
    return safe_filename(f"{num}{item['title']}")[:150] + ext


def download(
    client: GiuClient,
    course: str,
    season_id: str | None = None,
    content_ids: list[int] | None = None,
    week: str | None = None,
    content_type: str | None = None,
    include_videos: bool = False,
    overwrite: bool = False,
) -> dict:
    page = course_page(client, resolve_course(client, course, season_id))
    items = _find_items(page, content_ids, week, content_type, include_videos)
    root = client.settings.download_dir / safe_filename(f"{page['code']} {page['course']}".strip())
    files, errors = [], []
    for it in items:
        dest = root / safe_filename(it["week"] or "misc") / _nice_name(it)
        try:
            path, fresh = client.download(_check_upload_url(it["url"]), dest, overwrite=overwrite)
            files.append({"content_id": it["content_id"], "title": it["title"], "path": str(path), "downloaded": fresh})
        except Exception as e:  # keep going with the rest
            errors.append({"content_id": it["content_id"], "title": it["title"], "error": str(e)})
    return {"folder": str(root), "matched": len(items), "files": files, "errors": errors}


def read_file(
    client: GiuClient, course: str, content_id: int, season_id: str | None = None, start: int = 1, max_chars: int = 40000
) -> dict:
    page = course_page(client, resolve_course(client, course, season_id))
    item = _find_items(page, [content_id], None, None, True)[0]
    if item["is_video"]:
        raise ValueError("That item is a video; use cms_download to save it instead.")
    data, final = client.fetch_bytes(_check_upload_url(item["url"]), max_bytes=80 * 1024 * 1024)
    ext = PurePosixPath(urlparse(final).path).suffix.lower()
    parts = _extract(data, ext)
    start = max(1, start)
    chunks, used, last = [], 0, start - 1
    for i, text in enumerate(parts[start - 1 :], start=start):
        block = f"--- {'page' if ext == '.pdf' else 'slide' if ext in ('.pptx', '.ppt') else 'part'} {i} ---\n{text.strip()}\n"
        if used + len(block) > max_chars and chunks:
            break
        chunks.append(block[: max_chars - used])
        used += len(chunks[-1])
        last = i
    result: dict[str, Any] = {
        "title": item["title"],
        "type": item["type"],
        "file_type": ext.lstrip("."),
        "parts": len(parts),
        "showing": f"{start}-{last}" if chunks else "none",
        "text": "\n".join(chunks) if chunks else "(no extractable text — it may be a scanned PDF or images)",
    }
    if last < len(parts):
        result["next_start"] = last + 1
    return result


def _extract(data: bytes, ext: str) -> list[str]:
    if ext == ".pdf":
        from pypdf import PdfReader

        return [p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages]
    if ext == ".pptx":
        from pptx import Presentation

        slides = []
        for s in Presentation(io.BytesIO(data)).slides:
            texts = [sh.text_frame.text for sh in s.shapes if getattr(sh, "has_text_frame", False) and sh.text_frame.text]
            if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip():
                texts.append("[notes] " + s.notes_slide.notes_text_frame.text)
            slides.append("\n".join(texts))
        return slides
    if ext == ".docx":
        from docx import Document

        doc = Document(io.BytesIO(data))
        paras = [p.text for p in doc.paragraphs if p.text.strip()]
        return ["\n".join(paras[i : i + 60]) for i in range(0, len(paras), 60)] or [""]
    if ext in {".txt", ".md", ".csv", ".py", ".java", ".c", ".cpp", ".h", ".sql", ".js", ".html", ".xml", ".json", ".cs"}:
        text = data.decode("utf-8", errors="replace")
        return [text[i : i + 20000] for i in range(0, len(text), 20000)] or [""]
    raise GiuError(f"Can't extract text from {ext or 'this'} files; use cms_download to save it and open it instead.")
