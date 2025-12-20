import Link from "next/link";
import { getSilverClaimsCollection, getSilverFollowupsCollection, getSilverUpdatesCollection, type SilverClaim, type SilverFollowup, type SilverUpdate, ObjectId } from "@/lib/mongo";
import Countdown from "@/components/Countdown";
import { parseISODate, searchClaimIdsByText } from "@/lib/search";
import AdsenseAd from "@/components/AdSenseAd";

export const dynamic = "force-dynamic";

function asUTCStart(isoOrDate: string | Date): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(d.getTime())) return "";
  // Treat as date-only at 00:00:00Z
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  const utc = new Date(Date.UTC(y, m, day, 0, 0, 0));
  return utc.toISOString();
}

function typePriority(t: SilverClaim["type"]) {
  if (t === "promise") return 0;
  if (t === "goal") return 1;
  return 2; // statements are excluded, but keep fallback
}

export default async function CountdownsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await searchParams;
  const q = String(sp?.q ?? "").trim();
  const from = parseISODate(sp?.from);
  const to = parseISODate(sp?.to);
  const claimsColl = await getSilverClaimsCollection();
  const followupsColl = await getSilverFollowupsCollection();
  const updatesColl = await getSilverUpdatesCollection();

  // Get only promises and goals
  const claims = (await claimsColl
    .find({ type: { $in: ["promise", "goal"] } })
    .project({ claim: 1, verbatim_claim: 1, type: 1, completion_condition: 1, completion_condition_date: 1, article_id: 1 })
    .toArray()) as SilverClaim[];

  // Map claim ids to followups to find a fallback next date
  const ids = claims
    .map((c) => {
      try {
        return new ObjectId((c as any)._id);
      } catch {
        return (c as any)._id;
      }
    })
    .filter(Boolean);

  const followups = (await followupsColl
    .find({ claim_id: { $in: ids as any[] } })
    .project({ claim_id: 1, follow_up_date: 1 })
    .toArray()) as SilverFollowup[];

  const followupByClaim = new Map<string, Date>();
  for (const f of followups) {
    const key = String(f.claim_id);
    const d = new Date(f.follow_up_date as any);
    if (!Number.isNaN(d.getTime())) {
      const prev = followupByClaim.get(key);
      if (!prev || d < prev) followupByClaim.set(key, d);
    }
  }

  // Latest update per claim (verdict + created_at)
  const updates = (await updatesColl
    .find({ claim_id: { $in: ids as any[] } })
    .project({ claim_id: 1, verdict: 1, created_at: 1 })
    .sort({ created_at: -1, _id: -1 })
    .toArray()) as SilverUpdate[];
  const latestUpdateByClaim = new Map<string, SilverUpdate>();
  for (const u of updates) {
    const key = String(u.claim_id);
    if (!latestUpdateByClaim.has(key)) latestUpdateByClaim.set(key, u);
  }

  const now = new Date();

  // Build list with due date selection, status, and filter future-only
  const rows = claims
    .map((c) => {
      const dueRaw = (c as any).completion_condition_date || followupByClaim.get(String((c as any)._id));
      const dueISO = dueRaw ? asUTCStart(dueRaw as any) : "";
      const lu = latestUpdateByClaim.get(String((c as any)._id));
      const status = lu?.verdict ?? "in_progress";
      return {
        id: String((c as any)._id),
        type: c.type,
        claim: c.claim,
        completion_condition: c.completion_condition,
        dueISO,
        status,
      };
    })
    .filter((r) => !!r.dueISO && new Date(r.dueISO).getTime() > now.getTime())
    .sort((a, b) => {
      const tp = typePriority(a.type) - typePriority(b.type);
      if (tp !== 0) return tp;
      return new Date(a.dueISO).getTime() - new Date(b.dueISO).getTime();
    });

  // Text search via Atlas Search (claims/updates) -> filter by claim id
  let idsBySearch: Set<string> | null = null;
  if (q) idsBySearch = await searchClaimIdsByText(q);

  const rowsFiltered = rows.filter((r) => {
    if (from && new Date(r.dueISO).getTime() < from.getTime()) return false;
    if (to && new Date(r.dueISO).getTime() > to.getTime()) return false;
    if (q) {
      if (idsBySearch && idsBySearch.size > 0) {
        if (!idsBySearch.has(r.id)) return false;
      } else {
        const needle = q.toLowerCase();
        const hay = (r.claim || "").toLowerCase();
        if (!hay.includes(needle)) return false;
      }
    }
    return true;
  });

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="dateline mb-1">Promises and goals ordered by urgency</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          Countdowns
        </h1>
        <hr className="mt-4" />

        {/* Filters */}
        <form method="get" className="mt-4 flex flex-wrap items-end gap-3">
          <div className="flex min-w-[200px] flex-1 flex-col">
            <label htmlFor="q" className="text-xs text-foreground/70">Search</label>
            <input id="q" name="q" defaultValue={q} placeholder="Search text..." className="w-full rounded-md border px-2 py-1 text-sm" />
          </div>
          <div className="flex flex-col">
            <label htmlFor="from" className="text-xs text-foreground/70">From</label>
            <input id="from" name="from" type="date" defaultValue={from ? from.toISOString().slice(0,10) : ""} className="rounded-md border px-2 py-1 text-sm" />
          </div>
          <div className="flex flex-col">
            <label htmlFor="to" className="text-xs text-foreground/70">To</label>
            <input id="to" name="to" type="date" defaultValue={to ? to.toISOString().slice(0,10) : ""} className="rounded-md border px-2 py-1 text-sm" />
          </div>
          <button type="submit" className="rounded-md border px-3 py-2 text-sm hover:bg-black/5">Apply</button>
          {(q || from || to) && (
            <Link href="/countdowns" className="text-sm hover:underline">Reset</Link>
          )}
        </form>

        {rowsFiltered.length === 0 ? (
          <p className="mt-6 text-foreground/70">No upcoming deadlines yet.</p>
        ) : (
          <ul className="mt-6 space-y-4">
            {rowsFiltered.map((r) => (
              <li key={r.id} className="card border border-[var(--color-border)] p-4">
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide text-foreground/70">
                  <span>{r.type}</span>
                  <span
                    className="rounded-full border px-2 py-0.5 lowercase"
                    style={{
                      color:
                        r.status === "complete"
                          ? "var(--color-status-succeeded)"
                          : r.status === "failed"
                          ? "var(--color-status-failed)"
                          : "var(--color-status-pending)",
                    }}
                  >
                    {r.status.replace("_", " ")}
                  </span>
                </div>
                <Link href={`/claim/${r.id}`} className="text-lg font-semibold hover:underline" style={{ fontFamily: "var(--font-serif)" }}>
                  {r.claim}
                </Link>
                {r.completion_condition && (
                  <div className="mt-1 text-sm text-foreground/80">{r.completion_condition}</div>
                )}
                <div className="mt-2 text-sm text-accent">
                  <Countdown targetISO={r.dueISO} />
                </div>
              </li>
            ))}
          </ul>
        )}
        {/* Footer ad slot */}
        <div className="mt-6 rounded-md border border-dashed border-[var(--color-border)] p-3 text-center text-xs text-foreground/60">
          <AdsenseAd adSlot="4665141847" />
        </div>
      </div>
    </div>
  );
}
