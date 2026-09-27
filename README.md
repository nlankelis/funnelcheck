# FunnelCheck

A local tool for checking Roblox funnel data, finding where recorded progress drops,
and comparing daily cohorts around a game update.

I started FunnelCheck after analysing my Roblox game, **Size It Up**. I could see
where attempts stopped progressing, but needed a repeatable way to check the data
and compare dates after changes to the game. FunnelCheck brings validated rates,
update timing and questions to investigate into one report that can be saved and reopened.

**Python · FastAPI · React · TypeScript · pytest · Vitest**

## What it does

- Imports saved analytics JSON with its original query context.
- Validates measurements and explains missing or unusable data.
- Shows cumulative completion and step-by-step drop-off, with distinct denominators.
- Compares two daily cohorts and annotates a reported update time.
- Suggests rule-based questions linked to the observed data.
- Saves measurements and applied settings so an analysis can be reopened and recalculated.

The included example runs without a Roblox account or API key. The dashboard works
locally, processes imports in memory and has no accounts, database or chatbot.
CSV import is not implemented; the supported input is saved JSON.

## A real example: the tutorial update

The bundled [MatchCompletion_v2 example](examples/matchcompletion.json) contains
15 rates from Size It Up. All 15 were checked against the corresponding
[CSV excerpt](tests/fixtures/matchcompletion_rates.csv); other test cases deliberately
modify copies or use synthetic data to exercise edge cases.

The game owner reported a tutorial update at **approximately September 20, 2026,
04:00 UK time**, explaining the game and showing players how to play. This converts
to **03:00 UTC**. The daily cohort buckets use UTC:

| Cohort date | Timing relative to reported deployment | Match completion |
| --- | --- | ---: |
| September 19 | Before | 27.54% |
| September 20 | Transition day: includes time before and after | 48.65% |
| September 21 | After | 65.22% |

September 19 to 21 shows **+37.68 percentage points** in recorded match completion.
That observed difference **does not establish that the tutorial caused it**.
The data does not identify sample sizes, player mix or which deployed game version
each attempt experienced. Match completion also does not directly measure tutorial comprehension.

## Run locally

Install **Git, Python 3.12 and Node.js 24** (including npm). These runtime lines are
recorded in `.python-version` and `.nvmrc` and used by CI. Package installation needs
internet access; the bundled demo does not contact Roblox.

```text
git clone https://github.com/nlankelis/funnelcheck.git
cd funnelcheck
```

### Windows / PowerShell

Create a new environment and install dependencies from the project root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd --prefix frontend ci
```

If the Python launcher is unavailable, use `python -m venv .venv` after checking
that `python --version` reports Python 3.12. No environment activation is required.
Use `npm.cmd` in PowerShell to avoid execution-policy restrictions on `npm.ps1`.

Start the backend in one terminal:

```powershell
.\.venv\Scripts\python.exe -m uvicorn funnelcheck.server:app --host 127.0.0.1 --port 8000
```

In a second terminal, also from the project root:

```powershell
npm.cmd --prefix frontend run dev
```

### macOS / Linux

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix frontend ci
.venv/bin/python -m uvicorn funnelcheck.server:app --host 127.0.0.1 --port 8000
```

In a second terminal, from the project root:

```sh
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. The demo loads automatically. Stop either server with
Ctrl+C in its terminal. Both servers must run: Vite forwards `/api` requests to Python
on port 8000. Interactive API documentation is at **http://127.0.0.1:8000/docs**
(its documentation UI loads assets from a CDN).

**Common setup issues:** run commands from the repository root; confirm the Python
server is running if reports fail to load; stop an existing development server if
port 8000 or 5173 is already occupied. For a dependency change, rerun the relevant
install command. Do not copy `.venv` or `node_modules` between machines.

## Data and saved analyses

Use **Import saved JSON** with the bundled example or a snapshot from the CLI.
The document contains `query` and the completed Roblox operation `result`, plus
optional `update` and `compare` settings. Query metadata must describe the request
that produced those measurements; a response alone cannot verify that pairing.

**Save analysis** downloads normalized measurements, query context and the applied
settings. Unapplied form edits, calculated results, arbitrary operation metadata and
headers are excluded. Importing the file validates it again and recalculates the report.
Cleared update/comparison settings remain `null`. Without saving, refreshing restores
the demo. There is no server-side persistence.

The UI accepts files up to 5 MB; the HTTP analysis supports at most 366 days and
100 selected steps. These are application limits, not Roblox rules.

An optional CLI can fetch live data. From PowerShell, substitute the universe,
funnel, UTC date window and step IDs for your experience:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck fetch --universe 10765553159 --funnel MatchCompletion_v2 --start 2026-09-19 --end-exclusive 2026-09-22 --steps 1 2 3 4 5 --output data\matchcompletion.json
```

