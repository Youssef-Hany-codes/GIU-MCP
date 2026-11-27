"""Small parsing helpers shared by the portal and CMS scrapers."""

from __future__ import annotations

import re
from typing import Iterable, Sequence, TypeVar

from bs4 import Tag

T = TypeVar("T")

# Course codes look like INCS101, MATH304, DE202, SM101, CSEN103 (sometimes "DE 202").
CODE_RE = re.compile(r"\b([A-Z]{2,5})\s?(\d{3}[A-Z]?)\b")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def text_of(el: Tag | None) -> str:
    return clean(el.get_text(" ", strip=True)) if el is not None else ""


def norm_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper()


def split_course(label: str) -> tuple[str, str]:
    """'GIU-Cairo.Informatics ... 3rd - INCS101 Programming III' -> ('INCS101', 'Programming III').

    Works whether the code comes before or after the name, and drops the faculty prefix.
    """
    label = clean(label)
    tail = label.split(" - ")[-1] if " - " in label else label
    m = CODE_RE.search(tail) or CODE_RE.search(label)
    if not m:
        return "", tail
    code = m.group(1) + m.group(2)
    name = clean(CODE_RE.sub("", tail, count=1)).strip("-– ")
    return code, name


def option_list(select: Tag | None, skip_blank: bool = True) -> list[tuple[str, str]]:
    """[(value, label)] for a <select>, dropping the 'Choose …' placeholder."""
    if select is None:
        return []
    out = []
    for o in select.find_all("option"):
        val = (o.get("value") or "").strip()
        if skip_blank and val in ("", "0"):
            continue
        out.append((val, clean(o.get_text())))
    return out


def table_rows(table: Tag | None) -> list[list[str]]:
    """Text of every row in `table` that holds no nested table."""
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        if tr.find("table"):
            continue
        rows.append([text_of(td) for td in tr.find_all(["td", "th"], recursive=False)])
    return rows


def find_table_with_header(root: Tag, *headers: str) -> Tag | None:
    """The table whose own first row holds all `headers` (not a layout table wrapping it)."""
    want = [h.lower() for h in headers]
    for t in root.find_all("table"):
        first = next((tr for tr in t.find_all("tr") if tr.find_parent("table") is t), None)
        if not first:
            continue
        cells = [text_of(c).lower() for c in first.find_all(["td", "th"], recursive=False)]
        if all(w in cells for w in want):
            return t
    return None


def match_one(query: str, items: Sequence[T], keys, what: str) -> T:
    """Pick the item whose code/name best matches `query` (case/space-insensitive).

    `keys(item)` returns the strings to match against (codes first, then names).
    """
    q = clean(query).lower()
    qn = norm_code(query).lower()
    exact, partial = [], []
    for it in items:
        ks = [k for k in keys(it) if k]
        if any(qn == norm_code(k).lower() or q == k.lower() for k in ks):
            exact.append(it)
        elif any(q in k.lower() or (len(qn) >= 3 and qn in norm_code(k).lower()) for k in ks):
            partial.append(it)
    hits = exact or partial
    if len(hits) == 1:
        return hits[0]
    choices = "; ".join(" / ".join(k for k in keys(it) if k) for it in (hits or items))
    if not hits:
        raise ValueError(f"No {what} matches {query!r}. Options: {choices}")
    raise ValueError(f"{query!r} matches several {what}s, be more specific: {choices}")


def dedupe(rows: Iterable[T]) -> list[T]:
    seen, out = set(), []
    for r in rows:
        key = repr(r)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def parse_score(text: str) -> tuple[float | None, float | None]:
    """'10 / 10' -> (10.0, 10.0); '' -> (None, None)."""
    m = re.match(r"\s*([\d.]+)?\s*/\s*([\d.]+)?", text or "")
    if not m:
        try:
            return float(text), None
        except (TypeError, ValueError):
            return None, None
    to_f = lambda s: float(s) if s not in (None, "") else None  # noqa: E731
    return to_f(m.group(1)), to_f(m.group(2))
