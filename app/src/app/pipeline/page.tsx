import { Suspense } from "react";

import { PipelineColumns, PipelineSkeleton } from "@/features/jobs/components/PipelineSkeleton";

export const metadata = { title: "Pipeline · Job Hunt" };

export default function PipelinePage() {
  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Pipeline</h1>
        <p className="text-sm text-muted-foreground">Everything you saved, applied to, or passed on.</p>
      </div>
      <Suspense fallback={<PipelineSkeleton />}>
        <PipelineColumns />
      </Suspense>
    </div>
  );
}
