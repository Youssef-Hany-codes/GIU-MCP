"""Call every tool through the MCP server against the live sites, for whatever account is
signed in, and print a short summary. Downloads go to a temporary folder.

    python scripts/smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("GIU_DOWNLOAD_DIR", tempfile.mkdtemp(prefix="giu-smoke-"))

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402

from giu_mcp.server import mcp  # noqa: E402

FAILED: list[str] = []


def payload(result):
    """Pull the JSON payload out of a call_tool result, whatever shape the SDK returns."""
    if isinstance(result, tuple):
        result = result[-1] if result[-1] is not None else result[0]
    if isinstance(result, dict) and set(result) == {"result"}:
        return result["result"]
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        return structured["result"] if set(structured) == {"result"} else structured
    content = getattr(result, "content", result)
    if isinstance(content, list) and content and hasattr(content[0], "text"):
        try:
            return json.loads(content[0].text)
        except json.JSONDecodeError:
            return content[0].text
    return result


async def call(name: str, expect_error: bool = False, **args):
    t = time.perf_counter()
    try:
        data, err = payload(await mcp.call_tool(name, args)), None
    except ToolError as e:
        data, err = None, str(e)
    dt = time.perf_counter() - t
    ok = (err is not None) if expect_error else (err is None)
    if not ok:
        FAILED.append(name)
    status = "OK " if ok else "ERR"
    print(f"\n{status} {name}({', '.join(f'{k}={v!r}' for k, v in args.items())})  [{dt:.1f}s]")
    if err:
        print("    ", err[:300])
    return data


def show(obj, limit=500):
    s = json.dumps(obj, ensure_ascii=False, default=str)
    print("   ", s[:limit] + (" …" if len(s) > limit else ""))


async def main():
    show(await call("giu_profile"))

    d = await call("portal_schedule")
    if d:
        print("    days:", [(x["day"], len(x["slots"])) for x in d["days"]], d.get("message", ""))

    d = await call("portal_group_schedule")
    if d and d["groups"]:
        d2 = await call("portal_group_schedule", group=d["groups"][0]["id"])
        if d2:
            print("    group:", d2["group"], [(x["day"], len(x["slots"])) for x in d2["days"]])

    grades = await call("portal_grades")
    if grades:
        show(grades["midterms"], 300)
        for c in grades["courses"]:
            print(f"    {c['code']:8} {c['course'][:32]:32} items={len(c['items'])}")
        if grades["courses"]:
            await call("portal_grades", course=grades["courses"][0]["code"])

    seasons = await call("portal_previous_grades")
    for s in (seasons or {}).get("seasons", [])[:8]:
        d = await call("portal_previous_grades", season=s["name"])
        if d and d["courses"]:
            print("    season:", d["season"], [(c["code"], len(c["items"])) for c in d["courses"]])
            break

    d = await call("portal_transcript")
    if d:
        print("    cumulative GPA:", d["cumulative_gpa"], d.get("messages", ""))
        for y in d["years"]:
            for s in y["semesters"]:
                print(f"    {y['study_year']} | {s['semester']:30} courses={len(s['courses'])} hours={s.get('total_hours')}")

    d = await call("portal_attendance")
    if d:
        for c in d["courses"]:
            print(f"    {c['code']:8} attended={c['attended']} absent={c['absent']}")
        if d["courses"]:
            d2 = await call("portal_attendance", course=d["courses"][0]["code"])
            if d2:
                show(d2["courses"][0].get("sessions", [])[:1], 300)

    d = await call("portal_exam_seats")
    if d is not None:
        print("    exams:", len(d))

    courses = await call("cms_courses") or []
    print("    current:", [c["code"] for c in courses])
    every = await call("cms_courses", all_seasons=True) or []
    print("    seasons:", sorted({(c["season_id"], c["season"]) for c in every}))

    readable = None
    for c in courses:
        d = await call("cms_course_content", course=c["code"], latest_weeks=2)
        if not d:
            continue
        items = [i for w in d["weeks"] for i in w["items"]]
        print(f"    {d['code']} weeks={d['total_weeks']} shown={len(d['weeks'])} items={len(items)} announcement={d['announcement'][:60]!r}")
        readable = readable or next(
            ((c["code"], i) for i in items if (i["url"] or "").lower().endswith((".pdf", ".pptx", ".docx"))), None
        )
        if readable:
            break

    if courses:
        await call("cms_course_content", course=courses[0]["code"], unseen_only=True, latest_weeks=1)
    past = next((c for c in every if courses and c["season_id"] != courses[0]["season_id"]), None)
    if past:
        d = await call("cms_course_content", course=past["code"], season_id=past["season_id"], latest_weeks=1)
        if d:
            print("    past season:", d["code"], d["season"])

    d = await call("cms_whats_new")
    if d:
        print("    unseen:", [(x["code"], x["unseen"]) for x in d["unseen_per_course"]])
    d = await call("cms_notifications", limit=3)
    if d is not None:
        print("    notifications:", len(d))

    if readable:
        code, item = readable
        d = await call("cms_read_file", course=code, content_id=item["content_id"], max_chars=600)
        if d:
            print("    ", {k: d[k] for k in d if k != "text"})
        d = await call("cms_download", course=code, content_ids=[item["content_id"]])
        if d:
            print("     saved:", [f["path"] for f in d["files"]], d["errors"])

    await call("portal_grades", expect_error=True, course="no such course xyz")

    print("\n" + ("ALL PASSED" if not FAILED else f"FAILED: {', '.join(FAILED)}"))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
