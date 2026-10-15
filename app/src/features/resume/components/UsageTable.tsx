import { fetchUsage } from "@/features/resume/api";

const WHEN = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Bangkok",
});
const MONEY = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export async function UsageTable() {
  const usage = await fetchUsage(30);
  return (
    <div className="space-y-6">
      <p className="text-sm">
        Last {usage.days} days: {MONEY.format(Number(usage.cost_usd))} across {usage.runs} attempts,{" "}
        {usage.input_tokens.toLocaleString("en-US")} input tokens, {usage.output_tokens.toLocaleString("en-US")}{" "}
        output tokens.
      </p>
      <div className="overflow-x-auto rounded-2xl border bg-card shadow-sm">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">Day</th>
              <th className="px-4 py-3 font-medium">Model</th>
              <th className="px-4 py-3 font-medium">Attempts</th>
              <th className="px-4 py-3 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {usage.by_day.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-muted-foreground" colSpan={4}>
                  No usage yet.
                </td>
              </tr>
            ) : (
              usage.by_day.map((row) => (
                <tr key={`${row.day}-${row.model}`} className="border-b last:border-0">
                  <td className="px-4 py-3">{row.day}</td>
                  <td className="px-4 py-3">{row.model}</td>
                  <td className="px-4 py-3">{row.runs}</td>
                  <td className="px-4 py-3">{MONEY.format(Number(row.cost_usd))}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto rounded-2xl border bg-card shadow-sm">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-3 font-medium">When</th>
              <th className="px-4 py-3 font-medium">Job</th>
              <th className="px-4 py-3 font-medium">Attempt</th>
              <th className="px-4 py-3 font-medium">Model</th>
              <th className="px-4 py-3 font-medium">Tokens</th>
              <th className="px-4 py-3 font-medium">Turns</th>
              <th className="px-4 py-3 font-medium">Cost</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {usage.recent.map((row) => (
              <tr key={row.id} className="border-b last:border-0">
                <td className="px-4 py-3">{WHEN.format(new Date(row.created_at))}</td>
                <td className="px-4 py-3">{row.job_id ?? "–"}</td>
                <td className="px-4 py-3">{row.attempt}</td>
                <td className="px-4 py-3">{row.model}</td>
                <td className="px-4 py-3">
                  {row.input_tokens}/{row.output_tokens}
                </td>
                <td className="px-4 py-3">{row.num_turns}</td>
                <td className="px-4 py-3">{MONEY.format(Number(row.cost_usd))}</td>
                <td className="px-4 py-3">{row.status ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
