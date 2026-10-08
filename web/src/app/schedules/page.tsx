import { SchedulesView } from "@/components/schedules/schedules-view";

export const metadata = { title: "Schedules · Job Hunt" };

export default function SchedulesPage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Fit schedules</h1>
        <p className="text-sm text-muted-foreground">
          Scores are computed ahead of time. Change a schedule here and the worker picks it up without a restart.
        </p>
      </div>
      <SchedulesView />
    </div>
  );
}
