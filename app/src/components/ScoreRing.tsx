import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const TIER_COLORS: Record<string, string> = {
  strong: "text-emerald-500",
  good: "text-sky-500",
  fair: "text-amber-500",
  low: "text-slate-400",
};

const RADIUS = 18;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function ScoreRing({
  score,
  tier,
  stage,
  size = "md",
}: {
  score: number | null;
  tier: string | null;
  stage: string;
  size?: "md" | "lg";
}) {
  const scored = score !== null;
  const shown = scored ? Math.round(score) : null;
  const label = scored ? `Match score ${shown} of 100${tier ? `, ${tier}` : ""}` : `Not scored yet${stage && stage !== "not scored" ? `, ${stage}` : ""}`;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          role="img"
          aria-label={label}
          className={cn("relative grid shrink-0 place-items-center", size === "lg" ? "size-14" : "size-11")}
        >
          <svg viewBox="0 0 44 44" className="absolute inset-0 -rotate-90">
            <circle
              cx="22"
              cy="22"
              r={RADIUS}
              fill="none"
              strokeWidth="4"
              className="stroke-muted"
              strokeDasharray={scored ? undefined : "3 3"}
              stroke="currentColor"
            />
            {scored && (
              <circle
                cx="22"
                cy="22"
                r={RADIUS}
                fill="none"
                strokeWidth="4"
                strokeLinecap="round"
                stroke="currentColor"
                className={TIER_COLORS[tier ?? ""] ?? "text-primary"}
                strokeDasharray={CIRCUMFERENCE}
                strokeDashoffset={CIRCUMFERENCE * (1 - (shown ?? 0) / 100)}
              />
            )}
          </svg>
          <span className={cn("font-semibold tabular-nums", size === "lg" ? "text-base" : "text-xs", !scored && "text-muted-foreground")}>
            {scored ? shown : "–"}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
