# Part 1: understand a verified API response

## The path through the program

The command-line entry point builds a `FunnelQuery`. Live mode sends it through
`fetch_rates`; demo mode reads the saved result. Both paths then call the same
`parse_rates` and `validation_notes` functions before formatting the report.

1. **Query:** holds the universe, funnel name, UTC dates and expected step IDs.
   `end_exclusive` says exactly how the date boundary works. The payload always
   requests daily session-cohort rates, so counts cannot be mixed into this path.
2. **HTTP:** POST starts the query. A pending response supplies an operation path.
   GET checks that operation. Repeating POST is not the polling mechanism.
   A completed operation may still contain an error: `done` means finished,
   not successful.
3. **Parser:** Roblox returns one series per step, each with several dates.
   We flatten that nested structure into one `FunnelRow` per date and step.
   The dataclass names make each field's role visible. `frozen=True` prevents
   accidental reassignment after parsing.
4. **Validation:** malformed values stop the report. Incomplete or suspicious
   cohorts produce notes while preserving what Roblox actually returned.
5. **Display:** rates remain full-precision fractions until formatting turns
   `0.2753623127937317` into `27.54%`.

## Decisions worth understanding

**Why keep the query?** An API response has values, labels and timestamps but
does not repeat the selected metric and filters. A number between zero and one
is not proof that it is a conversion rate. The caller must know which request
produced the response.

**Why check timezone before taking the date?** `Z` and `+00:00` both represent
UTC. An offset timestamp must first be converted to UTC, or it can be assigned
to the wrong cohort. Daily buckets must land at UTC midnight.

**Why not use `float(value)` on everything?** That silently accepts inputs such
as `true`, `"0.5"`, `"NaN"` or missing data handled with an invented default.
This API's numeric contract is stricter. Booleans are particularly surprising:
Python considers them integers, so we explicitly exclude them.

**Why reject duplicates?** Silently keeping the last date/step value makes the
result depend on input order. Duplicates require investigation, not an arbitrary
winner.

**Why warnings for all-zero days?** A zero first-step rate gives no usable
starting-cohort baseline. The export cannot establish whether there were no
attempts, unavailable data or a reporting problem. It is not evidence that
every player abandoned the match.

**Why separate HTTP and parsing?** Parser tests run entirely offline. HTTP tests
can return controlled responses for immediate success, pending queries and
failures. No real key, rate limit or network outage affects those tests.

**Why restrict the polling path?** We attach an API key to requests. The server's
returned path is data that must be validated before constructing the next URL.
Redirects are also disabled so the key cannot follow an unexpected destination.

## Checks to run

