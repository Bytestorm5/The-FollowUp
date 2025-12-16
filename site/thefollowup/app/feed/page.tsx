import { getBronzeCollection, type BronzeLink } from "@/lib/mongo";
import Pagination from "@/components/Pagination";
import Link from "next/link";

export const dynamic = "force-dynamic";

function fmtDate(d: Date | string | undefined): string {
  if (!d) return "";
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    timeZone: "UTC", // treat stored date as date-only (00:00 UTC)
  }).format(date);
}

function getDomain(url: string): string | null {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

export default async function FeedPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const page = Math.max(1, parseInt(String(sp?.page ?? "1"), 10) || 1);
  const pageSize = Math.min(
    100,
    Math.max(5, parseInt(String(sp?.pageSize ?? "20"), 10) || 20)
  );
  const skip = (page - 1) * pageSize;

  let items: BronzeLink[] = [];
  let total = 0;
  let mongoError: string | null = null;

  try {
    const coll = await getBronzeCollection();
    const cursor = coll
      .find({}, { sort: { date: -1, inserted_at: -1 }, skip, limit: pageSize })
      .map((d) => d as BronzeLink);
    items = await cursor.toArray();
    total = await coll.countDocuments({});
  } catch (e: any) {
    mongoError = e?.message ?? "Unknown Mongo error";
  }

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-4xl px-4 py-10">
        <header className="mb-8">
          <div className="dateline mb-1">Bronze links · {total} total</div>
          <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
            Feed
          </h1>
          <hr className="mt-4" />
        </header>

        {mongoError ? (
          <div className="rounded-md border border-red-200 bg-red-50 p-4 text-red-800">
            <div className="font-medium">Cannot load Mongo data</div>
            <div className="text-sm opacity-90">
              {mongoError}. Set <code>MONGO_URI</code> (and optional <code>MONGO_DB</code>) in your env.
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            {items.map((it) => {
              const domain = it.link ? getDomain(it.link) : null;
              return (
                <article
                  key={(it as any)._id?.toString?.() ?? `${it.link}-${it.date}`}
                  className="card border border-[var(--color-border)] p-4"
                >
                  <div className="flex items-baseline justify-between gap-4">
                    <div className="text-sm text-[var(--color-status-pending)]">{fmtDate(it.date as any)}</div>
                    {domain && (
                      <div className="text-xs text-[var(--color-status-pending)]">{domain}</div>
                    )}
                  </div>
                  <h2 className="mt-1 text-xl font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>
                    <Link href={it.link} target="_blank" className="hover:underline">
                      {it.title}
                    </Link>
                  </h2>
                  {it.tags && it.tags.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {it.tags.map((t, i) => (
                        <span
                          key={`${t}-${i}`}
                          className="rounded-full border border-[var(--color-border)] px-2 py-1 text-xs text-foreground/80"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}

        {/* Pagination */}
        {!mongoError && (
          <Pagination basePath="/feed" page={page} pageSize={pageSize} total={total} />
        )}
      </div>
    </div>
  );
}
