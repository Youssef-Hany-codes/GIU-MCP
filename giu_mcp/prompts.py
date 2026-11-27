"""Ready-made prompts. Apps that support MCP prompts show them as menu or slash commands
(e.g. Claude Desktop's "+" menu, `/mcp__giu__weekly_briefing` in Claude Code)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

Course = Annotated[str, Field(description='Course code or name, e.g. "INCS101" or "Databases"')]


def register(mcp) -> None:
    @mcp.prompt(
        name="weekly_briefing",
        title="Weekly briefing",
        description="Classes, deadlines, new CMS content, grades, attendance warnings and exams, in one summary.",
    )
    def weekly_briefing() -> str:
        return """Give me my GIU weekly briefing. Use the GIU tools to gather it, then keep it short and easy to scan:

1. **Classes**: from portal_schedule, my classes for today and the coming days, with times and rooms. Point out anything unusual, like a free day.
2. **Deadlines and announcements**: read the course announcement and the newest week of every current course (cms_courses, then cms_course_content with latest_weeks=1). List every deadline, quiz or exam you find, soonest first, with the date and course.
3. **New on the CMS**: what's new or not opened yet (cms_whats_new).
4. **Grades**: anything recently graded or worth my attention (portal_grades).
5. **Attendance**: any absence warnings (portal_attendance).
6. **Exams**: exams still ahead, with date, hall and seat (portal_exam_seats).

End with the three most important things for me to do this week."""

    @mcp.prompt(
        name="whats_due",
        title="What's due",
        description="Every upcoming deadline, quiz and exam across your courses, as a dated table.",
    )
    def whats_due() -> str:
        return """What do I need to do soon? Go through the course announcement and the two newest weeks of every current course (cms_courses, then cms_course_content with latest_weeks=2), plus recent CMS notifications (cms_notifications).

List every assignment, quiz, exam and submission deadline you find as a table: date, course, what it is, and where or how to submit. Sort by date, flag anything due in the next 48 hours, and say clearly when a date is unclear or only implied."""

    @mcp.prompt(
        name="quiz_me",
        title="Quiz me",
        description="Quizzes you one question at a time on a lecture or topic, using the real course material.",
    )
    def quiz_me(
        course: Course,
        topic: Annotated[str, Field(description="Lecture or topic to cover (default: the most recent lecture)")] = "",
    ) -> str:
        target = topic.strip() or "the most recent lecture"
        return f"""Quiz me on {target} from my {course} course.

First find the matching material with cms_course_content (lecture slides, notes or tutorial sheets) and read it with cms_read_file. Then quiz me:
- Ask one question at a time and wait for my answer before going on.
- Mix multiple choice, short answer and small problems, getting harder as I go.
- After each answer, tell me whether I'm right and explain briefly, citing the slide or page.
- Keep score. After 10 questions, or when I say stop, summarise what I should review.

Only ask about what's in the course material."""

    @mcp.prompt(
        name="summarize_lecture",
        title="Summarise a lecture",
        description="Main ideas, definitions, a worked example and self-check questions for one lecture.",
    )
    def summarize_lecture(
        course: Course,
        lecture: Annotated[str, Field(description="Lecture title or number (default: the most recent lecture)")] = "",
    ) -> str:
        target = lecture.strip() or "the most recent lecture"
        return f"""Summarise {target} from my {course} course.

Find it with cms_course_content and read the whole file with cms_read_file (keep calling it with next_start until you reach the end). Then give me:
- the main ideas, in plain words
- key definitions and formulas
- one worked example
- the points that look most likely to come up in an exam
- 5 quick self-check questions, with the answers at the very end"""

    @mcp.prompt(
        name="exam_prep",
        title="Exam prep plan",
        description="A day-by-day study plan for a course's exam, built from your exam seat, materials and grades.",
    )
    def exam_prep(
        course: Course,
        exam_date: Annotated[str, Field(description="Exam date, if it isn't on the portal yet")] = "",
    ) -> str:
        when = (
            f"The exam is on {exam_date.strip()}."
            if exam_date.strip()
            else "Look up the exam date, time, hall and seat with portal_exam_seats."
        )
        return f"""Help me prepare for my {course} exam. {when}

- List every lecture, tutorial and assignment topic so far from cms_course_content.
- Check my grades in this course with portal_grades to see where I'm weaker.
- Build a day-by-day study plan up to the exam that covers each topic at least once, puts more time on my weak spots, and leaves the last day for review. Name the exact CMS files to read each day.

Ask me how many hours a day I can study before you finalise the plan."""
