import { Badge } from "@/components/ui/badge";
import { fetchRuns } from "@/features/scrape/api";
import type { Run } from "@/features/scrape/types";
import { sourceLabel } from "@/features/jobs/filters";
import { cn } from "@/lib/utils";

const WHEN = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Bangkok",
});
const COUNT = new Intl.NumberFormat("en-US");

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  partial: "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  failed: "bg-destructive/10 text-destructive",
  running: "bg-primary/10 text-primary",
  skipped: "bg-muted text-muted-foreground",
};

function duration(run: Run): string {
  if (!run.finished_at) return "–";
  const seconds = Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export async function RunsTable() {
  const runs = await fetchRuns();
  if (runs.length === 0) {
    return <p className="rounded-2xl border border-dashed p-8 text-center text-sm text-muted-foreground">No runs yet.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-2xl border bg-card shadow-sm">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-medium">Started</th>
            <th className="px-4 py-3 font-medium">Source</th>
            <th className="px-4 py-3 font-medium">Scope</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 text-right font-medium">Fetched</th>
            <th className="px-4 py-3 text-right font-medium">New</th>
            <th className="px-4 py-3 text-right font-medium">Updated</th>
            <th className="px-4 py-3 text-right font-medium">Closed</th>
            <th className="px-4 py-3 text-right font-medium">Skipped</th>
            <th className="px-4 py-3 text-right font-medium">Took</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-b last:border-0 hover:bg-muted/30">
              <td className="px-4 py-3 whitespace-nowrap">{WHEN.format(new Date(run.started_at))}</td>
              <td className="px-4 py-3">{sourceLabel(run.source_id)}</td>
              <td className="px-4 py-3 text-muted-foreground">{run.scope_name ?? "–"}</td>
              <td className="px-4 py-3">
                <Badge className={cn("capitalize", STATUS_STYLES[run.status])}>{run.status}</Badge>
                {run.source_alert && (
                  <Badge className="ml-2 bg-destructive/10 text-destructive">last 3 failed</Badge>
                )}
                {run.error && <p className="mt-1 max-w-xs truncate text-xs text-destructive" title={run.error}>{run.error}</p>}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.fetched ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.new_jobs ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.updated ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.closed ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.skipped ?? 0)}</td>
              <td className="px-4 py-3 text-right text-muted-foreground tabular-nums">{duration(run)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
