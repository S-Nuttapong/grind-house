"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { MultiSelect } from "@/features/jobs/components/MultiSelect";
import { sourceLabel } from "@/features/jobs/filters";
import {
  fetchHooks,
  fetchScrapeSettings,
  fetchSearches,
  removeSearch,
  runSearch,
  saveSearch,
  saveSettings,
} from "@/features/scrape/client";
import type { Search, SearchSource } from "@/features/scrape/types";

const BOARDS = [
  "linkedin_guest",
  "seek",
  "indeed",
  "glassdoor",
  "adzuna",
  "reed",
  "jooble",
  "mycareersfuture",
  "naukri",
].map((value) => ({ value, label: sourceLabel(value) }));

const COUNTRIES = [
  ["TH", "Thailand"],
  ["SG", "Singapore"],
  ["TW", "Taiwan"],
  ["JP", "Japan"],
  ["AU", "Australia"],
  ["NZ", "New Zealand"],
  ["HK", "Hong Kong"],
  ["MY", "Malaysia"],
  ["VN", "Vietnam"],
  ["ID", "Indonesia"],
  ["PH", "Philippines"],
  ["IN", "India"],
  ["GB", "United Kingdom"],
  ["DE", "Germany"],
  ["NL", "Netherlands"],
  ["FR", "France"],
].map(([value, label]) => ({ value, label }));

const ROLES = [
  ["software", "Software"],
  ["fullstack", "Full stack"],
  ["frontend", "Frontend"],
  ["backend", "Backend"],
  ["ml", "AI / ML"],
  ["product_engineer", "Product engineer"],
  ["growth_engineer", "Growth engineer"],
  ["platform_engineer", "Platform engineer"],
  ["web_engineer", "Web engineer"],
  ["forward_deployed", "Forward deployed"],
] as const;

function pollDefault(sourceId: string): number {
  if (sourceId === "indeed" || sourceId === "glassdoor") return 720;
  if (sourceId === "linkedin_guest" || sourceId === "seek") return 30;
  return 1440;
}

const WHEN = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Bangkok",
});

type Draft = {
  name: string;
  keywords: string[];
  countries: string[];
  sources: { source_id: string; poll_minutes: number; enabled: boolean }[];
};

const EMPTY: Draft = {
  name: "",
  keywords: ["Software Engineer"],
  countries: ["TH", "SG"],
  sources: BOARDS.map((board) => ({
    source_id: board.value,
    poll_minutes: pollDefault(board.value),
    enabled: true,
  })),
};