From the VS Code terminal in the project root:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck demo
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest -q -k pending
.\.venv\Scripts\python.exe -m pytest -q -k "missing or zero or duplicate"
```

- Demo: 15 rows, sorted by date then numeric step; no validation notes.
- Full suite: all tests pass, without contacting Roblox.
- Pending-query test: one POST, then two GETs to the same operation.
- Data checks: missing data stays absent, duplicates fail, zero cohorts are flagged.

You can inspect the exact checks in `tests/test_funnelcheck.py`. The reconciliation
test compares all 15 date/step/name/rate records with the CSV excerpt, not just
the three final completion rates.

## Your first three interview questions

Answer these in your own words before reading the next implementation:

1. Why can HTTP 200 with `done: true` still be a failed query? Where do we check?
2. What is the difference between a missing step value and an explicit zero,
   and how does this program preserve that difference?
3. If September 19 and September 20 have very different numbers of funnel
   starters, why isn't the arithmetic mean of their completion rates the pooled
   conversion rate? What extra data and matching definitions would you need?

## Part 2: step-by-step drop-off

After parsing and displaying validation notes, the CLI passes the same rows and
query to `calculate_dropoffs` in `funnelcheck/analysis.py`. Both demo and live mode
use this path. The function assumes rows came from `parse_rates`; it is not a
second raw-input parser. It performs the additional checks needed to interpret
the rows and returns immutable `StepDropoff` records. It makes no HTTP requests
and prints nothing, so a later web endpoint can reuse it.

Read the function in this order:

1. `by_day` is a dictionary of dates, each holding another dictionary keyed by
   step ID. It makes looking up a particular date/step straightforward.
2. Sort expected step IDs numerically. Text sorting would place `"10"` before
   `"2"`. Iterate every requested date, including days absent from the response.
3. Check the starting rate and cumulative ordering. An unusable starting rate,
   flagged baseline status or any increase withholds the day's calculations.
   The starting-rate check uses the existing validator's 0.000001 tolerance.
   Increases are handled strictly here: even a tiny increase gives an explanation
   instead of a negative drop or a value silently clipped to zero.
4. `zip(steps, steps[1:])` makes pairs such as `(1, 2)`, `(2, 3)`, `(3, 4)`.
   Pair expected steps, not just the returned rows: missing step 2 must never
   turn into an apparent step 1-to-3 transition. Unselected numeric gaps are also
   withheld until we have explicit support for a funnel's nonconsecutive IDs.
5. Check both endpoints exist and their statuses are absent or `Valid` before
   subtracting. A flagged endpoint affects its pairs; a flagged baseline affects
   the whole day. Missing or suspicious values remain visible in the raw table.
6. Calculate the two measures, keeping full precision. Only CLI formatting
   rounds them. `None` means unavailable; zero means a calculated zero.

### Work through the maths

Synthetic example: 80% reach step 2 and 60% reach step 3.

```python
previous = 0.8
current = 0.6
percentage_points = (previous - current) * 100  # about 20 pp of starters
relative_drop = (previous - current) / previous  # about 0.25, displayed as 25%
```

The second measure asks what fraction of step-2 progress is lost before step 3.
It uses the previous step as its denominator. The first uses the starting cohort.
For your September 19 step 3-to-4 data, the output is **47.83 pp** and **50.00%**.
Subtract the full stored rates before rounding: subtracting the displayed 95.65%
and 47.83% instead would give 47.82 pp, losing precision too early.

If `previous` is positive and `current` is zero, relative drop is 100%. If both
are zero in an otherwise usable cohort, the pp difference is zero but relative
drop is undefined (`0 / 0`): return `None` and a reason. If the starting step is
zero too, withhold both measures for the whole day.

### Checks to run

From the project root:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck demo
.\.venv\Scripts\python.exe -m pytest -q tests/test_analysis.py
.\.venv\Scripts\python.exe -m pytest -q
```

- Demo: 12 transitions; September 19 step 3-to-4 is 47.83 pp and 50.00%.
- Edge cases: missing steps, empty days, zero denominators, increasing rates,
  flagged statuses and numeric ordering have explicit tests.
- The real-data test also checks that each day's pp drops add up to its starting
  rate minus final rate, in pp. Relative percentages must not be added this way.
- Tests use the saved example and labelled synthetic cases; they never need a key.

### Interview questions for this part

1. Why does going from 80% to 60% mean a 20 pp drop but a 25% relative drop?
2. Why is a zero-to-zero transition different from an 80%-to-zero transition?
3. If step 2 is missing, why do we pair the expected IDs instead of zipping the
   available rows? Which test would fail if we changed that?

## Part 3: compare daily cohorts

`compare_daily_cohorts` accepts two lists of parsed rows, their matching queries
and the selected before/after dates. The CLI currently selects both dates from
one response, so it passes the same rows and query for both sides. The pure
function also accepts separate responses; it never fetches anything itself.

Read the new logic in `funnelcheck/comparison.py` in this order:

1. `validate_comparison_queries` rejects different universe IDs, exact funnel
   names (so `v1` and `v2` cannot mix), or requested step sets. Order within that
   set does not affect compatibility. The query type fixes the rate metric,
   daily granularity and breakdown; its only filters are funnel name and steps.
   If we later add platform filters, for example, we must extend this check.
2. Validate dates. The earlier date must precede the later one, and each must be
   inside its own query window. Different query windows are fine: we compare
   one day from each, not the totals of those windows. The CLI runs these checks
   before asking for a key or sending a request.
