"use client";

import { MapPinIcon, SearchIcon } from "lucide-react";
import { useState, type FormEvent } from "react";

import { useBoard } from "@/features/jobs/components/BoardProvider";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";

export function SearchBar() {
  const { filters, navigate, isPending } = useBoard();
  const [what, setWhat] = useState(filters.q ?? "");
  const [where, setWhere] = useState(filters.where ?? "");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate({ q: what.trim(), where: where.trim(), jk: "" });
  }

  return (
    <form
      role="search"
      onSubmit={submit}
      className="flex flex-col gap-2 rounded-2xl border bg-card p-2 shadow-sm sm:flex-row sm:items-center sm:gap-0"
    >
      <div className="flex flex-1 items-center gap-2 px-3">
        <SearchIcon className="size-4 shrink-0 text-muted-foreground" />
        <Label htmlFor="q" className="sr-only">
          What
        </Label>
        <input
          id="q"
          name="q"
          value={what}
          onChange={(event) => setWhat(event.target.value)}
          placeholder="Job title, skill, or company"
          className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      <div className="hidden h-6 w-px bg-border sm:block" />
      <div className="flex flex-1 items-center gap-2 px-3">
        <MapPinIcon className="size-4 shrink-0 text-muted-foreground" />
        <Label htmlFor="where" className="sr-only">
          Where
        </Label>
        <input
          id="where"
          name="where"
          value={where}
          onChange={(event) => setWhere(event.target.value)}
          placeholder="City or country code, e.g. Singapore or TH"
          className="h-10 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      <Button type="submit" size="lg" className="h-10 px-6" disabled={isPending}>
        Find jobs
      </Button>
    </form>
  );
}
