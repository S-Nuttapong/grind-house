import Link from "next/link";

import { fetchResumes, fetchSummary } from "@/features/profile/api";
import { ResumePanel } from "@/features/profile/components/resume-panel";
import { SummaryForm } from "@/features/profile/components/summary-form";
import { cn } from "@/lib/utils";

export async function ProfileView({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  const { tab } = await searchParams;
  const resumesTab = tab === "resumes";
  const [summary, resumes] = resumesTab
    ? await Promise.all([Promise.resolve({ body_md: "" }), fetchResumes()])
    : await Promise.all([fetchSummary(), Promise.resolve([])]);

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Job profile</h1>
        <p className="text-sm text-muted-foreground">
          The summary and the resume the fit worker scores jobs against. Accomplishments live on{" "}
          <Link href="/brag-docs" className="underline underline-offset-4">
            Brag docs
          </Link>
          . Edits apply on the next run.
        </p>
      </div>
      <nav aria-label="Profile sections" className="flex gap-1">
        <Tab href="/profile" current={!resumesTab}>
          Summary
        </Tab>
        <Tab href="/profile?tab=resumes" current={resumesTab}>
          Resumes
        </Tab>
      </nav>
      {resumesTab ? <ResumePanel resumes={resumes} /> : <SummaryForm summary={summary.body_md} />}
    </div>
  );
}

function Tab({ href, current, children }: { href: string; current: boolean; children: string }) {
  return (
    <Link
      href={href}
      aria-current={current ? "page" : undefined}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
        current && "bg-accent font-medium text-accent-foreground",
      )}
    >
      {children}
    </Link>
  );
}
