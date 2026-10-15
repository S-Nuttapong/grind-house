import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { UsageTable } from "@/features/resume/components/UsageTable";

export const metadata = { title: "Usage · Job Hunt" };

export default function UsagePage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Agent usage</h1>
        <p className="text-sm text-muted-foreground">
          Token cost for resume generation. Not shown on job cards.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-64 w-full rounded-2xl" />}>
        <UsageTable />
      </Suspense>
    </div>
  );
}
