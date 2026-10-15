"use client";

import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  rectIntersection,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { BookmarkIcon, CheckCircle2Icon, ThumbsDownIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition, type ReactNode } from "react";
import { toast } from "sonner";

import { CompanyLogo } from "@/components/CompanyLogo";
import { ScoreRing } from "@/components/ScoreRing";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { moveJobs, queueResumes, restoreJobs } from "@/features/jobs/actions";
import { MoveMenu } from "@/features/jobs/components/MoveMenu";
import type { JobStatus, JobSummary, Pipeline } from "@/features/jobs/types";
import { cn } from "@/lib/utils";

const COLUMNS: { status: JobStatus; title: string; icon: ReactNode; hint: string }[] = [
  { status: "saved", title: "Saved", icon: <BookmarkIcon className="size-4 text-primary" />, hint: "Jobs worth a closer look" },
  { status: "applied", title: "Applied", icon: <CheckCircle2Icon className="size-4 text-emerald-500" />, hint: "Applications sent" },
  { status: "skipped", title: "Not interested", icon: <ThumbsDownIcon className="size-4 text-muted-foreground" />, hint: "Hidden from your shortlist" },
];

const RESUME_LABEL: Record<string, string> = {
  queued: "Queued",
  running: "Writing",
  ok: "Resume ready",
  below_baseline: "Resume ready",
  failed: "Failed",
};

const columnUnderPointer: CollisionDetection = (args) => {
  const hits = pointerWithin(args);
  return hits.length > 0 ? hits : rectIntersection(args);
};

function isColumn(value: unknown): value is JobStatus {
  return value === "saved" || value === "applied" || value === "skipped";
}

function canGenerate(job: JobSummary): boolean {
  const open = job.resume_status == null || job.resume_status === "failed";
  return open && job.score !== null;
}

