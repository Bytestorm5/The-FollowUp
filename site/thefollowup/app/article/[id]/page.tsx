import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getBronzeCollection, getSilverClaimsCollection, getSilverUpdatesCollection, ObjectId, type BronzeLink, type SilverClaim, type SilverUpdate } from "@/lib/mongo";

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

function typeLabel(t: SilverClaim["type"]) {
  if (t === "goal") return "Goal";
  if (t === "promise") return "Promise";
  return "Statement";
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

export default async function ArticleDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let doc: BronzeLink | null = null;
  const coll = await getBronzeCollection();
  try {
    const oid = new ObjectId(id);
    doc = await coll.findOne({ _id: oid });
  } catch {
    doc = await coll.findOne({ _id: id as any });
  }

  if (!doc) return notFound();

  const claimsColl = await getSilverClaimsCollection();
  let claims: SilverClaim[] = [];
  try {
    const filters: any[] = [{ article_id: id }];
    try {
      const oid = new ObjectId(id);
      filters.push({ article_id: oid });
    } catch {}
    const primary = await claimsColl.find({ $or: filters }).sort({ _id: 1 }).toArray();
    if (primary.length > 0) {
      claims = primary as SilverClaim[];
    } else if (doc.link) {
      const byLink = await claimsColl.find({ article_link: doc.link }).sort({ _id: 1 }).toArray();
      claims = byLink as SilverClaim[];
    }
  } catch {}

  // Fetch latest update verdict per claim for status icons/labels
  const updatesColl = await getSilverUpdatesCollection();
  const claimIds = claims.map((c: any) => {
    try { return new ObjectId(String(c._id)); } catch { return String((c as any)._id); }
  });
  const updates = (await updatesColl
    .find({ claim_id: { $in: claimIds as any[] } })
    .project({ claim_id: 1, verdict: 1, created_at: 1 })
    .sort({ created_at: -1, _id: -1 })
    .toArray()) as SilverUpdate[];
  const latestVerdictByClaim = new Map<string, string>();
  for (const u of updates) {
    const key = String(u.claim_id);
    if (!latestVerdictByClaim.has(key)) latestVerdictByClaim.set(key, u.verdict);
  }

  const domain = (() => {
    try {
      const u = new URL(doc!.link);
      return u.hostname.replace(/^www\./, "");
    } catch {
      return null;
    }
  })();

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="dateline mb-1">{fmtDateUTC(doc.date as any)}{domain ? ` · ${domain}` : ""}</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          {doc.title}
        </h1>
        <hr className="mt-4" />

        
        {claims.length !== 0 ? (
          <section className="mt-6">
            <ul className="mt-3 list-disc space-y-3 pl-5">
              {claims.map((c) => (
                <li key={(c as any)._id?.toString?.() ?? c.claim} className="leading-relaxed">
                  <span className="mr-2 rounded-full border px-2 py-0.5 text-xs uppercase tracking-wide text-foreground/80 inline-flex items-center gap-1">
                    {typeLabel(c.type)}
                    {/* Status icon inside badge based on latest verdict */}
                    {(() => {
                      const v = latestVerdictByClaim.get(String((c as any)._id));
                      if (!v) return null;
                      return <VerdictIcon verdict={v} />;
                    })()}
                  </span>
                  <Link href={`/claim/${(c as any)._id?.toString?.()}`} className="font-medium hover:underline">
                    {c.claim}
                  </Link>
                  {c.completion_condition_date && (
                    <span className="ml-2 text-[var(--color-status-pending)]">(
                      due {fmtDateUTC(c.completion_condition_date as any)})</span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ) : (<span></span>)}
        

        {/* Key takeaways */}
        {Array.isArray(doc.key_takeaways) && doc.key_takeaways.length > 0 && (
          <section className="mt-8">
            <h2 className="text-lg font-semibold">Key takeaways</h2>
            <ul className="mt-3 list-disc space-y-2 pl-6 text-sm">
              {doc.key_takeaways!.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </section>
        )}

        {/* Original link between takeaways and article text */}
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href={doc.link}
            target="_blank"
            className="rounded-md border px-3 py-2 text-sm hover:bg-black/5"
          >
            Read original article
          </Link>
          <Link href="/feed" className="rounded-md border px-3 py-2 text-sm hover:bg-black/5">
            Back to Feed
          </Link>
        </div>

        {/* Cleaned article text (Markdown) */}
        {doc.clean_markdown && (
          <section className="prose prose-neutral mt-8 max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.clean_markdown}</ReactMarkdown>
          </section>
        )}
      </div>
    </div>
  );
}
