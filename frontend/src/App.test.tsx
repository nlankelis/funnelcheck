import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { cohortDays, percentage, points } from "./api";
import type { Report } from "./api";
import * as downloads from "./savedAnalysis";

function fixture(): Report {
  // Deliberately synthetic: isolates missing values from an explicit zero.
  const report = {
    query: {
      universe_id: "1",
      funnel_name: "Test_v1",
      metric: "FunnelCohortSessionCompletionRate",
      granularity: "OneDay",
      start: "2026-09-19",
      end_exclusive: "2026-09-21",
      step_ids: ["1", "2"],
    },
    update_context: null,
    diagnostics: null,
    units: {},
    rows: [
      {
        step_id: "1",
        step_name: "Started",
        cohort_date: "2026-09-19",
        completion_rate: 1,
        status: null,
      },
      {
        step_id: "2",
        step_name: "Finished",
        cohort_date: "2026-09-19",
        completion_rate: 0,
        status: null,
      },
    ],
    validation_notes: ["2026-09-20: missing steps 1, 2; missing is not zero."],
    dropoffs: [
      {
        cohort_date: "2026-09-19",
        from_step: "1",
        to_step: "2",
        percentage_points: 100,
        relative_drop: 1,
        reason: null,
      },
      {
        cohort_date: "2026-09-20",
        from_step: "1",
        to_step: "2",
        percentage_points: null,
        relative_drop: null,
        reason: "Step 1 is missing.",
      },
    ],
    comparisons: null,
    investigations: [],
    limitations: ["Synthetic test report."],
  };
  return {
    ...report,
    snapshot: {
      query: report.query,
      result: { done: true, response: { values: [] } },
      compare: null,
      update: null,
      hypothesis: null,
    },
  };
}

function respond(body: unknown, status = 200) {
  return { ok: status === 200, status, json: async () => body } as Response;
}
afterEach(() => vi.unstubAllGlobals());

describe("display contract", () => {
  it("preserves zero and missing values with the right units", () => {
    expect(percentage(null)).toBe("Unavailable");
    expect(percentage(0)).toBe("0.00%");
    expect(percentage(0.5)).toBe("50.00%");
    expect(points(21.11, true)).toBe("+21.11 pp");
    expect(points(null)).toBe("Unavailable");
    expect(percentage(0.000001)).not.toBe("0.00%");
  });
  it("lists absent cohort days using the exclusive UTC window", () => {
    expect(cohortDays(fixture())).toEqual(["2026-09-19", "2026-09-20"]);
  });
});

it("shows warnings and distinguishes a zero day from a missing day without fetching again", async () => {
  const fetcher = vi.fn().mockResolvedValue(respond(fixture()));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "Test_v1" });
  expect(
    screen.getByText("2026-09-20: missing steps 1, 2; missing is not zero."),
  ).toBeVisible();
  const funnel = document.getElementById("funnel")!;
  expect(within(funnel).getByText("0.00%")).toBeVisible();
  await userEvent.selectOptions(
    screen.getByLabelText("Inspect a day"),
    "2026-09-20",
  );
  expect(within(funnel).queryByText("0.00%")).not.toBeInTheDocument();
  expect(within(funnel).getAllByText("Unavailable").length).toBeGreaterThan(0);
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("requires explicit comparison and labels results with applied rather than draft dates", async () => {
  const compared = fixture();
  compared.comparisons = [
    {
      step_id: "2",
      step_name: "Finished",
      before_date: "2026-09-19",
      after_date: "2026-09-20",
      before_rate: 0,
      after_rate: null,
      change_pp: null,
      reason: "Missing after value.",
    },
  ];
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(respond(fixture()))
    .mockResolvedValueOnce(respond(compared));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "Test_v1" });
  await userEvent.click(screen.getByRole("button", { name: /Compare dates/ }));
  await screen.findByText("Missing after value.");
  expect(fetcher.mock.calls[1][0]).toBe("/api/demo");
  await userEvent.selectOptions(screen.getByLabelText("After"), "2026-09-19");
  expect(
    screen.getByText(/table still shows its labelled dates/),
  ).toBeVisible();
  expect(document.querySelector(".comparison-dates")).toHaveTextContent(
    "2026-09-20",
  );
  await userEvent.click(screen.getByRole("button", { name: /Compare dates/ }));
  expect(screen.getByRole("alert")).toHaveTextContent("before date earlier");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("turns a 422 error into a message and clears the prior report", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(respond(fixture()))
    .mockResolvedValueOnce(respond({ detail: "Dates are incompatible." }, 422));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "Test_v1" });
  await userEvent.click(screen.getByRole("button", { name: /Compare dates/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Dates are incompatible.",
  );
  expect(
    screen.queryByRole("heading", { name: "Test_v1" }),
  ).not.toBeInTheDocument();
});

