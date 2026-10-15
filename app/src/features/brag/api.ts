import { request } from "@/lib/apiClient";
import type { Tag, MetricKey, BragDoc, BragDocInput } from "@/features/brag/types";

export function fetchBragDocs(): Promise<BragDoc[]> {
  return request<BragDoc[]>("/api/brag-docs");
}

export function fetchTags(): Promise<Tag[]> {
  return request<Tag[]>("/api/tags");
}

export function fetchMetricKeys(): Promise<MetricKey[]> {
  return request<MetricKey[]>("/api/metric-keys");
}

export function fetchCompanies(): Promise<string[]> {
  return request<string[]>("/api/brag-docs/companies");
}

export function createBragDoc(input: BragDocInput): Promise<BragDoc> {
  return request<BragDoc>("/api/brag-docs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateBragDoc(id: string, input: BragDocInput): Promise<BragDoc> {
  return request<BragDoc>(`/api/brag-docs/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function removeBragDoc(id: string): Promise<void> {
  return request<void>(`/api/brag-docs/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function createTag(name: string): Promise<Tag & { created: boolean }> {
  return request<Tag & { created: boolean }>("/api/tags", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function createMetricKey(name: string): Promise<MetricKey & { created: boolean }> {
  return request<MetricKey & { created: boolean }>("/api/metric-keys", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  });
}