The end date is **exclusive**. The CLI prompts for an analytics key with
`universe.analytics:read`, or uses an existing `ROBLOX_API_KEY` environment variable.
It does not load `.env` files. Keys are not entered in the browser or saved in exports.
The client submits once, then polls pending operations with bounded attempts and
HTTP timeouts. Step discovery is currently manual. `--output` refuses to overwrite
an existing file and saves query/measurement inputs, without update or comparison settings.

To inspect the same measurements without credentials:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck demo --compare 2026-09-19 2026-09-21
```

On macOS/Linux, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

## How the analysis works

For rates stored as fractions:

| Calculation | Formula | Interpretation |
| --- | --- | --- |
| Step drop | `(previous - current) × 100` | Percentage points of the starting cohort |
| Relative step drop | `(previous - current) / previous` | Fraction of the preceding step's rate |
| Daily change | `(after - before) × 100` | Signed percentage-point difference |

Calculations use the original precision; rounding happens for display. Missing
measurements stay unavailable, never zero. A zero denominator makes relative drop
undefined. Invalid starting cohorts, cumulative increases, missing steps and flagged
statuses withhold affected calculations and produce explanations.

Comparisons check universe, funnel/version, step selection and labels. The supported
query type fixes the daily session-cohort metric and FunnelStep breakdown; additional
filters are rejected rather than silently compared. Matching names still cannot prove
unchanged event definitions or equal time for both cohorts to finish.

Update timing uses `Europe/London` or UTC rules. A day spanning deployment is labelled
transition; exactly midnight UTC starts an after day. Ambiguous/nonexistent UK
clock-change times are rejected instead of guessed. Labels reflect reported timing,
not confirmed exposure to a game version.

Questions are deterministic rules linked to dates, steps and evidence. They do not
infer game mechanics from labels, prescribe a predicted fix or use a language model.

## Code structure

| Location | Responsibility |
| --- | --- |
| `funnelcheck/funnel.py` | Query model, strict parsing and measurement validation |
| `funnelcheck/analysis.py`, `comparison.py` | Pure drop-off and comparison calculations |
| `funnelcheck/updates.py`, `investigations.py` | Update timing and evidence-linked questions |
| `funnelcheck/server.py` | FastAPI schemas and report composition |
| `funnelcheck/export.py` | Shared serialization of validated measurements |
| `funnelcheck/api.py`, `__main__.py` | Optional Roblox client and CLI |
| `frontend/src/` | React controls, API adapter, display and browser downloads |
| `tests/`, `frontend/src/*.test.*` | Backend and frontend automated checks |

The HTTP endpoints are `GET /health`, `GET /demo`, `POST /demo` (with update/comparison
settings) and `POST /analyze` (with saved inputs). A valid report can return **200** with
quality notes; invalid input returns **422**. These endpoints never fetch from Roblox.
Responses include calculated fields and a validated `snapshot` suitable for saving.

For development explanations and interview questions, see [WALKTHROUGH.md](WALKTHROUGH.md).

## Tests and CI

From PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pytest -q
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

On macOS/Linux, use `.venv/bin/python` and `npm`. The frontend build checks TypeScript
before producing `frontend/dist`. A successful build is not a deployed site; production
hosting and API routing are outside the current scope.

Tests cover the real CSV/API fixture agreement, malformed rates, missing/zero values,
comparison compatibility, timezone boundaries, HTTP validation, import/export round
trips, request failures and applied-versus-draft UI state. API client tests use fake
responses. No Roblox key, live game or running app server is needed to run tests.

[CI](.github/workflows/ci.yml) runs on pushes and pull requests and can be started
manually in GitHub Actions. Python tests and the offline CLI demo run on Windows
and Linux; frontend tests and the production build run on Linux with Node 24.
Dependency downloads are cached, but each job installs dependencies and runs its checks.
The workflow needs no custom secrets and does not deploy the app.

## Scope and limitations

- One supported metric: daily session-cohort completion rates. Sessions/attempts are
  not unique players, and drop-off is not a confirmed departure or its cause.
- The UI compares individual days within one imported dataset. It does not pool
  daily rates; matching denominators would be needed for a weighted aggregate.
- Rate-only data cannot establish player counts, statistical significance, causal
  update effects or predicted improvements. Three example days are not a controlled experiment.
- The current step-drop calculation requires consecutive numeric step IDs.
- CSV import, retention metrics, Home recommendation metrics, automatic funnel/step
  discovery and multi-file comparison controls are not implemented.
- There are no genre-based promotion thresholds, algorithm guarantees, accounts,
  database, billing or public deployment.

## References

- [Roblox Analytics Query API](https://create.roblox.com/docs/cloud/guides/analytics)
- [Roblox supported metrics](https://create.roblox.com/docs/cloud/guides/analytics/metrics)
- [Roblox funnel events](https://create.roblox.com/docs/production/analytics/funnel-events)
- [GitHub setup-python](https://github.com/actions/setup-python) and
  [setup-node](https://github.com/actions/setup-node), used by the CI workflow
