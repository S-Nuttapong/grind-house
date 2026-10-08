"use client";

import { MousePointerClickIcon, SearchXIcon, SlidersHorizontalIcon } from "lucide-react";
import Link from "next/link";
import { useSyncExternalStore } from "react";

import { useBoard } from "@/components/board/board-provider";
import { FilterSidebar } from "@/components/board/filter-sidebar";
import { JobCard } from "@/components/board/job-card";
import { JobDetail } from "@/components/board/job-detail";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { SORTS } from "@/lib/filters";
import type { Facets, JobDetail as Job, JobPage } from "@/lib/types";
import { cn } from "@/lib/utils";

const COUNT = new Intl.NumberFormat("en-US");
const DESKTOP_QUERY = "(min-width: 1024px)";

function subscribe(callback: () => void) {
  const media = window.matchMedia(DESKTOP_QUERY);
  media.addEventListener("change", callback);
  return () => media.removeEventListener("change", callback);
}

function useIsDesktop(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(DESKTOP_QUERY).matches,
    () => true,
  );
}

function pageNumbers(current: number, pages: number): (number | "gap")[] {
  const wanted = new Set([1, pages, current - 1, current, current + 1].filter((n) => n >= 1 && n <= pages));
  const sorted = [...wanted].sort((a, b) => a - b);
  const items: (number | "gap")[] = [];
  sorted.forEach((n, index) => {
    if (index > 0 && n - sorted[index - 1] > 1) items.push("gap");
    items.push(n);
  });
  return items;
}

function Pager({ page, pages }: { page: number; pages: number }) {
  const { hrefFor } = useBoard();
  if (pages <= 1) return null;
  const link = (n: number) => hrefFor({ page: n === 1 ? "" : String(n), jk: "" });
  return (
    <nav aria-label="Pagination" className="flex items-center justify-center gap-1 pt-2">
      <Button asChild variant="ghost" size="sm" className={cn(page <= 1 && "pointer-events-none opacity-40")}>
        <Link href={link(Math.max(1, page - 1))} aria-disabled={page <= 1}>
          Previous
        </Link>
      </Button>
      {pageNumbers(page, pages).map((item, index) =>
        item === "gap" ? (
          <span key={`gap-${index}`} className="px-1 text-muted-foreground">
            …
          </span>
        ) : (
          <Button key={item} asChild variant={item === page ? "outline" : "ghost"} size="icon-sm">
            <Link href={link(item)} aria-current={item === page ? "page" : undefined}>
              {item}
            </Link>
          </Button>
        ),
      )}
      <Button asChild variant="ghost" size="sm" className={cn(page >= pages && "pointer-events-none opacity-40")}>
        <Link href={link(Math.min(pages, page + 1))} aria-disabled={page >= pages}>
          Next
        </Link>
      </Button>
    </nav>
  );
}

function EmptyResults() {
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-16 text-center">
      <SearchXIcon className="size-8 text-muted-foreground" />
      <div>
        <p className="font-medium">No jobs match these filters</p>
        <p className="text-sm text-muted-foreground">Try a broader title, another location, or fewer filters.</p>
      </div>
      <Button asChild variant="outline">
        <Link href="/">Clear filters</Link>
      </Button>
    </div>
  );
}

function DetailPlaceholder() {
  return (
    <div className="flex h-full min-h-80 flex-col items-center justify-center gap-3 rounded-xl border border-dashed p-8 text-center text-muted-foreground">
      <MousePointerClickIcon className="size-8" />
      <p className="text-sm">Select a job to see the full description, pay, and match details.</p>
    </div>
  );
}

export function BoardView({ data, facets, selected }: { data: JobPage; facets: Facets; selected: Job | null }) {
  const { filters, navigate, isPending } = useBoard();
  const isDesktop = useIsDesktop();
  const sort = filters.sort ?? "match";
  const fitSource = filters.fit === "resume" ? "selected resume" : "brag bank";
  const showing = data.total === 0 ? 0 : (data.page - 1) * data.page_size + 1;
  const upTo = Math.min(data.total, data.page * data.page_size);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,1.15fr)]">
      <div className="hidden xl:block">
        <div className="sticky top-20">
          <FilterSidebar facets={facets} />
        </div>
      </div>

      <section aria-label="Job results" className={cn("min-w-0 space-y-3 transition-opacity", isPending && "opacity-60")}>
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {data.total === 0 ? (
              "No jobs"
            ) : (
              <>
                <span className="font-semibold text-foreground">{COUNT.format(data.total)}</span> jobs
                {data.pages > 1 && ` · ${showing}–${upTo}`}
              </>
            )}
          </p>
          <div className="flex items-center gap-2">
            <Sheet>
              <SheetTrigger asChild>
                <Button variant="outline" size="sm" className="xl:hidden">
                  <SlidersHorizontalIcon />
                  Filters
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="overflow-y-auto p-6">
                <SheetHeader className="sr-only">
                  <SheetTitle>Filters</SheetTitle>
                  <SheetDescription>Narrow the job list</SheetDescription>
                </SheetHeader>
                <FilterSidebar facets={facets} />
              </SheetContent>
            </Sheet>
            <Select value={sort} onValueChange={(value) => navigate({ sort: value === "match" ? "" : value })}>
              <SelectTrigger size="sm" aria-label="Sort by" className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent position="popper" align="end">
                {SORTS.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {data.jobs.length === 0 ? (
          <EmptyResults />
        ) : (
          <ol className="space-y-3">
            {data.jobs.map((job) => (
              <JobCard key={job.id} job={job} selected={selected?.id === job.id} />
            ))}
          </ol>
        )}
        <Pager page={data.page} pages={data.pages} />
      </section>

      <aside aria-label="Job details" className="hidden min-w-0 lg:block">
        <div className="sticky top-20 max-h-[calc(100vh-6rem)] overflow-y-auto rounded-2xl border bg-card p-6 shadow-sm">
          {selected ? <JobDetail job={selected} source={fitSource} /> : <DetailPlaceholder />}
        </div>
      </aside>

      {!isDesktop && (
        <Sheet open={selected !== null} onOpenChange={(open) => !open && navigate({ jk: "" })}>
          <SheetContent side="bottom" className="overflow-y-auto rounded-t-2xl p-5 pt-12 data-[side=bottom]:h-[92dvh]">
            <SheetHeader className="sr-only">
              <SheetTitle>{selected?.title ?? "Job"}</SheetTitle>
              <SheetDescription>Job details</SheetDescription>
            </SheetHeader>
            {selected && <JobDetail job={selected} source={fitSource} />}
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}
