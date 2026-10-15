"use client";

import { useState, useTransition } from "react";
import { toast } from "sonner";

import { saveSummary } from "@/features/profile/actions";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

export function SummaryForm({ summary }: { summary: string }) {
  const [body, setBody] = useState(summary);
  const [isPending, startTransition] = useTransition();
  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        startTransition(async () => {
          const result = await saveSummary(body);
          if (result.ok) toast.success("Summary saved");
          else toast.error(result.error);
        });
      }}
    >
      <Label htmlFor="profile-summary">Profile summary</Label>
      <Textarea
        id="profile-summary"
        value={body}
        className="min-h-28"
        onChange={(event) => setBody(event.target.value)}
      />
      <Button type="submit" variant="outline" disabled={isPending || body === summary}>
        {isPending ? "Saving…" : "Save summary"}
      </Button>
    </form>
  );
}
