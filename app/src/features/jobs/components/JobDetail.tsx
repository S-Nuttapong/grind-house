"use client";

import {
  BanknoteIcon,
  BriefcaseIcon,
  Building2Icon,
  CalendarIcon,
  ClipboardCopyIcon,
  ExternalLinkIcon,
  GlobeIcon,
  MapPinIcon,
  SparklesIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { toast } from "sonner";

import { AppliedButton, NotInterestedButton, SaveButton } from "@/features/jobs/components/JobActions";
import { GenerateResume } from "@/features/resume/components/GenerateResume";
import { CompanyLogo } from "@/components/CompanyLogo";
import { Markdown } from "@/components/Markdown";
import { ScoreRing } from "@/components/ScoreRing";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { sourceLabel } from "@/features/jobs/filters";
import type { JobDetail as Job } from "@/features/jobs/types";

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Bangkok",
});

function TermList({ label, terms }: { label: string; terms: string[] }) {
  return (
    <p>
      <span className="text-muted-foreground">{label}: </span>
      {terms.length > 0 ? terms.join(", ") : "none"}
    </p>
  );
}

function Fact({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-lg border bg-background/60 p-3">
      <span className="mt-0.5 text-muted-foreground [&_svg]:size-4">{icon}</span>
      <div className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd className="truncate text-sm font-medium">{children}</dd>
      </div>
    </div>
  );
}

export function JobDetail({ job, source }: { job: Job; source: string }) {
  const posted = job.posted_at ? DATE.format(new Date(job.posted_at)) : `Found ${DATE.format(new Date(job.first_seen_at))}`;

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(job.tailor_prompt);
      toast.success("Tailor prompt copied");
    } catch {
      toast.error("Could not copy. Select the text manually.");
    }
  }

  return (
    <article className="space-y-6">
      <header className="space-y-4">
        <div className="flex items-start gap-4">
          <CompanyLogo name={job.company} className="size-12 text-base" />
          <div className="min-w-0 flex-1">
            <h2 className="text-xl leading-tight font-semibold tracking-tight">{job.title}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {job.company}
              {job.place && ` · ${job.place}`}
            </p>
            {job.closed_at && (
              <Badge variant="destructive" className="mt-2">
                Closed
              </Badge>
            )}
          </div>
          <ScoreRing score={job.score} band={job.fit_tier} stage={job.stage} size="lg" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="lg" className="px-5">
            <a href={job.apply_url} target="_blank" rel="noopener noreferrer">
              Apply now
              <ExternalLinkIcon data-icon="inline-end" />
            </a>
          </Button>
          <SaveButton jobId={job.id} saved={job.status === "saved"} />
          <AppliedButton jobId={job.id} applied={job.status === "applied"} />
          <NotInterestedButton jobId={job.id} />
        </div>
      </header>

      <section aria-labelledby="match-heading" className="rounded-xl border border-dashed bg-accent/40 p-4">
        <h3 id="match-heading" className="flex items-center gap-2 text-sm font-semibold">
          <SparklesIcon className="size-4 text-primary" />
          Match
        </h3>
        <p className="mt-1 text-sm text-muted-foreground">
          {job.score === null
            ? "Not scored yet. The next scheduled fit run scores this job."
            : `${Math.round(job.score)}% match against your ${source}${job.fit_tier ? `, ${job.fit_tier}` : ""}.`}
        </p>
        {job.score !== null && (
          <div className="mt-3 space-y-2 text-sm">
            {job.coverage !== null && (
              <p>
                <span className="text-muted-foreground">Coverage: </span>
                {Math.round(job.coverage * 100)}% of the requirements have a brag doc.
              </p>
            )}
            {job.top_brags.length > 0 && (
              <ul className="space-y-2">
                {job.top_brags.map((brag) => (
                  <li key={brag.id}>
                    <span className="font-medium">{brag.title}</span>
                    <span className="text-muted-foreground"> · {Math.round(brag.similarity * 100)}%</span>
                    <p className="line-clamp-2 text-muted-foreground">{brag.aspect}</p>
                  </li>
                ))}
              </ul>
            )}
            {job.gaps.length > 0 && (
              <p>
                <span className="text-muted-foreground">Gaps: </span>
                {job.gaps.join("; ")}
              </p>
            )}
            <TermList label="Matched" terms={job.matched_terms} />
            <TermList label="Missing" terms={job.missing_terms} />
          </div>
        )}
        <div className="mt-3">
          <GenerateResume
            key={job.id}
            jobId={job.id}
            enabled={job.score !== null || job.top_brags.length > 0}
          />
        </div>
      </section>

      <section aria-labelledby="details-heading" className="space-y-3">
        <h3 id="details-heading" className="text-sm font-semibold">
          Job details
        </h3>
        <dl className="grid grid-cols-2 gap-2">
          <Fact icon={<BanknoteIcon />} label="Pay">
            {job.salary_label ?? "Not listed"}
          </Fact>
          <Fact icon={<BriefcaseIcon />} label="Job type">
            {job.employment_type ?? "Not listed"}
          </Fact>
          <Fact icon={<Building2Icon />} label="Workplace">
            {job.remote_label}
          </Fact>
          <Fact icon={<MapPinIcon />} label="Location">
            {job.place || "Not listed"}
          </Fact>
          <Fact icon={<CalendarIcon />} label="Posted">
            {posted}
          </Fact>
          <Fact icon={<GlobeIcon />} label="Sources">
            {job.postings.map((posting, index) => (
              <span key={`${posting.source_id}-${index}`}>
                {index > 0 && ", "}
                {posting.source_url ? (
                  <a href={posting.source_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                    {sourceLabel(posting.source_id)}
                  </a>
                ) : (
                  sourceLabel(posting.source_id)
                )}
              </span>
            ))}
          </Fact>
        </dl>
      </section>

      <Separator />

      <section aria-labelledby="description-heading">
        <h3 id="description-heading" className="mb-2 text-sm font-semibold">
          Full job description
        </h3>
        {job.description_md ? (
          <Markdown>{job.description_md}</Markdown>
        ) : (
          <p className="text-sm text-muted-foreground">No description was captured for this posting.</p>
        )}
      </section>

      <Separator />

      <section aria-labelledby="history-heading" className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h3 id="history-heading" className="text-sm font-semibold">
            Your activity
          </h3>
          <Button variant="outline" size="sm" onClick={copyPrompt}>
            <ClipboardCopyIcon />
            Copy tailor prompt
          </Button>
        </div>
        {job.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">No activity yet.</p>
        ) : (
          <ol className="space-y-2 border-l pl-4">
            {job.events.map((event, index) => (
              <li key={`${event.at}-${index}`} className="text-sm">
                <span className="font-medium capitalize">{event.status}</span>
                <span className="text-muted-foreground"> · {DATE_TIME.format(new Date(event.at))}</span>
                {event.reason && <p className="text-muted-foreground">“{event.reason}”</p>}
              </li>
            ))}
          </ol>
        )}
      </section>
    </article>
  );
}
