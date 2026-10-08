"use client";

import { CreatableCombobox } from "@/components/brag-docs/creatable-combobox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { BragFilters } from "@/lib/brag-filters";
import type { MetricKey, Tag } from "@/lib/types";

export function FilterBar({
  filters,
  tags,
  metricKeys,
  companies,
  onChange,
}: {
  filters: BragFilters;
  tags: Tag[];
  metricKeys: MetricKey[];
  companies: string[];
  onChange: (filters: BragFilters) => void;
}) {
  return (
    <div className="sticky top-14 z-30 -mx-4 border-b bg-background/95 px-4 py-3 backdrop-blur lg:-mx-6 lg:px-6">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <div className="space-y-1.5">
          <Label htmlFor="brag-search">Search</Label>
          <Input
            id="brag-search"
            value={filters.q}
            placeholder="Title, description, or 200ms"
            onChange={(event) => onChange({ ...filters, q: event.target.value })}
          />
        </div>
        <CreatableCombobox
          label="Tags"
          mode="multi"
          options={tags.map((tag) => ({ id: String(tag.id), label: tag.name, color: tag.color_hex }))}
          value={filters.tagIds.map(String)}
          placeholder="All tags"
          onChange={(ids) => onChange({ ...filters, tagIds: ids.map(Number) })}
        />
        <CreatableCombobox
          label="Company"
          mode="single"
          options={companies.map((name) => ({ id: name, label: name }))}
          value={filters.company ? [filters.company] : []}
          placeholder="All companies"
          onChange={(ids) => onChange({ ...filters, company: ids[0] ?? "" })}
        />
        <CreatableCombobox
          label="Metric"
          mode="single"
          options={metricKeys.map((key) => ({ id: String(key.id), label: key.name }))}
          value={filters.metricKeyId ? [String(filters.metricKeyId)] : []}
          placeholder="Any metric"
          onChange={(ids) => onChange({ ...filters, metricKeyId: ids[0] ? Number(ids[0]) : null })}
        />
      </div>
    </div>
  );
}
