"use client";

import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { Slider } from "@/components/ui/slider";
import { useBoard } from "@/features/jobs/components/BoardProvider";
import { CheckGroup, MultiSelect } from "@/features/jobs/components/MultiSelect";
import {
  FIT_SOURCES,
  hasActiveFilters,
  LEVEL_LABELS,
  POSTED_WITHIN,
  readList,
  REGION_LABELS,
  REMOTE_LABELS,
  ROLE_LABELS,
  sourceLabel,
  toggleValue,
  type FilterKey,
  type Filters,
} from "@/features/jobs/filters";
import type { Facets } from "@/features/jobs/types";

const countryNames = new Intl.DisplayNames(["en"], { type: "region" });

function Section({ title, children }: { title: string; children: ReactNode }) {
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
  legend,
}: {
  name: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  legend?: string;
}) {
  return (
    <RadioGroup value={value} onValueChange={onChange} aria-label={legend} className="gap-2.5">
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

function ExperienceSlider() {
  const { filters, navigate } = useBoard();
  const committed = Number(filters.min_experience || "0");
  const years = Number.isFinite(committed) ? committed : 0;
  const [value, setValue] = useState(years);
  const [seen, setSeen] = useState(years);
  if (years !== seen) {
    setSeen(years);
    setValue(years);
  }

  return (
    <div className="space-y-3">
      <p className="text-sm">{value === 0 ? "Any" : `${value}+ years`}</p>
      <Slider
        min={0}
        max={15}
        step={1}
        value={[value]}
        aria-label="Minimum years of experience"
        onValueChange={(next) => setValue(next[0] ?? 0)}
        onValueCommit={(next) => {
          const years = next[0] ?? 0;
          navigate({ min_experience: years === 0 ? "" : String(years) });
        }}
      />
    </div>
  );
}

function ScoreSlider() {
  const { filters, navigate } = useBoard();
  const committed = Number(filters.min_score || "0");
  const score = Number.isFinite(committed) ? committed : 0;
  const [value, setValue] = useState(score);
  const [seen, setSeen] = useState(score);
  if (score !== seen) {
    setSeen(score);
    setValue(score);
  }

  return (
    <div className="space-y-3">
      <p className="text-sm">{value === 0 ? "Any score" : `${value}+`}</p>
      <Slider
        min={0}
        max={100}
        step={5}
        value={[value]}
        aria-label="Minimum fit score"
        onValueChange={(next) => setValue(next[0] ?? 0)}
        onValueCommit={(next) => {
          const score = next[0] ?? 0;
          navigate({ min_score: score === 0 ? "" : String(score) });
        }}
      />
    </div>
  );
}

function labeled(values: string[], labels: Record<string, string>): { value: string; label: string }[] {
  return values.map((value) => ({ value, label: labels[value] ?? sourceLabel(value) }));
}

export function FilterSidebar({ facets }: { facets: Facets }) {
  const { filters, navigate } = useBoard();

  function setList(key: FilterKey, next: string[]) {
    const changes: Filters = { [key]: next.join(",") };
    navigate(changes);
  }

  function toggle(key: FilterKey, value: string) {
    const changes: Filters = { [key]: toggleValue(filters[key], value) };
    navigate(changes);
  }

  return (
    <aside aria-label="Filters" className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Filters</h2>
        {hasActiveFilters(filters) && (
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0"
            onClick={() =>
              navigate({
                q: "",
                where: "",
                remote: "",
                source: "",
                country: "",
                region: "",
                role: "",
                industry: "",
                level: "",
                min_experience: "",
                posted_within: "",
                has_salary: "",
                include_closed: "",
                fit: "",
                min_score: "",
                jk: "",
              })
            }
          >
            Clear all
          </Button>
        )}
      </div>
      <Section title="Match">
        <Choices
          name="fit"
          legend="Score against"
          value={filters.fit ?? ""}
          options={FIT_SOURCES}
          onChange={(fit) => navigate({ fit })}
        />
        <ScoreSlider />
      </Section>
      <Separator />
      {facets.countries.length > 0 && (
        <Section title="Country">
          <MultiSelect
            label="Country"
            options={facets.countries.map((code) => ({ value: code, label: countryNames.of(code) ?? code }))}
            selected={readList(filters, "country")}
            onChange={(next) => setList("country", next)}
          />
        </Section>
      )}
      <Section title="Region">
        <MultiSelect
          label="Region"
          options={labeled(facets.regions, REGION_LABELS)}
          selected={readList(filters, "region")}
          onChange={(next) => setList("region", next)}
        />
      </Section>
      {facets.roles.length > 0 && (
        <>
          <Separator />
          <Section title="Role">
            <MultiSelect
              label="Role"
              options={labeled(facets.roles, ROLE_LABELS)}
              selected={readList(filters, "role")}
              onChange={(next) => setList("role", next)}
            />
          </Section>
        </>
      )}
      {facets.industries.length > 0 && (
        <>
          <Separator />
          <Section title="Industry">
            <MultiSelect
              label="Industry"
              options={labeled(facets.industries, {})}
              selected={readList(filters, "industry")}
              onChange={(next) => setList("industry", next)}
            />
          </Section>
        </>
      )}
      <Separator />
      <Section title="Level">
        <CheckGroup
          name="level"
          options={labeled(facets.levels, LEVEL_LABELS)}
          selected={readList(filters, "level")}
          onToggle={(value) => toggle("level", value)}
        />
      </Section>
      <Separator />
      <Section title="Experience">
        <ExperienceSlider />
      </Section>
      <Separator />
      <Section title="Workplace">
        <CheckGroup
          name="remote"
          options={labeled(facets.remote, REMOTE_LABELS)}
          selected={readList(filters, "remote")}
          onToggle={(value) => toggle("remote", value)}
        />
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
      {facets.sources.length > 0 && (
        <>
          <Separator />
          <Section title="Source">
            <CheckGroup
              name="source"
              options={facets.sources.map((value) => ({ value, label: sourceLabel(value) }))}
              selected={readList(filters, "source")}
              onToggle={(value) => toggle("source", value)}
            />
          </Section>
        </>
      )}
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
