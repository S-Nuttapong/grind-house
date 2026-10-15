"use client";

import {
  BookmarkIcon,
  BriefcaseBusinessIcon,
  CalendarClockIcon,
  AwardIcon,
  IdCardIcon,
  KanbanSquareIcon,
  ListIcon,
  SearchIcon,
  ServerIcon,
  CircleDollarSignIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import type { JobPage, JobSummary } from "@/features/jobs/types";

export function CommandMenu() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [found, setFound] = useState<{ query: string; jobs: JobSummary[] }>({ query: "", jobs: [] });
  const query = term.trim();
  const results = found.query === query ? found.jobs : [];
  const loading = query.length >= 2 && found.query !== query;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((value) => !value);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open || query.length < 2) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`/api/jobs?${new URLSearchParams({ q: query })}`, {
          signal: controller.signal,
        });
        const jobs = response.ok ? ((await response.json()) as JobPage).jobs.slice(0, 8) : [];
        setFound({ query, jobs });
      } catch (error) {
        if (controller.signal.aborted) return;
        console.error("command search failed", error);
        setFound({ query, jobs: [] });
      }
    }, 200);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, open]);

  function go(href: string) {
    setOpen(false);
    setTerm("");
    router.push(href);
  }

  return (
    <>
      <Button
        variant="outline"
        className="h-8 w-9 justify-start gap-2 px-2 text-muted-foreground sm:w-56"
        onClick={() => setOpen(true)}
      >
        <SearchIcon />
        <span className="hidden sm:inline">Search jobs</span>
        <kbd className="ml-auto hidden rounded border bg-muted px-1.5 font-mono text-[10px] sm:inline">⌘K</kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title="Search jobs" description="Search jobs or jump to a page">
        <Command shouldFilter={false}>
          <CommandInput placeholder="Search titles, companies, skills…" value={term} onValueChange={setTerm} />
          <CommandList>
            <CommandEmpty>{loading ? "Searching…" : query.length < 2 ? "Type to search jobs." : "No jobs found."}</CommandEmpty>
            {results.length > 0 && (
              <CommandGroup heading="Jobs">
                {results.map((job) => (
                  <CommandItem key={job.id} value={`job-${job.id}`} onSelect={() => go(`/?jk=${job.id}`)}>
                    <BriefcaseBusinessIcon />
                    <span className="truncate">{job.title}</span>
                    <span className="ml-auto truncate text-xs text-muted-foreground">{job.company}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {query.length >= 2 && (
              <CommandGroup heading="Search">
                <CommandItem value="search-all" onSelect={() => go(`/?${new URLSearchParams({ q: query })}`)}>
                  <SearchIcon />
                  See all results for “{query}”
                </CommandItem>
              </CommandGroup>
            )}
            <CommandSeparator />
            <CommandGroup heading="Go to">
              <CommandItem value="nav-board" onSelect={() => go("/")}>
                <ListIcon />
                Board
              </CommandItem>
              <CommandItem value="nav-pipeline" onSelect={() => go("/pipeline")}>
                <KanbanSquareIcon />
                Pipeline
              </CommandItem>
              <CommandItem value="nav-brag-docs" onSelect={() => go("/brag-docs")}>
                <AwardIcon />
                Brag Docs
              </CommandItem>
              <CommandItem value="nav-profile" onSelect={() => go("/profile")}>
                <IdCardIcon />
                Profile
              </CommandItem>
              <CommandItem value="nav-searches" onSelect={() => go("/searches")}>
                <SearchIcon />
                Searches
              </CommandItem>
              <CommandItem value="nav-schedules" onSelect={() => go("/schedules")}>
                <CalendarClockIcon />
                Schedules
              </CommandItem>
              <CommandItem value="nav-saved" onSelect={() => go("/pipeline#saved")}>
                <BookmarkIcon />
                Saved jobs
              </CommandItem>
              <CommandItem value="nav-runs" onSelect={() => go("/runs")}>
                <ServerIcon />
                Runs
              </CommandItem>
              <CommandItem value="nav-usage" onSelect={() => go("/admin/usage")}>
                <CircleDollarSignIcon />
                Usage
              </CommandItem>
            </CommandGroup>
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  );
}