3. Select each day's rows and index them by step ID. A missing row cannot shift
   later rows into the wrong matches, which could happen if we zipped the lists.
   Check labels across responses too; the parser already checks them within one.
4. Reuse `cohort_issue`, extracted from the drop-off function without changing its
   checks. An unusable starting rate or a cumulative increase blocks changes.
   A missing non-starting step or a flagged status blocks only that step's change.
5. Return every requested step with before/after rates, `change_pp`, and a reason
   when unavailable. The CLI turns `None` into `N/A`; it doesn't replace it with
   zero. Observed rates remain visible even when interpretation is withheld.

The arithmetic is deliberately small:

```python
change_pp = (after_rate - before_rate) * 100
```

This differs from drop-off's `previous - current`: here a positive result means
a higher completion rate on the later date. For match completion on September
19 and 20, the unrounded rates give **+21.11 percentage points**. Each daily rate
has its own starting cohort; we do not invent starter counts or combine them.

Unlike relative drop-off, this expression has no division. A measured before
rate of zero is usable if that day's starting cohort is valid. For example,
step 3 going from 0% to 50% is +50 pp; it does not need a relative percentage
increase, which would be undefined with that zero denominator.

### Compatibility is limited to known metadata

Matching names and labels cannot establish that game code logged events the same
way on both dates. A developer could change an event's meaning without renaming
it. Version the funnel when definitions change; an API response cannot prove that
this discipline was followed.

Daily cohorts can also have different time available to complete their steps.
The saved example has no completion cutoff metadata, so equal cohort maturity
cannot be verified. A comparison displays observed rates, not an update's causal
effect. An update date or note alone would not fix that limitation.

### Checks to run

