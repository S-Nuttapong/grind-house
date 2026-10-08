"use client";

import { useBoard } from "@/components/board/board-provider";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { hasActiveFilters, POSTED_WITHIN, REMOTE_LABELS, sourceLabel } from "@/lib/filters";
import type { Facets } from "@/lib/types";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-3">
      <legend className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</legend>
      {children}
    </fieldset>
  );
}

function Choices({
  name,
  value,
  options,
  onChange,
}: {
  name: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <RadioGroup value={value} onValueChange={onChange} className="gap-2.5">
      {options.map((option) => {
        const id = `${name}-${option.value || "any"}`;
        return (
          <div key={id} className="flex items-center gap-2.5">
            <RadioGroupItem id={id} value={option.value} />
            <Label htmlFor={id} className="font-normal">
              {option.label}
            </Label>
          </div>
        );
      })}
    </RadioGroup>
  );
}

export function FilterSidebar({ facets }: { facets: Facets }) {
  const { filters, navigate } = useBoard();
  const remoteOptions = [
    { value: "", label: "Any" },
    ...facets.remote.map((value) => ({ value, label: REMOTE_LABELS[value] ?? value })),
  ];
  const sourceOptions = [
    { value: "", label: "All sources" },
    ...facets.sources.map((value) => ({ value, label: sourceLabel(value) })),
  ];

  return (
    <aside aria-label="Filters" className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Filters</h2>
        {hasActiveFilters(filters) && (
          <Button variant="link" size="sm" className="h-auto p-0" onClick={() => navigate({ q: "", where: "", remote: "", source: "", posted_within: "", has_salary: "", include_closed: "", jk: "" })}>
            Clear all
          </Button>
        )}
      </div>
      <Section title="Workplace">
        <Choices name="remote" value={filters.remote ?? ""} options={remoteOptions} onChange={(remote) => navigate({ remote })} />
      </Section>
      <Separator />
      <Section title="Date posted">
        <Choices
          name="posted"
          value={filters.posted_within ?? ""}
          options={POSTED_WITHIN}
          onChange={(posted_within) => navigate({ posted_within })}
        />
      </Section>
      <Separator />
      <Section title="Source">
        <Choices
          name="source"
          value={filters.source ?? ""}
          options={sourceOptions}
          onChange={(source) => navigate({ source })}
        />
      </Section>
      <Separator />
      <Section title="More">
        <div className="flex items-center gap-2.5">
          <Checkbox
            id="has_salary"
            checked={filters.has_salary === "1"}
            onCheckedChange={(checked) => navigate({ has_salary: checked === true ? "1" : "" })}
          />
          <Label htmlFor="has_salary" className="font-normal">
            Salary listed
          </Label>
        </div>
        <div className="flex items-center gap-2.5">
          <Checkbox
            id="include_closed"
            checked={filters.include_closed === "1"}
            onCheckedChange={(checked) => navigate({ include_closed: checked === true ? "1" : "" })}
          />
          <Label htmlFor="include_closed" className="font-normal">
            Include closed jobs
          </Label>
        </div>
      </Section>
    </aside>
  );
}
