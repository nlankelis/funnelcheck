import { afterEach, expect, it, vi } from "vitest";
import { downloadAnalysis } from "./savedAnalysis";
import type { SavedAnalysis } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("downloads input JSON with precise rates and releases its temporary URL", async () => {
  const snapshot: SavedAnalysis = {
    query: {
      universe_id: "1",
      funnel_name: "Test_v1",
      metric: "FunnelCohortSessionCompletionRate",
      granularity: "OneDay",
      start: "2026-09-19",
      end_exclusive: "2026-09-22",
      step_ids: ["1"],
    },
    result: {
      done: true,
      response: { values: [{ dataPoints: [{ value: 0.2753623127937317 }] }] },
    },
    compare: { before: "2026-09-19", after: "2026-09-21" },
    update: null,
  };
  const create = vi.fn().mockReturnValue("blob:test"),
    revoke = vi.fn();
  vi.stubGlobal("URL", { createObjectURL: create, revokeObjectURL: revoke });
  const click = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe(
        "funnelcheck-Test_v1-2026-09-19-2026-09-21.json",
      );
      expect(this.href).toBe("blob:test");
    });
  vi.useFakeTimers();
  expect(downloadAnalysis(snapshot)).toBe(
    "funnelcheck-Test_v1-2026-09-19-2026-09-21.json",
  );
  expect(click).toHaveBeenCalledOnce();
  expect(document.querySelector("a[download]")).toBeNull();
  expect(revoke).not.toHaveBeenCalled();
  vi.runAllTimers();
  expect(revoke).toHaveBeenCalledWith("blob:test");
  vi.useRealTimers();
  const reader = new FileReader();
  const text = new Promise<string>((resolve, reject) => {
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
  });
  reader.readAsText(create.mock.calls[0][0]);
  expect(JSON.parse(await text)).toEqual(snapshot);
});

it("refuses a download that would exceed the import limit", () => {
  const create = vi.fn();
  vi.stubGlobal("URL", { createObjectURL: create });
  const huge = {
    result: "x".repeat(5 * 1024 * 1024),
  } as unknown as SavedAnalysis;
  expect(() => downloadAnalysis(huge)).toThrow("5 MB import limit");
  expect(create).not.toHaveBeenCalled();
});
