"""Run with: python -m funnelcheck demo (no key or network needed)."""

import argparse
from datetime import date
import getpass
import json
import os
from pathlib import Path

from .api import RobloxAPIError, fetch_rates
from .analysis import calculate_dropoffs
from .comparison import compare_daily_cohorts, validate_comparison_queries
from .funnel import DataError, FunnelQuery, parse_rates, validation_notes
from .investigations import build_investigations
from .export import check_output_path, save_response


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a Roblox daily session-cohort funnel.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Read the verified Size It Up example, entirely offline.")
    fetch = commands.add_parser("fetch", help="Query Roblox using a local key or a hidden prompt.")
    fetch.add_argument("--universe", required=True)
    fetch.add_argument("--funnel", required=True)
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end-exclusive", type=date.fromisoformat, required=True)
    fetch.add_argument("--steps", nargs="+", required=True, help="Step IDs already discovered in Roblox.")
    for command in (demo, fetch):
        command.add_argument(
            "--output", type=Path, metavar="FILE.json",
            help="Save validated query/results for dashboard import; never overwrite an existing file.",
        )
        command.add_argument(
            "--compare", nargs=2, type=date.fromisoformat, metavar=("BEFORE", "AFTER"),
            help="Compare two daily cohorts inside the requested window (YYYY-MM-DD).",
        )
    args = parser.parse_args(argv)
    try:
        if args.output is not None:
            check_output_path(args.output)
        if args.command == "demo":
            sample = Path(__file__).resolve().parent.parent / "examples" / "matchcompletion.json"
            saved = json.loads(sample.read_text(encoding="utf-8"))
            context = saved["query"]
            query = FunnelQuery(
                context["universe_id"], context["funnel_name"],
                date.fromisoformat(context["start"]), date.fromisoformat(context["end_exclusive"]),
                tuple(context["step_ids"]),
            )
            envelope = saved["result"]
            print("Offline example: user-provided API response, verified against the CSV.")
        else:
            query = FunnelQuery(args.universe, args.funnel, args.start, args.end_exclusive, tuple(args.steps))
        if args.compare:
            validate_comparison_queries(query, query, *args.compare)
        if args.command == "fetch":
            key = os.environ.get("ROBLOX_API_KEY") or getpass.getpass("Roblox analytics key (hidden): ")
            envelope = fetch_rates(query, key)
        rows = parse_rates(envelope, query)
        notes = validation_notes(rows, query)
        print(f"\n{query.funnel_name}: {query.start} to {query.end_exclusive} (exclusive), UTC")
        print("Metric: cumulative session-cohort completion rate\n")
        print(f"{'Date':<12} {'Step':<6} {'Name':<27} {'Completion':>10}  Roblox status")
        for row in rows:
            print(f"{row.cohort_date!s:<12} {row.step_id:<6} {row.step_name:<27} {row.completion_rate:>9.2%}  {row.status or '-'}")
        print(f"\n{len(rows)} records; {len(notes)} validation notes.")
        for note in notes:
            print(f"- {note}")
        dropoffs = calculate_dropoffs(rows, query)
        print("\nStep drop-off (same daily cohort):")
        print("Starter drop = percentage points of starters; relative drop = % of the preceding step.")
        print(f"{'Date':<12} {'Steps':<9} {'Starter drop':>14} {'Relative drop':>15}")
        for drop in dropoffs:
            points = "N/A" if drop.percentage_points is None else f"{drop.percentage_points:.2f} pp"
            relative = "N/A" if drop.relative_drop is None else f"{drop.relative_drop:.2%}"
            pair = f"{drop.from_step} -> {drop.to_step}"
            print(f"{drop.cohort_date!s:<12} {pair:<9} {points:>14} {relative:>15}")
            if drop.reason:
                print(f"  {drop.reason}")
        if not dropoffs:
            print("At least two requested steps are needed for a step-to-step calculation.")
        print("N/A means unavailable, not zero. Drop-off describes recorded progress, not why it stopped.")
        if args.compare:
            before_date, after_date = args.compare
            comparisons = compare_daily_cohorts(rows, query, before_date, rows, query, after_date)
            print(f"\nDaily cohort comparison: {before_date} -> {after_date} (UTC)")
            print("Change = after minus before, in percentage points of each day's starters.")
            print(f"{'Step':<6} {'Name':<27} {'Before':>10} {'After':>10} {'Change':>12}")
            for item in comparisons:
                before = "N/A" if item.before_rate is None else f"{item.before_rate:.2%}"
                after = "N/A" if item.after_rate is None else f"{item.after_rate:.2%}"
                change = "N/A" if item.change_pp is None else f"{item.change_pp:+.2f} pp"
                print(f"{item.step_id:<6} {item.step_name:<27} {before:>10} {after:>10} {change:>12}")
                if item.reason:
                    print(f"  {item.reason}")
            print("Observed differences only: matching names cannot verify unchanged logging or equal cohort maturity.")
            print("Daily cohorts may still accumulate completions. These differences do not establish an update's effect.")
        prompts = build_investigations(rows, query, tuple(args.compare) if args.compare else None)
        print("\nQuestions to investigate (rule-based; not predictions):")
        for prompt in prompts:
            dates = " -> ".join(str(day) for day in prompt.dates)
            print(f"\n{dates}: {prompt.title} [{prompt.rule_id}]")
            print(f"  Evidence: {prompt.evidence}")
            for question in prompt.questions:
                print(f"  - {question}")
            print(f"  Limit: {prompt.limitation}")
        if not prompts:
            print("No investigation rule triggered. This does not establish that the funnel is healthy.")
        print("\nRates only: no sample-size, significance, causal or pooled-conversion claims.")
        if args.output is not None:
            saved_path = save_response(args.output, query, envelope)
            print(f"\nSaved snapshot: {saved_path}")
            print("Use Import saved JSON in the dashboard. Validation notes are recalculated on import.")
        return 0
    except (DataError, RobloxAPIError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
