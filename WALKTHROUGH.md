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

## Next part: comparisons

There is deliberately no comparison calculation in this milestone. We first
need trustworthy records. Next we will retain filter/version metadata, reject
incompatible comparisons, and calculate a step's rate change in percentage
points. We will walk through that code with a concrete before/after example.
An observed difference will not be described as proof of an update's effect.
