import { useState } from "react";
import type { FormEvent } from "react";
import { percentage, points } from "./api";
import type { HypothesisInput, Report } from "./api";

export const diagnosticLabel = (status: string) =>
  ({
    supporting: "Supporting observation",
    conflicting: "Conflicting observation",
    mixed: "Mixed observations",
    unchanged: "Unchanged observation",
    missing: "Insufficient evidence",
    insufficient_evidence: "Insufficient evidence",
  })[status] ?? status;

export default function HypothesisPanel({
  report,
  onApply,
}: {
  report: Report;
  onApply: (hypothesis: HypothesisInput | null) => void;
}) {
  const [error, setError] = useState("");
  const [edited, setEdited] = useState(false);
  const applied = report.snapshot.hypothesis;
  const result = report.diagnostics;
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const statement = String(fields.get("statement") ?? "").trim();
    const expectations = report.query.step_ids.flatMap((step_id) => {
      const direction = fields.get(`step-${step_id}`);
      return direction
        ? [
            {
              step_id,
              expected_direction:
                direction as HypothesisInput["expectations"][number]["expected_direction"],
            },
          ]
        : [];
    });
    if (!statement || expectations.length < 1 || expectations.length > 10) {
      setError("Write a hypothesis and select between 1 and 10 measurements.");
      return;
    }
    onApply({ statement, expectations });
  }
  return (
    <section
      className="panel hypothesis-panel"
      aria-labelledby="hypothesis-heading"
    >
      <div className="section-heading">
        <h2 id="hypothesis-heading">Check an update hypothesis</h2>
        <span className="pill">Explicit mapping</span>
      </div>
      <p>
        Describe what you expected, then select the cumulative step rates meant
        to reflect it. Step names alone do not establish what a player
        understood or saw.
      </p>
      {!report.update_context && (
        <p className="comparison-caution">
          Record an update to evaluate its hypothesis. You can save a mapping
          now.
        </p>
      )}
      {!report.snapshot.compare && (
        <p className="small">
          Apply a comparison of full days before and after the update to
          evaluate directions.
        </p>
      )}
      <details className="update-editor" open={applied ? undefined : true}>
        <summary>
          {applied
            ? "Edit hypothesis and measurements"
            : "Add hypothesis and measurements"}
        </summary>
        <form onSubmit={apply} onChange={() => setEdited(true)}>
          <label className="hypothesis-statement">
            Expected behaviour
            <textarea
              name="statement"
              required
              maxLength={500}
              defaultValue={applied?.statement ?? ""}
              placeholder="Describe the change and the behaviour you expected it to affect."
            />
          </label>
          <fieldset className="measurement-fields">
            <legend>Selected measurements · choose 1–10</legend>
            {[...report.query.step_ids]
              .sort((a, b) => Number(a) - Number(b))
              .map((step) => (
                <label key={step}>
                  <span>
                    {step} ·{" "}
                    {report.rows.find((row) => row.step_id === step)
                      ?.step_name ?? `Step ${step}`}
                  </span>
                  <select
                    name={`step-${step}`}
                    aria-label={`Expected direction for step ${step}`}
                    defaultValue={
                      applied?.expectations.find(
                        (item) => item.step_id === step,
                      )?.expected_direction ?? ""
                    }
                  >
                    <option value="">Not selected</option>
                    <option value="increase">Increase</option>
                    <option value="decrease">Decrease</option>
                    <option value="unchanged">Unchanged</option>
                  </select>
                </label>
              ))}
          </fieldset>
          <p className="small">
            Each measurement is a daily session-cohort cumulative completion
            rate, relative to starters. This release checks direction only.
          </p>
          {edited && (
            <p className="small">
              Edits are pending. Apply the hypothesis to update results; saving
              keeps the applied mapping.
            </p>
          )}
          {error && <p role="alert">{error}</p>}
          <div className="update-actions">
            <button className="secondary">Apply hypothesis</button>
            {applied && (
              <button
                type="button"
                className="text-button"
                onClick={() => onApply(null)}
              >
                Clear hypothesis
              </button>
            )}
          </div>
        </form>
      </details>
      {result && (
        <div className="diagnostic-result">
          <h3>{diagnosticLabel(result.status)}</h3>
          <p className="evidence">{result.statement}</p>
          <p className="small">
            Recorded update: {result.update_name ?? "Unavailable"}
          </p>
          <div className="diagnostic-observations">
            {result.observations.map((item) => (
              <article key={item.step_id}>
                <h3>
                  {item.step_name} · {diagnosticLabel(item.status)}
                </h3>
                <p className="small">{item.measurement}</p>
                <p>
                  {item.before_date ?? "No before date"} →{" "}
                  {item.after_date ?? "No after date"} · UTC
                </p>
                <p>
                  Expected: {item.expected_direction} · Observed:{" "}
                  {item.observed_direction ?? "Unavailable"}
                </p>
                <p>
                  {percentage(item.before_rate)} → {percentage(item.after_rate)}{" "}
                  · {points(item.change_pp, true)}
                </p>
                {item.reason && <p className="warning-text">{item.reason}</p>}
                <p className="investigation-question">
                  Investigate: {item.question}
                </p>
              </article>
            ))}
          </div>
          <details className="timing-notes">
            <summary>How to interpret these observations</summary>
            <ul>
              {result.limitations.map((limit) => (
                <li key={limit}>{limit}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
      <p className="small hypothesis-limit">
        Agreement is an observation, not proof that the update caused it.
        Counts, significance and predicted gains are unavailable.
      </p>
    </section>
  );
}
