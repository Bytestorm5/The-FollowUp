import Link from "next/link";
import Countdown from "@/components/Countdown";
import { getBronzeCollection, getSilverClaimsCollection, getSilverFollowupsCollection, getSilverRoundupsCollection, type BronzeLink, type SilverClaim, type SilverFollowup, ObjectId, type SilverRoundupDoc } from "@/lib/mongo";
import AdsenseAd from "@/components/AdSenseAd";

function stripMarkdownLinks(text?: string | null): string {
  if (!text) return "";
  // Remove markdown links while keeping anchor text
  return text
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/<a[^>]*>(.*?)<\/a>/gi, "$1");
}

async function pickHeroAndMediumsByHeuristic(items: BronzeLink[], claimsColl: Awaited<ReturnType<typeof getSilverClaimsCollection>>, maxMediums = 6) {
  if (!items || items.length === 0) return { hero: undefined as any, mediums: [] as BronzeLink[] };

  // Build list of article ids (as strings) and count related claims in one query
  const idStrings = items
    .map((a: any) => {
      const raw = (a as any)._id;
      try { return raw?.toString?.() ?? String(raw); } catch { return String(raw); }
    })
    .filter(Boolean) as string[];

  const claims = await claimsColl
    .find({ article_id: { $in: idStrings as any[] } })
    .project({ article_id: 1 })
    .toArray();

  const claimCountByArticle = new Map<string, number>();
  for (const c of claims as any[]) {
    const k = String((c as any).article_id);
    claimCountByArticle.set(k, (claimCountByArticle.get(k) || 0) + 1);
  }

  const now = Date.now();
  const scored = items.map((a: any) => {
    const idStr = (() => { try { return a?._id?.toString?.() ?? String(a?._id); } catch { return String(a?._id); } })();
    const kt = Array.isArray(a.key_takeaways) ? a.key_takeaways.length : 0;
    const cc = claimCountByArticle.get(idStr) || 0;
    let pri = typeof a.priority === "number" ? a.priority : 5;
    pri = (5 - pri) + 1
    const d = new Date(a.date as any);
    const hours = Number.isNaN(d.getTime()) ? 0 : Math.max(0, (now - d.getTime()) / 36e5);
    const decay = Math.pow(0.4, hours / 24);
    const score = (kt + cc) * pri * decay;
    return { a: a as BronzeLink, score };
  });

  scored.sort((x, y) => y.score - x.score);
  const hero = scored[0]?.a as BronzeLink | undefined;
  const mediums = scored.slice(1, 1 + maxMediums).map(s => s.a);
  return { hero, mediums };
}

function asUTCStart(isoOrDate: any): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(d?.getTime?.())) return "";
  const y = d.getUTCFullYear(); const m = d.getUTCMonth(); const day = d.getUTCDate();
  return new Date(Date.UTC(y, m, day, 0, 0, 0)).toISOString();
}

function priorityLabel(p?: number | null): string | null {
  const v = typeof p === "number" ? p : null;
  if (v === 1) return "Active Emergency";
  if (v === 2) return "Breaking News";
  if (v === 3) return "Important News";
  if (v === 4) return "Niche News";
  if (v === 5) return "Operational Updates";
  return null;
}