From the project root:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck demo --compare 2026-09-19 2026-09-20
.\.venv\Scripts\python.exe -m pytest -q tests/test_comparison.py
.\.venv\Scripts\python.exe -m pytest -q
```

- The final row shows 27.54%, 48.65%, +21.11 pp; other rows match by step ID.
- Change the after date to September 21: match completion becomes +37.68 pp.
- Use `--compare 2026-09-20 2026-09-19`: expect a date-order error.
- Use September 22 as the after date: expect an exclusive-end error.
- Tests cover positive, negative and zero changes, differing query windows,
  incompatible metadata, missing values, bad statuses and invalid cohorts.

### Interview questions for this part

1. Why can't +21.11 pp alone prove an update improved match completion?
2. Why match steps by ID rather than by their positions in two lists?
3. If mobile-only filtering is added later, what must change in the comparison
   checks before comparing two responses?

## Part 4: questions linked to evidence

`build_investigations` takes parsed rows, their query and optional comparison
dates. It returns `Investigation` dataclasses; it doesn't print, contact a model
or make a request. The CLI displays them, and a later web API can serialize the
same records. This is a small deterministic rules system: identical inputs give
identical results, with each rule's ID included for inspection and tests.

Each result carries `rule_id`, `dates`, `step_ids`, `title`, `evidence`, `questions`
and `limitation`. Evidence states the observation; questions suggest checks;
limitations say what that observation cannot establish. Labels appear as quoted
references, not instructions or a source of guessed game semantics.

Read `funnelcheck/investigations.py` in this order:

1. Reuse `calculate_dropoffs` and, if requested, `compare_daily_cohorts`. Keep
   the underlying mathematics and compatibility checks in their existing modules.
2. Group rows and calculated transitions by day. Check the baseline, missing
   steps, statuses and selected step sequence before ranking any daily drops.
3. If data needs checking, return a `check_daily_data` prompt for that date.
   This policy is stricter than the raw table: a table can display the valid
   pairs in a partial funnel, but we cannot know the largest drop when a pair
   is missing. Other complete days can still receive their own prompts.
4. For a complete usable day, take the largest positive `percentage_points`.
   Keep ties within 1e-9 pp rather than picking an arbitrary winner due to
   floating-point noise. The tolerance is numerical, not a significance test.
5. If every selected step comparison is available, choose the largest absolute
   `change_pp`. `abs()` is used only for ranking: evidence keeps the sign, so a
   decrease is never presented as an increase. Unavailable comparisons produce
   `check_comparison_data`; all-zero changes produce no change prompt.

### Why rank by percentage points?

Consider a synthetic funnel with cumulative rates of 100%, 50%, 10%, 0%.
The first transition loses **50 pp of starters** and **50% of its previous step**.
The last loses **10 pp of starters** but **100% of its previous step**. Ranking by
pp highlights the larger share of that day's starting cohort. Ranking by relative
drop would highlight a different transition. Neither measure tells us which fix
would work, or how many people could be recovered.

Zero-to-zero transitions do not block the positive-to-zero drop elsewhere in
an otherwise usable funnel. Their relative rate remains undefined, but they are
not positive-drop candidates. An all-zero starting cohort remains unusable.

### What the questions accomplish

For your September 19 step 3-to-4 data, the prompt records **47.83 pp** and
**50.00% relative drop**, then asks what a playtest and logs show between those
events. It does not assume long rounds, confusing controls or an actual exit.
Game-specific prompts will need explicit step definitions and supporting data.

A bigger rate change creates a place to investigate, not confidence that an
update worked. Questions cover logging, player mix, time available to complete
and whether the pattern recurs. There are no invented sample sizes, p-values,
uplift predictions, universal bad-rate thresholds or algorithm-promotion rules.

### Checks to run

From the project root:

```powershell
.\.venv\Scripts\python.exe -m funnelcheck demo --compare 2026-09-19 2026-09-20
.\.venv\Scripts\python.exe -m pytest -q tests/test_investigations.py
.\.venv\Scripts\python.exe -m pytest -q
```

- Expect three daily-drop prompts referencing steps 3 and 4, plus one comparison
  prompt referencing step 5 and +21.11 pp.
- Each prompt shows evidence, investigation questions and a limit.
- Tests check incomplete cohorts, bad statuses, ties, unchanged rates, small
  nonzero rates, input order, positive/negative changes and offline operation.
- The synthetic 100%, 50%, 10%, 0% test verifies the denominator choice above.

### Interview questions for this part

1. In the 100%, 50%, 10%, 0% example, why does our rule choose the first transition
   rather than the final 100% relative drop?
2. Why can we display a valid pair in an incomplete daily table but withhold a
   claim about the largest drop for that day?
3. Why does identifying the largest drop not predict the benefit of fixing it?

## Part 5: a local FastAPI interface

The existing CLI is one way to call the analysis functions. HTTP is now another:

```text
Browser or Postman sends JSON
    -> FastAPI validates its outer shape with Pydantic
    -> FunnelQuery validates domain settings
    -> parse_rates checks the raw Roblox measurements
    -> existing drop-off, comparison and investigation functions run
    -> AnalysisReport is serialized to JSON
