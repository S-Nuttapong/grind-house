"use client";

import { useTransition } from "react";
import { toast } from "sonner";

import { recordJobEvent } from "@/features/jobs/actions";
import type { MoveStatus } from "@/features/jobs/types";

const MESSAGES: Record<MoveStatus, string> = {
  saved: "Saved to your tracker",
  applied: "Marked as applied",
  skipped: "Hidden as not interested",
  removed: "Removed from your tracker",
};

export function useJobEvent(jobId: number) {
  const [isPending, startTransition] = useTransition();
  function send(status: MoveStatus, reason?: string) {
    startTransition(async () => {
      const result = await recordJobEvent(jobId, status, reason);
      if (result.ok) toast.success(MESSAGES[result.status]);
      else toast.error(result.error);
    });
  }
  return { send, isPending };
}
