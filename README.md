# FunnelCheck

A Python project for checking Roblox funnel data and, in later milestones,
comparing compatible cohorts around recorded updates.

**Part 1:** read-only API client, daily-rate parser, validation and an offline
example from Size It Up. There is no web app yet. The parser does not make
recommendations, calculate pooled conversion or claim an update caused a change.

## Run the first part on Windows

Open this folder in VS Code, then choose **Terminal > New Terminal**.
An isolated `.venv` has been prepared on this computer. Run these commands from
the project root; no environment activation or execution-policy change is needed:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck demo
.\.venv\Scripts\python.exe -m pytest -q
```

The demo uses no key and makes no network requests. Expect **15 records and
0 validation notes**. Match completion should be **27.54%, 48.65%, 65.22%** for
September 19, 20 and 21. Tests use fake HTTP responses and require no Roblox access.

In VS Code, use **Python: Select Interpreter** and choose
`.venv\Scripts\python.exe` if the Python extension is installed.

## Make the same live request you tested in Postman

```powershell
.\.venv\Scripts\python.exe -m funnelcheck fetch --universe 10765553159 --funnel MatchCompletion_v2 --start 2026-09-19 --end-exclusive 2026-09-22 --steps 1 2 3 4 5
```

Enter your analytics key at the hidden terminal prompt. Nothing appears while
you type or paste it; press Enter when finished. The key stays in process memory
and is not written to disk. Alternatively, an existing `ROBLOX_API_KEY`
environment variable is used. This version does not load `.env` files.

Use a key limited to the experience with `universe.analytics:read`. Do not put
keys in source code, command-line arguments, screenshots or GitHub. `.gitignore`
excludes `.venv`, `.env` files and `data/` for any future private responses.

The client submits one POST. If Roblox reports a pending operation, it polls
that same operation with GET, up to 15 times, two seconds apart. Each request has
a 15-second HTTP timeout; the overall run can take longer than 30 seconds.
Errors exit with code 1; a displayed report exits with code 0, including reports
with validation notes. A successful report is not a statistical-quality badge.

The date range is UTC and the end is **exclusive**. The steps are the IDs already
discovered in Postman, not guessed from names. Automatic discovery is a later
addition. No response is automatically saved, and polling paths are restricted
to the requested universe on Roblox's API host.

## New machine setup

Install Python 3.12 or newer, then:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The prepared environment on this computer uses an existing bundled Python
3.12 runtime; it does not install a system-wide Python. Virtual environments
are machine-specific and must not be committed or copied to another computer.

## What to read

- `funnelcheck/funnel.py`: query context, immutable records, parsing and validation.
- `funnelcheck/api.py`: HTTP request, polling, timeout and error handling.
- `funnelcheck/__main__.py`: command-line wiring and display formatting.
- `WALKTHROUGH.md`: explanations, checks and interview questions.

The example JSON contains the API values provided by the game owner on
2026-09-26. The CSV fixture is a 15-row excerpt of their export for the same
metric and dates. All 15 numeric rates matched; operation metadata was omitted
from the example. These are real observed rates, not synthetic player counts.
Other tests deliberately mutate copies to check failure cases.

## Limits and next milestone

- Supports daily session-cohort completion rates with one FunnelStep breakdown.
- Does not infer event meaning from a step label or treat sessions as unique players.
- Missing rows are not zero. All-zero cohorts receive a warning, not an abandonment score.
- No sample-size, significance or causal claims are made from rate-only data.
- The response does not echo its metric: query context must stay paired with it.
- Comparison logic, CSV importing, automatic step discovery, a FastAPI endpoint
  and a React interface will be introduced in separate milestones.

For comparisons we will check funnel version, filters, dates and definitions
before calculating percentage-point differences. Different tracking versions
will not be silently combined.

## References

- [Roblox Analytics Query API](https://create.roblox.com/docs/cloud/guides/analytics)
- [Supported metrics](https://create.roblox.com/docs/cloud/guides/analytics/metrics)
- [Funnel event semantics](https://create.roblox.com/docs/production/analytics/funnel-events)
- [HTTPX](https://www.python-httpx.org/quickstart/)
- [pytest](https://docs.pytest.org/en/stable/getting-started.html)
