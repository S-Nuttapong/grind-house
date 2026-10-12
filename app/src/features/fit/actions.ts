"use server";

import { ApiError } from "@/lib/api-client";
import { createSchedule, removeSchedule, runSchedule, updateSchedule } from "@/features/fit/api";
import type { FitMode, ScheduleInput } from "@/features/fit/types";

export type ActionResult = { ok: true } | { ok: false; error: string };
export type RunNowResult = { ok: true; runId: number; created: boolean } | { ok: false; error: string };

const MODES = new Set<FitMode>(["bank", "resume"]);

export async function saveSchedule(input: ScheduleInput, id?: number): Promise<ActionResult> {
  const schedule = normalize(input);
  const error = validate(schedule);
  if (error) return { ok: false, error };
  return run(async () => {
    if (id === undefined) await createSchedule(schedule);
    else await updateSchedule(id, schedule);
  });
}

export async function deleteSchedule(id: number): Promise<ActionResult> {
  if (!Number.isInteger(id) || id <= 0) return { ok: false, error: "Missing schedule" };
  return run(() => removeSchedule(id));
}

export async function runScheduleNow(id: number): Promise<RunNowResult> {
  if (!Number.isInteger(id) || id <= 0) return { ok: false, error: "Missing schedule" };
  try {
    const queued = await runSchedule(id);
    return { ok: true, runId: queued.run_id, created: queued.created };
  } catch (error) {
    console.error("runScheduleNow failed", error);
    return { ok: false, error: error instanceof ApiError ? error.message : "Could not queue the run. Is the API running?" };
  }
}

function normalize(input: ScheduleInput): ScheduleInput {
  return {
    name: input.name.trim(),
    mode: input.mode,
    cron: input.cron.trim(),
    timezone: input.timezone.trim() || "Asia/Bangkok",
    enabled: input.enabled,
  };
}

function validate(input: ScheduleInput): string | null {
  if (!input.name || input.name.length > 80) return "Add a name";
  if (!MODES.has(input.mode)) return "Choose brag docs or selected resume";
  if (!input.cron) return "Add a cron expression";
  return null;
}

async function run(work: () => Promise<unknown>): Promise<ActionResult> {
  try {
    await work();
  } catch (error) {
    console.error("schedule action failed", error);
    return { ok: false, error: error instanceof ApiError ? error.message : "Could not save. Is the API running?" };
  }
  return { ok: true };
}
