import { ResumeQueue } from "@/features/resume/components/ResumeQueue";

export const metadata = { title: "Resume queue · Job Hunt" };

export default function ResumeQueuePage() {
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Resume queue</h1>
        <p className="text-sm text-muted-foreground">
          One resume is written at a time. New requests wait here until the worker picks them up.
        </p>
      </div>
      <ResumeQueue />
    </div>
  );
}
