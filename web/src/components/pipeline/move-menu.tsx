"use client";

import { MoreHorizontalIcon } from "lucide-react";

import { useJobEvent } from "@/components/board/job-actions";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { JobStatus } from "@/lib/types";

const TARGETS: { status: JobStatus; label: string }[] = [
  { status: "saved", label: "Saved" },
  { status: "applied", label: "Applied" },
  { status: "skipped", label: "Not interested" },
];

export function MoveMenu({ jobId, current }: { jobId: number; current: string }) {
  const { send, isPending } = useJobEvent(jobId);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label="Move job" disabled={isPending} className="relative z-10">
          <MoreHorizontalIcon />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>Move to</DropdownMenuLabel>
        {TARGETS.filter((target) => target.status !== current).map((target) => (
          <DropdownMenuItem key={target.status} onSelect={() => send(target.status)}>
            {target.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
