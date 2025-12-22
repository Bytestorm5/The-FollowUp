import StatsCharts from "@/components/StatsCharts";
import { getSilverLogsCollection, type SilverLog } from "@/lib/mongo";

export const dynamic = "force-dynamic";

function num(n: any): number {
  const v = typeof n === "number" ? n : Number(n ?? 0);
  return Number.isFinite(v) ? v : 0;
}

export default async function StatisticsPage() {
  const coll = await getSilverLogsCollection();
  const logs = (await coll
    .find({}, { sort: { run_finished_at: 1 }, limit: 300 })
    .toArray()) as SilverLog[];

  const times: string[] = logs.map((l: any) => new Date(l.run_finished_at || l.run_started_at || Date.now()).toISOString());

  // Scrape
  const scrape = logs.length
    ? {
        inserted: logs.map((l: any) => num(l.scrape?.inserted)),
        updated: logs.map((l: any) => num(l.scrape?.updated)),
      }
    : undefined;

  // Enrichment priorities (1..5)
  function seriesFromKey(key: string) {
    return logs.map((l: any) => num(l.enrich?.priority_counts?.[key]));
  }
  const enrich = logs.length
    ? {
        "1": seriesFromKey("1"),
        "2": seriesFromKey("2"),
        "3": seriesFromKey("3"),
        "4": seriesFromKey("4"),
        "5": seriesFromKey("5"),
      }
    : undefined;

  const claims = logs.length
    ? {
        "1": logs.map((l: any) => num(l.claims?.priority_counts?.["1"])),
        "2": logs.map((l: any) => num(l.claims?.priority_counts?.["2"])),
        "3": logs.map((l: any) => num(l.claims?.priority_counts?.["3"])),
        "4": logs.map((l: any) => num(l.claims?.priority_counts?.["4"])),
        "5": logs.map((l: any) => num(l.claims?.priority_counts?.["5"])),
      }
    : undefined;

  // Updates by verdict and type
  const verdictKeys = Array.from(
    logs.reduce((acc: Set<string>, l: any) => {
      Object.keys(l.updates?.by_verdict || {}).forEach((k) => acc.add(k));
      return acc;
    }, new Set<string>())
  );
  const updatesByVerdict = verdictKeys.length
    ? verdictKeys.reduce((obj: Record<string, number[]>, key: string) => {
        obj[key] = logs.map((l: any) => num(l.updates?.by_verdict?.[key]));
        return obj;
      }, {})
    : undefined;

  const typeKeys = Array.from(
    logs.reduce((acc: Set<string>, l: any) => {
      Object.keys(l.updates?.by_type || {}).forEach((k) => acc.add(k));
      return acc;
    }, new Set<string>())
  );
  const updatesByType = typeKeys.length
    ? typeKeys.reduce((obj: Record<string, number[]>, key: string) => {
        obj[key] = logs.map((l: any) => num(l.updates?.by_type?.[key]));
        return obj;
      }, {})
    : undefined;

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="dateline mb-1">Internal metrics over time</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          Site Statistics
        </h1>
        <hr className="mt-4" />
        {logs.length === 0 ? (
          <p className="mt-6 text-foreground/70">No logs found.</p>
        ) : (
          <div className="mt-6">
            <StatsCharts
              data={{
                times,
                scrape,
                enrich,
                claims,
                updatesByVerdict,
                updatesByType,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