```

Read `funnelcheck/server.py` in this order:

1. **Input schemas.** `QueryInput`, `ComparisonInput` and `AnalyzeRequest` name
   the accepted fields. `extra="forbid"` prevents typos or unsupported filters
   from being silently ignored. Numeric IDs must be strings; dates must be ISO
   calendar strings rather than timestamps or Unix numbers. Metric and daily
   granularity are required literals, so a counts query cannot be explicitly
   labelled as supported. A caller can still supply incorrect context: these
   fields cannot independently authenticate the metric in an API response.
2. **Domain conversion.** `to_domain()` constructs the existing `FunnelQuery`.
   Its checks still enforce date ordering and unique step IDs. The HTTP adapter
   also limits report size to 366 days and 100 steps. Those are app policies,
   not inferred Roblox constraints.
3. **Raw result.** `result` remains a dictionary and goes through `parse_rates`.
   We do not create a permissive float schema that could turn `true` or `"0.5"`
   into a plausible measurement before our strict parser sees it.
4. **Composition.** `create_report` calls the functions we already tested and
   assembles a response. It contains no new conversion formulas, HTTP calls or
   file writes. The stored example supplies an executable request for `/docs`.
5. **HTTP errors.** The routes translate expected `DataError` exceptions into
   HTTP 422 with a message. Pydantic shape failures also return 422, with field
   locations. We don't catch every exception and disguise programming bugs as
   user mistakes. A report with missing rows can still be valid input, returning
   200 with notes and unavailable results.
6. **Output schema.** `AnalysisReport` describes the response and reuses our
   dataclasses. Dates become ISO strings, tuples become JSON arrays and Python
   `None` becomes JSON `null`. Numbers stay full precision; formatting belongs
   in the interface. Explicit units help avoid multiplying pp values by 100 twice.

### Why POST if nothing is being saved?

The client sends a structured JSON body to be processed. POST can perform a
calculation; it does not require a database insert. GET `/demo` instead retrieves
a report based on a known example. GET `/health` only says this local server is
running, not that your Roblox key works or that the data is healthy.

### Why keep the existing pure functions?

An HTTP status code is a transport concern. Rate validation and calculations
belong to the domain. Keeping those separate lets the CLI and future React app
use the same behaviour without reimplementing maths in each interface. This
milestone doesn't move API-key handling into the browser or server; CLI `fetch`
still performs the live Roblox queries.

### Checks to run

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_server.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn funnelcheck.server:app --host 127.0.0.1 --port 8000
```

While the last command is running:

1. Open `http://127.0.0.1:8000/docs`. Expand **GET /demo**, choose **Try it out**,
   enter before `2026-09-19` and after `2026-09-20`, then **Execute**. Expect 200,
   15 rows, 12 drop-offs, 5 comparisons and 4 investigation prompts.
2. Read the fifth comparison: `change_pp` should be approximately 21.112418.
   Its `before_rate` is approximately 0.275362, not 27.5362.
3. Change after to `2026-09-22`. Expect 422 because the example's end is exclusive.
4. Expand **POST /analyze** and execute the supplied example. Then change one
   measured `value` to `true` and execute again: expect 422, not a converted 1.
5. Restore the example and remove one data point. Expect 200 with validation
   notes and appropriate `null` calculations, not an invented zero.

Press Ctrl+C in the server terminal to stop it. Tests use FastAPI's `TestClient`
to exercise requests in-process without a network server or Roblox credentials.
The installed Starlette version currently emits an upstream warning about its
HTTPX-based TestClient; it does not affect these passing tests or report results.

### Interview questions for this part

1. What is the difference between validating the JSON shape and validating the
   meaning of a funnel measurement? Why do we need both?
2. Why can missing data return HTTP 200 with notes, while `value: true` returns 422?
3. Why should the JSON API return `null` for an unavailable calculation instead
   of zero or the text `"N/A"`?

## Part 6: the React interface

The screen is deliberately one page, with no router, global state library or
chart dependency. A CSS bar represents a recorded cumulative rate; the adjacent
text and tables contain the values for people who cannot use the visual alone.

Read `frontend/src/api.ts` first. `Report` describes the FastAPI response for
TypeScript. Type annotations do not validate incoming JSON at runtime: this
version relies on the local server's response schema. `requestReport` uses GET
for the demo, and POST with query/result JSON for an imported file. It translates
both a string domain error and Pydantic's field-error list into a readable message.
The Vite proxy sends those requests to Python; credentials aren't involved.

`percentage` multiplies a fraction by 100 for display. `points` doesn't: pp fields
are already percentage points. Both test for null/undefined explicitly. Avoid
`value || 'Unavailable'`, because zero is falsy in JavaScript and would disappear.
Very small nonzero values remain nonzero when formatted.

Next read `frontend/src/App.tsx`:

1. **State:** `report` is the last successful server response. `source` remembers
   demo versus the imported JSON in memory. `day` chooses a view of the existing
   rows; `before` and `after` are draft comparison selections.
2. **Requests:** `load` clears the previous report while a new one is pending.
   This prevents old numbers appearing to belong to a new file or date request.
   A 20-second timeout has a readable recovery message. AbortController cancels
   superseded requests and prevents their results overwriting newer ones.