export function PipelineBoard({ initial }: { initial: Pipeline }) {
  const [columns, setColumns] = useState(initial);
  const [seen, setSeen] = useState(initial);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [activeId, setActiveId] = useState<number | null>(null);
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor),
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") setSelected(new Set());
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  if (initial !== seen) {
    setSeen(initial);
    setColumns(initial);
    const live = new Set(Object.values(initial).flat().map((job) => job.id));
    setSelected((current) => new Set([...current].filter((id) => live.has(id))));
  }

  const jobs = Object.values(columns).flat();
  const selectedJobs = jobs.filter((job) => selected.has(job.id));
  const generatable = selectedJobs.filter(canGenerate);
  const activeJob = jobs.find((job) => job.id === activeId) ?? null;
  const dragCount = activeJob && selected.has(activeJob.id) ? selected.size : 1;

  function toggle(id: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleColumn(status: JobStatus) {
    const ids = columns[status].map((job) => job.id);
    const allOn = ids.length > 0 && ids.every((id) => selected.has(id));
    setSelected((current) => {
      const next = new Set(current);
      for (const id of ids) {
        if (allOn) next.delete(id);
        else next.add(id);
      }
      return next;
    });
  }

  function move(ids: number[], target: JobStatus) {
    if (ids.length === 0 || ids.every((id) => columns[target].some((job) => job.id === id))) return;
    const previous = columns;
    setColumns(relocate(columns, ids, target));
    startTransition(async () => {
      const result = await moveJobs(ids, target);
      if (!result.ok) {
        setColumns(previous);
        toast.error(result.error);
      }
    });
  }

  function generate() {
    const ids = selectedJobs.map((job) => job.id);
    startTransition(async () => {
      const result = await queueResumes(ids);
      if (!result.ok) {
        toast.error(result.error);
        return;
      }
      setColumns((current) => markQueued(current, result.queued.map((item) => item.job_id)));
      toast.success(`${result.queued.length} queued, ${result.skipped.length} skipped`, {
        action: { label: "View queue", onClick: () => router.push("/resume-queue") },
      });
    });
  }

  function removeSelected() {
    const snapshot = selectedJobs.flatMap((job) =>
      isColumn(job.status) ? [{ id: job.id, status: job.status }] : [],
    );
    const ids = snapshot.map((item) => item.id);
    const previous = columns;
    const previousSelected = selected;
    setColumns(without(columns, ids));
    setSelected(new Set());
    startTransition(async () => {
      const result = await moveJobs(ids, "removed");
      if (!result.ok) {
        setColumns(previous);
        setSelected(previousSelected);
        toast.error(result.error);
        return;
      }
      toast.success("Removed from pipeline", {
        action: {
          label: "Undo",
          onClick: () => {
            setColumns((current) => putBack(current, snapshot, jobs));
            startTransition(async () => {
              const restored = await restoreJobs(snapshot);
              if (!restored.ok) toast.error(restored.error);
            });
          },
        },
      });
    });
  }

  function onDragEnd(event: DragEndEvent) {
    setActiveId(null);
    const target = event.over?.id;
    if (!isColumn(target)) return;
    const id = Number(event.active.id);
    const ids = selected.has(id) ? [...selected] : [id];
    move(ids, target);
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={columnUnderPointer}
      onDragStart={(event: DragStartEvent) => setActiveId(Number(event.active.id))}
      onDragEnd={onDragEnd}
      onDragCancel={() => setActiveId(null)}
    >
      {selected.size > 0 && (
        <div className="sticky top-16 z-30 mb-4 flex flex-wrap items-center gap-2 rounded-xl border bg-card px-4 py-2 shadow-sm">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <Button type="button" size="sm" disabled={generatable.length === 0 || isPending} onClick={generate}>
            Generate resume ({generatable.length})
          </Button>
          <Button type="button" size="sm" variant="outline" disabled={isPending} onClick={removeSelected}>
            Remove from pipeline
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
            Clear
          </Button>
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-3">
        {COLUMNS.map((column) => (
          <Column
            key={column.status}
            column={column}
            jobs={columns[column.status]}
            selected={selected}
            onToggle={toggle}
            onToggleColumn={toggleColumn}
          />
        ))}
      </div>
      <DragOverlay>
        {activeJob &&
          (dragCount > 1 ? (
            <div className="rounded-xl border bg-card px-4 py-3 text-sm font-medium shadow-lg">{dragCount} jobs</div>
          ) : (
            <div className="max-w-xs rounded-xl border bg-card px-4 py-3 text-sm font-medium shadow-lg">
              {activeJob.title}
            </div>
          ))}
      </DragOverlay>
    </DndContext>
  );
}

function Column({
  column,
  jobs,
  selected,
  onToggle,
  onToggleColumn,
}: {
  column: (typeof COLUMNS)[number];
  jobs: JobSummary[];
  selected: Set<number>;
  onToggle: (id: number) => void;
  onToggleColumn: (status: JobStatus) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: column.status });
  const ids = jobs.map((job) => job.id);
  const allOn = ids.length > 0 && ids.every((id) => selected.has(id));
  const someOn = ids.some((id) => selected.has(id));
  return (
    <section
      ref={setNodeRef}
      id={column.status}
      suppressHydrationWarning
      aria-labelledby={`${column.status}-heading`}
      className={cn(
        "flex min-h-64 flex-col rounded-2xl border bg-muted/40 p-3",
        isOver && "ring-2 ring-primary",
      )}
    >
      <header className="flex items-center gap-2 px-1 pb-3">
        <Checkbox
          checked={allOn ? true : someOn ? "indeterminate" : false}
          onCheckedChange={() => onToggleColumn(column.status)}
          disabled={jobs.length === 0}
          aria-label={`Select all in ${column.title}`}
        />
        {column.icon}
        <h2 id={`${column.status}-heading`} className="text-sm font-semibold">
          {column.title}
        </h2>
        <Badge variant="secondary" className="ml-auto tabular-nums">
          {jobs.length}
        </Badge>
      </header>
      {jobs.length === 0 ? (
        <p className="m-auto px-4 text-center text-sm text-muted-foreground">{column.hint}. Nothing here yet.</p>
      ) : (
        <ol className="space-y-2">
          {jobs.map((job) => (
            <PipelineCard key={job.id} job={job} selected={selected.has(job.id)} onToggle={onToggle} />
          ))}
        </ol>
      )}
    </section>
  );
}

function PipelineCard({
  job,
  selected,
  onToggle,
}: {
  job: JobSummary;
  selected: boolean;
  onToggle: (id: number) => void;
}) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: job.id });
  const label = job.resume_status ? RESUME_LABEL[job.resume_status] : null;
  return (
    <li
      ref={setNodeRef}
      suppressHydrationWarning
      className={cn(
        "relative flex gap-3 rounded-xl border bg-card p-3 pl-8 shadow-xs",
        selected && "ring-2 ring-primary",
        isDragging && "opacity-40",
      )}
      {...listeners}
      {...attributes}
    >
      <div className="absolute top-2.5 left-2 z-20" onPointerDown={(event) => event.stopPropagation()}>
        <Checkbox
          checked={selected}
          onCheckedChange={() => onToggle(job.id)}
          aria-label={`Select ${job.title}`}
        />
      </div>
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
        {job.salary_label && (
          <p className="mt-1 text-xs font-medium text-emerald-600 dark:text-emerald-400">{job.salary_label}</p>
        )}
        {label && (
          <Badge variant="secondary" className="relative z-10 mt-1">
            {label}
          </Badge>
        )}
      </div>
      <div
        className="flex flex-col items-end gap-1"
        onPointerDown={(event) => event.stopPropagation()}
      >
        <MoveMenu jobId={job.id} current={job.status ?? ""} />
        <div className="relative z-10">
          <ScoreRing score={job.score} band={job.fit_tier} stage={job.stage} />
        </div>
      </div>
    </li>
  );
}

