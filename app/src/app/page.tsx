import { Suspense } from "react";

import { BoardProvider } from "@/features/jobs/components/board-provider";
import { BoardSkeleton } from "@/features/jobs/components/board-skeleton";
import { BoardView } from "@/features/jobs/components/board-view";
import { SearchBar } from "@/features/jobs/components/search-bar";
import { fetchFacets, fetchJob, fetchJobs } from "@/features/jobs/api";
import { apiQuery, readFilters } from "@/features/jobs/filters";

export default function BoardPage({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<BoardSkeleton />}>
      <Board searchParams={searchParams} />
    </Suspense>
  );
}

async function Board({ searchParams }: Pick<PageProps<"/">, "searchParams">) {
  const filters = readFilters(await searchParams);
  const selectedId = Number(filters.jk);
  const [data, facets, selected] = await Promise.all([
    fetchJobs(apiQuery(filters)),
    fetchFacets(),
    Number.isInteger(selectedId) && selectedId > 0 ? fetchJob(selectedId, filters.fit ?? "") : Promise.resolve(null),
  ]);

  return (
    <BoardProvider filters={filters}>
      <div className="space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Find your next role</h1>
          <p className="text-sm text-muted-foreground">Search every board you track. Save, skip, and apply from one place.</p>
        </div>
        <SearchBar key={`${filters.q ?? ""}|${filters.where ?? ""}`} />
        <BoardView data={data} facets={facets} selected={selected} />
      </div>
    </BoardProvider>
  );
}
