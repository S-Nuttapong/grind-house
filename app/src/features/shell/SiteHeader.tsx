"use client";

import { BriefcaseBusinessIcon } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { CommandMenu } from "@/features/shell/CommandMenu";

const ScoringPill = dynamic(
  () => import("@/features/fit/components/ScoringPill").then((mod) => mod.ScoringPill),
  { ssr: false },
);
import { ThemeToggle } from "@/features/shell/ThemeToggle";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Board" },
  { href: "/tracker", label: "Tracker" },
  { href: "/brag-docs", label: "Brag Docs" },
  { href: "/profile", label: "Profile" },
  { href: "/searches", label: "Searches" },
  { href: "/schedules", label: "Schedules" },
  { href: "/resume-queue", label: "Resume queue" },
  { href: "/runs", label: "Runs" },
];

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center gap-6 px-4 lg:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-primary-foreground">
            <BriefcaseBusinessIcon className="size-4" />
          </span>
          <span className="hidden sm:inline">Job Hunt</span>
        </Link>
        <nav aria-label="Main" className="flex items-center gap-1 overflow-x-auto text-sm">
          {NAV.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-accent font-medium text-accent-foreground hover:bg-accent",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <ScoringPill />
          <CommandMenu />
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
