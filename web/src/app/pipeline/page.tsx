import { BookmarkIcon, CheckCircle2Icon, ThumbsDownIcon } from "lucide-react";
import Link from "next/link";
import { Suspense, type ReactNode } from "react";

import { CompanyLogo } from "@/components/company-logo";
import { MoveMenu } from "@/components/pipeline/move-menu";
import { ScoreRing } from "@/components/score-ring";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchPipeline } from "@/lib/api";
import type { JobStatus, JobSummary } from "@/lib/types";

export const metadata = { title: "Pipeline · Job Hunt" };

const COLUMNS: { status: JobStatus; title: string; icon: ReactNode; hint: string }[] = [
  { status: "saved", title: "Saved", icon: <BookmarkIcon className="size-4 text-primary" />, hint: "Jobs worth a closer look" },
  { status: "applied", title: "Applied", icon: <CheckCircle2Icon className="size-4 text-emerald-500" />, hint: "Applications sent" },
  { status: "skipped", title: "Not interested", icon: <ThumbsDownIcon className="size-4 text-muted-foreground" />, hint: "Hidden from your shortlist" },
];

export default function PipelinePage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Pipeline</h1>
        <p className="text-sm text-muted-foreground">Everything you saved, applied to, or passed on.</p>
      </div>
      <Suspense fallback={<PipelineSkeleton />}>
        <Columns />
      </Suspense>
    </div>
  );
}

async function Columns() {
  const pipeline = await fetchPipeline();
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {COLUMNS.map((column) => (
        <section
          key={column.status}
          id={column.status}
          aria-labelledby={`${column.status}-heading`}
          className="flex min-h-64 flex-col rounded-2xl border bg-muted/40 p-3"
        >
          <header className="flex items-center gap-2 px-1 pb-3">
            {column.icon}
            <h2 id={`${column.status}-heading`} className="text-sm font-semibold">
              {column.title}
            </h2>
            <Badge variant="secondary" className="ml-auto tabular-nums">
              {pipeline[column.status].length}
            </Badge>
          </header>
          {pipeline[column.status].length === 0 ? (
            <p className="m-auto px-4 text-center text-sm text-muted-foreground">{column.hint}. Nothing here yet.</p>
          ) : (
            <ol className="space-y-2">
              {pipeline[column.status].map((job) => (
                <PipelineCard key={job.id} job={job} />
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  );
}

function PipelineCard({ job }: { job: JobSummary }) {
  return (
    <li className="relative flex gap-3 rounded-xl border bg-card p-3 shadow-xs transition-shadow hover:shadow-md">
      <CompanyLogo name={job.company} className="size-9 text-xs" />
      <div className="min-w-0 flex-1">
        <Link
          href={`/?jk=${job.id}`}
          className="line-clamp-2 text-sm leading-snug font-medium after:absolute after:inset-0 after:rounded-xl hover:text-primary"
        >
          {job.title}
        </Link>
        <p className="truncate text-xs text-muted-foreground">
          {job.company}
          {job.place && ` · ${job.place}`}
        </p>
        {job.salary_label && <p className="mt-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">{job.salary_label}</p>}
      </div>
      <div className="flex flex-col items-end gap-1">
        <MoveMenu jobId={job.id} current={job.status ?? ""} />
        <div className="relative z-10">
          <ScoreRing score={job.score} band={job.fit_tier} stage={job.stage} />
        </div>
      </div>
    </li>
  );
}

function PipelineSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {COLUMNS.map((column) => (
        <div key={column.status} className="space-y-2 rounded-2xl border bg-muted/40 p-3">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ))}
    </div>
  );
}
