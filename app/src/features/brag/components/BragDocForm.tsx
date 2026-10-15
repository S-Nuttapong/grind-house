"use client";

import { PlusIcon, XIcon } from "lucide-react";
import { useState, useTransition, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { toast } from "sonner";

import { createMetricKey, createTag, saveBragDoc } from "@/features/brag/actions";
import { CreatableCombobox, type ComboOption } from "@/features/brag/components/CreatableCombobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { quarterOf } from "@/features/brag/filters";
import type { BragDoc, BragDocInput, MetricKey, Tag } from "@/features/brag/types";

type MetricRow = { keyId: string; value: string };

export function BragDocForm({
  open,
  doc,
  tags,
  metricKeys,
  companies,
  onOpenChange,
}: {
  open: boolean;
  doc: BragDoc | null;
  tags: Tag[];
  metricKeys: MetricKey[];
  companies: string[];
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        {open && (
          <FormBody
            doc={doc}
            tags={tags}
            metricKeys={metricKeys}
            companies={companies}
            onClose={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function FormBody({
  doc,
  tags: initialTags,
  metricKeys: initialKeys,
  companies,
  onClose,
}: {
  doc: BragDoc | null;
  tags: Tag[];
  metricKeys: MetricKey[];
  companies: string[];
  onClose: () => void;
}) {
  const [title, setTitle] = useState(doc?.title ?? "");
  const [date, setDate] = useState(doc?.date ?? todayIso());
  const [company, setCompany] = useState(doc?.company ?? "");
  const [extraCompanies, setExtraCompanies] = useState<string[]>([]);
  const [role, setRole] = useState(doc?.role ?? "");
  const [impact, setImpact] = useState(doc?.impact ? String(doc.impact) : "");
  const [tags, setTags] = useState(initialTags);
  const [tagIds, setTagIds] = useState(doc?.tags.map((tag) => String(tag.id)) ?? []);
  const [keys, setKeys] = useState(initialKeys);
  const [metrics, setMetrics] = useState<MetricRow[]>(
    doc?.metrics.map((metric) => ({ keyId: String(metric.metric_key_id), value: metric.value })) ?? [],
  );
  const [links, setLinks] = useState(doc?.attachments.map((item) => item.link) ?? []);
  const [description, setDescription] = useState(doc?.description_md ?? "");
  const [isPending, startTransition] = useTransition();

  const companyOptions = [...new Set([...companies, ...extraCompanies, company].filter(Boolean))].map(
    (name) => ({ id: name, label: name }),
  );
  const quarter = quarterOf(date);

  function submit() {
    const input: BragDocInput = {
      title: title.trim(),
      date,
      company: company.trim() || null,
      role: role.trim() || null,
      description_md: description,
      impact: impact ? Number(impact) : null,
      tag_ids: tagIds.map(Number),
      metrics: metrics
        .filter((row) => row.keyId || row.value.trim())
        .map((row) => ({ metric_key_id: Number(row.keyId), value: row.value.trim() })),
      attachments: links
        .map((link) => link.trim())
        .filter(Boolean)
        .map((link) => ({ type: "url" as const, link })),
    };
    startTransition(async () => {
      const result = await saveBragDoc(input, doc?.id ?? null);
      if (result.ok) {
        toast.success(doc ? "Brag doc updated" : "Brag doc logged");
        onClose();
      } else toast.error(result.error);
    });
  }

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submit();
        }
        if (event.key === "Enter" && event.target instanceof HTMLElement && event.target.closest("[data-slot=command]")) {
          event.preventDefault();
        }
      }}
    >
      <DialogHeader>
        <DialogTitle>{doc ? "Edit brag doc" : "Log a brag doc"}</DialogTitle>
        <DialogDescription>Title, date, and the proof points you want to find later.</DialogDescription>
      </DialogHeader>
      <Field label="Title" htmlFor="brag-title">
        <Input id="brag-title" autoFocus value={title} onChange={(event) => setTitle(event.target.value)} />
      </Field>
      <div className="grid grid-cols-[1fr_auto] items-end gap-3">
        <Field label="Date" htmlFor="brag-date">
          <Input id="brag-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </Field>
        <p className="pb-1.5 text-sm text-muted-foreground" aria-live="polite">
          {quarter || "Pick a date"}
        </p>
      </div>
      <CreatableCombobox
        label="Company"
        mode="single"
        options={companyOptions}
        value={company ? [company] : []}
        placeholder="Company or context"
        onChange={(next) => setCompany(next[0] ?? "")}
        onCreate={async (name) => {
          setExtraCompanies((current) => (current.includes(name) ? current : [...current, name]));
          return { id: name, label: name };
        }}
      />
      <Field label="Role" htmlFor="brag-role">
        <Input id="brag-role" value={role} onChange={(event) => setRole(event.target.value)} />
      </Field>
      <Field label="Impact" htmlFor="brag-impact">
        <select
          id="brag-impact"
          className="h-9 w-full rounded-md border bg-background px-3 text-sm"
          value={impact}
          onChange={(event) => setImpact(event.target.value)}
        >
          <option value="">Not rated</option>
          <option value="5">5 — highest</option>
          <option value="4">4</option>
          <option value="3">3</option>
          <option value="2">2</option>
          <option value="1">1 — lowest</option>
        </select>
      </Field>
      <CreatableCombobox
        label="Tags"
        mode="multi"
        options={tags.map((tag) => ({ id: String(tag.id), label: tag.name, color: tag.color_hex }))}
        value={tagIds}
        placeholder="Search or create a tag"
        onChange={setTagIds}
        onCreate={(name) => addTag(name, setTags)}
      />
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Metrics</span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setMetrics((rows) => [...rows, { keyId: "", value: "" }])}
          >
            <PlusIcon /> Add metric
          </Button>
        </div>
        {metrics.map((row, index) => (
          <div key={index} className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
            <CreatableCombobox
              label={index === 0 ? "Metric" : `Metric ${index + 1}`}
              mode="single"
              options={keys.map((key) => ({ id: String(key.id), label: key.name }))}
              value={row.keyId ? [row.keyId] : []}
              placeholder="Latency Reduction"
              onChange={(next) => updateMetric(setMetrics, index, { keyId: next[0] ?? "" })}
              onCreate={(name) => addMetricKey(name, setKeys)}
            />
            <Field label="Value" htmlFor={`brag-metric-${index}`}>
              <Input
                id={`brag-metric-${index}`}
                value={row.value}
                placeholder="200ms"
                onChange={(event) => updateMetric(setMetrics, index, { value: event.target.value })}
              />
            </Field>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove metric ${index + 1}`}
              onClick={() => setMetrics((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}
            >
              <XIcon />
            </Button>
          </div>
        ))}
      </div>
      <Field label="Description" htmlFor="brag-description">
        <Textarea
          id="brag-description"
          value={description}
          className="min-h-24"
          onChange={(event) => setDescription(event.target.value)}
          onInput={(event) => {
            const field = event.currentTarget;
            field.style.height = "auto";
            field.style.height = `${field.scrollHeight}px`;
          }}
        />
      </Field>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">Links</span>
          <Button type="button" variant="outline" size="sm" onClick={() => setLinks((rows) => [...rows, ""])}>
            <PlusIcon /> Add link
          </Button>
        </div>
        {links.map((link, index) => (
          <div key={index} className="flex items-end gap-2">
            <Field label={index === 0 ? "URL" : `URL ${index + 1}`} htmlFor={`brag-link-${index}`}>
              <Input
                id={`brag-link-${index}`}
                type="url"
                value={link}
                placeholder="https://"
                onChange={(event) =>
                  setLinks((rows) => rows.map((item, rowIndex) => (rowIndex === index ? event.target.value : item)))
                }
              />
            </Field>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove link ${index + 1}`}
              onClick={() => setLinks((rows) => rows.filter((_, rowIndex) => rowIndex !== index))}
            >
              <XIcon />
            </Button>
          </div>
        ))}
      </div>
      <DialogFooter>
        <Button type="submit" disabled={isPending}>
          {isPending ? "Saving…" : "Save"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="min-w-0 flex-1 space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function todayIso() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

function updateMetric(
  setMetrics: Dispatch<SetStateAction<MetricRow[]>>,
  index: number,
  patch: Partial<MetricRow>,
) {
  setMetrics((rows) => rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
}

async function addTag(name: string, setTags: Dispatch<SetStateAction<Tag[]>>): Promise<ComboOption | null> {
  const result = await createTag(name);
  if (!result.ok) {
    toast.error(result.error);
    return null;
  }
  setTags((current) => (current.some((tag) => tag.id === result.tag.id) ? current : [...current, result.tag]));
  return { id: String(result.tag.id), label: result.tag.name, color: result.tag.color_hex };
}

async function addMetricKey(
  name: string,
  setKeys: Dispatch<SetStateAction<MetricKey[]>>,
): Promise<ComboOption | null> {
  const result = await createMetricKey(name);
  if (!result.ok) {
    toast.error(result.error);
    return null;
  }
  setKeys((current) =>
    current.some((key) => key.id === result.metricKey.id) ? current : [...current, result.metricKey],
  );
  return { id: String(result.metricKey.id), label: result.metricKey.name };
}
