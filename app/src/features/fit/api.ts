import { request } from "@/lib/api-client";
import type { ScheduleInput } from "@/features/fit/types";

export function createSchedule(input: ScheduleInput): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/api/fit/schedules", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateSchedule(id: number, input: ScheduleInput): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/fit/schedules/${id}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function removeSchedule(id: number): Promise<void> {
  return request<void>(`/api/fit/schedules/${id}`, { method: "DELETE" });
}

export function runSchedule(id: number): Promise<{ run_id: number; created: boolean }> {
  return request<{ run_id: number; created: boolean }>(`/api/fit/schedules/${id}/run`, { method: "POST" });
}
