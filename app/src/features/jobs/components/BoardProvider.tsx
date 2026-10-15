"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useTransition, type ReactNode } from "react";

import { toQuery, type Filters } from "@/features/jobs/filters";

type BoardContextValue = {
  filters: Filters;
  isPending: boolean;
  navigate: (changes: Filters) => void;
  hrefFor: (changes: Filters) => string;
};

const BoardContext = createContext<BoardContextValue | null>(null);

export function BoardProvider({ filters, children }: { filters: Filters; children: ReactNode }) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function hrefFor(changes: Filters): string {
    const query = toQuery(filters, changes);
    return query ? `/?${query}` : "/";
  }

  function navigate(changes: Filters) {
    startTransition(() => router.push(hrefFor(changes), { scroll: false }));
  }

  return (
    <BoardContext.Provider value={{ filters, isPending, navigate, hrefFor }}>{children}</BoardContext.Provider>
  );
}

export function useBoard(): BoardContextValue {
  const value = useContext(BoardContext);
  if (!value) throw new Error("useBoard must be used inside BoardProvider");
  return value;
}
