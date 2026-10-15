"use client";

import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { useMemo, useState, type ReactNode } from "react";

const DAY_MS = 24 * 60 * 60 * 1000;

export function FitQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { gcTime: DAY_MS, retry: 1 },
        },
      }),
  );
  const persister = useMemo(
    () =>
      createSyncStoragePersister({
        key: "jobhunt-fit",
        storage: typeof window === "undefined" ? undefined : window.localStorage,
      }),
    [],
  );
  return (
    <PersistQueryClientProvider
      client={client}
      persistOptions={{
        persister,
        maxAge: DAY_MS,
        dehydrateOptions: {
          shouldDehydrateQuery: (query) => String(query.queryKey[0]).startsWith("fit-"),
        },
      }}
    >
      {children}
    </PersistQueryClientProvider>
  );
}
