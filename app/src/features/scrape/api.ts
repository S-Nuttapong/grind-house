import { request } from "@/lib/apiClient";
import type { HooksView, Run } from "@/features/scrape/types";

export function fetchRuns(): Promise<Run[]> {
  return request<Run[]>("/api/runs");
}

export function fetchTickHooks(): Promise<HooksView> {
  return request<HooksView>("/api/tick-hooks");
}