it("explains a service connection failure and offers recovery", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: false,
      json: async () => {
        throw new Error("not JSON");
      },
    }),
  );
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Python server is running on port 8000",
  );
  expect(screen.getByRole("button", { name: "Retry request" })).toBeEnabled();
});

it("imports JSON via POST, preserves saved selections for validation, and reports invalid JSON", async () => {
  const fetcher = vi.fn().mockResolvedValue(respond(fixture()));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "Test_v1" });
  const payload = {
    query: fixture().query,
    result: { done: true },
    compare: { before: "old", after: "old" },
  };
  const file = new File([JSON.stringify(payload)], "saved.json", {
    type: "application/json",
  });
  Object.defineProperty(file, "text", {
    value: async () => JSON.stringify(payload),
  });
  fireEvent.change(screen.getByLabelText("Import saved JSON"), {
    target: { files: [file] },
  });
  await screen.findByText("saved.json");
  expect(fetcher.mock.calls[1][0]).toBe("/api/analyze");
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
    ...payload,
  });
  const bad = new File(["not JSON"], "bad.json");
  Object.defineProperty(bad, "text", { value: async () => "not JSON" });
  fireEvent.change(screen.getByLabelText("Import saved JSON"), {
    target: { files: [bad] },
  });
  expect(await screen.findByRole("alert")).toHaveTextContent("not valid JSON");
  expect(
    screen.queryByRole("button", { name: "Retry request" }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Load demo" })).toBeEnabled();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("aborts a pending request when the component unmounts", async () => {
  const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const view = render(<App />);
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  view.unmount();
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
});

it("preserves applied update context in comparisons and does not restore it after removal", async () => {
  const initial = fixture();
  initial.update_context = {
    update: {
      name: "Test update",
      local_time: "2026-09-20T01:00",
      time_zone: "Europe/London",
      approximate: true,
    },
    occurred_at_utc: "2026-09-20T00:00:00Z",
    cohorts: [
      { cohort_date: "2026-09-19", phase: "before" },
      { cohort_date: "2026-09-20", phase: "after" },
    ],
    suggested_comparison: { before: "2026-09-19", after: "2026-09-20" },
    notes: [],
  };
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(respond(initial))
    .mockResolvedValueOnce(respond(initial))
    .mockResolvedValue(respond(fixture()));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "Test update" });
  await userEvent.click(
    screen.getByRole("button", { name: "Compare surrounding full days" }),
  );
  await screen.findByRole("heading", { name: "Test update" });
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
    compare: initial.update_context.suggested_comparison,
    update: initial.update_context.update,
    hypothesis: null,
  });
  await userEvent.click(screen.getByText("Edit update details"));
  await userEvent.click(
    screen.getByRole("button", { name: "Remove update context" }),
  );
  await screen.findByText("Record an update");
  expect(JSON.parse(fetcher.mock.calls[2][1].body).update).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Compare dates" }));
  await screen.findByText("Record an update");
  expect(JSON.parse(fetcher.mock.calls[3][1].body).update).toBeNull();
});

