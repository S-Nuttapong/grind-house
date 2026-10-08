"use client";

import { Trash2Icon, XIcon } from "lucide-react";
import { useState, useTransition, type FormEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { deleteEntry, saveEntry } from "@/app/profile/actions";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import type { BankEntry, BankEntryInput, BankRole, BankStatus } from "@/lib/types";

const ROLES: BankRole[] = ["led", "built", "co-built", "contributed"];
const STATUSES: { value: BankStatus; label: string }[] = [
  { value: "draft", label: "Draft" },
  { value: "needs-metric", label: "Needs a metric" },
  { value: "verified", label: "Verified" },
];

const selectClass =
  "h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30";

export function blankEntry(id: string): BankEntry {
  return {
    id,
    title: "",
    company: null,
    role: null,
    period: null,
    my_role: null,
    scope: null,
    metrics: [],
    strength: null,
    confidential: false,
    status: "draft",
    tags: [],
    body_md: "",
    origin: "ui",
    updated_at: "",
  };
}

export function nextEntryId(entries: BankEntry[]): string {
  const used = entries.map((entry) => {
    const match = /^BB-(\d+)$/.exec(entry.id);
    return match ? Number(match[1]) : 0;
  });
  return `BB-${String(Math.max(0, ...used) + 1).padStart(3, "0")}`;
}

export function EntryForm({
  entry,
  mode,
  takenIds,
  onSaved,
  onDeleted,
}: {
  entry: BankEntry;
  mode: "create" | "edit";
  takenIds: Set<string>;
  onSaved: (id: string) => void;
  onDeleted: () => void;
}) {
  const [draft, setDraft] = useState(entry);
  const [tag, setTag] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [isPending, startTransition] = useTransition();

  function update(patch: Partial<BankEntry>) {
    setDraft((current) => ({ ...current, ...patch }));
  }

  function addTag() {
    const next = tag.trim();
    if (!next || draft.tags.includes(next)) {
      setTag("");
      return;
    }
    update({ tags: [...draft.tags, next] });
    setTag("");
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (mode === "create" && takenIds.has(draft.id.trim())) {
      toast.error("That id already exists. Open the entry to edit it.");
      return;
    }
    const input: BankEntryInput = {
      id: draft.id,
      title: draft.title,
      company: draft.company,
      role: draft.role,
      period: draft.period,
      my_role: draft.my_role,
      scope: draft.scope,
      metrics: draft.metrics,
      strength: draft.strength,
      confidential: draft.confidential,
      status: draft.status,
      tags: draft.tags,
      body_md: draft.body_md,
    };
    startTransition(async () => {
      const result = await saveEntry(input, mode);
      if (result.ok) {
        toast.success(mode === "create" ? "Entry added" : "Entry saved");
        onSaved(draft.id.trim());
      } else toast.error(result.error);
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-xl border bg-card p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{mode === "create" ? "New entry" : draft.title || draft.id}</h2>
        {mode === "edit" && (
          <Button type="button" variant="ghost" size="sm" onClick={() => setConfirming(true)}>
            <Trash2Icon />
            Delete
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Id" htmlFor="entry-id">
          <Input
            id="entry-id"
            value={draft.id}
            disabled={mode === "edit"}
            required
            onChange={(event) => update({ id: event.target.value })}
          />
        </Field>
        <Field label="Title" htmlFor="entry-title">
          <Input id="entry-title" value={draft.title} required onChange={(event) => update({ title: event.target.value })} />
        </Field>
        <Field label="Company" htmlFor="entry-company">
          <Input id="entry-company" value={draft.company ?? ""} onChange={(event) => update({ company: event.target.value })} />
        </Field>
        <Field label="Role" htmlFor="entry-role">
          <Input id="entry-role" value={draft.role ?? ""} onChange={(event) => update({ role: event.target.value })} />
        </Field>
        <Field label="Period" htmlFor="entry-period">
          <Input id="entry-period" value={draft.period ?? ""} placeholder="2024-01 – 2024-06" onChange={(event) => update({ period: event.target.value })} />
        </Field>
        <Field label="My part" htmlFor="entry-my-role">
          <select
            id="entry-my-role"
            className={selectClass}
            value={draft.my_role ?? ""}
            onChange={(event) => update({ my_role: (event.target.value || null) as BankEntry["my_role"] })}
          >
            <option value="">Not set</option>
            {ROLES.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Status" htmlFor="entry-status">
          <select
            id="entry-status"
            className={selectClass}
            value={draft.status}
            onChange={(event) => update({ status: event.target.value as BankStatus })}
          >
            {STATUSES.map((status) => (
              <option key={status.value} value={status.value}>
                {status.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Strength" htmlFor="entry-strength">
          <select
            id="entry-strength"
            className={selectClass}
            value={draft.strength ?? ""}
            onChange={(event) => update({ strength: event.target.value ? Number(event.target.value) : null })}
          >
            <option value="">Not set</option>
            {[1, 2, 3, 4, 5].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Scope" htmlFor="entry-scope">
        <Input id="entry-scope" value={draft.scope ?? ""} onChange={(event) => update({ scope: event.target.value })} />
      </Field>
      <div className="flex items-center gap-2.5">
        <Checkbox
          id="entry-confidential"
          checked={draft.confidential}
          onCheckedChange={(checked) => update({ confidential: checked === true })}
        />
        <Label htmlFor="entry-confidential" className="font-normal">
          Confidential. Kept out of any model that sends text off this machine.
        </Label>
      </div>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Tags</legend>
        <div className="flex flex-wrap gap-1.5">
          {draft.tags.map((item) => (
            <button
              key={item}
              type="button"
              className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-0.5 text-xs"
              onClick={() => update({ tags: draft.tags.filter((tag) => tag !== item) })}
            >
              {item}
              <XIcon className="size-3" />
              <span className="sr-only">Remove {item}</span>
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <Label htmlFor="entry-tag" className="sr-only">
            Add a tag
          </Label>
          <Input
            id="entry-tag"
            value={tag}
            placeholder="skill/go"
            onChange={(event) => setTag(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === ",") {
                event.preventDefault();
                addTag();
              }
            }}
          />
          <Button type="button" variant="outline" onClick={addTag}>
            Add
          </Button>
        </div>
      </fieldset>
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">Metrics</legend>
        {draft.metrics.map((metric, index) => (
          <div key={index} className="flex gap-2">
            <Label htmlFor={`metric-${index}`} className="sr-only">
              Metric {index + 1}
            </Label>
            <Input
              id={`metric-${index}`}
              value={metric.text}
              placeholder="retries -38%"
              onChange={(event) => {
                const metrics = draft.metrics.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, text: event.target.value } : item,
                );
                update({ metrics });
              }}
            />
            <Label htmlFor={`metric-confidence-${index}`} className="sr-only">
              Confidence {index + 1}
            </Label>
            <Input
              id={`metric-confidence-${index}`}
              value={metric.confidence ?? ""}
              placeholder="exact"
              className="max-w-32"
              onChange={(event) => {
                const metrics = draft.metrics.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, confidence: event.target.value } : item,
                );
                update({ metrics });
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={`Remove metric ${index + 1}`}
              onClick={() => update({ metrics: draft.metrics.filter((_, itemIndex) => itemIndex !== index) })}
            >
              <XIcon />
            </Button>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => update({ metrics: [...draft.metrics, { text: "" }] })}>
          Add metric
        </Button>
      </fieldset>
      <Field label="What I did" htmlFor="entry-body">
        <Textarea
          id="entry-body"
          value={draft.body_md}
          className="min-h-40"
          onChange={(event) => update({ body_md: event.target.value })}
        />
      </Field>
      <Button type="submit" disabled={isPending}>
        {isPending ? "Saving…" : "Save entry"}
      </Button>
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {draft.id}?</DialogTitle>
            <DialogDescription>This removes the entry from the local brag bank. The vault file is left as it is.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={isPending}
              onClick={() => {
                startTransition(async () => {
                  const result = await deleteEntry(draft.id);
                  if (result.ok) {
                    toast.success("Entry deleted");
                    setConfirming(false);
                    onDeleted();
                  } else toast.error(result.error);
                });
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </form>
  );
}

function Field({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}