export default async function Home() {
  // Fetch a pool of potential front-page articles
  const coll = await getBronzeCollection();
  const pool = (await coll
    .find({}, { sort: { inserted_at: -1 }, limit: 40 })
    .toArray()) as BronzeLink[];

  // Build compact countdowns (soon finishing) - and reuse claims collection for scoring
  const claimsColl = await getSilverClaimsCollection();
  const { hero, mediums } = await pickHeroAndMediumsByHeuristic(pool, claimsColl, 6);

  // Build compact countdowns (soon finishing)
  const followupsColl = await getSilverFollowupsCollection();
  const claims = (await claimsColl
    .find({ type: { $in: ["promise", "goal"] } })
    .project({ claim: 1, type: 1, completion_condition_date: 1, slug: 1 })
    .toArray()) as SilverClaim[];

  const ids = claims
    .map((c: any) => {
      try { return new ObjectId(String(c._id)); } catch { return String((c as any)._id); }
    })
    .filter(Boolean);

  const followups = (await followupsColl
    .find({ claim_id: { $in: ids as any[] } })
    .project({ claim_id: 1, follow_up_date: 1 })
    .toArray()) as SilverFollowup[];

  const earliestFollowupById = new Map<string, Date>();
  for (const f of followups) {
    const key = String((f as any).claim_id);
    const d = new Date((f as any).follow_up_date as any);
    if (!Number.isNaN(d.getTime())) {
      const prev = earliestFollowupById.get(key);
      if (!prev || d < prev) earliestFollowupById.set(key, d);
    }
  }

  const now = new Date();
  const countdowns = claims
    .map((c: any) => {
      const dueRaw = (c as any).completion_condition_date || earliestFollowupById.get(String(c._id));
      const dueISO = dueRaw ? asUTCStart(dueRaw) : "";
      return { id: String(c._id), slug: (c as any).slug || undefined, text: c.claim as string, dueISO };
    })
    .filter((r) => !!r.dueISO && new Date(r.dueISO).getTime() > now.getTime())
    .sort((a, b) => new Date(a.dueISO).getTime() - new Date(b.dueISO).getTime())
    .slice(0, 6);

  // Left sidebar: latest roundups (daily, weekly, monthly, yearly)
  const rcoll = await getSilverRoundupsCollection();
  const latestDaily = await rcoll.find({ roundup_type: "daily" }).sort({ period_end: -1 }).limit(1).toArray() as SilverRoundupDoc[];
  const latestWeekly = await rcoll.find({ roundup_type: "weekly" }).sort({ period_end: -1 }).limit(1).toArray() as SilverRoundupDoc[];
  const latestMonthly = await rcoll.find({ roundup_type: "monthly" }).sort({ period_end: -1 }).limit(1).toArray() as SilverRoundupDoc[];
  const latestYearly = await rcoll.find({ roundup_type: "yearly" }).sort({ period_end: -1 }).limit(1).toArray() as SilverRoundupDoc[];

  const leftRoundups: Array<{ label: string; item: SilverRoundupDoc | null }> = [
    { label: "Daily", item: latestDaily[0] || null },
    { label: "Weekly", item: latestWeekly[0] || null },
    { label: "Monthly", item: latestMonthly[0] || null },
    { label: "Yearly", item: latestYearly[0] || null },
  ];

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-7xl px-4 py-6">
        <div className="grid gap-6 lg:grid-cols-9">
          {/* Left sidebar: Roundups */}
          <aside className="space-y-4 hidden lg:block lg:col-span-2">
            <div className="rounded-md border border-[var(--color-border)] p-3">
              <div className="mb-2 text-sm font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Roundups</div>
              <ul className="space-y-2 text-sm">
                {leftRoundups.map((r, idx) => (
                  <li key={idx} className="border-b border-[var(--color-border)] pb-2 last:border-b-0 last:pb-0">
                    {!r.item ? (
                      <div className="text-foreground/60">{r.label}: Not available</div>
                    ) : (
                      <div>
                        <div className="text-foreground/70 text-xs">{r.label}</div>
                        <Link href={`/roundups/${(r.item as any).slug || (r.item as any)._id?.toString?.()}`} className="hover:underline">
                          {r.item.title}
                        </Link>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            {/* Left sidebar ad slot */}
            <div className="rounded-md border border-dashed border-[var(--color-border)] p-6 text-center text-xs text-foreground/60">
              <AdsenseAd adSlot="3876912311"></AdsenseAd>
            </div>
          </aside>

          {/* Main content (hero + mediums) */}
          <div className="lg:col-span-5">
            {/* Hero article */}
            {hero && (
              <article className="card border border-[var(--color-border)] p-4">
                <div className="dateline mb-1">{new Date(hero.date as any).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" })}</div>
                {priorityLabel((hero as any).priority) && (
                  <div className="mb-2 inline-flex items-center gap-2 text-xs text-foreground/70">
                    <span className="rounded-full border px-2 py-0.5">{priorityLabel((hero as any).priority)}</span>
                  </div>
                )}
                <h2 className="text-3xl font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>
                  <Link href={`/article/${(hero as any).slug || (hero as any)._id?.toString?.()}`} className="hover:underline">
                    {hero.title}
                  </Link>
                </h2>
                {hero.summary_paragraph && (
                  <p className="mt-3 text-foreground/80 text-base">{stripMarkdownLinks(hero.summary_paragraph)}</p>
                )}
              </article>
            )}
            {/* Front-page ad below hero */}
            <div className="mt-4 rounded-md border border-dashed border-[var(--color-border)] p-3 text-center text-xs text-foreground/60">
              <AdsenseAd adSlot="8719936923"></AdsenseAd>
            </div>

            {/* Medium articles grid */}
            {mediums && mediums.length > 0 && (
              <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
                {mediums.map((m, i) => (
                  <article
                    key={(m as any)._id?.toString?.() || m.link}
                    className={`card border border-[var(--color-border)] p-3 ${
                      i >= 4 ? 'hidden lg:block' : i >= 2 ? 'hidden md:block sm:block' : ''
                    }`}
                  >
                    <div className="dateline mb-1 text-xs text-foreground/70">{new Date(m.date as any).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" })}</div>
                    {priorityLabel((m as any).priority) && (
                      <div className="mb-1 inline-flex items-center gap-2 text-[10px] text-foreground/70">
                        <span className="rounded-full border px-2 py-0.5">{priorityLabel((m as any).priority)}</span>
                      </div>
                    )}
                    <h3 className="text-lg font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>
                      <Link href={`/article/${(m as any).slug || (m as any)._id?.toString?.()}`} className="hover:underline">
                        {m.title}
                      </Link>
                    </h3>
                    {m.summary_paragraph && (
                      <p className="mt-2 line-clamp-3 text-sm text-foreground/80">{stripMarkdownLinks(m.summary_paragraph)}</p>
                    )}
                  </article>
                ))}
              </div>
            )}
            {/* Footer ad slot */}
            <div className="mt-6 rounded-md border border-dashed border-[var(--color-border)] p-3 text-center text-xs text-foreground/60">
              <AdsenseAd adSlot="4665141847" />
            </div>
          </div>

          {/* Right Sidebar: compact countdowns + ad slot */}
          <aside className="space-y-4 lg:col-span-2">
            <div className="rounded-md border border-[var(--color-border)] p-3">
              <div className="mb-2 text-sm font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Countdowns</div>
              {countdowns.length === 0 ? (
                <div className="text-sm text-foreground/60">No upcoming deadlines.</div>
              ) : (
                <ul className="space-y-2 text-sm">
                  {countdowns.map((c) => (
                    <li key={c.id} className="border-b border-[var(--color-border)] pb-2 last:border-b-0 last:pb-0">
                      <Link href={`/claim/${c.slug || c.id}`} className="hover:underline">
                        {c.text}
                      </Link>
                      <div className="text-accent"><Countdown targetISO={c.dueISO} /></div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {/* Sidebar ad slot */}
            <div className="rounded-md border border-dashed border-[var(--color-border)] p-6 text-center text-xs text-foreground/60">
              <AdsenseAd adSlot="6251161032"></AdsenseAd>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
