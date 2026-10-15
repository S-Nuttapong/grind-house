"use client";

import { BookmarkIcon, CheckIcon, ThumbsDownIcon } from "lucide-react";
import { useState, useTransition } from "react";
import { toast } from "sonner";

import { recordJobEvent } from "@/features/jobs/actions";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { MoveStatus } from "@/features/jobs/types";

import { cn } from "@/lib/utils";

const MESSAGES: Record<MoveStatus, string> = {
  saved: "Saved to your pipeline",
  applied: "Marked as applied",
  skipped: "Hidden as not interested",
  removed: "Removed from your pipeline",
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

export function SaveButton({ jobId, saved, compact = false }: { jobId: number; saved: boolean; compact?: boolean }) {
  const { send, isPending } = useJobEvent(jobId);
  const label = saved ? "Saved" : "Save job";
  const icon = <BookmarkIcon className={cn(saved && "fill-current text-primary")} />;
  if (compact) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={label}
            aria-pressed={saved}
            disabled={isPending || saved}
            onClick={() => send("saved")}
          >
            {icon}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <Button variant="outline" size="lg" aria-pressed={saved} disabled={isPending || saved} onClick={() => send("saved")}>
      {icon}
      {label}
    </Button>
  );
}

export function AppliedButton({ jobId, applied }: { jobId: number; applied: boolean }) {
  const { send, isPending } = useJobEvent(jobId);
  return (
    <Button variant="outline" size="lg" disabled={isPending || applied} onClick={() => send("applied")}>
      <CheckIcon />
      {applied ? "Applied" : "I applied"}
    </Button>
  );
}

export function NotInterestedButton({ jobId, compact = false }: { jobId: number; compact?: boolean }) {
  const { send, isPending } = useJobEvent(jobId);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");

  return (
    <>
      {compact ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Not interested" onClick={() => setOpen(true)}>
              <ThumbsDownIcon />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Not interested</TooltipContent>
        </Tooltip>
      ) : (
        <Button variant="ghost" size="lg" onClick={() => setOpen(true)}>
          <ThumbsDownIcon />
          Not interested
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Not interested?</DialogTitle>
            <DialogDescription>A short reason helps tune future matches. It is optional.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={`reason-${jobId}`}>Reason</Label>
            <Textarea
              id={`reason-${jobId}`}
              value={reason}
              maxLength={500}
              onChange={(event) => setReason(event.target.value)}
              placeholder="e.g. too junior, on-site only, wrong stack"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              disabled={isPending}
              onClick={() => {
                send("skipped", reason);
                setOpen(false);
                setReason("");
              }}
            >
              Hide job
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