export function SearchesView() {
  const queryClient = useQueryClient();
  const searches = useQuery({ queryKey: ["searches"], queryFn: fetchSearches });
  const settings = useQuery({ queryKey: ["scrape-settings"], queryFn: fetchScrapeSettings });
  const hooks = useQuery({ queryKey: ["tick-hooks"], queryFn: fetchHooks });
  const [openId, setOpenId] = useState<number | null>(null);
  const [editing, setEditing] = useState<Search | "new" | null>(null);
  const [roles, setRoles] = useState<string[] | null>(null);
  const allowed = roles ?? settings.data?.allowed_roles ?? [];

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ["searches"] });
  }

  return (
    <div className="space-y-8">
      <section className="space-y-3" aria-labelledby="searches-heading">
        <div className="flex items-center justify-between gap-3">
          <h2 id="searches-heading" className="text-sm font-semibold">
            Saved searches
          </h2>
          <Button type="button" onClick={() => setEditing("new")}>
            New search
          </Button>
        </div>
        {searches.isLoading && <p className="text-sm text-muted-foreground">Loading searches…</p>}
        {searches.isError && <p className="text-sm text-destructive">Could not load searches.</p>}
        <div className="overflow-x-auto rounded-2xl border bg-card">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Name</th>
                <th className="px-4 py-3 font-medium">Keywords</th>
                <th className="px-4 py-3 font-medium">Countries</th>
                <th className="px-4 py-3 font-medium">Sources</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {(searches.data ?? []).map((search) => (
                <SearchRows
                  key={search.id}
                  search={search}
                  open={openId === search.id}
                  onToggle={() => setOpenId(openId === search.id ? null : search.id)}
                  onEdit={() => setEditing(search)}
                  onChanged={refresh}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="space-y-3" aria-labelledby="roles-heading">
        <h2 id="roles-heading" className="text-sm font-semibold">
          Titles to keep
        </h2>
        <div className="flex flex-wrap gap-4">
          {ROLES.map(([value, label]) => (
            <label key={value} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={allowed.includes(value)}
                onCheckedChange={(checked) => {
                  const next =
                    checked === true ? [...allowed, value] : allowed.filter((role) => role !== value);
                  setRoles(next);
                }}
              />
              {label}
            </label>
          ))}
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            saveSettings(allowed)
              .then(() => {
                toast.success("Saved allowed roles");
                setRoles(null);
                return queryClient.invalidateQueries({ queryKey: ["scrape-settings"] });
              })
              .catch((error: Error) => toast.error(error.message));
          }}
        >
          Save roles
        </Button>
      </section>

      <section className="space-y-3" aria-labelledby="hooks-heading">
        <h2 id="hooks-heading" className="text-sm font-semibold">
          Tick hooks
        </h2>
        <ul className="space-y-1 text-sm text-muted-foreground">
          {(hooks.data?.configured ?? []).map((hook) => (
            <li key={`${hook.phase}-${hook.name}`}>
              {hook.phase}: {hook.name} · {hook.run}
              {hook.on_fail ? ` · on fail ${hook.on_fail}` : ""}
            </li>
          ))}
        </ul>
        {(hooks.data?.recent.length ?? 0) > 0 && (
          <ul className="space-y-1 text-sm">
            {hooks.data?.recent.slice(0, 6).map((hook) => (
              <li key={hook.id}>
                {hook.name} exit {hook.exit_code ?? "–"} in {hook.duration_ms}ms
                {hook.error ? ` (${hook.error})` : ""}
              </li>
            ))}
          </ul>
        )}
      </section>

      {editing && (
        <SearchDialog
          search={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            return refresh();
          }}
        />
      )}
    </div>
  );
}

function SearchRows({
  search,
  open,
  onToggle,
  onEdit,
  onChanged,
}: {
  search: Search;
  open: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onChanged: () => Promise<void>;
}) {
  return (
    <>
      <tr className="border-b">
        <td className="px-4 py-3 font-medium">{search.name}</td>
        <td className="px-4 py-3">{search.keywords.join(", ")}</td>
        <td className="px-4 py-3">{search.countries.join(", ")}</td>
        <td className="px-4 py-3">{search.sources.length}</td>
        <td className="px-4 py-3 text-right">
          <Button type="button" variant="ghost" onClick={onToggle}>
            {open ? "Hide" : "Sources"}
          </Button>
          <Button type="button" variant="ghost" onClick={onEdit}>
            Edit
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              removeSearch(search.id)
                .then(onChanged)
                .catch((error: Error) => toast.error(error.message));
            }}
          >
            Delete
          </Button>
        </td>
      </tr>
      {open &&
        search.sources.map((source) => (
          <tr key={source.source_id} className="border-b bg-muted/20 text-xs">
            <td className="px-4 py-2 pl-8" colSpan={5}>
              <SourceLine search={search} source={source} />
            </td>
          </tr>
        ))}
    </>
  );
}

function SourceLine({ search, source }: { search: Search; source: SearchSource }) {
  const circuit = source.paused_until
    ? `paused until ${WHEN.format(new Date(source.paused_until))}`
    : source.strikes > 0
      ? `${source.strikes} throttle signal`
      : "clear";
  return (
    <div className="flex flex-wrap items-center gap-3">
      <span className="font-medium">{sourceLabel(source.source_id)}</span>
      <span>every {source.poll_minutes} min</span>
      <span>{source.last_polled_at ? WHEN.format(new Date(source.last_polled_at)) : "never polled"}</span>
      <Badge variant="outline">{source.last_status ?? "no run"}</Badge>
      <span className="text-muted-foreground">{circuit}</span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={() => {
          runSearch(search.id)
            .then(() => toast.success("Run queued"))
            .catch((error: Error) => toast.error(error.message));
        }}
      >
        Run now
      </Button>
    </div>
  );
}