function relocate(columns: Pipeline, ids: number[], target: JobStatus): Pipeline {
  const moving = new Map<number, JobSummary>();
  const next = emptyColumns();
  for (const status of Object.keys(next) as JobStatus[]) {
    for (const job of columns[status]) {
      if (ids.includes(job.id)) moving.set(job.id, { ...job, status: target });
      else next[status].push(job);
    }
  }
  const ordered = ids.flatMap((id) => {
    const job = moving.get(id);
    return job ? [job] : [];
  });
  next[target] = [...ordered, ...next[target]];
  return next;
}

function without(columns: Pipeline, ids: number[]): Pipeline {
  const drop = new Set(ids);
  const next = emptyColumns();
  for (const status of Object.keys(next) as JobStatus[]) {
    next[status] = columns[status].filter((job) => !drop.has(job.id));
  }
  return next;
}

function markQueued(columns: Pipeline, ids: number[]): Pipeline {
  const queued = new Set(ids);
  const paint = (jobs: JobSummary[]) =>
    jobs.map((job) => (queued.has(job.id) ? { ...job, resume_status: "queued" } : job));
  return { saved: paint(columns.saved), applied: paint(columns.applied), skipped: paint(columns.skipped) };
}

function putBack(
  columns: Pipeline,
  snapshot: { id: number; status: JobStatus }[],
  known: JobSummary[],
): Pipeline {
  const byId = new Map(known.map((job) => [job.id, job]));
  const next = {
    saved: [...columns.saved],
    applied: [...columns.applied],
    skipped: [...columns.skipped],
  };
  for (const item of snapshot) {
    const job = byId.get(item.id);
    if (!job || next[item.status].some((current) => current.id === item.id)) continue;
    next[item.status] = [{ ...job, status: item.status }, ...next[item.status]];
  }
  return next;
}

function emptyColumns(): Pipeline {
  return { saved: [], applied: [], skipped: [] };
}