3. **Initial effect:** load the demo on mount. Cleanup aborts the pending request
   on unmount. React StrictMode can run setup/cleanup again during development;
   cancelled responses must not update the screen.
4. **Date selection:** `cohortDays` uses UTC and the exclusive query end. It
   includes absent days, rather than deriving the options only from available
   rows. Changing the inspected day filters locally and needs no new request.
5. **Comparison:** pressing the button sends the chosen dates to Python. The
   table heading uses dates returned by Python, not unsubmitted dropdown values.
   A draft-change message helps prevent reading an old report under new dates.
6. **Import:** read a JSON file into memory, check its basic object shape and send
   it to Python. The backend still validates the data, metadata and dates. A saved
   comparison is validated and restored from the server response, including its controls.
7. **Presentation:** rates, pp changes and reasons come from the backend. Sorting
   step IDs, choosing visible rows and formatting numbers are frontend concerns.
   The frontend doesn't reimplement funnel conversion or investigation rules.

The source is formatted with Prettier so it is easier to read. You can rerun
`npm.cmd --prefix frontend run format` after editing. Package versions and the
lockfile are committed source material; installed dependencies and build output
are ignored by Git.

### Checks to run

Start Python on port 8000 and Vite on port 5173 using the README commands, then:

1. Confirm the demo's September 19 recorded final-step rate is **27.54%** and
   step 3-to-4 has **47.83 pp** / **50.00%** drop-off.
2. Change **Inspect a day** to September 21: expect **65.22%** at the final step.
3. Compare September 19 to 20: the final comparison should show **+21.11 pp**.
4. Change the after dropdown to September 21 without applying it. The table must
   still label September 20; applying it should then give **+37.68 pp**.
5. Import the example JSON. Try an invalid file too: a clear error should replace
   the report, with a way to retry or load the demo.
6. Run `npm.cmd --prefix frontend test` and `npm.cmd --prefix frontend run build`.
   The tests use a synthetic fixture with a measured zero and a completely absent
   day, so both cases are exercised independently of the real example.

### Interview questions for this part

1. Why do we format a rate in React but calculate drop-off and comparison changes
   in Python? What would go wrong if both implemented their own formulas?
2. Why should a comparison table use the applied dates returned by the server,
   rather than whichever dates are currently selected in the dropdowns?
3. Why is `value || 'Unavailable'` wrong when a legitimate measured rate is zero?

## Next part

Review the complete local flow before expanding it. Recorded update notes and
import convenience can be added in a separate small milestone.

## Part 7: saved snapshots and a restrained interface

`--output FILE.json` works with both `demo` and `fetch`. Before asking for a key
or sending a request, the CLI checks the filename extension and whether a file
already exists. The report is still printed normally. Only a successful run
with an explicit output path calls `save_response`.

Read `funnelcheck/export.py`:

1. Parse the response using the original `FunnelQuery`. Failed, pending or
   malformed responses cannot become apparently valid saved snapshots.
2. Group the validated rows by step ID to reconstruct the expected Roblox series
   shape. Include only the label, ID, timestamp, value and optional status.
   The exporter has no API-key parameter and does not copy arbitrary metadata.
3. Include the query's universe, funnel, metric, daily granularity, UTC window
   and expected steps. Rates alone cannot tell an importer this context.
4. Serialize before creating a file. Do not round, insert missing rows, or
   replace unknown values. `allow_nan=False` prevents non-standard JSON numbers.
5. Open with mode `"x"`, which means create exclusively. This prevents overwriting
   even if a file appears after the initial check. If writing a newly created
   file fails, remove that incomplete file and report the error.

The browser does not need a new importer: the saved format is already accepted
by `POST /analyze`. Tests save a file, parse it back, compare every original
measurement, and submit it through FastAPI. Live fetch is exercised using a fake
key and mocked response; no real credential is required for the tests.

Try the demo export and import it into the dashboard, then try saving to the
same filename again. Expect an error and the first file to remain unchanged.

