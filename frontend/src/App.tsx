import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { cohortDays, percentage, points, requestReport } from "./api";
import type { ComparisonDates, Report, Source, UpdateInput } from "./api";
import UpdatePanel, { phaseLabel } from "./UpdatePanel";
import { downloadAnalysis } from "./savedAnalysis";

export default function App() {
  const [report, setReport] = useState<Report | null>(null);
  const [source, setSource] = useState<Source>({ kind: "demo" });
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [saveNotice, setSaveNotice] = useState("");
  const [day, setDay] = useState("");
  const [before, setBefore] = useState("");
  const [after, setAfter] = useState("");
  const controller = useRef<AbortController | null>(null);

  const load = useCallback(
    async (
      nextSource: Source,
      dates?: ComparisonDates | null,
      update?: UpdateInput | null,
    ) => {
      controller.current?.abort();
      const active = new AbortController();
      controller.current = active;
      const timeout = window.setTimeout(() => active.abort("timeout"), 20000);
      setBusy(true);
      setError("");
      setSaveNotice("");
      setReport(null);
      try {
        const next = await requestReport(
          nextSource,
          dates,
          active.signal,
          update,
        );
        if (active.signal.aborted) return;
        const days = cohortDays(next);
        setReport(next);
        setSource(nextSource);
        setDay((current) => (days.includes(current) ? current : days[0]));
        setBefore(
          next.snapshot.compare?.before ??
            next.update_context?.suggested_comparison?.before ??
            days[0],
        );
        setAfter(
          next.snapshot.compare?.after ??
            next.update_context?.suggested_comparison?.after ??
            days[Math.min(1, days.length - 1)],
        );
      } catch (caught) {
        if (!active.signal.aborted)
          setError(
            caught instanceof Error
              ? caught.message
              : "Unable to load this report.",
          );
        else if (active.signal.reason === "timeout")
          setError(
            "The analysis service took too long. Check the Python server, then try again.",
          );
      } finally {
        window.clearTimeout(timeout);
        if (controller.current === active) setBusy(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load({ kind: "demo" });
    return () => controller.current?.abort();
  }, [load]);

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // Selecting the same file again should retry the import.
    if (!file) return;
    controller.current?.abort();
    setError("");
    setSaveNotice("");
    setReport(null);
    setBusy(true);
    try {
      if (file.size > 5 * 1024 * 1024)
        throw new Error("Choose a saved JSON response smaller than 5 MB.");
      let payload: unknown;
      try {
        payload = JSON.parse(await file.text());
      } catch {
        throw new Error(
          "This file is not valid JSON. Use a saved response containing query and result; CSV import is not available yet.",
        );
      }
      if (
        payload === null ||
        typeof payload !== "object" ||
        Array.isArray(payload)
      )
        throw new Error(
          "The JSON must be an object containing query and result.",
        );
      await load({
        kind: "file",
        name: file.name,
        payload: payload as Record<string, unknown>,
      });
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Unable to read this file.",
      );
      setBusy(false);
    }
  }

  function save() {
    if (!report || busy) return;
    try {
      const filename = downloadAnalysis(report.snapshot);
      setSaveNotice(`Download started: ${filename}`);
    } catch (caught) {
      setSaveNotice(
        caught instanceof Error
          ? caught.message
          : "Unable to save this analysis.",
      );
    }
  }

  function compare(event: FormEvent) {
    event.preventDefault();
    if (!before || !after || before >= after) {
      setError("Choose a before date earlier than the after date.");
      return;
    }
    void load(
      source,
      { before, after },
      report?.update_context?.update ?? null,
    );
  }

  const days = report ? cohortDays(report) : [];
  const steps = report
    ? [...report.query.step_ids].sort((a, b) => Number(a) - Number(b))
    : [];
  const rows = report?.rows.filter((row) => row.cohort_date === day) ?? [];
  const drops =
    report?.dropoffs.filter((drop) => drop.cohort_date === day) ?? [];
  const finalRow = rows.find((row) => row.step_id === steps.at(-1));
  const activePrompts =
    report?.investigations.filter(
      (prompt) => prompt.dates.length > 1 || prompt.dates[0] === day,
    ) ?? [];
  const compared = report?.comparisons?.[0];
  const timing = (date: string) =>
    report?.update_context?.cohorts.find((item) => item.cohort_date === date)
      ?.phase;
  const draftChanged =
    compared &&
    (before !== compared.before_date || after !== compared.after_date);

  return (
    <>
      <a href="#report" className="skip">
        Skip to report
      </a>
      <header className="topbar">
        <a className="brand" href="#report" aria-label="FunnelCheck home">
          <img src="/mark.svg" alt="" width="34" height="34" />
        </a>
        <nav aria-label="Report sections">
          <a href="#report">Overview</a>
          <a href="#funnel">Funnel</a>
          <a href="#comparison">Compare</a>
          <a href="#investigations">Investigate</a>
        </nav>
        <span className="local">Local workspace</span>
      </header>
      <main id="report">
        <div className="page-title">
          <div>
            <p className="eyebrow">FunnelCheck</p>
            <h1>Funnel overview</h1>
            <p className="intro">
              Inspect completion rates, compare cohorts, and review questions to
              investigate.
            </p>
          </div>
        </div>
        <div className="workspace">
          <aside className="sidebar" aria-label="Report controls">
            <section className="panel source-panel">
              <h2>Data source</h2>
              <p>Use the Size It Up example or import a saved response.</p>
              <button
                className="primary wide"
                disabled={busy}
                onClick={() => void load({ kind: "demo" })}
              >
                Load demo
              </button>
              <label className={`upload ${busy ? "disabled" : ""}`}>
                Import saved JSON
                <input
                  aria-label="Import saved JSON"
                  type="file"
                  accept=".json,application/json"
                  disabled={busy}
                  onChange={(event) => void importFile(event)}
                />
              </label>
              <button
                className="secondary wide save-analysis"
                disabled={!report || busy}
                onClick={save}
              >
                Save analysis
              </button>
              <p className="small">
                Save applied update details and comparison dates with the source
                data. Import the JSON to reopen it.
              </p>
              {saveNotice && (
                <p className="small save-notice" role="status">
                  {saveNotice}
                </p>
              )}
              <div className="source-note">
                <span className="mini-label">Current source</span>
                <strong>
                  {report
                    ? source.kind === "demo"
                      ? "Size It Up · demo"
                      : source.name
                    : "Awaiting report"}
                </strong>
              </div>
            </section>
            <section className="panel controls">
              <h2>Cohort</h2>
              <label htmlFor="cohort">Inspect a day</label>
              <select
                id="cohort"
                value={day}
                disabled={!report || busy}
                onChange={(event) => setDay(event.target.value)}
              >
                {days.map((date) => (
                  <option key={date} value={date}>
                    {date}
                    {timing(date) ? ` · ${phaseLabel(timing(date)!)}` : ""}
                  </option>
                ))}
              </select>
              <p className="small">
                Dates refer to when attempts entered the funnel. All dates use
                UTC.
              </p>
              <div className="divider" />
              <form onSubmit={compare}>
                <h2>Compare two days</h2>
                <label htmlFor="before">Before</label>
                <select
                  id="before"
                  value={before}
                  disabled={!report || busy}
                  onChange={(event) => setBefore(event.target.value)}
                >
                  {days.map((date) => (
                    <option key={date} value={date}>
                      {date}
                      {timing(date) ? ` · ${phaseLabel(timing(date)!)}` : ""}
                    </option>
                  ))}
                </select>
                <label htmlFor="after">After</label>
                <select
                  id="after"
                  value={after}
                  disabled={!report || busy}
                  onChange={(event) => setAfter(event.target.value)}
                >
                  {days.map((date) => (
                    <option key={date} value={date}>
                      {date}
                      {timing(date) ? ` · ${phaseLabel(timing(date)!)}` : ""}
                    </option>
                  ))}
                </select>
                <button
                  className="secondary wide"
                  disabled={!report || busy || days.length < 2}
                >
                  Compare dates
                </button>
              </form>
              {report?.comparisons && (
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    void load(
                      source,
                      null,
                      report?.update_context?.update ?? null,
                    )
                  }
                >
                  Clear comparison
                </button>
              )}
              {draftChanged && (
                <p className="small">
                  Apply dates to update the comparison. The table still shows
                  its labelled dates.
                </p>
              )}
            </section>
            <div className="reading-note">
              <span className="mini-label">About this report</span>
              <p>
                Rate changes describe observations. They do not prove an
                update’s effect.
              </p>
            </div>
          </aside>
          <div className="report-content" aria-busy={busy}>
            {error && (
              <div className="error" role="alert">
                <strong>We couldn’t complete that request.</strong>
                <p>{error}</p>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    void load(
                      source,
                      null,
                      report?.update_context?.update ?? null,
                    )
                  }
                >
                  Retry current source
                </button>
              </div>
            )}
            {busy && (
              <div className="panel loading" role="status">
                <span className="spinner" aria-hidden="true" />
                <h2>Checking the data…</h2>
                <p>Preparing your funnel report.</p>
              </div>
            )}
            {report && (
              <>
                <div className="report-heading">
                  <div>
                    <span className="mini-label">
                      {source.kind === "demo"
                        ? "Verified example"
                        : "Imported response"}
                    </span>
                    <h2>{report.query.funnel_name}</h2>
                  </div>
                  <span className="date-tag">{day} · UTC</span>
                </div>
                <UpdatePanel
                  context={report.update_context}
                  onApply={(update) =>
                    void load(
                      source,
                      compared
                        ? {
                            before: compared.before_date,
                            after: compared.after_date,
                          }
                        : null,
                      update,
                    )
                  }
                  onCompare={(dates) =>
                    void load(source, dates, report.update_context?.update)
                  }
                />
                <div className="summary-grid">
                  <div className="metric">
                    <span className="mini-label">Last selected step</span>
                    <strong>{percentage(finalRow?.completion_rate)}</strong>
                    <span>
                      Recorded rate ·{" "}
                      {finalRow?.step_name ?? `step ${steps.at(-1)}`}
                    </span>
                    {finalRow?.status && finalRow.status !== "Valid" && (
                      <span className="warning-text">
                        Status: {finalRow.status}
                      </span>
                    )}
                  </div>
                  <div className="metric">
                    <span className="mini-label">Funnel coverage</span>
                    <strong>
                      {rows.length}
                      <small> / {steps.length}</small>
                    </strong>
                    <span>Steps with data on this day</span>
                  </div>
                  <div className="metric">
                    <span className="mini-label">Validation notes</span>
                    <strong>
                      {report.validation_notes.length
                        .toString()
                        .padStart(2, "0")}
                    </strong>
                    <span>Across the full requested window</span>
                  </div>
                </div>
                {report.validation_notes.length > 0 && (
                  <details className="warnings" open>
                    <summary>
                      {report.validation_notes.length} data notes to review
                    </summary>
                    <ul>
                      {report.validation_notes.map((note, index) => (
                        <li key={index}>{note}</li>
                      ))}
                    </ul>
                  </details>
                )}
                <section className="panel funnel" id="funnel">
                  <div className="section-heading">
                    <div>
                      <h2>Funnel completion</h2>
                    </div>
                    <span className="pill">Cumulative rates</span>
                  </div>
                  <p>
                    Each rate is relative to this day’s starting cohort. Missing
                    steps stay unavailable.
                  </p>
                  <ol className="funnel-list">
                    {steps.map((step) => {
                      const row = rows.find((item) => item.step_id === step);
                      const name =
                        row?.step_name ??
                        report.rows.find((item) => item.step_id === step)
                          ?.step_name ??
                        `Step ${step}`;
                      return (
                        <li key={step}>
                          <span className="step-number">
                            {step.padStart(2, "0")}
                          </span>
                          <div className="step-body">
                            <div className="step-label">
                              <span>{name}</span>
                              <strong>
                                {percentage(row?.completion_rate)}
                              </strong>
                            </div>
                            <div
                              className={`bar-track ${row ? "" : "missing"}`}
                              aria-hidden="true"
                            >
                              {row && (
                                <div
                                  className="bar-fill"
                                  style={{
                                    width: `${row.completion_rate * 100}%`,
                                  }}
                                />
                              )}
                            </div>
                            {row?.status && row.status !== "Valid" && (
                              <small className="warning-text">
                                Roblox status: {row.status}
                              </small>
                            )}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                  <div className="table-heading">
                    <h3>Between the steps</h3>
                    <span>Same daily cohort</span>
                  </div>
                  {drops.length ? (
                    <div className="table-scroll">
                      <table>
                        <caption className="sr-only">
                          Drop-off for {day}
                        </caption>
                        <thead>
                          <tr>
                            <th>Transition</th>
                            <th>Of starters</th>
                            <th>Of previous step</th>
                          </tr>
                        </thead>
                        <tbody>
                          {drops.map((drop) => (
                            <tr key={`${drop.from_step}-${drop.to_step}`}>
                              <th scope="row">
                                {drop.from_step} → {drop.to_step}
                                {drop.reason && (
                                  <span className="cell-note">
                                    {drop.reason}
                                  </span>
                                )}
                              </th>
                              <td>{points(drop.percentage_points)}</td>
                              <td>{percentage(drop.relative_drop)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p>Select at least two steps to inspect transitions.</p>
                  )}
                  <p className="table-foot">
                    pp = percentage points. A relative drop uses the preceding
                    step as its denominator.
                  </p>
                </section>
                <section className="panel" id="comparison">
                  <div className="section-heading">
                    <div>
                      <h2>Compare cohorts</h2>
                    </div>
                  </div>
                  {compared ? (
                    <>
                      <p className="comparison-dates">
                        {compared.before_date} <span aria-hidden="true">→</span>{" "}
                        {compared.after_date} <span className="muted">UTC</span>
                        {report.update_context && (
                          <small className="comparison-phases">
                            {phaseLabel(timing(compared.before_date)!)} →{" "}
                            {phaseLabel(timing(compared.after_date)!)}
                          </small>
                        )}
                      </p>
                      {report.update_context &&
                        (timing(compared.before_date) !== "before" ||
                          timing(compared.after_date) !== "after") && (
                          <p className="comparison-caution">
                            This selection does not pair a full before day with
                            a full after day. Transition days may mix periods
                            before and after deployment.
                          </p>
                        )}
                      <div className="table-scroll">
                        <table>
                          <caption className="sr-only">
                            Daily rate comparison
                          </caption>
                          <thead>
                            <tr>
                              <th>Step</th>
                              <th>Before</th>
                              <th>After</th>
                              <th>Change</th>
                            </tr>
                          </thead>
                          <tbody>
                            {report.comparisons?.map((item) => (
                              <tr key={item.step_id}>
                                <th scope="row">
                                  {item.step_name}
                                  {item.reason && (
                                    <span className="cell-note">
                                      {item.reason}
                                    </span>
                                  )}
                                </th>
                                <td>{percentage(item.before_rate)}</td>
                                <td>{percentage(item.after_rate)}</td>
                                <td
                                  className={
                                    item.change_pp == null
                                      ? ""
                                      : item.change_pp > 0
                                        ? "increase"
                                        : item.change_pp < 0
                                          ? "decrease"
                                          : ""
                                  }
                                >
                                  {points(item.change_pp, true)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <p className="table-foot">
                        After minus before. These differences do not establish
                        an update’s effect; cohorts may have had different time
                        to finish.
                      </p>
                    </>
                  ) : (
                    <div className="empty-comparison">
                      <p>Choose a before and after date to see what changed.</p>
                      <small>
                        We compare recorded rates, not the impact of an update.
                      </small>
                    </div>
                  )}
                </section>
                <section id="investigations">
                  <div className="section-heading investigation-heading">
                    <div>
                      <h2>Questions to investigate</h2>
                    </div>
                    <span className="pill">
                      {activePrompts.length}{" "}
                      {activePrompts.length === 1 ? "prompt" : "prompts"}
                    </span>
                  </div>
                  <p>
                    Questions for {day}
                    {compared ? " and your selected comparison" : ""}. These are
                    investigation prompts, not predicted fixes.
                  </p>
                  <div className="question-list">
                    {activePrompts.map((prompt, index) => (
                      <article
                        className="question-card"
                        key={`${prompt.rule_id}-${prompt.dates.join()}`}
                      >
                        <div className="question-index">
                          {String(index + 1).padStart(2, "0")}
                        </div>
                        <div>
                          <span className="mini-label">
                            {prompt.dates.join(" → ")}
                          </span>
                          <h3>{prompt.title}</h3>
                          <p className="evidence">{prompt.evidence}</p>
                          <ul>
                            {prompt.questions.map((question) => (
                              <li key={question}>{question}</li>
                            ))}
                          </ul>
                          <details>
                            <summary>How to interpret this prompt</summary>
                            <p>{prompt.limitation}</p>
                            <code>{prompt.rule_id}</code>
                          </details>
                        </div>
                      </article>
                    ))}
                  </div>
                  {!activePrompts.length && (
                    <div className="panel">
                      <p>
                        No investigation rule triggered for this view. That does
                        not establish that the funnel is healthy.
                      </p>
                    </div>
                  )}
                </section>
                <details className="report-limits">
                  <summary>What this report can and can’t tell you</summary>
                  <ul>
                    {report.limitations.map((limit) => (
                      <li key={limit}>{limit}</li>
                    ))}
                  </ul>
                </details>
              </>
            )}
            {!report && !busy && !error && (
              <div className="panel">
                <p>Load the demo or import a response to begin.</p>
              </div>
            )}
          </div>
        </div>
        <footer>
          <span>FunnelCheck</span>
          <span>Daily session cohorts · All dates in UTC</span>
        </footer>
      </main>
    </>
  );
}
