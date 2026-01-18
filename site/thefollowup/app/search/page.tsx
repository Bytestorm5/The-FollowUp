import Link from "next/link";
import {
  getBronzeCollection,
  getSilverClaimsCollection,
  getSilverUpdatesCollection,
  getSilverRoundupsCollection,
  type BronzeLink,
  type SilverClaim,
  type SilverUpdate,
  type SilverRoundupDoc,
  ObjectId,
} from "@/lib/mongo";
import { searchClaimIdsByText } from "@/lib/search";
import AdsenseAd from "@/components/AdSenseAd";
import { stripInlineMarkdown } from "@/lib/text";

export const dynamic = "force-dynamic";

function displayHeadline(article: BronzeLink | null | undefined): string {
  if (!article) return "";
  const nh = (article as any).neutral_headline;
  if (typeof nh === "string" && nh.trim()) return stripInlineMarkdown(nh);
  return stripInlineMarkdown((article as any).title || "");
}

function displayClaimHeadline(claim: SilverClaim | null | undefined): string {
  if (!claim) return "";
  const nh = (claim as any).neutral_headline;
  if (typeof nh === "string" && nh.trim()) return stripInlineMarkdown(nh);
  return stripInlineMarkdown((claim as any).claim || "");
}

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
  let articles: (BronzeLink & { score?: number })[] = [];
  try {
    articles = (await bronze
      .aggregate< BronzeLink & { score?: number } >([
        {
          $search: {
            index: indexName,
            text: {
              query: q,
              path: [
                "title",
                "neutral_headline",
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
        { $project: { title: 1, neutral_headline: 1, date: 1, link: 1, summary_paragraph: 1, score: { $meta: "searchScore" } } },
        { $sort: { score: -1, date: -1 } },
        { $limit: 20 },
      ])
      .toArray()) as (BronzeLink & { score?: number })[];
  } catch {
    // Fallback regex search if Atlas Search index missing
    articles = (await bronze
      .find({ $or: [
        { title: { $regex: q, $options: "i" } },
        { neutral_headline: { $regex: q, $options: "i" } },
        { clean_markdown: { $regex: q, $options: "i" } },
        { raw_content: { $regex: q, $options: "i" } },
        { summary_paragraph: { $regex: q, $options: "i" } },
        { key_takeaways: { $regex: q, $options: "i" } },
      ] })
      .project({ title: 1, neutral_headline: 1, date: 1, link: 1, summary_paragraph: 1 })
      .sort({ date: -1 })
      .limit(20)
      .toArray()) as (BronzeLink & { score?: number })[];
  }

  // Fetch roundup results via Atlas Search (title + body)
  const roundupsColl = await getSilverRoundupsCollection();
  let roundups: (SilverRoundupDoc & { score?: number })[] = [];
  try {
    roundups = (await roundupsColl
      .aggregate< SilverRoundupDoc & { score?: number } >([
        {
          $search: {
            index: indexName,
            text: {
              query: q,
              path: ["title", "summary_markdown"],
              fuzzy: {},
              matchCriteria: "any",
            },
          },
        },
        { $project: { title: 1, period_start: 1, period_end: 1, slug: 1, roundup_type: 1, score: { $meta: "searchScore" } } },
        { $sort: { score: -1, period_end: -1 } },
        { $limit: 10 },
      ])
      .toArray()) as any;
  } catch {
    // Fallback regex search if Atlas Search index missing
    roundups = (await roundupsColl
      .find({ $or: [
        { title: { $regex: q, $options: "i" } },
        { summary_markdown: { $regex: q, $options: "i" } },
      ] })
      .project({ title: 1, period_start: 1, period_end: 1, slug: 1, roundup_type: 1 })
      .sort({ period_end: -1 })
      .limit(10)
      .toArray()) as any;
  }

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
          {/* Articles + Roundups column */}
          <div>
            <div className="dateline mb-1">Articles & Roundups</div>
            {(() => {
              // Merge and sort by score desc, then recency
              const merged = [
                ...articles.map((a) => ({ kind: "article" as const, score: (a as any).score ?? 0, when: new Date((a as any).date as any).getTime() || 0, a })),
                ...roundups.map((r) => ({ kind: "roundup" as const, score: (r as any).score ?? 0, when: new Date((r as any).period_end as any).getTime() || 0, r })),
              ].sort((x, y) => (y.score - x.score) || (y.when - x.when)).slice(0, 20);

              if (merged.length === 0) {
                return <p className="text-foreground/70 text-sm">No results found.</p>;
              }
              return (
                <ul className="space-y-4">
                  {merged.map((m, i) => {
                    if (m.kind === "article") {
                      const a = m.a as any;
                      return (
                        <li key={`a-${String(a._id)}`} className="card border border-[var(--color-border)] p-4">
                          <Link href={`/article/${a.slug || String(a._id)}`} className="text-lg font-semibold hover:underline" style={{ fontFamily: "var(--font-serif)" }}>
                            {displayHeadline(a as any)}
                          </Link>
                          {a.summary_paragraph && (
                            <div className="mt-1 text-sm text-foreground/80 line-clamp-3">{stripInlineMarkdown(a.summary_paragraph)}</div>
                          )}
                          <div className="mt-2 text-xs text-foreground/60">{new Date(a.date as any).toLocaleDateString()}</div>
                        </li>
                      );
                    }
                    const r = (m as any).r as SilverRoundupDoc;
                    return (
                      <li key={`r-${String((r as any)._id)}`} className="card border border-[var(--color-border)] p-4">
                        <div className="mb-1 text-xs text-foreground/70">Roundup • {String((r as any).roundup_type).toUpperCase()}</div>
                        <Link href={`/roundups/${(r as any).slug || String((r as any)._id)}`} className="text-lg font-semibold hover:underline" style={{ fontFamily: "var(--font-serif)" }}>
                          {r.title}
                        </Link>
                        <div className="mt-2 text-xs text-foreground/60">{new Date(r.period_start as any).toLocaleDateString()} – {new Date(r.period_end as any).toLocaleDateString()}</div>
                      </li>
                    );
                  })}
                </ul>
              );
            })()}
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
                        {displayClaimHeadline(c as any)}
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
