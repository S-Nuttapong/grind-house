"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { fetchResumeQueue } from "@/features/resume/client";
import type { ResumeQueueItem, ResumeStatus } from "@/features/resume/types";

const STATUS_LABEL: Record<ResumeStatus, string> = {
  queued: "Queued",
  running: "Writing",
  ok: "Ready",
  below_baseline: "Below baseline",
  failed: "Failed",
};

export function ResumeQueue() {
  const query = useQuery({
    queryKey: ["resume-queue"],
    queryFn: fetchResumeQueue,
    refetchInterval: 3000,
  });

  if (query.isPending) {
    return <p className="text-sm text-muted-foreground">Loading the queue…</p>;
  }
  if (query.isError || !query.data) {
    return <p className="text-sm text-destructive">Could not load the queue.</p>;
  }

  return (
    <div className="space-y-8">
      <section className="space-y-2" aria-labelledby="queue-active">
        <h2 id="queue-active" className="text-sm font-semibold">
          Active
        </h2>
        <QueueTable rows={query.data.active} empty="Nothing is queued." showPosition />
      </section>
      <section className="space-y-2" aria-labelledby="queue-recent">
        <h2 id="queue-recent" className="text-sm font-semibold">
          Recent
        </h2>
        <QueueTable rows={query.data.recent} empty="No finished resumes yet." />
      </section>
    </div>
  );
}

function QueueTable({
  rows,
  empty,
  showPosition = false,
}: {
  rows: ResumeQueueItem[];
  empty: string;
  showPosition?: boolean;
}) {
  if (rows.length === 0) {
    return <p className="text-sm text-muted-foreground">{empty}</p>;
  }
  return (
    <div className="overflow-x-auto rounded-2xl border bg-card shadow-sm">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
          <tr>
            {showPosition && <th className="px-4 py-3 font-medium">#</th>}
            <th className="px-4 py-3 font-medium">Job</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">When</th>
            <th className="px-4 py-3 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-b last:border-0">
              {showPosition && (
                <td className="px-4 py-3 tabular-nums text-muted-foreground">{(row.ahead ?? 0) + 1}</td>
              )}
              <td className="px-4 py-3">
                <Link href={`/?jk=${row.job_id}`} className="font-medium hover:text-primary">
                  {row.title}
                </Link>
                <p className="text-xs text-muted-foreground">{row.company}</p>
              </td>
              <td className="px-4 py-3">{STATUS_LABEL[row.status]}</td>
              <td className="px-4 py-3 text-muted-foreground">{ago(row.started_at ?? row.created_at)}</td>
              <td className="px-4 py-3">
                <Result row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Result({ row }: { row: ResumeQueueItem }) {
  if (row.status === "failed") {
    return <span className="text-muted-foreground">{row.error || "Failed"}</span>;
  }
  if (row.status !== "ok" && row.status !== "below_baseline") {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span className="space-x-2">
      {row.resume_score !== null && row.baseline_score !== null && (
        <span className="text-muted-foreground">
          {Math.round(row.resume_score)}% · shortlist {Math.round(row.baseline_score)}%
        </span>
      )}
      <a className="text-primary hover:underline" href={`/api/resume-runs/${row.id}/pdf`}>
        Download PDF
      </a>
    </span>
  );
}

function ago(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
