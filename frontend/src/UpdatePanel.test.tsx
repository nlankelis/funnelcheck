import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import UpdatePanel from "./UpdatePanel";
import type { UpdateContext } from "./api";

const context: UpdateContext = {
  update: {
    name: "Tutorial explanation update",
    local_time: "2026-09-20T04:00",
    time_zone: "Europe/London",
    approximate: true,
  },
  occurred_at_utc: "2026-09-20T03:00:00Z",
  cohorts: [
    { cohort_date: "2026-09-19", phase: "before" },
    { cohort_date: "2026-09-20", phase: "transition" },
    { cohort_date: "2026-09-21", phase: "after" },
  ],
  suggested_comparison: { before: "2026-09-19", after: "2026-09-21" },
  notes: ["Labels are based on an approximate reported time."],
};

it("renders applied UTC timing and only applies edits on submit", async () => {
  const onApply = vi.fn();
  render(
    <UpdatePanel context={context} onApply={onApply} onCompare={vi.fn()} />,
  );
  expect(screen.getByText("UTC: 2026-09-20 03:00")).toBeVisible();
  expect(screen.getByText("Transition day")).toBeVisible();
  await userEvent.click(screen.getByText("Edit update details"));
  fireEvent.change(screen.getByLabelText("Deployment time"), {
    target: { value: "2026-09-21T05:00" },
  });
  expect(onApply).not.toHaveBeenCalled();
  expect(screen.getByText("UTC: 2026-09-20 03:00")).toBeVisible();
  await userEvent.click(
    screen.getByRole("button", { name: "Apply update details" }),
  );
  expect(onApply).toHaveBeenCalledWith({
    ...context.update,
    local_time: "2026-09-21T05:00",
  });
});

it("uses server-suggested dates and removes context explicitly", async () => {
  const onApply = vi.fn(),
    onCompare = vi.fn();
  render(
    <UpdatePanel context={context} onApply={onApply} onCompare={onCompare} />,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Compare surrounding full days" }),
  );
  expect(onCompare).toHaveBeenCalledWith(context.suggested_comparison);
  await userEvent.click(screen.getByText("Edit update details"));
  await userEvent.click(
    screen.getByRole("button", { name: "Remove update context" }),
  );
  expect(onApply).toHaveBeenCalledWith(null);
});

it("does not invent dates when a full before/after pair is unavailable", () => {
  render(
    <UpdatePanel
      context={{ ...context, suggested_comparison: null }}
      onApply={vi.fn()}
      onCompare={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: "Compare surrounding full days" }),
  ).not.toBeInTheDocument();
});

it("submits the current native date value even when a picker does not emit a React change event", async () => {
  const onApply = vi.fn();
  render(
    <UpdatePanel context={context} onApply={onApply} onCompare={vi.fn()} />,
  );
  await userEvent.click(screen.getByText("Edit update details"));
  (screen.getByLabelText("Deployment time") as HTMLInputElement).value =
    "2026-09-21T05:00";
  await userEvent.click(
    screen.getByRole("button", { name: "Apply update details" }),
  );
  expect(onApply).toHaveBeenCalledWith({
    ...context.update,
    local_time: "2026-09-21T05:00",
  });
});
