import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import Script from "next/script";
import Countdown from "@/components/Countdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getBronzeCollection, getSilverClaimsCollection, getSilverFollowupsCollection, getSilverUpdatesCollection, ObjectId, type SilverClaim, type SilverFollowup, type SilverUpdate } from "@/lib/mongo";
import AdsenseAd from "@/components/AdSenseAd";
import { absUrl } from "@/lib/seo";
import { getVerdictInfo } from "@/lib/factcheck";

export const dynamic = "force-dynamic";

function fmtDateUTC(d: Date | string | undefined): string {
  if (!d) return "";
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    timeZone: "UTC",
  }).format(date);
}

function asUTCStart(isoOrDate: string | Date): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  const utc = new Date(Date.UTC(y, m, day, 0, 0, 0));
  return utc.toISOString();
}

export default async function ClaimPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  const claimsColl = await getSilverClaimsCollection();
  let claim: SilverClaim | null = null;
  try {
    const oid = new ObjectId(id);
    claim = (await claimsColl.findOne({ _id: oid })) as SilverClaim | null;
  } catch {
    claim = (await claimsColl.findOne({ slug: id as any })) as SilverClaim | null;
    if (!claim) claim = (await claimsColl.findOne({ _id: id as any })) as SilverClaim | null;
  }

  if (!claim) return notFound();

  // Source article summary
  let sourceSummary: string | null = null;
  try {
    const artColl = await getBronzeCollection();
    const art = await artColl.findOne({ _id: (() => { try { return new ObjectId(String((claim as any).article_id)); } catch { return (claim as any).article_id; } })() as any });
    sourceSummary = (art as any)?.summary_paragraph ?? null;
    // Use article slug if present when linking
    (claim as any)._articleSlug = (art as any)?.slug;
  } catch {}

  // Fallback next update date from followups if no completion date
  let dueISO = "";
  if ((claim as any).completion_condition_date) {
    dueISO = asUTCStart((claim as any).completion_condition_date as any);
  } else {
    const claimIdStr = String((claim as any)._id);
    let claimIdObj: any = null; try { claimIdObj = new ObjectId(claimIdStr); } catch {}
    const claimIdVariants = [claimIdStr].concat(claimIdObj ? [claimIdObj] : []);
    const followups = await (await getSilverFollowupsCollection())
      .find({ claim_id: { $in: claimIdVariants as any[] } })
      .project({ follow_up_date: 1 })
      .sort({ follow_up_date: 1 })
      .limit(1)
      .toArray();
    if (followups.length > 0) {
      dueISO = asUTCStart(followups[0].follow_up_date as any);
    }
  }

  // Next scheduled update (future follow_up_date if any)
  let nextScheduledISO = "";
  const now = new Date();
  const followupsColl = await getSilverFollowupsCollection();
  const claimIdStr2 = String((claim as any)._id);
  let claimIdObj2: any = null; try { claimIdObj2 = new ObjectId(claimIdStr2); } catch {}
  const claimIdVariants2 = [claimIdStr2].concat(claimIdObj2 ? [claimIdObj2] : []);
  const nextFollowup = await followupsColl
    .find({ claim_id: { $in: claimIdVariants2 as any[] }, follow_up_date: { $gte: now } })
    .project({ follow_up_date: 1 })
    .sort({ follow_up_date: 1 })
    .limit(1)
    .toArray();
  if (nextFollowup.length > 0) nextScheduledISO = asUTCStart(nextFollowup[0].follow_up_date as any);

  // All scheduled followups (past and future, processed or not)
  const allFollowups = await followupsColl
    .find({ claim_id: { $in: claimIdVariants2 as any[] } })
    .project({ follow_up_date: 1, processed_at: 1 })
    .sort({ follow_up_date: 1 })
    .toArray();

  // Load generated updates, newest first
  const updatesColl = await getSilverUpdatesCollection();
  const idVariants = [claimIdStr2].concat(claimIdObj2 ? [claimIdObj2] : []);
  const updates = (await updatesColl
    .find({ claim_id: { $in: idVariants as any[] } })
    .sort({ created_at: -1, _id: -1 })
    .toArray()) as SilverUpdate[];
  const latest = updates[0];
  const updatesAsc = [...updates].reverse();

  // Build unified timeline events and sort by date desc (latest first)
  type TLItem = { kind: "article" | "update" | "scheduled" | "due"; date: Date; payload?: any };
  const timeline: TLItem[] = [];
  // Original article (date-only)
  if ((claim as any).article_date) {
    const ad = new Date(asUTCStart((claim as any).article_date as any));
    if (!Number.isNaN(ad.getTime())) timeline.push({ kind: "article", date: ad });
  }
  // Updates
  for (const u of updates) {
    const d = u.created_at ? new Date(u.created_at as any) : null;
    if (d && !Number.isNaN(d.getTime())) timeline.push({ kind: "update", date: d, payload: u });
  }
  // Scheduled followups (all)
  for (const f of allFollowups) {
    const d = (f as any).follow_up_date ? new Date((f as any).follow_up_date as any) : null;
    if (d && !Number.isNaN(d.getTime())) timeline.push({ kind: "scheduled", date: d, payload: f });
  }
  // Completion due milestone
  if (dueISO) {
    const dd = new Date(dueISO);
    if (!Number.isNaN(dd.getTime())) timeline.push({ kind: "due", date: dd });
  }

  timeline.sort((a, b) => b.date.getTime() - a.date.getTime());

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-8">
        {/* ClaimReview JSON-LD for statements */}
        {claim.type === "statement" && latest && (() => {
          const idStr = String((claim as any)._id);
          const url = absUrl(`/claim/${(claim as any).slug || idStr}`);
          const mo: any = (latest as any).model_output;
          const rawVerdict: string | undefined = (mo && typeof mo === 'object' && mo?.verdict) ? String(mo.verdict) : String((latest as any)?.verdict || "");
          const info = getVerdictInfo(rawVerdict);
          const alt = info?.label || "Unclear";
          const ratingValue = alt === "True" ? 5 : alt === "False" ? 1 : 3;
          const datePublished = (() => { try { return new Date((latest as any).created_at as any).toISOString(); } catch { return undefined; } })();
          const data = {
            '@context': 'https://schema.org',
            '@type': 'ClaimReview',
            url,
            datePublished,
            claimReviewed: (claim as any).claim,
            reviewRating: {
              '@type': 'Rating',
              ratingValue,
              worstRating: 1,
              bestRating: 5,
              alternateName: alt,
            },
            author: {
              '@type': 'Organization',
              name: 'The Follow Up',
            },
          } as any;
          return <Script id="ld-claimreview" type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
        })()}
        <div className="dateline mb-1">{claim.type.toUpperCase()}</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          {claim.claim}
        </h1>
        {latest && (() => {
          const mo: any = (latest as any).model_output;
          const rawVerdict: string | undefined = (mo && typeof mo === 'object' && mo?.verdict) ? String(mo.verdict) : String((latest as any)?.verdict || "");
          const info = getVerdictInfo(rawVerdict);
          if (!info) return null;
          return (
            <div className="mt-2">
              <div className="flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: info.color }}>
                {info.icon}
                <span>{info.label}</span>
              </div>
              <p className="mt-1 text-sm text-foreground/80">
                {info.explanation} {" "}
                <Link href="/about/methodology" className="underline decoration-dotted underline-offset-2">Learn more in Methodology</Link>.
              </p>
            </div>
          );
        })()}
        <hr className="mt-4" />

        {/* Mechanism pill if present */}
        {claim.mechanism && (
          <div className="mt-2">
            <span className="rounded-full border px-2 py-0.5 text-xs uppercase tracking-wide text-foreground/70">{claim.mechanism}</span>
          </div>
        )}

        {claim.completion_condition && (
          <p className="mt-4 text-foreground/80">{claim.completion_condition}</p>
        )}

        {/* Source summary paragraph */}
        {sourceSummary && (
          <div className="mt-4 rounded-md border border-[var(--color-border)] bg-white/60 p-3 text-sm text-foreground/80">
            <div className="mb-1 text-xs uppercase tracking-wide text-foreground/70">Source summary</div>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ p: ({ children }) => <>{children}</>, a: ({ href, children }) => <a href={href} className="underline">{children}</a> }}>
              {sourceSummary}
            </ReactMarkdown>
            <div className="mt-2 text-base italic">
              <Link href={`/article/${String((claim as any)._articleSlug || (claim as any).article_id)}`} className="hover:underline">View original article →</Link>
            </div>
          </div>
        )}

        {/* Latest fact check text (statements) */}
        {claim.type === "statement" && latest && (
          <div className="mt-4 rounded-md border border-[var(--color-border)] bg-white/60 p-3">
            <div className="mb-2 text-xs uppercase tracking-wide text-foreground/70">Latest fact check</div>
            {(() => {
              const mo = latest.model_output as any;
              const text: string | undefined = typeof mo === "string" ? mo : mo?.text;
              const sources: string[] | undefined = typeof mo === "object" && mo?.sources ? mo.sources : undefined;
              return (
                <div className="prose prose-neutral max-w-none text-sm">
                  {text ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown> : <p className="text-foreground/70">No details provided.</p>}
                  {sources && sources.length > 0 && (
                    <div className="mt-2">
                      <div className="text-xs font-medium">Sources</div>
                      <ul className="mt-1 list-disc pl-5">
                        {sources.map((s, i) => (
                          <li key={i}><a className="hover:underline" href={s} target="_blank" rel="noreferrer">{s}</a></li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              );
            })()}
          </div>
        )}

        {/* Mid-page ad slot */}
        <div className="mt-4 rounded-md border border-dashed border-[var(--color-border)] p-3 text-center text-xs text-foreground/60">
          <AdsenseAd adSlot="1318398556" format="fluid" layout="in-article" style={{ display: "block", textAlign: "center" }} />
        </div>

        {dueISO && (
          <div className="mt-4 text-sm text-accent">
            <Countdown targetISO={dueISO} />
          </div>
        )}

        {nextScheduledISO && (
          <div className="mt-2 text-sm text-foreground/80">
            Next scheduled update: {new Date(nextScheduledISO).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "2-digit" })}
            <div className="mt-1 text-accent">
              <Countdown targetISO={nextScheduledISO} />
            </div>
          </div>
        )}

        {/* Timeline */}
        <section className="mt-8">
          <h2 className="text-lg font-semibold">Timeline</h2>
          <ol className="timeline mt-4 pl-6">
            {timeline.map((ev, idx) => {
              const first = idx === 0;
              const last = idx === timeline.length - 1;
              const baseCls = ["timeline-item", first ? "first" : "", last ? "last" : ""].filter(Boolean).join(" ");
              if (ev.kind === "article") {
                return (
                  <li key={`art-${idx}`} className={baseCls}>
                    <span className="timeline-dot" />
                    <div className="text-sm text-foreground/70">Original article · {fmtDateUTC(ev.date as any)}</div>
                    <div className="mt-1">
                      <Link href={`/article/${String((claim as any)._articleSlug || (claim as any).article_id)}`} className="hover:underline">View article</Link>
                    </div>
                  </li>
                );
              }
              if (ev.kind === "update") {
                const u = ev.payload as SilverUpdate;
                const mo = u.model_output as any;
                const verdict: string | undefined = u.verdict || mo?.verdict;
                const text: string | undefined = typeof mo === "string" ? mo : mo?.text;
                const sources: string[] | undefined = typeof mo === "object" && mo?.sources ? mo.sources : undefined;
                return (
                  <li key={`upd-${(u as any)._id ?? idx}`} className={baseCls}>
                    <span className="timeline-dot" />
                    <div className="text-sm text-foreground/70">Update · {ev.date.toLocaleString("en-US", { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" })}
                      {verdict && (
                        <span className="ml-2 rounded-full border px-2 py-0.5 text-xs uppercase text-foreground/70">{verdict}</span>
                      )}
                    </div>
                    {text && <div className="mt-1 text-sm">{text}</div>}
                    {sources && sources.length > 0 && (
                      <ul className="mt-1 list-disc pl-5 text-sm">
                        {sources.map((s, i) => (
                          <li key={i}>
                            <a className="hover:underline" href={s} target="_blank" rel="noreferrer">{s}</a>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              }
              if (ev.kind === "scheduled") {
                const f = ev.payload as any;
                const isPast = ev.date.getTime() < now.getTime();
                const isUnprocessed = !f.processed_at;
                const itemCls = [baseCls, "scheduled", isPast && isUnprocessed ? "overdue" : ""].filter(Boolean).join(" ");
                const dotCls = ["timeline-dot", "scheduled", isPast && isUnprocessed ? "overdue" : ""].filter(Boolean).join(" ");
                return (
                  <li key={`sched-${idx}`} className={itemCls}>
                    <span className={dotCls} />
                    <div className="text-sm text-foreground/70">
                      Scheduled follow-up · {fmtDateUTC(ev.date as any)}
                      {isPast && isUnprocessed && (
                        <span className="ml-2 text-[var(--color-status-failed)]">overdue</span>
                      )}
                    </div>
                  </li>
                );
              }
              // due milestone
              const dueCls = [baseCls, "scheduled"].join(" ");
              return (
                <li key={`due-${idx}`} className={dueCls}>
                  <span className="timeline-dot scheduled" />
                  <div className="text-sm text-foreground/70">Completion due · {fmtDateUTC(ev.date as any)}</div>
                </li>
              );
            })}
          </ol>
        </section>

        <div className="mt-8 flex flex-wrap gap-3">
          <Link href="/countdowns" className="rounded-md border px-3 py-2 text-sm hover:bg-black/5">
            Back to Countdowns
          </Link>
        </div>
      </div>
    </div>
  );
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const claimsColl = await getSilverClaimsCollection();
  let claim: SilverClaim | null = null;
  try {
    const oid = new ObjectId(id);
    claim = (await claimsColl.findOne({ _id: oid })) as any;
  } catch {
    claim = (await claimsColl.findOne({ slug: id as any })) as any;
    if (!claim) claim = (await claimsColl.findOne({ _id: id as any })) as any;
  }
  if (!claim) return {};

  // source summary for description
  let sourceSummary: string | null = null;
  try {
    const artColl = await getBronzeCollection();
    const art = await artColl.findOne({ _id: (() => { try { return new ObjectId(String((claim as any).article_id)); } catch { return (claim as any).article_id; } })() as any });
    sourceSummary = (art as any)?.summary_paragraph ?? null;
  } catch {}

  const title = (claim as any).claim;
  const description = sourceSummary || (claim as any).completion_condition || "";
  const path = `/claim/${(claim as any).slug || String((claim as any)._id)}`;
  const url = absUrl(path);

  return {
    title,
    description,
    alternates: { canonical: path },
    openGraph: {
      type: "article",
      url,
      title,
      description,
    },
    twitter: { card: "summary", title, description },
  };
}
