"""Save an importable snapshot, using only validated query and measurement fields."""

import json
from pathlib import Path

from .funnel import DataError, FunnelQuery, METRIC, FunnelRow, parse_rates


def check_output_path(path: Path) -> None:
    if path.suffix.lower() != ".json":
        raise DataError("Choose an output filename ending in .json.")
    if path.exists() or path.is_symlink():
        raise DataError("Output already exists; choose a new filename to preserve the saved snapshot.")


def save_response(path: Path, query: FunnelQuery, envelope: dict) -> Path:
    """Validate before writing; keep missing rows absent and numeric precision intact.

    Reconstruct the response from parser output rather than copying arbitrary
    envelope fields. Credentials, headers and operation metadata have no place in
    this file format. Saving is explicit and never overwrites an existing file.
    """
    check_output_path(path)
    rows = parse_rates(envelope, query)
    document = snapshot_from_rows(query, rows)
    content = json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        # Exclusive creation closes the race between the path check and writing.
        with path.open("x", encoding="utf-8", newline="\n") as destination:
            created = True
            destination.write(content)
    except OSError:
        if created:
            path.unlink(missing_ok=True)
        raise
    return path.resolve()


def snapshot_from_rows(query: FunnelQuery, rows: list[FunnelRow]) -> dict:
    """Build a portable input document from validated rows, never derived rates."""
    series = {}
    for row in rows:
        item = series.setdefault(row.step_id, {
            "breakdowns": [{"dimension": "FunnelStep", "value": row.step_id, "displayValue": row.step_name}],
            "dataPoints": [],
        })
        point = {"time": row.cohort_date.isoformat() + "T00:00:00Z", "value": row.completion_rate}
        if row.status is not None:
            point["status"] = row.status
        item["dataPoints"].append(point)
    return {
        "query": {
            "universe_id": query.universe_id, "funnel_name": query.funnel_name,
            "metric": METRIC, "granularity": "OneDay",
            "start": query.start.isoformat(), "end_exclusive": query.end_exclusive.isoformat(),
            "step_ids": list(query.step_ids),
        },
        "result": {"done": True, "response": {"values": [series[step] for step in sorted(series, key=int)]}},
    }
