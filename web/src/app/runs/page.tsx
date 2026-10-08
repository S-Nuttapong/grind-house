import { Suspense } from "react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchRuns } from "@/lib/api";
import { sourceLabel } from "@/lib/filters";
import type { Run } from "@/lib/types";
import { cn } from "@/lib/utils";

export const metadata = { title: "Runs · Job Hunt" };

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
};

export default function RunsPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
        <p className="text-sm text-muted-foreground">Recent scrapes per source. Times are Bangkok time.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
        <RunsTable />
      </Suspense>
    </div>
  );
}

function duration(run: Run): string {
  if (!run.finished_at) return "–";
  const seconds = Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000);
  return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

async function RunsTable() {
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
                {run.error && <p className="mt-1 max-w-xs truncate text-xs text-destructive" title={run.error}>{run.error}</p>}
              </td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.fetched ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.new_jobs ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.updated ?? 0)}</td>
              <td className="px-4 py-3 text-right tabular-nums">{COUNT.format(run.closed ?? 0)}</td>
              <td className="px-4 py-3 text-right text-muted-foreground tabular-nums">{duration(run)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
