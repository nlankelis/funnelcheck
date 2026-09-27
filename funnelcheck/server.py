"""Local HTTP adapter for saved responses; run with uvicorn funnelcheck.server:app."""

from datetime import date
import json
from pathlib import Path
import re
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictBool, StrictStr

from .analysis import StepDropoff, calculate_dropoffs
from .comparison import StepComparison, compare_daily_cohorts, validate_comparison_queries
from .funnel import DataError, FunnelQuery, FunnelRow, parse_rates, validation_notes
from .investigations import Investigation, build_investigations
from .export import snapshot_from_rows
from .updates import RecordedUpdate, UpdateContext, build_update_context


def _iso_date(value: Any) -> Any:
    # Reject timestamps and Unix numbers instead of coercing them into cohort dates.
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("Use an ISO calendar date: YYYY-MM-DD.")
    return value


ISODate = Annotated[date, BeforeValidator(_iso_date)]
NumericID = Annotated[StrictStr, Field(pattern=r"^[1-9][0-9]*$", max_length=20)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryInput(InputModel):
    universe_id: NumericID
    funnel_name: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    metric: Literal["FunnelCohortSessionCompletionRate"]
    granularity: Literal["OneDay"]
    start: ISODate
    end_exclusive: ISODate
    step_ids: Annotated[list[NumericID], Field(min_length=1, max_length=100)]

    def to_domain(self) -> FunnelQuery:
        query = FunnelQuery(
            self.universe_id, self.funnel_name, self.start, self.end_exclusive,
            tuple(self.step_ids),
        )
        if (query.end_exclusive - query.start).days > 366:
            raise DataError("This local endpoint accepts at most 366 days per report.")
        return query


class ComparisonInput(InputModel):
    before: ISODate
    after: ISODate


class UpdateInput(InputModel):
    name: Annotated[StrictStr, Field(min_length=1, max_length=120, pattern=r"\S")]
    local_time: StrictStr
    time_zone: Literal["Europe/London", "UTC"]
    approximate: StrictBool

    def to_domain(self) -> RecordedUpdate:
        return RecordedUpdate(self.name.strip(), self.local_time, self.time_zone, self.approximate)


class DemoRequest(InputModel):
    compare: ComparisonInput | None = None
    update: UpdateInput | None = None


class SavedAnalysis(InputModel):
    query: QueryInput
    result: dict[str, Any] = Field(description="Completed Roblox operation envelope, including done and response.")
    compare: ComparisonInput | None = None
    update: UpdateInput | None = None


class AnalyzeRequest(SavedAnalysis):
    source: Annotated[StrictStr, Field(max_length=2048)] | None = None


class AnalysisReport(BaseModel):
    snapshot: SavedAnalysis = Field(description="Validated inputs for saving and reanalysis; no computed results.")
    query: QueryInput
    units: dict[str, str]
    rows: list[FunnelRow]
    validation_notes: list[str]
    dropoffs: list[StepDropoff]
    comparisons: list[StepComparison] | None = Field(description="null when no comparison was requested.")
    investigations: list[Investigation]
    limitations: list[str]
    update_context: UpdateContext | None


EXAMPLE_PATH = Path(__file__).resolve().parent.parent / "examples" / "matchcompletion.json"
EXAMPLE = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

app = FastAPI(
    title="FunnelCheck", version="0.1.0",
    description="Local analysis of saved daily session-cohort rates. No credentials or Roblox requests are used by these endpoints.",
)


def create_report(payload: AnalyzeRequest) -> AnalysisReport:
    """Compose existing pure functions; keep HTTP error handling in the routes."""
    query = payload.query.to_domain()
    dates = None
    if payload.compare is not None:
        dates = (payload.compare.before, payload.compare.after)
        validate_comparison_queries(query, query, *dates)
    rows = parse_rates(payload.result, query)
    comparisons = None
    if dates is not None:
        comparisons = compare_daily_cohorts(rows, query, dates[0], rows, query, dates[1])
    return AnalysisReport(
        snapshot=SavedAnalysis(
            **snapshot_from_rows(query, rows), compare=payload.compare, update=payload.update,
        ),
        query=payload.query,
        update_context=build_update_context(payload.update.to_domain(), query, dates) if payload.update else None,
        units={
            "completion_rate": "fraction", "before_rate": "fraction", "after_rate": "fraction",
            "relative_drop": "fraction", "percentage_points": "percentage_points", "change_pp": "percentage_points",
        },
        rows=rows,
        validation_notes=validation_notes(rows, query),
        dropoffs=calculate_dropoffs(rows, query),
        comparisons=comparisons,
        investigations=build_investigations(rows, query, dates),
        limitations=[
            "Rates alone do not establish sample sizes, statistical significance or pooled conversion.",
            "Observed changes do not establish an update's effect or predict improvement.",
            "Matching labels cannot verify unchanged logging definitions or equal cohort maturity.",
            "The submitted query must describe the request that produced the result; the response does not verify that pairing.",
        ],
    )


def _report_or_422(payload: AnalyzeRequest) -> AnalysisReport:
    try:
        return create_report(payload)
    except DataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/demo", response_model=AnalysisReport)
def demo(before: ISODate | None = None, after: ISODate | None = None) -> AnalysisReport:
    """Analyse the saved Size It Up example; optionally supply both comparison dates."""
    if (before is None) != (after is None):
        raise HTTPException(status_code=422, detail="Provide both before and after, or neither.")
    comparison = None if before is None else {"before": before.isoformat(), "after": after.isoformat()}
    payload = AnalyzeRequest.model_validate({**EXAMPLE, "compare": comparison})
    return _report_or_422(payload)


@app.post("/demo", response_model=AnalysisReport)
def analyze_demo(options: DemoRequest) -> AnalysisReport:
    """Apply session-specific context without changing the saved demo."""
    payload = AnalyzeRequest.model_validate({**EXAMPLE, **options.model_dump(mode="json")})
    return _report_or_422(payload)


@app.post("/analyze", response_model=AnalysisReport)
def analyze(payload: Annotated[AnalyzeRequest, Body(openapi_examples={
    "size_it_up": {"summary": "Verified Size It Up daily rates", "value": EXAMPLE},
})]) -> AnalysisReport:
    """Analyse a saved response with explicit query metadata; no data is stored."""
    return _report_or_422(payload)
