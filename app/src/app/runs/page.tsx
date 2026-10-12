import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { RunsTable } from "@/features/scrape/components/runs-table";
import { fetchTickHooks } from "@/features/scrape/api";

export const metadata = { title: "Runs · Job Hunt" };

export default function RunsPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Runs</h1>
        <p className="text-sm text-muted-foreground">Recent scrapes per source. Times are Bangkok time.</p>
      </div>
      <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
        <RunsTable />
        <HookResults />
      </Suspense>
    </div>
  );
}

async function HookResults() {
  const hooks = await fetchTickHooks();
  if (hooks.recent.length === 0) return null;
  return (
    <section className="space-y-2" aria-labelledby="hook-results">
      <h2 id="hook-results" className="text-sm font-semibold">
        Tick hooks
      </h2>
      <ul className="space-y-1 text-sm text-muted-foreground">
        {hooks.recent.slice(0, 8).map((hook) => (
          <li key={hook.id}>
            {hook.name} · exit {hook.exit_code ?? "–"} · {hook.duration_ms}ms
            {hook.error ? ` · ${hook.error}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}
