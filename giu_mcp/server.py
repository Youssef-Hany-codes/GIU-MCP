"""MCP server exposing the GIU student portal and CMS as read-only tools."""

from __future__ import annotations

import functools
from typing import Any, Callable

import anyio
import requests
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, cms, portal
from .client import GiuError, get_client
from .config import ConfigError

INSTRUCTIONS = """\
Tools for the German International University (GIU) student portal (portal.giu-uni.de)
and course management system (cms.giu-uni.de), signed in as the student.

- portal_* tools: schedule, grades, transcript, attendance, exam seats. Grades use the
  German scale: 0.7 (A+) is the best, 4.0 is the lowest pass, 5.0 / F fails. "Fx" in a
  transcript means the course was not passed in that round; a later "Makeup" semester
  lists the retake. Midterm/coursework percentages are out of 100.
- cms_* tools: course materials. Call cms_course_content to see the weeks and items,
  then cms_read_file (text of a PDF/PPTX/DOCX) or cms_download (save to disk).
- Courses can be named by code ("INCS101"), name ("Databases") or CMS id.
- All tools only read data; nothing is submitted, registered or paid on the user's behalf.
"""

mcp = MCPServer(name="giu", title="GIU Portal & CMS", version=__version__, instructions=INSTRUCTIONS)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
WRITE_LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)


async def _run(fn: Callable[..., Any], *args, **kwargs) -> Any:
    """Run a blocking scraper in a worker thread so the server stays responsive.

    Expected failures become ToolError so their message (e.g. the list of valid course
    names) reaches the model; anything else is a crash and stays opaque.
    """
    try:
        return await anyio.to_thread.run_sync(functools.partial(fn, get_client(), *args, **kwargs))
    except (ValueError, GiuError, ConfigError) as e:
        raise ToolError(str(e)) from e
    except requests.Timeout as e:
        raise ToolError("The GIU site took too long to answer; try again in a moment.") from e
    except requests.RequestException as e:
        raise ToolError(f"Could not reach the GIU site: {e}") from e


# ============================================================================ portal
@mcp.tool(annotations=READ)
async def giu_profile() -> dict:
    """The signed-in student's name, ID, username, faculty and major."""
    return await _run(portal.profile)


@mcp.tool(annotations=READ)
async def portal_schedule() -> dict:
    """The student's own weekly timetable: for each day, the periods (with times) and the
    course, room, group and session type (Lecture / Tut / Lab) in each."""
    return await _run(portal.my_schedule)


@mcp.tool(annotations=READ)
async def portal_group_schedule(group: str | None = None) -> dict:
    """Timetable of any study group, e.g. "Informatics and Computer Science 3rd".

    Leave `group` empty to list every group that has a timetable.
    """
    if not group:
        return {"groups": await _run(portal.schedule_groups)}
    return await _run(portal.group_schedule, group)


@mcp.tool(annotations=READ)
async def portal_grades(course: str | None = None) -> dict:
    """Current-semester grades: midterm percentage per course, plus every graded quiz,
    assignment and other item (score / out of, and who graded it).

    `course` limits the detail to one course; leave empty for all courses.
    """
    return await _run(portal.current_grades, course)


@mcp.tool(annotations=READ)
async def portal_previous_grades(season: str | None = None, course: str | None = None) -> dict:
    """Coursework and midterm grades of a past season: `season` is a name like "Spring 2026"
    or an id from the list.

    Leave `season` empty to list the seasons available.
    """
    if not season:
        return {"seasons": await _run(portal.previous_seasons)}
    return await _run(portal.previous_grades, season, course)


@mcp.tool(annotations=READ)
async def portal_transcript(year: str | None = None) -> dict:
    """Official transcript: final grade, numeric grade and credit hours per course, grouped
    by semester, plus the cumulative GPA.

    `year` is a study year like "2025-2026"; leave empty for every year the student was
    enrolled (slower: one page per year).
    """
    return await _run(portal.transcript, year)


@mcp.tool(annotations=READ)
async def portal_attendance(course: str | None = None, include_sessions: bool | None = None) -> dict:
    """Attendance: absence warning levels, and attended/absent counts per course.

    With `course`, also lists every session (date, type, group, attended or absent).
    Set `include_sessions` to override that.
    """
    sessions = include_sessions if include_sessions is not None else bool(course)
    return await _run(portal.attendance, course, sessions)


@mcp.tool(annotations=READ)
async def portal_exam_seats() -> list[dict]:
    """Exam hall and seat assignments: course, date, time, hall, seat and exam type."""
    return await _run(portal.exam_seats)


# ============================================================================ CMS
@mcp.tool(annotations=READ)
async def cms_courses(all_seasons: bool = False) -> list[dict]:
    """Courses on the CMS (code, name, CMS course_id and season_id).

    By default only the current season; `all_seasons=True` includes past ones.
    """
    return await _run(cms.all_courses if all_seasons else cms.current_courses)


@mcp.tool(annotations=READ)
async def cms_course_content(
    course: str,
    season_id: str | None = None,
    latest_weeks: int | None = None,
    content_type: str | None = None,
    unseen_only: bool = False,
) -> dict:
    """A course's CMS page: the course announcement and, week by week (newest first), the
    week's announcement, description and items (lecture slides, assignments, videos …),
    each with a content_id for cms_read_file / cms_download and whether it was opened.

    Filters: `latest_weeks` (only the N newest weeks), `content_type` (e.g. "Lecture",
    "Assignment", "VoD"), `unseen_only`. `season_id` picks a past season (see cms_courses).
    """
    return await _run(cms.course_content, course, season_id, latest_weeks, content_type, unseen_only)


@mcp.tool(annotations=READ)
async def cms_whats_new() -> dict:
    """Unopened CMS content: count per course and the most recently posted items."""
    return await _run(cms.whats_new)


@mcp.tool(annotations=READ)
async def cms_notifications(limit: int = 30) -> list[dict]:
    """Recent CMS notifications (new weeks, new content, announcements), newest first."""
    return await _run(cms.notifications, limit)


@mcp.tool(annotations=READ)
async def cms_read_file(
    course: str, content_id: int, season_id: str | None = None, start: int = 1, max_chars: int = 40000
) -> dict:
    """Extract the text of a course file (PDF, PPTX, DOCX or plain text) so it can be read,
    summarised or quizzed on. Get `content_id` from cms_course_content.

    Long files come back in parts: pass the returned `next_start` as `start` to continue.
    """
    return await _run(cms.read_file, course, content_id, season_id, start, max_chars)


@mcp.tool(annotations=WRITE_LOCAL)
async def cms_download(
    course: str,
    content_ids: list[int] | None = None,
    week: str | None = None,
    content_type: str | None = None,
    include_videos: bool = False,
    season_id: str | None = None,
    overwrite: bool = False,
) -> dict:
    """Save course files to the local download folder (default ~/Downloads/GIU), organised
    as <course>/<week>/<number - title>. Files already there are skipped unless `overwrite`.

    Pick files with `content_ids`, or filter by `week` (e.g. "2026-11-21"), `content_type`
    (e.g. "Lecture slides"); with no filter, every file of the course is downloaded.
    Videos are skipped unless `include_videos=True`.
    """
    return await _run(cms.download, course, season_id, content_ids, week, content_type, include_videos, overwrite)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
