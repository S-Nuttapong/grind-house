import { SearchesView } from "@/features/scrape/components/searches-view";

export const metadata = { title: "Searches · Job Hunt" };

export default function SearchesPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Searches</h1>
        <p className="text-sm text-muted-foreground">
          Software roles across LinkedIn, SEEK, and the other boards. Each source keeps its own poll interval.
        </p>
      </div>
      <SearchesView />
    </div>
  );
}
