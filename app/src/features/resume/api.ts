import { request } from "@/lib/apiClient";
import type { UsageSummary } from "@/features/resume/types";

export function fetchUsage(days = 30): Promise<UsageSummary> {
  return request<UsageSummary>(`/api/admin/usage?days=${days}`, { cache: "no-store" });
}
