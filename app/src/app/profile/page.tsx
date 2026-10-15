import { Suspense } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { ProfileView } from "@/features/profile/components/ProfileView";

export const metadata = { title: "Profile · Job Hunt" };

export default function ProfilePage({ searchParams }: { searchParams: Promise<{ tab?: string }> }) {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full rounded-2xl" />}>
      <ProfileView searchParams={searchParams} />
    </Suspense>
  );
}
