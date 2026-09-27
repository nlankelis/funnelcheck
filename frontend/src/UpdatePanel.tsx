import type { FormEvent } from "react";
import type { ComparisonDates, UpdateContext, UpdateInput } from "./api";

export const phaseLabel = (phase: string) =>
  phase === "transition"
    ? "Transition day"
    : phase === "before"
      ? "Before update"
      : "After update";

export default function UpdatePanel({
  context,
  onApply,
  onCompare,
}: {
  context: UpdateContext | null;
  onApply: (update: UpdateInput | null) => void;
  onCompare: (dates: ComparisonDates) => void;
}) {
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // Read the native form once on Apply, including date-picker/autofill edits.
    // Applied labels still come exclusively from the Python report.
    const fields = new FormData(event.currentTarget);
    onApply({
      name: String(fields.get("name") ?? "").trim(),
      local_time: String(fields.get("local_time") ?? ""),
      time_zone: String(fields.get("time_zone")) as UpdateInput["time_zone"],
      approximate: fields.has("approximate"),
    });
  }
  return (
    <section className="panel update-panel" aria-labelledby="update-heading">
      <div className="section-heading">
        <h2 id="update-heading">Update context</h2>
        <span className="pill">Reported timing</span>
      </div>
      {context ? (
        <>
          <h3>{context.update.name}</h3>
          <p className="update-time">
            {context.update.approximate ? "Approximately " : ""}
            {context.update.local_time.replace("T", " ")} ·{" "}
            {context.update.time_zone === "Europe/London" ? "UK time" : "UTC"}
          </p>
          <p className="small">
            UTC: {context.occurred_at_utc.slice(0, 16).replace("T", " ")}
          </p>
          <ul className="cohort-timing" aria-label="Daily cohort timing">
            {context.cohorts.map((item) => (
              <li key={item.cohort_date} className={item.phase}>
                <strong>{item.cohort_date}</strong>
                <span>{phaseLabel(item.phase)}</span>
              </li>
            ))}
          </ul>
          {context.suggested_comparison && (
            <button
              className="secondary"
              onClick={() => onCompare(context.suggested_comparison!)}
            >
              Compare surrounding full days
            </button>
          )}
          {context.suggested_comparison && (
            <p className="small suggested-dates">
              {context.suggested_comparison.before} →{" "}
              {context.suggested_comparison.after} · Missing measurements remain
              unavailable.
            </p>
          )}
          <details className="timing-notes">
            <summary>How these dates are labelled</summary>
            <ul>
              {context.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </details>
        </>
      ) : (
        <p>
          Record when a game update went live to put daily changes in context.
        </p>
      )}
      <details className="update-editor" open={context ? undefined : true}>
        <summary>
          {context ? "Edit update details" : "Record an update"}
        </summary>
        <form onSubmit={apply}>
          <div className="update-fields">
            <label>
              Update name
              <input
                required
                maxLength={120}
                name="name"
                defaultValue={context?.update.name ?? ""}
                placeholder="Tutorial explanation update"
              />
            </label>
            <label>
              Deployment time
              <input
                required
                type="datetime-local"
                min="1900-01-01T00:00"
                max="9998-12-31T23:59"
                step="60"
                name="local_time"
                defaultValue={context?.update.local_time ?? ""}
              />
            </label>
            <label>
              Time zone
              <select
                name="time_zone"
                defaultValue={context?.update.time_zone ?? "Europe/London"}
              >
                <option value="Europe/London">UK (Europe/London)</option>
                <option value="UTC">UTC</option>
              </select>
            </label>
          </div>
          <label className="checkbox-label">
            <input
              type="checkbox"
              name="approximate"
              defaultChecked={context?.update.approximate ?? true}
            />
            Time is approximate
          </label>
          <p className="small">
            Changes apply when you save. Your browser’s time zone is not used.
          </p>
          <div className="update-actions">
            <button className="secondary">Apply update details</button>
            {context && (
              <button
                className="text-button"
                type="button"
                onClick={() => onApply(null)}
              >
                Remove update context
              </button>
            )}
          </div>
        </form>
      </details>
      <p className="small update-storage">
        Use Save analysis to keep applied details. Refreshing or loading another
        file replaces this session.
      </p>
    </section>
  );
}
