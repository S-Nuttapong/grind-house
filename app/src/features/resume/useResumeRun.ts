"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { fetchResumeRun } from "@/features/resume/client";
import type { ResumeRun, ResumeStreamEvent } from "@/features/resume/types";

const DONE: ResumeRun["status"][] = ["ok", "below_baseline", "failed"];

export function useResumeRun(runId: number | null) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<ResumeStreamEvent[]>([]);
  const [eventsFor, setEventsFor] = useState(runId);
  if (runId !== eventsFor) {
    setEventsFor(runId);
    setEvents([]);
  }

  const query = useQuery({
    queryKey: ["resume-run", runId],
    enabled: runId !== null,
    queryFn: () => fetchResumeRun(runId ?? 0),
    refetchInterval: (current) => {
      if (connected) return false;
      const status = current.state.data?.status;
      if (status && DONE.includes(status)) return false;
      return 2000;
    },
  });

  useEffect(() => {
    if (runId === null) return;
    const source = new EventSource(`/api/resume-runs/${runId}/stream`);
    source.onopen = () => setConnected(true);
    source.onmessage = (message) => {
      const data = JSON.parse(message.data) as Omit<ResumeStreamEvent, "id">;
      const id = Number(message.lastEventId);
      setEvents((current) => (current.some((item) => item.id === id) ? current : [...current, { ...data, id }]));
      if (data.kind === "status" && data.status) {
        queryClient.setQueryData<ResumeRun>(["resume-run", runId], (current) =>
          current ? { ...current, status: data.status ?? current.status } : current,
        );
        void queryClient.invalidateQueries({ queryKey: ["resume-run", runId] });
        source.close();
        setConnected(false);
      }
    };
    source.onerror = () => setConnected(false);
    return () => {
      source.close();
      setConnected(false);
    };
  }, [queryClient, runId]);

  return { run: query.data, events, connected };
}
