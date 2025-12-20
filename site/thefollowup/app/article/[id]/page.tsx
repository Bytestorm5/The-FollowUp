import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { mapVerdictDisplay } from "@/lib/verdict";
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


export default async function ArticleDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let doc: BronzeLink | null = null;
  const coll = await getBronzeCollection();
  try {
    const oid = new ObjectId(id);
    doc = await coll.findOne({ _id: oid });
  } catch {
    // Try by slug, then by raw _id string
    doc = await coll.findOne({ slug: id as any }) || await coll.findOne({ _id: id as any });
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
    .project({ claim_id: 1, verdict: 1, created_at: 1, model_output: 1 })
    .sort({ created_at: -1, _id: -1 })
    .toArray()) as SilverUpdate[];
  const latestVerdictByClaim = new Map<string, string>();
  for (const u of updates) {
    const key = String(u.claim_id);
    if (!latestVerdictByClaim.has(key)) {
      const mo: any = (u as any).model_output;
      const v = (mo && typeof mo === 'object' && (mo as any).verdict) ? (mo as any).verdict : u.verdict;
      latestVerdictByClaim.set(key, String(v));
    }
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
                  <span className="mr-2 inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs uppercase tracking-wide text-foreground/80">
                    {(() => {
                      const v = latestVerdictByClaim.get(String((c as any)._id));
                      if (c.type === 'statement' && v) return v;
                      return typeLabel(c.type);
                    })()}
                    {/* Status icon inside badge based on latest verdict */}
                    {(() => {
                      const v = latestVerdictByClaim.get(String((c as any)._id));
                      if (!v) return null;
                      const d = mapVerdictDisplay(v);
                      return <span style={{ color: d.color }}>{d.icon}</span>;
                    })()}
                  </span>
                  <Link href={`/claim/${(c as any).slug || (c as any)._id?.toString?.()}`} className="font-medium hover:underline">
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
