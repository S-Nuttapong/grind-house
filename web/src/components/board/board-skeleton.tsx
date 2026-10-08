import { Skeleton } from "@/components/ui/skeleton";

export function BoardSkeleton() {
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] xl:grid-cols-[220px_minmax(0,1fr)_minmax(0,1.15fr)]">
      <div className="hidden space-y-4 xl:block">
        {Array.from({ length: 8 }, (_, index) => (
          <Skeleton key={index} className="h-4 w-3/4" />
        ))}
      </div>
      <div className="space-y-3">
        <Skeleton className="h-5 w-32" />
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className="flex gap-4 rounded-xl border bg-card p-4">
            <Skeleton className="size-11 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-3 w-1/3" />
              <Skeleton className="h-3 w-full" />
            </div>
          </div>
        ))}
      </div>
      <div className="hidden rounded-2xl border bg-card p-6 lg:block">
        <Skeleton className="h-6 w-2/3" />
        <Skeleton className="mt-3 h-4 w-1/3" />
        <Skeleton className="mt-6 h-9 w-48" />
        <Skeleton className="mt-8 h-40 w-full" />
      </div>
    </div>
  );
}
