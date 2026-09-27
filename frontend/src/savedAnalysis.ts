import type { SavedAnalysis } from "./api";

export function downloadAnalysis(snapshot: SavedAnalysis): string {
  // Python supplied only validated inputs. Never serialize the whole report or drafts.
  const blob = new Blob([JSON.stringify(snapshot, null, 2) + "\n"], {
    type: "application/json",
  });
  if (blob.size > 5 * 1024 * 1024) {
    throw new Error(
      "This analysis exceeds the 5 MB import limit. Use a smaller date window before saving.",
    );
  }
  const name =
    snapshot.query.funnel_name.replace(/[^a-zA-Z0-9_-]/g, "-").slice(0, 80) ||
    "analysis";
  const lastDay = new Date(`${snapshot.query.end_exclusive}T00:00:00Z`);
  lastDay.setUTCDate(lastDay.getUTCDate() - 1);
  const filename = `funnelcheck-${name}-${snapshot.query.start}-${lastDay.toISOString().slice(0, 10)}.json`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  try {
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
  } finally {
    link.remove();
    // Give the browser time to consume the URL before releasing its memory.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return filename;
}
