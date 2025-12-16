import Link from "next/link";
import { notFound } from "next/navigation";
import { getBronzeCollection, getSilverClaimsCollection, ObjectId, type BronzeLink, type SilverClaim } from "@/lib/mongo";

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

        <section className="mt-6">
          <h2 className="text-lg font-semibold">Related items</h2>
          {claims.length === 0 ? (
            <p className="mt-2 text-foreground/70">No extracted claims yet.</p>
          ) : (
            <ul className="mt-3 list-disc space-y-3 pl-5">
              {claims.map((c) => (
                <li key={(c as any)._id?.toString?.() ?? c.claim} className="leading-relaxed">
                  <span className="mr-2 rounded-full border px-2 py-0.5 text-xs uppercase tracking-wide text-foreground/80">
                    {typeLabel(c.type)}
                  </span>
                  <span className="font-medium">{c.claim}</span>
                  {c.completion_condition_date && (
                    <span className="text-foreground/80"> — {c.completion_condition_date.toString()}</span>
                  )}
                  {c.completion_condition_date && (
                    <span className="ml-2 text-[var(--color-status-pending)]">(
                      due {fmtDateUTC(c.completion_condition_date as any)})</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

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
      </div>
    </div>
  );
}
