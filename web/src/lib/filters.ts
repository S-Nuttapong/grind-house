export const FILTER_KEYS = [
  "q",
  "where",
  "remote",
  "source",
  "posted_within",
  "has_salary",
  "include_closed",
  "fit",
  "min_score",
  "sort",
  "page",
  "jk",
] as const;

export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Partial<Record<FilterKey, string>>;

export const POSTED_WITHIN = [
  { value: "", label: "Any time" },
  { value: "1", label: "Last 24 hours" },
  { value: "3", label: "Last 3 days" },
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
];

export const SORTS = [
  { value: "match", label: "Best match" },
  { value: "posted", label: "Date posted" },
  { value: "first_seen", label: "Recently found" },
];

export const FIT_SOURCES = [
  { value: "", label: "Brag bank" },
  { value: "resume", label: "Selected resume" },
];

export const MIN_SCORES = [
  { value: "", label: "Any" },
  { value: "40", label: "40+" },
  { value: "60", label: "60+" },
  { value: "80", label: "80+" },
];

export const TIER_LABELS: Record<string, string> = {
  strong: "Strong",
  good: "Good",
  fair: "Fair",
  low: "Low",
};

export const REMOTE_LABELS: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
  unknown: "Not stated",
};

export function sourceLabel(sourceId: string): string {
  return sourceId.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function readFilters(params: Record<string, string | string[] | undefined>): Filters {
  const filters: Filters = {};
  for (const key of FILTER_KEYS) {
    const raw = params[key];
    const value = Array.isArray(raw) ? raw[0] : raw;
    if (value) filters[key] = value;
  }
  return filters;
}

export function toQuery(filters: Filters, changes: Filters = {}): string {
  const merged: Filters = { ...filters, ...changes };
  const resetsPage = Object.keys(changes).some((key) => key !== "page" && key !== "jk");
  if (resetsPage) delete merged.page;
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = merged[key];
    if (value) params.set(key, value);
  }
  return params.toString();
}

export function apiQuery(filters: Filters): string {
  const rest = { ...filters };
  delete rest.jk;
  return toQuery(rest);
}

export function hasActiveFilters(filters: Filters): boolean {
  return FILTER_KEYS.some((key) => key !== "page" && key !== "jk" && key !== "sort" && filters[key]);
}