function SearchDialog({
  search,
  onClose,
  onSaved,
}: {
  search: Search | null;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(
    search
      ? {
          name: search.name,
          keywords: search.keywords,
          countries: search.countries,
          sources: search.sources.map((source) => ({
            source_id: source.source_id,
            poll_minutes: source.poll_minutes,
            enabled: source.enabled,
          })),
        }
      : EMPTY,
  );
  const [keyword, setKeyword] = useState("");

  function addKeyword() {
    const next = keyword.trim();
    if (!next || draft.keywords.includes(next)) return;
    setDraft({ ...draft, keywords: [...draft.keywords, next] });
    setKeyword("");
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{search ? "Edit search" : "New search"}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="search-name">Name</Label>
            <Input
              id="search-name"
              value={draft.name}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="search-keyword">Keywords</Label>
            <div className="flex gap-2">
              <Input
                id="search-keyword"
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    addKeyword();
                  }
                }}
              />
              <Button type="button" variant="outline" onClick={addKeyword}>
                Add
              </Button>
            </div>
            <div className="flex flex-wrap gap-2">
              {draft.keywords.map((word) => (
                <Badge key={word} variant="secondary">
                  {word}
                  <button
                    type="button"
                    className="ml-1"
                    aria-label={`Remove ${word}`}
                    onClick={() =>
                      setDraft({ ...draft, keywords: draft.keywords.filter((item) => item !== word) })
                    }
                  >
                    ×
                  </button>
                </Badge>
              ))}
            </div>
          </div>
          <MultiSelect
            label="Countries"
            options={COUNTRIES}
            selected={draft.countries}
            onChange={(countries) => setDraft({ ...draft, countries })}
          />
          <MultiSelect
            label="Sources"
            options={BOARDS}
            selected={draft.sources.map((source) => source.source_id)}
            onChange={(ids) =>
              setDraft({
                ...draft,
                sources: ids.map(
                  (source_id) =>
                    draft.sources.find((source) => source.source_id === source_id) ?? {
                      source_id,
                      poll_minutes: 30,
                      enabled: true,
                    },
                ),
              })
            }
          />
          <div className="space-y-2">
            {draft.sources.map((source) => (
              <div key={source.source_id} className="flex items-center gap-3">
                <Label className="w-36" htmlFor={`poll-${source.source_id}`}>
                  {sourceLabel(source.source_id)}
                </Label>
                <Input
                  id={`poll-${source.source_id}`}
                  className="w-24"
                  type="number"
                  min={1}
                  aria-label={`${sourceLabel(source.source_id)} poll minutes`}
                  value={source.poll_minutes}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      sources: draft.sources.map((item) =>
                        item.source_id === source.source_id
                          ? { ...item, poll_minutes: Number(event.target.value) }
                          : item,
                      ),
                    })
                  }
                />
                <span className="text-xs text-muted-foreground">min</span>
                <Switch
                  checked={source.enabled}
                  aria-label={`${sourceLabel(source.source_id)} enabled`}
                  onCheckedChange={(enabled) =>
                    setDraft({
                      ...draft,
                      sources: draft.sources.map((item) =>
                        item.source_id === source.source_id ? { ...item, enabled } : item,
                      ),
                    })
                  }
                />
              </div>
            ))}
          </div>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => {
              saveSearch(
                { ...draft, timezone: "Asia/Bangkok", enabled: true },
                search?.id,
              )
                .then(() => {
                  toast.success("Saved search");
                  return onSaved();
                })
                .catch((error: Error) => toast.error(error.message));
            }}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
