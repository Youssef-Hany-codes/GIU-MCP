# GIU MCP

Let your AI assistant read **your own** GIU student portal (`portal.giu-uni.de`) and CMS
(`cms.giu-uni.de`). Ask things like *"what's my schedule tomorrow?"*, *"how am I doing in
Databases?"*, *"summarise this week's lecture slides"* or *"download all OS lab manuals"*.

It works with any AI app that supports local MCP servers: Claude Code, Claude Desktop,
Cursor, VS Code (Copilot agent mode), Windsurf, Gemini CLI, OpenAI Codex CLI, LM Studio
and others.

> **Unofficial.** This is a student project, not made or endorsed by GIU. It reads the
> same pages you see in your browser, signed in as you.
>
> **Free for personal and non-commercial use.** If you share it or build on it, keep the
> credit line. Commercial use needs permission first. See [License](#license).

## Your account and your data stay with you

- Every student runs their **own copy** on their own computer with their **own** GIU
  username and password. Nobody else, including whoever shared this with you, ever sees
  your password or your data.
- `giu-mcp login` stores your password in your operating system's credential store
  (Windows Credential Manager / macOS Keychain / Linux Secret Service), not in a plain file.
- Your password is only ever sent to `portal.giu-uni.de` and `cms.giu-uni.de`. Every
  redirect is checked first, so it is never sent anywhere else.
- **Read-only.** It never submits anything: no registration, evaluations, excuses,
  uploads or payments. The only thing it writes is files you ask it to download, saved
  to your own Downloads folder.

## Install

You need Python 3.11 or newer, or [uv](https://docs.astral.sh/uv/), which installs Python
for you.

**Option A: uv (recommended)**

```powershell
# Windows: install uv once (macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

uv tool install git+https://github.com/Youssef-Hany-codes/GIU-MCP
```

**Option B: pipx**

```powershell
pipx install git+https://github.com/Youssef-Hany-codes/GIU-MCP
```

To update later, run `uv tool upgrade giu-mcp` (or `pipx upgrade giu-mcp`), then restart
your AI app.

## Set up (2 minutes)

```powershell
giu-mcp login     # asks for your GIU username + password, checks them, saves them securely
giu-mcp status    # optional: confirms the portal and CMS both work
giu-mcp config    # prints the exact snippet for your AI app
```

Use the same username and password as the browser sign-in box on the portal.

Then add the server to your app with the snippet `giu-mcp config` printed:

- **Claude Code:** run the printed `claude mcp add giu …` command once.
- **Claude Desktop:** Settings → Developer → Edit Config, paste the `"giu"` entry inside
  `"mcpServers"`, then restart Claude Desktop.
- **Cursor / Windsurf / Gemini CLI / most others:** the same `"mcpServers"` JSON in that
  app's MCP config file.
- **VS Code:** `giu-mcp config vscode`. **Codex CLI:** `giu-mcp config codex`.

Restart the app, and the GIU tools will show up. To switch accounts, run
`giu-mcp login` again. To remove yours, run `giu-mcp logout`.

## What it can do

| Tool | What it returns |
| --- | --- |
| `giu_profile` | Name, student ID, username, faculty, major |
| `portal_schedule` | Your weekly timetable (day → period → course, room, group, type) |
| `portal_group_schedule` | Timetable of any study group (empty = list groups) |
| `portal_grades` | This semester's midterm % per course + every quiz/assignment score |
| `portal_previous_grades` | The same for a past season (empty = list seasons) |
| `portal_transcript` | Final grades, hours and cumulative GPA, by semester |
| `portal_attendance` | Absence warning levels, attended/absent counts, every session |
| `portal_exam_seats` | Exam date, time, hall and seat |
| `cms_courses` | Your CMS courses (current or all seasons) |
| `cms_course_content` | Course announcement + weekly items (slides, assignments, videos) |
| `cms_whats_new` | Unopened content per course and the latest posts |
| `cms_notifications` | Recent CMS notifications |
| `cms_read_file` | Text of a course PDF / PPTX / DOCX so the AI can summarise or quiz you |
| `cms_download` | Save course files to `~/Downloads/GIU/<course>/<week>/` |

Courses can be named loosely: `"INCS101"`, `"databases"`, `"German"`.

## Settings

All optional. Set them as environment variables, or in a `.env` file in the config
folder (`giu-mcp status` shows where that is).

| Variable | Meaning |
| --- | --- |
| `GIU_USERNAME`, `GIU_PASSWORD` | Use these instead of the account saved by `giu-mcp login` |
| `GIU_DOMAIN` | Windows domain, only if sign-in fails without it |
| `GIU_DOWNLOAD_DIR` | Where `cms_download` saves files (default `~/Downloads/GIU`) |
| `GIU_TIMEOUT` | Request timeout in seconds (default 45) |

## Troubleshooting

- **"No GIU account is set up"**: run `giu-mcp login` in a terminal.
- **"GIU rejected the username/password"**: run `giu-mcp login` again. If your password
  changed, the saved one is stale.
- **A tool returns a "Portal message"**: that page is closed on the portal right now
  (for example, outside its registration or evaluation window).
- **Tools disappeared after an update**: restart the AI app.

## Reporting problems

If a tool breaks or shows wrong data, GIU probably changed that page.
[Open an issue](https://github.com/Youssef-Hany-codes/GIU-MCP/issues) saying which tool
and what went wrong. **Don't paste your password, grades or other personal data** into
the issue.

## For developers

```powershell
git clone https://github.com/Youssef-Hany-codes/GIU-MCP
cd GIU-MCP
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\giu-mcp.exe login
.venv\Scripts\python.exe scripts\smoke_test.py    # calls every tool for your account
```

- `giu_mcp/client.py`: one `requests` session with NTLM auth. Redirects are followed by
  hand so each hop is host-checked before the handshake. It also replays ASP.NET WebForms
  postbacks for the "choose a course / season / year" dropdowns. The portal only sets up
  its session once `Home.aspx` loads, so the client opens that page first.
- `giu_mcp/portal.py`, `giu_mcp/cms.py`: HTML scrapers for each page.
- `giu_mcp/server.py`: the MCP tools (Python MCP SDK 2.x, stdio transport).
- `giu_mcp/credentials.py`, `giu_mcp/config.py`, `giu_mcp/cli.py`: per-user account
  storage and the `giu-mcp` command.
- `scripts/discover.py`: a read-only crawler that saves your pages to `.discovery/`
  (git-ignored, it holds personal data), for fixing scrapers when GIU changes a page.
- `scripts/smoke_test.py`: calls every tool against the live sites for whichever account
  is signed in. It picks courses and seasons from that account, so it works for anyone.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). In plain words (the license text is what counts):

- **You can** use, copy, modify and share it for any non-commercial purpose: personal
  use, study, student clubs, schools and universities.
- **You must** give credit. Anyone you pass it on to, changed or not, must also get the
  license terms and this line:

  `Required Notice: Copyright (c) 2026 Youssef-Hany-codes (https://github.com/Youssef-Hany-codes/GIU-MCP)`

- **You need permission** for any commercial use, such as selling it, putting it in a
  paid product or service, or using it at a company. Ask through
  [GitHub](https://github.com/Youssef-Hany-codes).
