import Link from "next/link";
import Countdown from "@/components/Countdown";
import { getBronzeCollection, getSilverClaimsCollection, getSilverFollowupsCollection, type BronzeLink, type SilverClaim, type SilverFollowup, ObjectId } from "@/lib/mongo";
import AdsenseAd from "@/components/AdSenseAd";

function pickHeroAndMediums(items: BronzeLink[], maxMediums = 4) {
  // Sort by priority (1 highest), then date desc, then inserted_at desc
  const sorted = [...items].sort((a: any, b: any) => {
    const pa = a.priority ?? 5;
    const pb = b.priority ?? 5;
    if (pa !== pb) return pa - pb;
    const da = new Date(a.date as any).getTime();
    const db = new Date(b.date as any).getTime();
    if (db !== da) return db - da;
    return 0;
  });
  const hero = sorted[0];
  const mediums = sorted.slice(1, 1 + maxMediums);
  return { hero, mediums };
}

function asUTCStart(isoOrDate: any): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(d?.getTime?.())) return "";
  const y = d.getUTCFullYear(); const m = d.getUTCMonth(); const day = d.getUTCDate();
  return new Date(Date.UTC(y, m, day, 0, 0, 0)).toISOString();
}

export default async function Home() {
  // Fetch a pool of potential front-page articles
  const coll = await getBronzeCollection();
  const pool = (await coll
    .find({}, { sort: { inserted_at: -1 }, limit: 40 })
    .toArray()) as BronzeLink[];

  const { hero, mediums } = pickHeroAndMediums(pool, 6);

  // Build compact countdowns (soon finishing)
  const claimsColl = await getSilverClaimsCollection();
  const followupsColl = await getSilverFollowupsCollection();
  const claims = (await claimsColl
    .find({ type: { $in: ["promise", "goal"] } })
    .project({ claim: 1, type: 1, completion_condition_date: 1 })
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
      return { id: String(c._id), text: c.claim as string, dueISO };
    })
    .filter((r) => !!r.dueISO && new Date(r.dueISO).getTime() > now.getTime())
    .sort((a, b) => new Date(a.dueISO).getTime() - new Date(b.dueISO).getTime())
    .slice(0, 6);

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-6xl px-4 py-6">
        <div className="grid gap-6 lg:grid-cols-3">
          {/* Main content (hero + mediums) */}
          <div className="lg:col-span-2">
            {/* Hero article */}
            {hero && (
              <article className="card border border-[var(--color-border)] p-4">
                <div className="dateline mb-1">{new Date(hero.date as any).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" })}</div>
                <h2 className="text-3xl font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>
                  <Link href={`/article/${(hero as any).slug || (hero as any)._id?.toString?.()}`} className="hover:underline">
                    {hero.title}
                  </Link>
                </h2>
                {hero.summary_paragraph && (
                  <p className="mt-3 text-foreground/80 text-base">{hero.summary_paragraph}</p>
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
                    <h3 className="text-lg font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>
                      <Link href={`/article/${(m as any).slug || (m as any)._id?.toString?.()}`} className="hover:underline">
                        {m.title}
                      </Link>
                    </h3>
                    {m.summary_paragraph && (
                      <p className="mt-2 line-clamp-3 text-sm text-foreground/80">{m.summary_paragraph}</p>
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

          {/* Sidebar: compact countdowns + ad slot */}
          <aside className="space-y-4">
            <div className="rounded-md border border-[var(--color-border)] p-3">
              <div className="mb-2 text-sm font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Countdowns</div>
              {countdowns.length === 0 ? (
                <div className="text-sm text-foreground/60">No upcoming deadlines.</div>
              ) : (
                <ul className="space-y-2 text-sm">
                  {countdowns.map((c) => (
                    <li key={c.id} className="border-b border-[var(--color-border)] pb-2 last:border-b-0 last:pb-0">
                      <Link href={`/claim/${c.id}`} className="hover:underline">
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
