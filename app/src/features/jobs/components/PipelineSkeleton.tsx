import { Skeleton } from "@/components/ui/skeleton";
import { fetchPipeline } from "@/features/jobs/api";
import { PipelineBoard } from "@/features/jobs/components/PipelineBoard";

const COLUMNS = ["saved", "applied", "skipped"];

export async function PipelineColumns() {
  const pipeline = await fetchPipeline();
  return <PipelineBoard initial={pipeline} />;
}

export function PipelineSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {COLUMNS.map((column) => (
        <div key={column} className="space-y-2 rounded-2xl border bg-muted/40 p-3">
          <Skeleton className="h-5 w-24" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ))}
    </div>
  );
}
