export type ComparisonDates = { before: string; after: string };
export interface UpdateInput {
  name: string;
  local_time: string;
  time_zone: "Europe/London" | "UTC";
  approximate: boolean;
}
export interface UpdateContext {
  update: UpdateInput;
  occurred_at_utc: string;
  cohorts: { cohort_date: string; phase: "before" | "transition" | "after" }[];
  suggested_comparison: ComparisonDates | null;
  notes: string[];
}
export type Source =
  | { kind: "demo" }
  | { kind: "file"; name: string; payload: Record<string, unknown> };
export interface SavedAnalysis {
  query: Report["query"];
  result: { done: true; response: { values: unknown[] } };
  compare: ComparisonDates | null;
  update: UpdateInput | null;
}
export interface Report {
  snapshot: SavedAnalysis;
  update_context: UpdateContext | null;
  query: {
    universe_id: string;
    funnel_name: string;
    metric: string;
    granularity: string;
    start: string;
    end_exclusive: string;
    step_ids: string[];
  };
  units: Record<string, string>;
  rows: {
    step_id: string;
    step_name: string;
    cohort_date: string;
    completion_rate: number;
    status: string | null;
  }[];
  validation_notes: string[];
  dropoffs: {
    cohort_date: string;
    from_step: string;
    to_step: string;
    percentage_points: number | null;
    relative_drop: number | null;
    reason: string | null;
  }[];
  comparisons:
    | {
        step_id: string;
        step_name: string;
        before_date: string;
        after_date: string;
        before_rate: number | null;
        after_rate: number | null;
        change_pp: number | null;
        reason: string | null;
      }[]
    | null;
  investigations: {
    rule_id: string;
    dates: string[];
    step_ids: string[];
    title: string;
    evidence: string;
    questions: string[];
    limitation: string;
  }[];
  limitations: string[];
}

export async function requestReport(
  source: Source,
  dates: ComparisonDates | null | undefined,
  signal: AbortSignal,
  update?: UpdateInput | null,
): Promise<Report> {
  const search = dates ? `?${new URLSearchParams(dates)}` : "";
  const isPost = source.kind === "file" || update !== undefined;
  const response = await fetch(
    source.kind === "demo"
      ? `/api/demo${isPost ? "" : search}`
      : "/api/analyze",
    {
      signal,
      ...(isPost
        ? {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // undefined restores the file's selection; null explicitly clears it.
            body: JSON.stringify({
              ...(source.kind === "file" ? source.payload : {}),
              ...(dates !== undefined ? { compare: dates } : {}),
              ...(update !== undefined ? { update } : {}),
            }),
          }
        : {}),
    },
  );
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(
      "The analysis service did not return a report. Check that the Python server is running on port 8000.",
    );
  }
  if (!response.ok) {
    const detail = data.detail;
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (error: { loc?: (string | number)[]; msg?: string }) =>
                  `${error.loc?.join(" →") || "Input"}: ${error.msg || "Invalid value"}`,
              )
              .join("; ")
          : "The analysis service could not process this request.";
    throw new Error(message);
  }
  // TypeScript describes the contract; Python validates the report and raw measurements.
  return data as Report;
}

export function percentage(value: number | null | undefined): string {
  return value == null
    ? "Unavailable"
    : `${value === 0 || Math.abs(value * 100) >= 0.01 ? (value * 100).toFixed(2) : (value * 100).toPrecision(2)}%`;
}
export function points(
  value: number | null | undefined,
  signed = false,
): string {
  if (value == null) return "Unavailable";
  const number =
    value === 0 || Math.abs(value) >= 0.01
      ? value.toFixed(2)
      : value.toPrecision(2);
  return `${signed && value > 0 ? "+" : ""}${number} pp`;
}
export function cohortDays(report: Report): string[] {
  const days: string[] = [];
  const cursor = new Date(`${report.query.start}T00:00:00Z`);
  const end = new Date(`${report.query.end_exclusive}T00:00:00Z`);
  while (cursor < end) {
    days.push(cursor.toISOString().slice(0, 10));
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return days;
}
