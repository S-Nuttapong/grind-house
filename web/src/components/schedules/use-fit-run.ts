"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { fetchFitRun } from "@/lib/fit-client";
import type { FitRunDetail, FitStreamEvent } from "@/lib/types";

export function useFitRun(runId: number | null) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<FitStreamEvent[]>([]);
  const [eventsFor, setEventsFor] = useState(runId);
  if (runId !== eventsFor) {
    setEventsFor(runId);
    setEvents([]);
  }

  const query = useQuery({
    queryKey: ["fit-run", runId],
    enabled: runId !== null,
    queryFn: () => fetchFitRun(runId ?? 0),
    refetchInterval: (current) => {
      if (connected) return false;
      const status = current.state.data?.status;
      if (status === "ok" || status === "failed") return false;
      return 2000;
    },
  });

  useEffect(() => {
    if (runId === null) return;
    const source = new EventSource(`/api/fit/runs/${runId}/stream`);
    source.onopen = () => setConnected(true);
    source.onmessage = (message) => {
      const data = JSON.parse(message.data) as Omit<FitStreamEvent, "id">;
      const id = Number(message.lastEventId);
      setEvents((current) => (current.some((item) => item.id === id) ? current : [...current, { ...data, id }]));
      if (data.kind === "progress") {
        queryClient.setQueryData<FitRunDetail>(["fit-run", runId], (current) =>
          current
            ? {
                ...current,
                progress: {
                  id,
                  kind: "progress",
                  at: current.progress?.at ?? "",
                  payload: { done: data.done, total: data.total, pct: data.pct },
                },
              }
            : current,
        );
      }
      if (data.kind === "status") {
        queryClient.setQueryData<FitRunDetail>(["fit-run", runId], (current) =>
          current ? { ...current, status: data.status === "failed" ? "failed" : "ok" } : current,
        );
        void queryClient.invalidateQueries({ queryKey: ["fit-runs"] });
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
