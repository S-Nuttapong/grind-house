"use client";

import { FileDownIcon, Loader2Icon } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { fetchResumeRuns, startResume } from "@/features/resume/client";
import { useResumeRun } from "@/features/resume/components/use-resume-run";

export function GenerateResume({ jobId, enabled }: { jobId: number; enabled: boolean }) {
  const [runId, setRunId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const { run, events } = useResumeRun(runId);
  const latest = events.at(-1);
  const running = run?.status === "queued" || run?.status === "running" || starting;

  useEffect(() => {
    let cancelled = false;
    void fetchResumeRuns(jobId)
      .then((runs) => {
        if (!cancelled && runs[0]) setRunId(runs[0].id);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  async function generate() {
    setStarting(true);
    try {
      const created = await startResume(jobId);
      setRunId(created.run_id);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not start");
    } finally {
      setStarting(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!enabled || running}
        onClick={() => void generate()}
        data-testid="generate-resume"
      >
        {running ? <Loader2Icon className="animate-spin" /> : <FileDownIcon />}
        Generate resume
      </Button>
      {running && (
        <p className="text-sm text-muted-foreground" data-testid="resume-progress">
          {run?.status === "running" || latest?.stage === "generating"
            ? `Writing attempt ${latest?.attempt ?? 1}…`
            : run?.ahead
              ? `Queued, ${run.ahead} ahead…`
              : "Queued…"}{" "}
          <Link href="/resume-queue" className="text-primary hover:underline">
            View queue
          </Link>
        </p>
      )}
      {run && !starting && run.status !== "queued" && run.status !== "running" && (
        <div className="space-y-1 text-sm" data-testid="resume-status">
          <p>
            {run.status === "ok" && "Resume ready."}
            {run.status === "below_baseline" && "Resume ready, below the shortlist baseline."}
            {run.status === "failed" && (run.error || "Resume failed.")}
          </p>
          {run.resume_score !== null && run.baseline_score !== null && (
            <p className="text-muted-foreground">
              Resume {Math.round(run.resume_score)}% · shortlist {Math.round(run.baseline_score)}%
            </p>
          )}
          {run.lost_aspects.length > 0 && (
            <p className="text-muted-foreground">Lost: {run.lost_aspects.join("; ")}</p>
          )}
          {run.filler_ids.length > 0 && (
            <p className="text-muted-foreground" data-testid="resume-filler">
              Filled with {run.filler_ids.join(", ")}
            </p>
          )}
          {(run.status === "ok" || run.status === "below_baseline") && (
            <a
              className="text-primary hover:underline"
              href={`/api/resume-runs/${run.id}/pdf`}
              data-testid="resume-download"
            >
              Download PDF
            </a>
          )}
        </div>
      )}
    </div>
  );
}
