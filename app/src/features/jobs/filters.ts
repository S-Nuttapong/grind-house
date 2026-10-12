export const FILTER_KEYS = [
  "q",
  "where",
  "remote",
  "source",
  "country",
  "region",
  "role",
  "industry",
  "level",
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
  { value: "", label: "Brag docs" },
  { value: "resume", label: "Selected resume" },
];

export const ROLE_LABELS: Record<string, string> = {
  frontend: "Frontend",
  backend: "Backend",
  software: "Software",
  fullstack: "Full stack",
  mobile: "Mobile",
  data: "Data",
  ml: "Machine learning",
  devops: "DevOps / platform",
  security: "Security",
  qa: "QA",
  engineering_manager: "Engineering manager",
  product: "Product",
  design: "Design",
  other: "Other",
};

export const REGION_LABELS: Record<string, string> = {
  apac: "APAC",
  sea: "Southeast Asia",
  europe: "Europe",
  north_america: "North America",
};

export const LEVEL_LABELS: Record<string, string> = {
  intern: "Intern",
  junior: "Junior",
  mid: "Mid",
  senior: "Senior",
  staff: "Staff",
  principal: "Principal",
  lead: "Lead",
  manager: "Manager",
  unknown: "Not stated",
};

export function readList(filters: Filters, key: FilterKey): string[] {
  return listValues(filters[key]);
}

export function listValues(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

export function toggleValue(current: string | undefined, value: string): string {
  const items = listValues(current);
  const next = items.includes(value) ? items.filter((item) => item !== value) : [...items, value];
  return next.join(",");
}

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
