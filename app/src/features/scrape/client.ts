import type { HooksView, ScrapeSettings, Search } from "@/features/scrape/types";

async function readJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { accept: "application/json", "content-type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `${path} returned ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function fetchSearches(): Promise<Search[]> {
  return readJson<Search[]>("/api/searches");
}

export function fetchScrapeSettings(): Promise<ScrapeSettings> {
  return readJson<ScrapeSettings>("/api/scrape-settings");
}

export function fetchHooks(): Promise<HooksView> {
  return readJson<HooksView>("/api/tick-hooks");
}

export function saveSearch(body: unknown, id?: number): Promise<Search> {
  return readJson<Search>(id === undefined ? "/api/searches" : `/api/searches/${id}`, {
    method: id === undefined ? "POST" : "PUT",
    body: JSON.stringify(body),
  });
}

export function removeSearch(id: number): Promise<void> {
  return readJson<void>(`/api/searches/${id}`, { method: "DELETE" });
}

export function runSearch(id: number): Promise<{ accepted: boolean }> {
  return readJson<{ accepted: boolean }>(`/api/searches/${id}/run`, { method: "POST" });
}

export function saveSettings(allowedRoles: string[]): Promise<ScrapeSettings> {
  return readJson<ScrapeSettings>("/api/scrape-settings", {
    method: "PUT",
    body: JSON.stringify({ allowed_roles: allowedRoles }),
  });
}
