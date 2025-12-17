import Link from "next/link";
import { getSilverClaimsCollection, getSilverUpdatesCollection, ObjectId, type SilverClaim, type SilverUpdate } from "@/lib/mongo";

export const dynamic = "force-dynamic";

function verdictLabel(v?: string) {
  if (v === "complete") return "True";
  if (v === "failed") return "False";
  return "Complicated";
}

function VerdictIcon({ verdict }: { verdict?: string }) {
  if (verdict === "complete")
    return (
      <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="var(--color-status-succeeded)"><path d="M16.704 5.29a1 1 0 0 1 .006 1.414l-7.25 7.333a1 1 0 0 1-1.438.006L3.29 9.99A1 1 0 1 1 4.71 8.57l3.03 3.016 6.544-6.613a1 1 0 0 1 1.42.317z"/></svg>
    );
  if (verdict === "failed")
    return (
      <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="var(--color-status-failed)"><path d="M11.414 10l3.536-3.536a1 1 0 0 0-1.414-1.414L10 8.586 6.464 5.05A1 1 0 1 0 5.05 6.464L8.586 10l-3.536 3.536a1 1 0 1 0 1.414 1.414L10 11.414l3.536 3.536a1 1 0 0 0 1.414-1.414L11.414 10z"/></svg>
    );
  return (
    <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="var(--color-status-technicality)"><path d="M10 2a1 1 0 0 1 .894.553l7 14A1 1 0 0 1 17 18H3a1 1 0 0 1-.894-1.447l7-14A1 1 0 0 1 10 2zm0 12a1 1 0 1 0 0 2 1 1 0 0 0 0-2zm-1-6v4a1 1 0 1 0 2 0V8a1 1 0 1 0-2 0z"/></svg>
  );
}

export default async function FactChecksPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const q = String(sp?.q ?? "").trim();
  const v = String(sp?.v ?? "").toLowerCase(); // "true" | "false" | "complicated" | ""
  const claimsColl = await getSilverClaimsCollection();
  const updatesColl = await getSilverUpdatesCollection();

  const statements = (await claimsColl
    .find({ type: "statement" })
    .project({ claim: 1, article_id: 1 })
    .toArray()) as SilverClaim[];

  const ids = statements.map((c: any) => {
    try { return new ObjectId(String(c._id)); } catch { return String(c._id); }
  });

  const updates = (await updatesColl
    .find({ claim_id: { $in: ids as any[] } })
    .project({ claim_id: 1, verdict: 1, created_at: 1, model_output: 1 })
    .sort({ created_at: -1, _id: -1 })
    .toArray()) as SilverUpdate[];

  const latestById = new Map<string, SilverUpdate>();
  for (const u of updates) {
    const key = String(u.claim_id);
    if (!latestById.has(key)) latestById.set(key, u);
  }

  const rows = statements
    .map((c: any) => {
      const lu = latestById.get(String(c._id));
      if (!lu) return null;
      // extract latest text for search
      const mo: any = (lu as any).model_output;
      const latestText: string | undefined = typeof mo === "string" ? mo : mo?.text;
      return { id: String(c._id), claim: c.claim, latest: lu, latestText };
    })
    .filter(Boolean) as { id: string; claim: string; latest: SilverUpdate; latestText?: string }[];

  // MongoDB Atlas Search (fuzzy) for q against claims and updates
  let idsBySearch: Set<string> | null = null;
  if (q) {
    try {
      const indexName = process.env.MONGO_SEARCH_INDEX || "default";
      const claimMatches = await (await getSilverClaimsCollection()).aggregate([
        {
          $search: {
            index: indexName,
            text: { query: q, path: ["claim", "verbatim_claim"], fuzzy: {}, matchCriteria: "any" },
          },
        },
        { $project: { _id: 1 } },
      ]).toArray();

      const updateMatches = await (await getSilverUpdatesCollection()).aggregate([
        {
          $search: {
            index: indexName,
            text: { query: q, path: ["model_output", "claim_text"], fuzzy: {}, matchCriteria: "any" },
          },
        },
        { $project: { claim_id: 1 } },
        { $group: { _id: "$claim_id" } },
      ]).toArray();

      idsBySearch = new Set<string>();
      for (const d of claimMatches) idsBySearch.add(String(d._id));
      for (const d of updateMatches) idsBySearch.add(String(d._id));
    } catch {
      // If Atlas Search isn't available, fall back to substring filtering below
      console.log("Atlas Search Failed")
      idsBySearch = null;
    }
  }
  // Apply filters
  const rowsFiltered = rows.filter((r) => {
    // verdict filter
    if (v) {
      const label = verdictLabel(r.latest.verdict).toLowerCase();
      if (label !== v) return false;
    }
    // if Atlas Search ran, constrain to those ids; otherwise, substring fallback
    if (q) {
      if (idsBySearch && idsBySearch.size > 0) {
        if (!idsBySearch.has(r.id)) return false;
      } else {
        const needle = q.toLowerCase();
        const hay1 = (r.claim || "").toLowerCase();
        const hay2 = (r.latestText || "").toLowerCase();
        if (!hay1.includes(needle) && !hay2.includes(needle)) return false;
      }
    }
    return true;
  });

  rowsFiltered.sort((a, b) => (new Date(b.latest.created_at as any).getTime() - new Date(a.latest.created_at as any).getTime()));

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="dateline mb-1">Statements with completed fact checks</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          Fact Checks
        </h1>
        <hr className="mt-4" />

        {/* Filters */}
        <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex flex-col">
            <label htmlFor="v" className="text-xs text-foreground/70">Verdict</label>
            <select id="v" name="v" defaultValue={v} className="rounded-md border px-2 py-1 text-sm">
              <option value="">All</option>
              <option value="true">True</option>
              <option value="complicated">Complicated</option>
              <option value="false">False</option>
            </select>
          </div>
          <div className="flex min-w-[200px] flex-1 flex-col">
            <label htmlFor="q" className="text-xs text-foreground/70">Search</label>
            <input id="q" name="q" defaultValue={q} placeholder="Search text..." className="w-full rounded-md border px-2 py-1 text-sm" />
          </div>
          <button type="submit" className="rounded-md border px-3 py-2 text-sm hover:bg-black/5">Apply</button>
          {(v || q) && (
            <Link href="/fact_checks" className="text-sm hover:underline">Reset</Link>
          )}
        </form>

        {rowsFiltered.length === 0 ? (
          <p className="mt-6 text-foreground/70">No fact checks yet.</p>
        ) : (
          <ul className="mt-6 space-y-4">
            {rowsFiltered.map((r) => (
              <li key={r.id} className="card border border-[var(--color-border)] p-4">
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-foreground/70">
                  <VerdictIcon verdict={r.latest.verdict} />
                  <span>{verdictLabel(r.latest.verdict)}</span>
                </div>
                <Link href={`/claim/${r.id}`} className="text-lg font-semibold hover:underline" style={{ fontFamily: "var(--font-serif)" }}>
                  {r.claim}
                </Link>
                <div className="mt-1 text-xs text-foreground/60">Updated {new Date(r.latest.created_at as any).toLocaleString()}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
