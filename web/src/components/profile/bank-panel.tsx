"use client";

import { useMemo, useState, useTransition } from "react";
import { toast } from "sonner";

import { saveSummary } from "@/app/profile/actions";
import { blankEntry, EntryForm, nextEntryId } from "@/components/profile/entry-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { BankEntry } from "@/lib/types";
import { cn } from "@/lib/utils";

export function BankPanel({ entries, summary }: { entries: BankEntry[]; summary: string }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(entries[0]?.id ?? null);
  const [creating, setCreating] = useState(false);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((entry) =>
      [entry.id, entry.title, entry.company, entry.role, entry.body_md, ...entry.tags]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [entries, query]);

  const selected = entries.find((entry) => entry.id === selectedId) ?? null;
  const formKey = creating ? "new" : (selected?.id ?? "empty");
  const formEntry = creating ? blankEntry(nextEntryId(entries)) : selected;

  return (
    <div className="space-y-6">
      <SummaryEditor summary={summary} />
      <div className="grid items-start gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <Label htmlFor="entry-search" className="sr-only">
              Search entries
            </Label>
            <Input
              id="entry-search"
              value={query}
              placeholder="Search entries"
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            className="w-full"
            onClick={() => {
              setCreating(true);
              setSelectedId(null);
            }}
          >
            New entry
          </Button>
          <ul className="max-h-[36rem] space-y-1 overflow-auto" aria-label="Brag bank entries">
            {visible.length === 0 && <li className="px-2 py-6 text-sm text-muted-foreground">No entries match.</li>}
            {visible.map((entry) => {
              const active = !creating && entry.id === selectedId;
              return (
                <li key={entry.id}>
                  <button
                    type="button"
                    onClick={() => {
                      setCreating(false);
                      setSelectedId(entry.id);
                    }}
                    className={cn(
                      "w-full rounded-lg px-3 py-2 text-left transition-colors hover:bg-muted",
                      active && "bg-accent",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium">{entry.title}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{entry.id}</span>
                    </span>
                    <span className="mt-1 flex flex-wrap gap-1">
                      {entry.confidential && <Badge variant="outline">Confidential</Badge>}
                      <Badge variant="secondary" className="capitalize">
                        {entry.status.replace("-", " ")}
                      </Badge>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
        {formEntry ? (
          <EntryForm
            key={formKey}
            entry={formEntry}
            mode={creating ? "create" : "edit"}
            takenIds={new Set(entries.map((entry) => entry.id))}
            onSaved={(id) => {
              setCreating(false);
              setSelectedId(id);
            }}
            onDeleted={() => {
              setCreating(false);
              setSelectedId(null);
            }}
          />
        ) : (
          <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
            Add an entry to start the brag bank. The next fit run scores jobs against whatever is saved here.
          </p>
        )}
      </div>
    </div>
  );
}

function SummaryEditor({ summary }: { summary: string }) {
  const [body, setBody] = useState(summary);
  const [isPending, startTransition] = useTransition();
  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        startTransition(async () => {
          const result = await saveSummary(body);
          if (result.ok) toast.success("Summary saved");
          else toast.error(result.error);
        });
      }}
    >
      <Label htmlFor="profile-summary">Profile summary</Label>
      <Textarea id="profile-summary" value={body} className="min-h-28" onChange={(event) => setBody(event.target.value)} />
      <Button type="submit" variant="outline" disabled={isPending || body === summary}>
        {isPending ? "Saving…" : "Save summary"}
      </Button>
    </form>
  );
}
