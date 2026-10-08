import { Suspense } from "react";

import { BragDocsView } from "@/components/brag-docs/brag-docs-view";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchBragDocs, fetchCompanies, fetchMetricKeys, fetchTags } from "@/lib/api";

export const metadata = { title: "Brag Docs · Job Hunt" };

export default function BragDocsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-2xl" />}>
      <BragDocs />
    </Suspense>
  );
}

async function BragDocs() {
  const [docs, tags, metricKeys, companies] = await Promise.all([
    fetchBragDocs(),
    fetchTags(),
    fetchMetricKeys(),
    fetchCompanies(),
  ]);
  return <BragDocsView docs={docs} tags={tags} metricKeys={metricKeys} companies={companies} />;
}
