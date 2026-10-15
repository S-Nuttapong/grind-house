"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { deleteSchedule, runScheduleNow, saveSchedule } from "@/features/fit/actions";
import { useFitRun } from "@/features/fit/useFitRun";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { fetchFitRuns, fetchFitSchedules, fetchFitStatus } from "@/features/fit/client";
import { useHydrated } from "@/lib/useHydrated";
import type { FitMode, FitRun, FitSchedule, FitStreamEvent, ScheduleInput } from "@/features/fit/types";
import { cn } from "@/lib/utils";

const PRESETS = [
  { label: "Hourly", cron: "0 * * * *" },
  { label: "Daily 07:00", cron: "0 7 * * *" },
  { label: "Weekdays", cron: "0 7 * * 1-5" },
];

const WHEN = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Bangkok",
});

const MODE_LABEL: Record<FitMode, string> = { bank: "Brag docs", resume: "Selected resume" };

export function SchedulesView() {
  const hydrated = useHydrated();
  const queryClient = useQueryClient();
  const schedules = useQuery({ queryKey: ["fit-schedules"], queryFn: fetchFitSchedules });
  const runs = useQuery({
    queryKey: ["fit-runs"],
    queryFn: fetchFitRuns,
    refetchInterval: (current) => (current.state.data?.some(isActive) ? 2000 : 15000),
  });
  const status = useQuery({ queryKey: ["fit-status"], queryFn: fetchFitStatus, refetchInterval: 30000 });
  const [editing, setEditing] = useState<FitSchedule | null | "new">(null);
  const [removing, setRemoving] = useState<FitSchedule | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const active = runs.data?.find(isActive) ?? null;
  const watchedId = selectedId ?? active?.id ?? runs.data?.[0]?.id ?? null;
  const live = useFitRun(watchedId);
  const [isPending, startTransition] = useTransition();

  function refreshSchedules() {
    return queryClient.invalidateQueries({ queryKey: ["fit-schedules"] });
  }

  if (!hydrated) {
    return <p className="text-sm text-muted-foreground">Loading schedules…</p>;
  }

  return (
    <div className="space-y-8">
      <WorkerNote heartbeat={status.data?.worker.heartbeat_at ?? null} />
      <section className="space-y-3" aria-labelledby="schedules-heading">
        <div className="flex items-center justify-between gap-3">
          <h2 id="schedules-heading" className="text-sm font-semibold">
            Schedules
          </h2>
          <Button type="button" onClick={() => setEditing("new")}>
            New schedule
          </Button>
        </div>
        {schedules.isLoading ? (
          <p className="text-sm text-muted-foreground">Loading schedules…</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[52rem] text-sm">
              <thead className="bg-muted/50 text-left text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 font-medium">Name</th>
                  <th className="px-3 py-2 font-medium">Mode</th>
                  <th className="px-3 py-2 font-medium">When</th>
                  <th className="px-3 py-2 font-medium">Next runs</th>
                  <th className="px-3 py-2 font-medium">Last run</th>
                  <th className="px-3 py-2 font-medium">On</th>
                  <th className="px-3 py-2 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {schedules.data?.map((schedule) => (
                  <tr key={schedule.id} className="border-t">
                    <td className="px-3 py-3 font-medium">{schedule.name}</td>
                    <td className="px-3 py-3">{MODE_LABEL[schedule.mode]}</td>
                    <td className="px-3 py-3">
                      <div>{schedule.description}</div>
                      <div className="font-mono text-xs text-muted-foreground">{schedule.cron}</div>
                    </td>
                    <td className="px-3 py-3 text-muted-foreground">
                      {schedule.upcoming.slice(0, 3).map((moment) => (
                        <div key={moment}>{WHEN.format(new Date(moment))}</div>
                      ))}
                    </td>
                    <td className="px-3 py-3">
                      <LastRun run={schedule.last_run} />
                    </td>
                    <td className="px-3 py-3">
                      <Switch
                        checked={schedule.enabled}
                        aria-label={`${schedule.enabled ? "Disable" : "Enable"} ${schedule.name}`}
                        disabled={isPending}
                        onCheckedChange={(checked) => {
                          startTransition(async () => {
                            const result = await saveSchedule({ ...schedule, enabled: checked === true }, schedule.id);
                            if (result.ok) await refreshSchedules();
                            else toast.error(result.error);
                          });
                        }}
                      />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-1">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={isPending}
                          onClick={() => {
                            startTransition(async () => {
                              const result = await runScheduleNow(schedule.id);
                              if (!result.ok) {
                                toast.error(result.error);
                                return;
                              }
                              setSelectedId(result.runId);
                              toast.success(result.created ? "Run queued" : "That run is already queued");
                              await queryClient.invalidateQueries({ queryKey: ["fit-runs"] });
                            });
                          }}
                        >
                          Run now
                        </Button>
                        <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(schedule)}>
                          Edit
                        </Button>
                        <Button type="button" size="sm" variant="ghost" onClick={() => setRemoving(schedule)}>
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="space-y-3" aria-labelledby="runs-heading">
        <h2 id="runs-heading" className="text-sm font-semibold">
          Recent fit runs
        </h2>
        {runs.data && runs.data.length === 0 && <p className="text-sm text-muted-foreground">No fit runs yet.</p>}
        <ul className="space-y-2">
          {runs.data?.map((run) => (
            <li key={run.id}>
              <button
                type="button"
                onClick={() => setSelectedId(run.id)}
                className={cn(
                  "flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left",
                  watchedId === run.id && "border-primary/50",
                )}
              >
                <span>
                  <span className="font-medium">{MODE_LABEL[run.mode]}</span>
                  <span className="text-muted-foreground"> · {run.trigger}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{runSummary(run)}</span>
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {WHEN.format(new Date(run.queued_at))}
                  <Badge variant="outline" className="capitalize">
                    {run.status}
                  </Badge>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {watchedId !== null && <RunDetail runId={watchedId} run={live.run} events={live.events} />}
      </section>
      <ScheduleDialog
        target={editing}
        onClose={() => setEditing(null)}
        onSaved={async () => {
          setEditing(null);
          await refreshSchedules();
        }}
      />
      <Dialog open={removing !== null} onOpenChange={(open) => !open && setRemoving(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {removing?.name}?</DialogTitle>
            <DialogDescription>Past runs stay in the list. This only removes the schedule.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setRemoving(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isPending || removing === null}
              onClick={() => {
                if (!removing) return;
                startTransition(async () => {
                  const result = await deleteSchedule(removing.id);
                  if (result.ok) {
                    toast.success("Schedule deleted");
                    setRemoving(null);
                    await refreshSchedules();
                  } else toast.error(result.error);
                });
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function isActive(run: FitRun): boolean {
  return run.status === "queued" || run.status === "running";
}

function took(run: FitRun): string | null {
  if (!run.started_at || !run.finished_at) return null;
  const seconds = Math.max(0, Math.round((Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function runSummary(run: FitRun): string {
  const counts = `${run.scored.toLocaleString()} scored, ${run.skipped.toLocaleString()} skipped`;
  const duration = took(run);
  return duration ? `${counts} · ${duration}` : counts;
}

function LastRun({ run }: { run: FitRun | null }) {
  if (!run) return <span className="text-muted-foreground">Never</span>;
  const when = run.started_at ?? run.queued_at;
  return (
    <div>
      <div className="flex items-center gap-2">
        <span>{WHEN.format(new Date(when))}</span>
        <Badge variant="outline" className="capitalize">
          {run.status}
        </Badge>
      </div>
      <div className="text-xs text-muted-foreground">{runSummary(run)}</div>
    </div>
  );
}

function RunDetail({
  runId,
  run,
  events,
}: {
  runId: number;
  run: { status: string; error: string | null; progress: { payload: { done?: number; total?: number; pct?: number } } | null } | undefined;
  events: FitStreamEvent[];
}) {
  const latest = [...events].reverse().find((event) => event.kind === "progress");
  const done = latest?.done ?? run?.progress?.payload.done;
  const total = latest?.total ?? run?.progress?.payload.total;
  const pct = latest?.pct ?? run?.progress?.payload.pct;
  const status = run?.status ?? "";
  const showBar = status === "queued" || status === "running" || (pct !== undefined && pct < 100);
  return (
    <div className="space-y-3 rounded-xl border bg-card p-4">
      <h3 className="text-sm font-semibold">Run {runId}</h3>
      {showBar && pct !== undefined && done !== undefined && total !== undefined && (
        <div>
          <div className="h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">
            <div className="h-full bg-primary" style={{ width: `${Math.max(0, Math.min(100, pct))}%` }} />
          </div>
          <p className="mt-2 text-sm text-muted-foreground">
            {done.toLocaleString()} / {total.toLocaleString()} jobs, {Math.round(pct)}%
          </p>
        </div>
      )}
      {run?.error && <p className="text-sm text-destructive">{run.error}</p>}
      {events.length > 0 && (
        <ol className="max-h-48 space-y-1 overflow-auto font-mono text-xs text-muted-foreground" aria-label="Run events">
          {events.map((event) => (
            <li key={event.id}>{formatEvent(event)}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

function formatEvent(event: FitStreamEvent): string {
  if (event.kind === "progress" && event.done !== undefined && event.total !== undefined && event.pct !== undefined) {
    return `${event.done.toLocaleString()} / ${event.total.toLocaleString()} jobs, ${Math.round(event.pct)}%`;
  }
  if (event.kind === "status") return `Finished: ${event.status}`;
  return event.kind;
}

function WorkerNote({ heartbeat }: { heartbeat: string | null }) {
  if (heartbeat !== null) return null;
  return <p className="text-sm text-muted-foreground">The fit worker has not started. Run now waits in the queue until it does.</p>;
}

function ScheduleDialog({
  target,
  onClose,
  onSaved,
}: {
  target: FitSchedule | null | "new";
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        {target !== null && <ScheduleForm key={target === "new" ? "new" : target.id} target={target} onClose={onClose} onSaved={onSaved} />}
      </DialogContent>
    </Dialog>
  );
}

function ScheduleForm({
  target,
  onClose,
  onSaved,
}: {
  target: FitSchedule | "new";
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const existing = target === "new" ? null : target;
  const [draft, setDraft] = useState<ScheduleInput>({
    name: existing?.name ?? "",
    mode: existing?.mode ?? "bank",
    cron: existing?.cron ?? "0 7 * * *",
    timezone: existing?.timezone ?? "Asia/Bangkok",
    enabled: existing?.enabled ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await saveSchedule(draft, existing?.id);
          if (result.ok) {
            toast.success(existing ? "Schedule saved" : "Schedule added");
            await onSaved();
          } else setError(result.error);
        });
      }}
    >
      <DialogHeader>
        <DialogTitle>{existing ? "Edit schedule" : "New schedule"}</DialogTitle>
        <DialogDescription>Runs at least 15 minutes apart. Times use the schedule timezone.</DialogDescription>
      </DialogHeader>
      <div className="space-y-1.5">
        <Label htmlFor="schedule-name">Name</Label>
        <Input id="schedule-name" value={draft.name} required onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Score against</legend>
        {(["bank", "resume"] as const).map((mode) => (
          <div key={mode} className="flex items-center gap-2">
            <input
              id={`schedule-mode-${mode}`}
              type="radio"
              name="schedule-mode"
              checked={draft.mode === mode}
              onChange={() => setDraft({ ...draft, mode })}
            />
            <Label htmlFor={`schedule-mode-${mode}`} className="font-normal">
              {MODE_LABEL[mode]}
            </Label>
          </div>
        ))}
      </fieldset>
      <div className="space-y-1.5">
        <Label htmlFor="schedule-cron">Cron</Label>
        <Input
          id="schedule-cron"
          value={draft.cron}
          required
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "schedule-cron-error" : undefined}
          className="font-mono"
          onChange={(event) => {
            setDraft({ ...draft, cron: event.target.value });
            setError(null);
          }}
        />
        <div className="flex flex-wrap gap-2">
          {PRESETS.map((preset) => (
            <Button
              key={preset.cron}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                setDraft({ ...draft, cron: preset.cron });
                setError(null);
              }}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        {error && (
          <p id="schedule-cron-error" role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="schedule-timezone">Timezone</Label>
        <Input id="schedule-timezone" value={draft.timezone} onChange={(event) => setDraft({ ...draft, timezone: event.target.value })} />
      </div>
      <div className="flex items-center gap-2.5">
        <Switch id="schedule-enabled" checked={draft.enabled} onCheckedChange={(checked) => setDraft({ ...draft, enabled: checked === true })} />
        <Label htmlFor="schedule-enabled" className="font-normal">
          Enabled
        </Label>
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" disabled={isPending}>
          {isPending ? "Saving…" : "Save schedule"}
        </Button>
      </DialogFooter>
    </form>
  );
}
