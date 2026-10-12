import type { BragDoc } from "@/features/brag/types";

export type BragFilters = {
  q: string;
  tagIds: number[];
  company: string;
  metricKeyId: number | null;
};

export function quarterOf(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(isoDate);
  if (!match) return "";
  const month = Number(match[2]);
  if (month < 1 || month > 12) return "";
  return `Q${Math.floor((month - 1) / 3) + 1} ${match[1]}`;
}

export function filtersFromParams(params: { get(name: string): string | null }): BragFilters {
  const tagIds = (params.get("tags") ?? "")
    .split(",")
    .map((part) => Number(part))
    .filter((id) => Number.isInteger(id) && id > 0);
  const metric = Number(params.get("metric"));
  return {
    q: params.get("q") ?? "",
    tagIds,
    company: params.get("company") ?? "",
    metricKeyId: Number.isInteger(metric) && metric > 0 ? metric : null,
  };
}

export function filterBragDocs(docs: BragDoc[], filters: BragFilters): BragDoc[] {
  const needle = filters.q.trim().toLowerCase();
  return docs.filter((doc) => {
    if (filters.company && doc.company !== filters.company) return false;
    if (filters.metricKeyId != null && !doc.metrics.some((metric) => metric.metric_key_id === filters.metricKeyId)) {
      return false;
    }
    if (filters.tagIds.length > 0 && !filters.tagIds.every((id) => doc.tags.some((tag) => tag.id === id))) {
      return false;
    }
    if (!needle) return true;
    const haystack = [doc.title, doc.description_md, ...doc.metrics.map((metric) => metric.value)]
      .join("\n")
      .toLowerCase();
    return haystack.includes(needle);
  });
}

export function groupByQuarter(docs: BragDoc[]): { quarter: string; docs: BragDoc[] }[] {
  const groups: { quarter: string; docs: BragDoc[] }[] = [];
  for (const doc of docs) {
    const last = groups.at(-1);
    if (last?.quarter === doc.quarter) last.docs.push(doc);
    else groups.push({ quarter: doc.quarter, docs: [doc] });
  }
  return groups;
}

export function byDateDesc(left: BragDoc, right: BragDoc): number {
  if (left.date !== right.date) return left.date < right.date ? 1 : -1;
  return left.id < right.id ? 1 : -1;
}
