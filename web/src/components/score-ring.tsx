import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const BAND_COLORS: Record<string, string> = {
  apply: "text-emerald-500",
  maybe: "text-amber-500",
  skip: "text-slate-400",
};

const RADIUS = 18;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function ScoreRing({
  score,
  band,
  stage,
  size = "md",
}: {
  score: number | null;
  band: string | null;
  stage: string;
  size?: "md" | "lg";
}) {
  const scored = score !== null;
  const label = scored ? `Match score ${score} of 100${band ? `, ${band}` : ""}` : `Not scored yet (${stage})`;
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
                className={BAND_COLORS[band ?? ""] ?? "text-primary"}
                strokeDasharray={CIRCUMFERENCE}
                strokeDashoffset={CIRCUMFERENCE * (1 - score / 100)}
              />
            )}
          </svg>
          <span className={cn("font-semibold tabular-nums", size === "lg" ? "text-base" : "text-xs", !scored && "text-muted-foreground")}>
            {scored ? score : "–"}
          </span>
        </div>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}
