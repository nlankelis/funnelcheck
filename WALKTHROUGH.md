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

## Next part: comparisons

Date comparisons are still a separate milestone. We will retain filter/version
metadata, reject incompatible comparisons, and calculate a step's rate change
in percentage points. An observed difference will not be described as proof
of an update's effect.
