import Link from "next/link";
import { getSilverClaimsCollection, getSilverFollowupsCollection, getSilverUpdatesCollection, type SilverClaim, type SilverFollowup, type SilverUpdate, ObjectId } from "@/lib/mongo";

export const dynamic = "force-dynamic";

function asUTCStart(isoOrDate: string | Date): string {
  const d = typeof isoOrDate === "string" ? new Date(isoOrDate) : isoOrDate;
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const day = d.getUTCDate();
  const utc = new Date(Date.UTC(y, m, day, 0, 0, 0));
  return utc.toISOString();
}

function fmtDate(d: Date | string | undefined) {
  if (!d) return "";
  const date = typeof d === "string" ? new Date(d) : d;
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", { year: "numeric", month: "short", day: "2-digit" }).format(date);
}

function typePriority(t: SilverClaim["type"]) {
  if (t === "promise") return 0;
  if (t === "goal") return 1;
  return 2;
}

export default async function PastCountdownsPage() {
  const claimsColl = await getSilverClaimsCollection();
  const followupsColl = await getSilverFollowupsCollection();
  const updatesColl = await getSilverUpdatesCollection();

  const claims = (await claimsColl
    .find({ type: { $in: ["promise", "goal"] } })
    .project({ claim: 1, type: 1, completion_condition: 1, completion_condition_date: 1 })
    .toArray()) as SilverClaim[];

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

  const rows = claims
    .map((c) => {
      const key = String((c as any)._id);
      const dueRaw = (c as any).completion_condition_date || followupByClaim.get(key);
      const due = dueRaw ? new Date(asUTCStart(dueRaw as any)) : null;
      const lu = latestUpdateByClaim.get(key);
      const eventDate = lu?.created_at ? new Date(lu.created_at as any) : due;
      const status = lu?.verdict ?? "in_progress";
      return { id: key, type: c.type, claim: c.claim, completion_condition: c.completion_condition, eventDate, status };
    })
    .filter((r) => r.eventDate && r.eventDate.getTime() <= now.getTime())
    .sort((a, b) => {
      const tp = typePriority(a.type) - typePriority(b.type);
      if (tp !== 0) return tp;
      return b.eventDate!.getTime() - a.eventDate!.getTime();
    });

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="dateline mb-1">Promises and goals with past deadlines or updates</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          Past Countdowns
        </h1>
        <hr className="mt-4" />

        {rows.length === 0 ? (
          <p className="mt-6 text-foreground/70">No past items.</p>
        ) : (
          <ul className="mt-6 space-y-4">
            {rows.map((r) => (
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
                <div className="mt-2 text-sm text-foreground/70">Date: {fmtDate(r.eventDate as any)}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
