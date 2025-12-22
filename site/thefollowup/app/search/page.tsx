import Link from "next/link";
import {
  getBronzeCollection,
  getSilverClaimsCollection,
  getSilverUpdatesCollection,
  type BronzeLink,
  type SilverClaim,
  type SilverUpdate,
  ObjectId,
} from "@/lib/mongo";
import { searchClaimIdsByText } from "@/lib/search";
import AdsenseAd from "@/components/AdSenseAd";

export const dynamic = "force-dynamic";

export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const q = String(sp?.q ?? "").trim();

  // Render input-only if empty
  if (!q) {
    return (
      <div className="min-h-screen w-full bg-background text-foreground">
        <div className="mx-auto max-w-3xl px-4 py-8">
          <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
            Search
          </h1>
          <hr className="mt-4" />
          <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
            <div className="flex min-w-[280px] flex-1 flex-col">
              <label htmlFor="q" className="text-xs text-foreground/70">Search</label>
              <input id="q" name="q" placeholder="Search articles, promises, updates..." className="w-full rounded-md border px-2 py-1 text-sm" />
            </div>
            <button type="submit" className="rounded-md border px-3 py-2 text-sm hover:bg-black/5">Search</button>
          </form>
          <p className="mt-6 text-foreground/70 text-sm">Enter keywords to search across articles, promises/statements, and updates.</p>
        </div>
      </div>
    );
  }

  const indexName = process.env.MONGO_SEARCH_INDEX || "default";

  // Fetch article results via Atlas Search
  const bronze = await getBronzeCollection();
  const articles = (await bronze
    .aggregate< BronzeLink & { score?: number } >([
      {
        $search: {
          index: indexName,
          text: {
            query: q,
            path: [
              "title",
              "clean_markdown",
              "raw_content",
              "summary_paragraph",
              "key_takeaways",
            ],
            fuzzy: {},
            matchCriteria: "any",
          },
        },
      },
      { $project: { title: 1, date: 1, link: 1, summary_paragraph: 1, score: { $meta: "searchScore" } } },
      { $sort: { score: -1, date: -1 } },
      { $limit: 20 },
    ])
    .toArray()) as (BronzeLink & { score?: number })[];

  // Collect claim IDs by searching claims and updates
  const claimIdSet = await searchClaimIdsByText(q);
  let claimIds: (string | ObjectId)[] = Array.from(claimIdSet);

  // Convert to ObjectIds where possible
  claimIds = claimIds.map((id) => {
    try {
      return new ObjectId(id as string);
    } catch {
      return id;
    }
  });

  const claimsColl = await getSilverClaimsCollection();
  const updatesColl = await getSilverUpdatesCollection();

  // Fetch matched claims
  const claims = (await claimsColl
    .find({ _id: { $in: claimIds as any[] } })
    .project({ claim: 1, verbatim_claim: 1, type: 1, completion_condition: 1, completion_condition_date: 1 })
    .limit(40)
    .toArray()) as SilverClaim[];

  // Fetch latest update per claim for status badge
  const updates = (await updatesColl
    .find({ claim_id: { $in: claimIds as any[] } })
    .project({ claim_id: 1, verdict: 1, created_at: 1 })
    .sort({ created_at: -1, _id: -1 })
    .toArray()) as SilverUpdate[];

  const latestUpdateByClaim = new Map<string, SilverUpdate>();
  for (const u of updates) {
    const key = String(u.claim_id);
    if (!latestUpdateByClaim.has(key)) latestUpdateByClaim.set(key, u);
  }

  // Simple type priority for ordered display
  function typePriority(t: SilverClaim["type"]) {
    if (t === "promise") return 0;
    if (t === "goal") return 1;
    return 2;
  }

  const claimsSorted = [...claims].sort((a, b) => typePriority(a.type) - typePriority(b.type));

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-6xl px-4 py-8">
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          Search
        </h1>
        <hr className="mt-4" />

        <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex min-w-[280px] flex-1 flex-col">
            <label htmlFor="q" className="text-xs text-foreground/70">Search</label>
            <input id="q" name="q" defaultValue={q} placeholder="Search text..." className="w-full rounded-md border px-2 py-1 text-sm" />
          </div>
          <button type="submit" className="rounded-md border px-3 py-2 text-sm hover:bg-black/5">Search</button>
          {q && (
            <Link href="/search" className="text-sm hover:underline">Reset</Link>
          )}
        </form>

        <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2">
          {/* Articles column */}
          <div>
            <div className="dateline mb-1">Articles</div>
            {articles.length === 0 ? (
              <p className="text-foreground/70 text-sm">No articles found.</p>
            ) : (
              <ul className="space-y-4">
                {articles.map((a) => (
                  <li key={String((a as any)._id)} className="card border border-[var(--color-border)] p-4">
                    <Link href={`/article/${String((a as any)._id)}`} className="text-lg font-semibold hover:underline" style={{ fontFamily: "var(--font-serif)" }}>
                      {a.title}
                    </Link>
                    {a.summary_paragraph && (
                      <div className="mt-1 text-sm text-foreground/80 line-clamp-3">{a.summary_paragraph}</div>
                    )}
                    <div className="mt-2 text-xs text-foreground/60">{new Date(a.date as any).toLocaleDateString()}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Claims column */}
          <div>
            <div className="dateline mb-1">Promises / Statements</div>
            {claimsSorted.length === 0 ? (
              <p className="text-foreground/70 text-sm">No claims found.</p>
            ) : (
              <ul className="space-y-4">
                {claimsSorted.map((c) => {
                  const lu = latestUpdateByClaim.get(String((c as any)._id));
                  const status = (lu?.verdict ?? "in_progress").replace("_", " ");
                  return (
                    <li key={String((c as any)._id)} className="card border border-[var(--color-border)] p-4">
                      <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-foreground/70">
                        <span>{c.type}</span>
                        <span
                          className="rounded-full border px-2 py-0.5 lowercase"
                          style={{
                            color:
                              lu?.verdict === "complete"
                                ? "var(--color-status-succeeded)"
                                : lu?.verdict === "failed"
                                ? "var(--color-status-failed)"
                                : "var(--color-status-pending)",
                          }}
                        >
                          {status}
                        </span>
                      </div>
                      <Link href={`/claim/${String((c as any)._id)}`} className="text-lg font-semibold hover:underline" style={{ fontFamily: "var(--font-serif)" }}>
                        {c.claim}
                      </Link>
                      {c.completion_condition && (
                        <div className="mt-1 text-sm text-foreground/80">{c.completion_condition}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        {/* Footer ad slot */}
        <div className="mt-6 rounded-md border border-dashed border-[var(--color-border)] p-3 text-center text-xs text-foreground/60">
          <AdsenseAd adSlot="4665141847" />
        </div>
      </div>
    </div>
  );
}