The UI refresh changes typography, spacing, borders, colors and copy while
retaining the existing controls and calculation pipeline. The logo is a small
editable SVG, not a bitmap. Its check represents inspection, not certification
that an observed improvement is real or caused by an update.

Interview questions:

1. Why must the saved file contain query metadata as well as measurements?
2. Why isn't checking `path.exists()` alone enough to prevent overwriting a file?
3. Why save raw numeric rates instead of strings such as `"27.54%"`?

## Part 8: reported update timing

Follow `updates.py` → `server.py` → `UpdatePanel.tsx`.
The original rate parser and comparison calculations are unchanged.

1. `UpdateInput` rejects unsupported zones, blank names, non-boolean approximate
   flags and unexpected fields. `RecordedUpdate` keeps this human report separate
   from the Roblox measurements.
2. `update_in_utc` parses a wall-clock minute and uses `ZoneInfo`, not a hard-coded
   minus-one-hour offset. UK winter uses UTC; summer uses UTC+1. A round trip through
   UTC checks both possible clock-change interpretations. Zero valid instants means
   a nonexistent time; two means ambiguous. We reject both instead of guessing.
3. Each cohort day is the interval `[00:00 UTC, next midnight)`. If the day ends at
   or before deployment it is before; if it starts at or after deployment it is
   after; otherwise it is transition. At exactly midnight there is no transition day.
4. Suggest the nearest full day on either side within the requested window. This
   does not certify measurement completeness: existing missing-data checks still apply.
   If either side is absent, do not invent a date or suggestion.
5. The UI sends update edits only on Apply and renders labels from the returned
   report. Comparisons retain the applied update. Importing another file replaces it.

Checks to run: load the demo, confirm 04:00 UK → 03:00 UTC and the three timing
labels, click Compare surrounding full days, and confirm Match completed +37.68 pp.
Select September 20 as After: the table must say Transition day and show a caution.
Edit the deployment without applying: current labels must stay unchanged.
Remove the context: the measured rates and selected date comparison must remain.

Interview questions:
- Why does a deployment at 00:00 UTC have no transition day?
- Why is subtracting one hour from every UK timestamp incorrect?
- Why does labelling September 21 After update not prove its improvement was caused
  by the tutorial, or that every session used that version?

## Part 9: save inputs, recalculate outputs

`snapshot_from_rows` in `export.py` is shared by the CLI export and HTTP reports.
It serializes validated measurements while retaining zeros, missing rows, statuses
and full rate precision. The HTTP `snapshot` adds the validated update and applied
comparison. It deliberately excludes derived differences and questions.

`savedAnalysis.ts` turns that snapshot into a JSON Blob and starts a browser
download. It does not read the draft form fields, so the saved setup always matches
the displayed report. The temporary object URL is released after the download starts.

On import, `requestReport` leaves comparison metadata untouched when its dates
argument is undefined. Explicit null means Clear comparison. That distinction
prevents both accidental clearing on import and reappearing selections after clearing.
Selectors are restored from the validated response, never directly from untrusted JSON.
Every import goes through the same Python parser, validation and comparison functions.

Manual check: apply a new update name and Sep 19 → 21 comparison, save, refresh,
and import the downloaded file. Check the name, approximate flag, 03:00 UTC timing,
transition label and +37.68 pp result. Change a date without applying it, save again,
and confirm the file still contains the applied dates. Remove the update and clear
the comparison, then save/import: both must stay cleared.

Interview questions: Why save raw rates instead of rounded percentages? Why does
import validate an app-generated file again? How are undefined and null different
in the comparison request? Why should a download use applied rather than draft state?


## Part 10: an explicit hypothesis, a bounded diagnostic rule

The tutorial was added; there was no old tutorial. The owner describes a quick,
detailed explanation of the game. This tells us what changed, but does not identify
which analytics event measures the intended behaviour. The app therefore asks the
user to choose measurements instead of supplying a default event mapping.

Read `diagnostics.py` → `server.py` → `api.ts` → `HypothesisPanel.tsx`:

