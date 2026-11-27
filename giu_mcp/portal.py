"""Scrapers for the student portal, portal.giu-uni.de/GIUb/EXTStudent/.

Everything here is read-only: pages are fetched, and the only postbacks replayed are
the "choose a course / season / year" dropdowns that switch what a page displays.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from bs4 import BeautifulSoup, Tag

from .client import GiuClient, Page, PortalBounce
from .config import PORTAL_BASE
from .util import (
    clean,
    dedupe,
    find_table_with_header,
    match_one,
    norm_code,
    option_list,
    parse_score,
    split_course,
    table_rows,
    text_of,
)

EXT = f"{PORTAL_BASE}/GIUb/EXTStudent/"
ODD_EVEN = {"#999999": "odd weeks", "#66ccff": "even weeks"}


# --------------------------------------------------------------------------- helpers
def _with_retry(client: GiuClient, fn: Callable[[], Any]) -> Any:
    """Run fn; if the portal bounced us to Home (stale session state), warm up and retry once."""
    try:
        return fn()
    except PortalBounce:
        return fn()


def _choose(client: GiuClient, path: str, select_name: str, value: str) -> Page:
    """GET `path` and replay the dropdown postback for `select_name` = `value`."""
    return _with_retry(client, lambda: _pick(client, client.get(EXT + path), select_name, value))


def _pick(client: GiuClient, page: Page, select_name: str, value: str) -> Page:
    return client.postback(page, event_target=select_name, fields={select_name: value})


def _walk(client: GiuClient, path: str, select_name: str, values: list[str]) -> tuple[Page, list[Page]]:
    """GET `path`, then choose each value in turn, chaining postbacks like a browser would."""

    def run():
        base = page = client.get(EXT + path)
        results = []
        for v in values:
            page = _pick(client, page, select_name, v)
            results.append(page)
        return base, results

    return _with_retry(client, run)


def _label(soup: BeautifulSoup, suffix: str) -> str:
    return text_of(soup.find(id=f"ContentPlaceHolder1_{suffix}"))


def _course_option(options: list[tuple[str, str]], query: str) -> tuple[str, str]:
    def keys(o):
        code, name = split_course(o[1])
        return [code, name, o[1]]

    return match_one(query, options, keys, "course")


# --------------------------------------------------------------------------- profile
def profile(client: GiuClient) -> dict:
    soup = client.get(EXT + "Home.aspx").soup
    user = ""
    for a in soup.find_all("a"):
        t = text_of(a)
        if re.search(r"\[\d+\]$", t):
            user = t
            break
    m = re.match(r"(.+)\[(\d+)\]$", user)
    return {
        "name": _label(soup, "lbl_message"),
        "username": m.group(1) if m else user,
        "student_id": m.group(2) if m else "",
        "application_no": _label(soup, "LBL_AppNo"),
        "faculty": _label(soup, "lbl_fac"),
        "major": _label(soup, "lbl_maj"),
    }


# --------------------------------------------------------------------------- schedules
def _periods(header_row: Tag) -> list[dict]:
    out = []
    for td in header_row.find_all(["td", "th"], recursive=False)[1:]:
        t = text_of(td)
        m = re.match(r"(.*?Period)\s*(\d{1,2}:\d{2})?\s*-?\s*(\d{1,2}:\d{2})?", t)
        out.append(
            {"period": clean(m.group(1)) if m else t, "start": m.group(2) if m else None, "end": m.group(3) if m else None}
        )
    return out


def _grid(table: Tag, parse_cell: Callable[[Tag], list[dict]]) -> dict:
    rows = table.find_all("tr", recursive=False) or (table.tbody.find_all("tr", recursive=False) if table.tbody else [])
    periods = _periods(rows[0])
    days = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue
        day = text_of(cells[0]).rstrip(":")
        if not day or day.endswith("Session"):
            continue
        slots = []
        for i, td in enumerate(cells[1:]):
            entries = parse_cell(td)
            if entries:
                p = periods[i] if i < len(periods) else {"period": f"Period {i + 1}", "start": None, "end": None}
                slots.append({**p, "classes": entries})
        days.append({"day": day, "free": not slots, "slots": slots})
    return {"days": days}


def _weeks_flag(td: Tag) -> str | None:
    for el in [td, *td.find_all(["td", "table"])]:
        col = (el.get("bgcolor") or "").lower()
        if col in ODD_EVEN:
            return ODD_EVEN[col]
    return None


def _my_cell(td: Tag) -> list[dict]:
    out = []
    for tr in td.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3 or tr.find("table"):
            continue
        course, room = text_of(tds[0]), text_of(tds[1])
        lines = [clean(x) for x in tds[2].get_text("\n").split("\n") if clean(x)]
        kind = lines[-1] if len(lines) > 1 else ""
        group = " ".join(lines[:-1]) if len(lines) > 1 else (lines[0] if lines else "")
        if course or room:
            entry = {"course": course, "room": room, "group": group, "type": kind}
            if w := _weeks_flag(td):
                entry["weeks"] = w
            out.append(entry)
    return out


def my_schedule(client: GiuClient) -> dict:
    soup = client.get(EXT + "GroupSchedule_m.aspx").soup
    anchor = soup.find(id="ContentPlaceHolder1_rw2") or soup.find(id=re.compile(r"ContentPlaceHolder1_rw\d"))
    if anchor is None:
        msg = _label(soup, "L_Restricted") or "No schedule table found on the page."
        return {"message": msg, "days": []}
    result = _grid(anchor.find_parent("table"), _my_cell)
    if note := _label(soup, "L_Restricted"):
        result["message"] = note
    return result


def _group_cell(td: Tag) -> list[dict]:
    out = []
    for tr in td.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 3 or tr.find("table"):
            continue
        group, room, what = text_of(tds[0]), text_of(tds[1]), text_of(tds[2])
        if not (group or room or what):
            continue
        m = re.match(r"(.*?\d{3}[A-Z]?)\s+(\w+)$", what)
        entry = {
            "group": group,
            "room": room,
            "course_code": norm_code(m.group(1)) if m else what,
            "type": m.group(2) if m else "",
            "course": tds[2].get("title", ""),
        }
        if w := _weeks_flag(tr) or _weeks_flag(td):
            entry["weeks"] = w
        out.append(entry)
    return out


def schedule_groups(client: GiuClient) -> list[dict]:
    soup = client.get(EXT + "GroupsSchedule_m.aspx", ttl=600).soup
    return [{"id": v, "name": n} for v, n in option_list(soup.find(id="ContentPlaceHolder1_scdTpLst"))]


def group_schedule(client: GiuClient, group: str) -> dict:
    groups = schedule_groups(client)
    pick = next((g for g in groups if g["id"] == group), None) or match_one(
        group, groups, lambda g: [g["name"]], "schedule group"
    )
    page = _choose(client, "GroupsSchedule_m.aspx", "ctl00$ContentPlaceHolder1$scdTpLst", pick["id"])
    table = page.soup.find(id="ContentPlaceHolder1_scdTbl")
    if table is None:
        return {"group": pick["name"], "days": [], "message": "No timetable returned for this group."}
    return {"group": pick["name"], **_grid(table, _group_cell)}


# --------------------------------------------------------------------------- grades
def _midterms(soup: BeautifulSoup) -> list[dict]:
    out = []
    for row in table_rows(soup.find(id="ContentPlaceHolder1_midDg"))[1:]:
        if len(row) >= 2 and row[0]:
            code, name = split_course(row[0])
            try:
                pct = float(row[1])
            except ValueError:
                pct = None
            out.append({"code": code, "course": name, "midterm_percent": pct})
    return out


def _grade_items(soup: BeautifulSoup) -> list[dict]:
    table = find_table_with_header(soup, "Quiz/Assignment", "Grade")
    items, current = [], ""
    for row in table_rows(table)[1:]:
        if len(row) < 3 or row[0] == "Quiz/Assignment":
            continue
        current = row[0] or current
        score, out_of = parse_score(row[2])
        items.append(
            {
                "category": current,
                "item": row[1],
                "score": score,
                "out_of": out_of,
                "graded_by": row[3] if len(row) > 3 else "",
            }
        )
    return items


def _grade_courses(soup: BeautifulSoup) -> list[tuple[str, str]]:
    return option_list(soup.find(id="ContentPlaceHolder1_smCrsLst"))


def current_grades(client: GiuClient, course: str | None = None) -> dict:
    options = _grade_courses(client.get(EXT + "CheckGrade_m.aspx").soup)
    picks = [_course_option(options, course)] if course else options
    base, pages = _walk(client, "CheckGrade_m.aspx", "ctl00$ContentPlaceHolder1$smCrsLst", [v for v, _ in picks])
    result: dict[str, Any] = {"midterms": _midterms(base.soup), "courses": []}
    for (_, label), page in zip(picks, pages):
        code, name = split_course(label)
        result["courses"].append({"code": code, "course": name, "items": _grade_items(page.soup)})
    return result


def previous_seasons(client: GiuClient) -> list[dict]:
    soup = client.get(EXT + "CheckGradePreviousSemester_m.aspx", ttl=600).soup
    return [{"id": v, "name": n} for v, n in option_list(soup.find(id="ContentPlaceHolder1_ddl_season"))]


def _season_candidates(seasons: list[dict], season: str) -> list[dict]:
    by_id = [s for s in seasons if s["id"] == season.strip()]
    if by_id:
        return by_id
    # The portal lists some season names twice under different ids; try each of them.
    exact = [s for s in seasons if s["name"].lower() == clean(season).lower()]
    return exact or [match_one(season, seasons, lambda s: [s["name"]], "season")]


def previous_grades(client: GiuClient, season: str, course: str | None = None) -> dict:
    candidates = _season_candidates(previous_seasons(client), season)
    first = None
    for pick in candidates:
        result = _season_grades(client, pick, course)
        if result["courses"]:
            return result
        first = first or result
    return first


def _season_grades(client: GiuClient, pick: dict, course: str | None) -> dict:
    def run() -> dict:
        page = _choose(client, "CheckGradePreviousSemester_m.aspx", "ctl00$ContentPlaceHolder1$ddl_season", pick["id"])
        options = _grade_courses(page.soup)
        out: dict[str, Any] = {"season": pick["name"], "midterms": _midterms(page.soup), "courses": []}
        if not options:
            out["message"] = "No courses recorded for this season."
            return out
        for value, label in [_course_option(options, course)] if course else options:
            page = _pick(client, page, "ctl00$ContentPlaceHolder1$smCrsLst", value)
            code, name = split_course(label)
            out["courses"].append({"code": code, "course": name, "items": _grade_items(page.soup)})
        return out

    return _with_retry(client, run)


# --------------------------------------------------------------------------- transcript
def transcript_years(client: GiuClient) -> list[dict]:
    soup = client.get(EXT + "Transcript_m.aspx", ttl=600).soup
    return [{"id": v, "name": n} for v, n in option_list(soup.find(id="ContentPlaceHolder1_stdYrLst"))]


def _parse_transcript(soup: BeautifulSoup) -> dict:
    semesters: list[dict] = []
    current: dict | None = None
    cumulative = _label(soup, "cmGpaLbl")
    for row in table_rows(soup.find(id="ContentPlaceHolder1_trsTbl")):
        cells = [clean(c) for c in row]
        joined = " ".join(cells)
        if not any(cells) or cells[:2] == ["Semester", "Course Name"]:
            continue
        if "Cumulative GPA" in joined:
            cumulative = next((c for c in reversed(cells) if re.fullmatch(r"[\d.]+", c)), cumulative)
            continue
        if len(cells) >= 2 and cells[1].startswith("Semester GPA"):
            # ['', 'Semester GPA in Current Study Group', <gpa>, <grade>, <total hours>]
            if current is not None:
                padded = cells + [""] * (5 - len(cells))
                current["semester_gpa"] = padded[2] or padded[3] or None
                current["total_hours"] = padded[4] or None
            continue
        if len(cells) >= 5 and current is not None:
            current["courses"].append(
                {"group": cells[0], "course": cells[1], "numeric": cells[2], "grade": cells[3], "hours": cells[4]}
            )
            continue
        if len(cells) == 2 and cells[0] and not cells[1]:
            current = {"semester": cells[0], "courses": []}
            semesters.append(current)
    return {
        "study_year": _label(soup, "stdYrLbl"),
        "cumulative_gpa": cumulative,
        "semesters": [s for s in semesters if s["courses"]],
        "messages": [m for m in (_label(soup, "msgLbl"), _label(soup, "msgLbl2"), _label(soup, "lblAction")) if m],
    }


def transcript(client: GiuClient, year: str | None = None) -> dict:
    """One study year, or (year=None) every year that has courses, newest first."""
    years = transcript_years(client)
    if year:
        pick = next((y for y in years if y["id"] == year), None) or match_one(year, years, lambda y: [y["name"]], "year")
        page = _choose(client, "Transcript_m.aspx", "ctl00$ContentPlaceHolder1$stdYrLst", pick["id"])
        return _parse_transcript(page.soup)

    # Newest first: skip future years that are still empty, stop at the first empty year
    # before enrolment. Each year needs a fresh page: chaining year postbacks gets HTTP 500.
    out: list[dict] = []
    messages: list[str] = []
    cumulative = None
    for y in reversed(years):
        page = _choose(client, "Transcript_m.aspx", "ctl00$ContentPlaceHolder1$stdYrLst", y["id"])
        data = _parse_transcript(page.soup)
        cumulative = cumulative or data["cumulative_gpa"]
        messages.extend(m for m in data["messages"] if m not in messages)
        if data["semesters"]:
            out.append(data)
        elif out:
            break
    result: dict[str, Any] = {"cumulative_gpa": cumulative, "years": out}
    if messages:
        result["messages"] = messages
    return result


# --------------------------------------------------------------------------- attendance
SESSION_RE = re.compile(
    r"^(?P<season>\S+)\s+-\s+(?P<code>[A-Z]+\s?\d+\w*)\s+-\s+(?P<course>.+?)\s+-\s+(?P<group>.+?)\s+"
    r"(?P<kind>[A-Za-z]+)\s+@(?P<date>\d{4}\.\d{2}\.\d{2})\s*-\s*(?P<rest>.*)$"
)


def _absence_report(soup: BeautifulSoup) -> list[dict]:
    rows = table_rows(soup.find(id="DG_AbsenceReport"))
    return [
        {"code": norm_code(r[1]), "course": r[2], "absence_level": r[3], "policy": r[0]}
        for r in rows[1:]
        if len(r) >= 4 and r[1]
    ]


def _sessions(soup: BeautifulSoup) -> list[dict]:
    out = []
    for r in table_rows(soup.find(id="DG_StudentCourseAttendance"))[1:]:
        if len(r) < 3:
            continue
        m = SESSION_RE.match(r[2])
        s = {"status": r[1], "session": r[2]}
        if m:
            rest = [clean(x) for x in m.group("rest").split(" - ")]
            s.update(
                {
                    "date": m.group("date").replace(".", "-"),
                    "type": m.group("kind"),
                    "group": m.group("group"),
                    "slot": next((x for x in rest if x.lower().startswith("slot")), None),
                }
            )
        out.append(s)
    return out


def attendance(client: GiuClient, course: str | None = None, include_sessions: bool = True) -> dict:
    path = "ClassAttendance_ViewStudentAttendance_b.aspx"
    first = client.get(EXT + path).soup
    options = option_list(first.find("select", attrs={"name": "DDL_Courses"}))
    picks = [_course_option(options, course)] if course else options
    base, pages = _walk(client, path, "DDL_Courses", [v for v, _ in picks])
    result: dict[str, Any] = {"absence_warnings": _absence_report(base.soup), "courses": []}
    for (_, label), page in zip(picks, pages):
        if not result["absence_warnings"]:
            result["absence_warnings"] = _absence_report(page.soup)
        sessions = _sessions(page.soup)
        code, name = split_course(label)
        entry = {
            "code": code,
            "course": name,
            "attended": sum(s["status"].lower() == "attended" for s in sessions),
            "absent": sum(s["status"].lower() == "absent" for s in sessions),
            "total": len(sessions),
        }
        if include_sessions:
            entry["sessions"] = sessions
        result["courses"].append(entry)
    return result


# --------------------------------------------------------------------------- exams
def exam_seats(client: GiuClient) -> list[dict]:
    soup = client.get(EXT + "ViewExamSeat_m.aspx").soup
    table = find_table_with_header(soup, "Exam Day", "Seat") or soup.find(id="Table2")
    rows = table_rows(table)
    if not rows:
        return []
    out = []
    for r in rows[1:]:
        if len(r) < 8 or not r[0]:
            continue
        label, _, season = r[0].rpartition(" - ")
        code, name = split_course(label or r[0])
        out.append(
            {
                "code": code,
                "course": name,
                "season": season,
                "day": r[1],
                "date": r[2],
                "start": r[3],
                "end": r[4],
                "hall": r[5],
                "seat": r[6],
                "exam_type": r[7],
            }
        )
    return dedupe(out)
