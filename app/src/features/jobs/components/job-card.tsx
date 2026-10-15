"use client";

import { BanknoteIcon, MapPinIcon } from "lucide-react";
import Link from "next/link";

import { useBoard } from "@/features/jobs/components/board-provider";
import { NotInterestedButton, SaveButton } from "@/features/jobs/components/job-actions";
import { CompanyLogo } from "@/components/company-logo";
import { ScoreRing } from "@/components/score-ring";
import { Badge } from "@/components/ui/badge";
import { sourceLabel, TIER_LABELS } from "@/features/jobs/filters";
import type { JobSummary } from "@/features/jobs/types";
import { cn } from "@/lib/utils";

const TIER_BADGE: Record<string, string> = {
  strong: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  good: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  fair: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-slate-100 text-slate-600 dark:bg-slate-900 dark:text-slate-300",
};

export function JobCard({ job, selected }: { job: JobSummary; selected: boolean }) {
  const { hrefFor, navigate } = useBoard();
  return (
    <li
      aria-current={selected ? "true" : undefined}
      className={cn(
        "group relative rounded-xl border bg-card p-4 shadow-xs transition-all hover:border-primary/40 hover:shadow-md",
        selected && "border-primary/60 ring-2 ring-primary/20",
        job.status === "skipped" && "opacity-60",
      )}
    >
      <div className="flex gap-4">
        <ScoreRing score={job.score} band={job.fit_tier} stage={job.stage} />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <h3 className="leading-snug font-semibold">
                <Link
                  data-testid={`job-card-${job.id}`}
                  href={hrefFor({ jk: String(job.id) })}
                  scroll={false}
                  onClick={(event) => {
                    if (event.metaKey || event.ctrlKey || event.shiftKey) return;
                    event.preventDefault();
                    navigate({ jk: String(job.id) });
                  }}
                  className="outline-none after:absolute after:inset-0 after:rounded-xl focus-visible:after:ring-2 focus-visible:after:ring-ring"
                >
                  {job.title}
                </Link>
              </h3>
              <p className="mt-0.5 flex items-center gap-2 text-sm text-muted-foreground">
                <CompanyLogo name={job.company} className="size-5 rounded text-[9px]" />
                <span className="truncate">{job.company}</span>
              </p>
            </div>
            <div className="relative z-10 -mt-1 -mr-2 flex items-center">
              <SaveButton jobId={job.id} saved={job.status === "saved"} compact />
              <NotInterestedButton jobId={job.id} compact />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            {job.place && (
              <span className="inline-flex items-center gap-1 text-muted-foreground">
                <MapPinIcon className="size-3.5" />
                {job.place}
              </span>
            )}
            {job.salary_label && (
              <Badge variant="secondary" className="gap-1 bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                <BanknoteIcon />
                {job.salary_label}
              </Badge>
            )}
            {job.experience_label && <Badge variant="secondary">{job.experience_label}</Badge>}
            {job.remote && job.remote !== "unknown" && <Badge variant="secondary">{job.remote_label}</Badge>}
            {job.employment_type && <Badge variant="outline">{job.employment_type}</Badge>}
            {job.fit_tier && job.score !== null && (
              <Badge className={TIER_BADGE[job.fit_tier]}>
                {Math.round(job.score)}% {TIER_LABELS[job.fit_tier]}
              </Badge>
            )}
            {job.age &&
              (job.is_new ? (
                <Badge className="bg-primary/10 text-primary">{job.age} ago</Badge>
              ) : (
                <span className="text-muted-foreground">{job.age} ago</span>
              ))}
            {job.status && job.status !== "skipped" && (
              <Badge variant="outline" className="capitalize">
                {job.status}
              </Badge>
            )}
          </div>
          {job.snippet && <p className="line-clamp-2 text-sm text-muted-foreground">{job.snippet}</p>}
          <div className="flex flex-wrap gap-1">
            {job.sources.map((source) => (
              <span key={source} className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
                {sourceLabel(source)}
              </span>
            ))}
          </div>
        </div>
      </div>
    </li>
  );
}
