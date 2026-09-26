"""Run with: python -m funnelcheck demo (no key or network needed)."""

import argparse
from datetime import date
import getpass
import json
import os
from pathlib import Path

from .api import RobloxAPIError, fetch_rates
from .funnel import DataError, FunnelQuery, parse_rates, validation_notes


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect a Roblox daily session-cohort funnel.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="Read the verified Size It Up example, entirely offline.")
    fetch = commands.add_parser("fetch", help="Query Roblox using a local key or a hidden prompt.")
    fetch.add_argument("--universe", required=True)
    fetch.add_argument("--funnel", required=True)
    fetch.add_argument("--start", type=date.fromisoformat, required=True)
    fetch.add_argument("--end-exclusive", type=date.fromisoformat, required=True)
    fetch.add_argument("--steps", nargs="+", required=True, help="Step IDs already discovered in Roblox.")
    args = parser.parse_args(argv)
    try:
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
        print("\nRates only: no sample-size, significance, causal or pooled-conversion claims.")
        return 0
    except (DataError, RobloxAPIError, OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
