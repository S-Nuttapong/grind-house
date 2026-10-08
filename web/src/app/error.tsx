"use client";

import { ServerCrashIcon } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function BoardError({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-24 text-center">
      <ServerCrashIcon className="size-10 text-muted-foreground" />
      <h1 className="text-lg font-semibold">Could not load jobs</h1>
      <p className="text-sm text-muted-foreground">
        The job API did not answer. Start it with <code className="rounded bg-muted px-1">make api</code>, then retry.
      </p>
      {error.digest && <p className="text-xs text-muted-foreground">Error id {error.digest}</p>}
      <Button onClick={() => retry()}>Try again</Button>
    </div>
  );
}
