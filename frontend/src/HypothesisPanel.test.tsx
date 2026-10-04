import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import HypothesisPanel from "./HypothesisPanel";
import type { DiagnosticResult, Report } from "./api";

function report(
  status: DiagnosticResult["status"] = "insufficient_evidence",
): Report {
  return {
    query: { step_ids: ["1", "2"] },
    rows: [{ step_id: "2", step_name: "A labelled event" }],
    snapshot: { hypothesis: null, compare: null },
    update_context: null,
    diagnostics: {
      statement: "An explicitly chosen expectation",
      update_name: null,
      status,
      observations: [
        {
          step_id: "2",
          step_name: "A labelled event",
          measurement: "Cumulative rate relative to starters",
          expected_direction: "increase",
          observed_direction: null,
          before_date: "2026-09-19",
          after_date: "2026-09-21",
          before_rate: 0,
          after_rate: null,
          change_pp: null,
          status: "missing",
          reason: "Missing after rate.",
          question: "What event should be measured next?",
        },
      ],
      limitations: ["No causal inference."],
    },
  } as Report;
}

describe("explicit measurement controls", () => {
  it("requires a selected measurement and does not invent a default mapping", async () => {
    const onApply = vi.fn();
    render(<HypothesisPanel report={report()} onApply={onApply} />);
    expect(screen.getByLabelText("Expected direction for step 2")).toHaveValue(
      "",
    );
    fireEvent.change(screen.getByLabelText("Expected behaviour"), {
      target: { value: "Expected action" },
    });
    await userEvent.click(
      screen.getByRole("button", { name: "Apply hypothesis" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "select between 1 and 10",
    );
    expect(onApply).not.toHaveBeenCalled();
    await userEvent.selectOptions(
      screen.getByLabelText("Expected direction for step 2"),
      "decrease",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Apply hypothesis" }),
    );
    expect(onApply).toHaveBeenCalledWith({
      statement: "Expected action",
      expectations: [{ step_id: "2", expected_direction: "decrease" }],
    });
  });

  it("enforces the selection bound without sending a request", async () => {
    const data = report();
    data.query.step_ids = Array.from({ length: 11 }, (_, i) => String(i + 1));
    const onApply = vi.fn();
    render(<HypothesisPanel report={data} onApply={onApply} />);
    fireEvent.change(screen.getByLabelText("Expected behaviour"), {
      target: { value: "Check many steps" },
    });
    for (const step of data.query.step_ids)
      fireEvent.change(
        screen.getByLabelText(`Expected direction for step ${step}`),
        { target: { value: "increase" } },
      );
    await userEvent.click(
      screen.getByRole("button", { name: "Apply hypothesis" }),
    );
    expect(onApply).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("1 and 10");
  });

  it("displays zero, missing evidence, dates, reason and next measurement", async () => {
    render(<HypothesisPanel report={report()} onApply={vi.fn()} />);
    expect(screen.getByText(/0.00% → Unavailable/)).toBeVisible();
    expect(screen.getByText(/2026-09-19 → 2026-09-21/)).toBeVisible();
    expect(screen.getByText("Missing after rate.")).toBeVisible();
    expect(
      screen.getByText(/What event should be measured next/),
    ).toBeVisible();
    expect(screen.getByText(/not proof/)).toBeVisible();
    await userEvent.click(
      screen.getByText("How to interpret these observations"),
    );
    expect(screen.getByText("No causal inference.")).toBeVisible();
  });

  it.each([
    ["supporting", "Supporting observation"],
    ["conflicting", "Conflicting observation"],
    ["mixed", "Mixed observations"],
    ["unchanged", "Unchanged observation"],
    ["insufficient_evidence", "Insufficient evidence"],
  ] as const)("renders the server summary %s", (status, label) => {
    render(<HypothesisPanel report={report(status)} onApply={vi.fn()} />);
    expect(screen.getByRole("heading", { name: label })).toBeVisible();
  });
});