it("restores imported comparison dates from the validated response and saves applied state", async () => {
  const restored = fixture();
  restored.query.end_exclusive = "2026-09-22";
  restored.snapshot.compare = { before: "2026-09-19", after: "2026-09-21" };
  restored.snapshot.update = {
    name: "Saved update",
    local_time: "2026-09-20T04:00",
    time_zone: "Europe/London",
    approximate: true,
  };
  restored.comparisons = [
    {
      step_id: "2",
      step_name: "Finished",
      before_date: "2026-09-19",
      after_date: "2026-09-21",
      before_rate: 0,
      after_rate: null,
      change_pp: null,
      reason: "Missing after value.",
    },
  ];
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(respond(fixture()))
    .mockResolvedValueOnce(respond(restored));
  vi.stubGlobal("fetch", fetcher);
  const saver = vi
    .spyOn(downloads, "downloadAnalysis")
    .mockReturnValue("test-analysis.json");
  render(<App />);
  expect(screen.getByRole("button", { name: "Save analysis" })).toBeDisabled();
  await screen.findByRole("heading", { name: "Test_v1" });
  const file = new File([JSON.stringify(restored.snapshot)], "reopened.json", {
    type: "application/json",
  });
  Object.defineProperty(file, "text", {
    value: async () => JSON.stringify(restored.snapshot),
  });
  fireEvent.change(screen.getByLabelText("Import saved JSON"), {
    target: { files: [file] },
  });
  await screen.findByText("reopened.json");
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual(restored.snapshot);
  expect(screen.getByLabelText("After")).toHaveValue("2026-09-21");
  await userEvent.selectOptions(screen.getByLabelText("After"), "2026-09-20");
  await userEvent.click(screen.getByRole("button", { name: "Save analysis" }));
  expect(saver).toHaveBeenCalledWith(restored.snapshot);
  expect(saver.mock.calls[0][0].compare?.after).toBe("2026-09-21");
  expect(screen.getByRole("status")).toHaveTextContent(
    "Download started: test-analysis.json",
  );
});

it("applies explicit hypotheses, keeps drafts out of saves, and preserves mappings through date changes and clearing", async () => {
  const initial = fixture();
  const mapped = fixture();
  mapped.snapshot.hypothesis = {
    statement: "More attempts finish",
    expectations: [{ step_id: "2", expected_direction: "increase" }],
  };
  const cleared = fixture();
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(respond(initial))
    .mockResolvedValueOnce(respond(mapped))
    .mockResolvedValueOnce(respond(mapped))
    .mockResolvedValueOnce(respond(cleared))
    .mockResolvedValue(respond(cleared));
  vi.stubGlobal("fetch", fetcher);
  const saver = vi
    .spyOn(downloads, "downloadAnalysis")
    .mockReturnValue("analysis.json");
  render(<App />);
  await screen.findByRole("heading", { name: "Test_v1" });
  fireEvent.change(screen.getByLabelText("Expected behaviour"), {
    target: { value: "More attempts finish" },
  });
  await userEvent.selectOptions(
    screen.getByLabelText("Expected direction for step 2"),
    "increase",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Apply hypothesis" }),
  );
  await screen.findByText("Edit hypothesis and measurements");
  expect(JSON.parse(fetcher.mock.calls[1][1].body).hypothesis).toEqual(
    mapped.snapshot.hypothesis,
  );
  await userEvent.click(screen.getByText("Edit hypothesis and measurements"));
  fireEvent.change(screen.getByLabelText("Expected behaviour"), {
    target: { value: "Unapplied draft" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Save analysis" }));
  expect(saver).toHaveBeenCalledWith(mapped.snapshot);
  await userEvent.click(screen.getByRole("button", { name: "Compare dates" }));
  await screen.findByText("Edit hypothesis and measurements");
  expect(JSON.parse(fetcher.mock.calls[2][1].body).hypothesis).toEqual(
    mapped.snapshot.hypothesis,
  );
  await userEvent.click(screen.getByText("Edit hypothesis and measurements"));
  expect(screen.getByLabelText("Expected behaviour")).toHaveValue(
    "More attempts finish",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Clear hypothesis" }),
  );
  await screen.findByText("Add hypothesis and measurements");
  expect(JSON.parse(fetcher.mock.calls[3][1].body).hypothesis).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Compare dates" }));
  await screen.findByText("Add hypothesis and measurements");
  expect(JSON.parse(fetcher.mock.calls[4][1].body).hypothesis).toBeNull();
});

it("retries a failed hypothesis request with the exact attempted settings", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(respond(fixture()))
    .mockRejectedValueOnce(new Error("Temporary failure"))
    .mockResolvedValueOnce(respond(fixture()));
  vi.stubGlobal("fetch", fetcher);
  render(<App />);
  await screen.findByRole("heading", { name: "Test_v1" });
  fireEvent.change(screen.getByLabelText("Expected behaviour"), {
    target: { value: "Check this expectation" },
  });
  await userEvent.selectOptions(
    screen.getByLabelText("Expected direction for step 2"),
    "increase",
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Apply hypothesis" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Temporary failure",
  );
  await userEvent.click(screen.getByRole("button", { name: "Retry request" }));
  await screen.findByRole("heading", { name: "Test_v1" });
  expect(fetcher.mock.calls[2][1].body).toBe(fetcher.mock.calls[1][1].body);
});
