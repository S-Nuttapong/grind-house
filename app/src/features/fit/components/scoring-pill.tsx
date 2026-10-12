"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { fetchFitRun, fetchFitRuns } from "@/features/fit/client";
import { useHydrated } from "@/lib/use-hydrated";

export function ScoringPill() {
  const hydrated = useHydrated();
  const runs = useQuery({
    queryKey: ["fit-runs"],
    queryFn: fetchFitRuns,
    refetchInterval: (current) => (current.state.data?.some((run) => run.status === "queued" || run.status === "running") ? 2000 : 15000),
  });
  const active = runs.data?.find((run) => run.status === "queued" || run.status === "running");
  const detail = useQuery({
    queryKey: ["fit-run", active?.id ?? null],
    enabled: active !== undefined,
    queryFn: () => fetchFitRun(active?.id ?? 0),
    refetchInterval: (current) => {
      const status = current.state.data?.status ?? active?.status;
      return status === "ok" || status === "failed" ? false : 2000;
    },
  });
  if (!hydrated || !active) return null;
  const pct = detail.data?.progress?.payload.pct;
  const label = pct === undefined ? "Scoring" : `Scoring ${Math.round(pct)}%`;
  return (
    <Link href="/schedules" className="rounded-full bg-primary/10 px-2.5 py-1 text-xs font-medium text-primary">
      {label}
    </Link>
  );
}