1. Frozen `Expectation` and `Hypothesis` dataclasses validate a nonblank statement,
   supported directions, unique step IDs and the 1–10 measurement limit. HTTP
   schemas additionally reject wrong types and unexpected fields. A hypothesis
   step must be part of its query; a typo cannot become an apparently missing event.
2. `evaluate_hypothesis` accepts rows already checked by `parse_rates`, their query,
   optional applied dates and the recorded update. It calls `compare_daily_cohorts`
   instead of implementing another set of quality checks or formulas. This keeps
   missing values, unusable starting cohorts, increasing cumulative rates and
   flagged Roblox statuses consistent with the comparison table.
3. Match by explicit step ID. The expected sign comes from the user, while the
   observed sign comes from the original `(after_rate - before_rate) * 100`.
   Rounding is display-only. Zero is a measurement; `None` means unavailable.
4. `build_update_context` checks that the selected dates are full days either side
   of the reported deployment. A transition day, same-side pair, absent update or
   absent comparison withholds a verdict. Valid descriptive rates and differences
   may remain visible beside the reason; this distinction prevents hiding data.
5. Compare observed and expected direction. Exact agreement supports a direction;
   an opposite nonzero direction conflicts; zero when change was expected is
   unchanged. Expecting unchanged and observing zero supports that expectation.
   No numerical tolerance represents statistical equivalence or significance.
6. The summary has explicit precedence: missing → insufficient; support plus
   conflict → mixed; any conflict → conflicting; any remaining unchanged → unchanged;
   otherwise supporting. Individual observations remain visible. There is no
   score, majority vote, pooling, weighting, causal model or predicted benefit.
7. Save `hypothesis` inputs in the validated snapshot, not computed `diagnostics`.
   Older snapshots default to no hypothesis. Import revalidates and recalculates.
   Date/update edits preserve the applied mapping, even when it becomes insufficient.
   Clearing sends explicit null so a file's original mapping cannot reappear.
8. React reads the native form only on Apply. No measurement is selected initially.
   Pending edits are labelled and excluded from saves; directions and arithmetic
   are evaluated in Python. Request retries reuse the failed attempt's settings.

### Concrete checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_diagnostics.py
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
```

In the running app:

1. Load demo; choose **Compare surrounding full days**. Write an illustrative
   hypothesis that more attempts reach match completion and select only step 5,
   expected Increase. Apply: expect 27.54% → 65.22%, +37.68 pp, Supporting observation.
   This does not establish that the tutorial caused it or was understood.
2. Edit step 5 to Decrease without applying. Results and Save analysis must still
   use Increase. Apply: expect Conflicting observation and an investigation question.
3. Select Sep 20 as After and compare: expect Insufficient evidence, a transition
   explanation and the preserved descriptive +21.11 pp. Return to full days.
4. Save, refresh and import the downloaded JSON. Expect the applied statement,
   mapping, update and dates restored. Change a source rate in a copy and import:
   results must recalculate. Removing a selected measurement produces missing
   evidence, not a measured zero. Setting a rate to `true` must return an error.
5. Clear the hypothesis; save/import. It must stay cleared. Remove the update or
   clear the comparison while a mapping is present: expect Insufficient evidence.
6. Import malformed JSON and confirm a clear message and Load demo recovery.
   Stop Python, request a comparison, restart Python and Retry request: the same
   dates and mapping must be retried. At phone width, measurements stack vertically
   and wide tables scroll within their panel.

### Interview questions

- Why does the diagnostic function call the existing comparison function rather
  than subtracting rates itself? Which invariants would otherwise be duplicated?
- Why can a supported direction still be insufficient to demonstrate the tutorial
  helped players understand the game? What additional measurement would you define?
- Why keep a valid transition-day difference visible but withhold its verdict?
- How does a missing selected measurement differ from a zero rate or unchanged rate?
- Why does an imported file require validation even when this app generated it?

The first release is intentionally limited to explicit expected directions for
one imported dataset and one applied daily comparison. Demo recording, CI for new changes
and any public hosting remain separate from local implementation.
