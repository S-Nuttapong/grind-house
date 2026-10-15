import { Suspense } from "react";

import { TrackerColumns, TrackerSkeleton } from "@/features/jobs/components/TrackerSkeleton";

export const metadata = { title: "Application tracker · Job Hunt" };

export default function TrackerPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Application tracker</h1>
        <p className="text-sm text-muted-foreground">Everything you saved, applied to, or passed on.</p>
      </div>
      <Suspense fallback={<TrackerSkeleton />}>
        <TrackerColumns />
      </Suspense>
    </div>
  );
}
