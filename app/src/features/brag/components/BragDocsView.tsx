"use client";

import { useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import { deleteBragDoc } from "@/features/brag/actions";
import { BragDocCard } from "@/features/brag/components/BragDocCard";
import { BragDocForm } from "@/features/brag/components/BragDocForm";
import { FilterBar } from "@/features/brag/components/FilterBar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { byDateDesc, filterBragDocs, filtersFromParams, groupByQuarter, type BragFilters } from "@/features/brag/filters";
import type { BragDoc, MetricKey, Tag } from "@/features/brag/types";

export function BragDocsView({
  docs,
  tags,
  metricKeys,
  companies,
}: {
  docs: BragDoc[];
  tags: Tag[];
  metricKeys: MetricKey[];
  companies: string[];
}) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const filters = useMemo(() => filtersFromParams(searchParams), [searchParams]);
  const groups = useMemo(
    () => groupByQuarter(filterBragDocs([...docs].sort(byDateDesc), filters)),
    [docs, filters],
  );
  const [editing, setEditing] = useState<BragDoc | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<BragDoc | null>(null);

  function writeFilters(next: BragFilters) {
    const params = new URLSearchParams(searchParams.toString());
    put(params, "q", next.q.trim());
    put(params, "tags", next.tagIds.join(","));
    put(params, "company", next.company);
    put(params, "metric", next.metricKeyId ? String(next.metricKeyId) : "");
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Brag docs</h1>
          <p className="text-sm text-muted-foreground">
            Accomplishments grouped by quarter. The next fit run scores jobs against whatever is saved here.
          </p>
        </div>
        <Button
          type="button"
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          Log a brag doc
        </Button>
      </div>
      <FilterBar filters={filters} tags={tags} metricKeys={metricKeys} companies={companies} onChange={writeFilters} />
      {groups.length === 0 ? (
        <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">
          {docs.length === 0 ? "No brag docs yet." : "Nothing matches these filters."}
        </p>
      ) : (
        <div className="space-y-8">
          {groups.map((group) => (
            <section key={group.quarter} className="space-y-3">
              <h2 className="text-sm font-semibold tracking-tight text-muted-foreground">{group.quarter}</h2>
              <div className="space-y-3">
                {group.docs.map((doc) => (
                  <BragDocCard
                    key={doc.id}
                    doc={doc}
                    onEdit={(selected) => {
                      setEditing(selected);
                      setFormOpen(true);
                    }}
                    onDelete={setPendingDelete}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
      <BragDocForm
        open={formOpen}
        doc={editing}
        tags={tags}
        metricKeys={metricKeys}
        companies={companies}
        onOpenChange={setFormOpen}
      />
      <Dialog open={pendingDelete != null} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this brag doc?</DialogTitle>
            <DialogDescription>
              This removes it from the local database. A vault file, if you imported one, is left as it is.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="destructive"
              onClick={async () => {
                if (!pendingDelete) return;
                const result = await deleteBragDoc(pendingDelete.id);
                if (result.ok) {
                  toast.success("Brag doc deleted");
                  setPendingDelete(null);
                } else toast.error(result.error);
              }}
            >
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function put(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
  else params.delete(key);
}
