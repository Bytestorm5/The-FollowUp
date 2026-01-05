import Link from "next/link";
import { getSilverRoundupsCollection, type SilverRoundupDoc, ObjectId } from "@/lib/mongo";

export const dynamic = "force-dynamic";

async function getLatestByType(): Promise<Partial<Record<"daily"|"weekly"|"monthly"|"yearly", SilverRoundupDoc | null>>> {
  const coll = await getSilverRoundupsCollection();
  const types: Array<"daily"|"weekly"|"monthly"|"yearly"> = ["yearly", "monthly", "weekly", "daily"]; // fetch all
  const res: Partial<Record<string, SilverRoundupDoc | null>> = {};
  await Promise.all(types.map(async (t) => {
    const doc = await coll.find({ roundup_type: t }).sort({ period_end: -1 }).limit(1).toArray();
    (res as any)[t] = doc[0] || null;
  }));
  return res as any;
}

async function getRecent(limit = 20): Promise<SilverRoundupDoc[]> {
  const coll = await getSilverRoundupsCollection();
  return await coll.find({}).sort({ period_end: -1 }).limit(limit).toArray();
}

function label(kind: string): string {
  return kind === "daily" ? "Daily" : kind === "weekly" ? "Weekly" : kind === "monthly" ? "Monthly" : kind === "yearly" ? "Yearly" : kind;
}

export default async function RoundupsPage() {
  const latestByType = await getLatestByType();
  const recent = await getRecent(30);

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-5xl px-4 py-6">
        <h1 className="mb-4 text-3xl font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>Roundups</h1>

        {/* Featured latest by window */}
        <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {(["yearly","monthly","weekly","daily"] as const).map((k) => {
            const r = latestByType[k];
            return (
              <article key={k} className="rounded-md border border-[var(--color-border)] p-4">
                <div className="mb-1 text-xs text-foreground/70">{label(k)}</div>
                {!r ? (
                  <div className="text-sm text-foreground/60">Not available yet.</div>
                ) : (
                  <>
                    <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-serif)" }}>
                      <Link href={`/roundups/${(r as any).slug || (r as any)._id?.toString?.()}`}>{r.title}</Link>
                    </h2>
                    <div className="mt-1 text-xs text-foreground/60">
                      {new Date(r.period_start as any).toLocaleDateString()} – {new Date(r.period_end as any).toLocaleDateString()}
                    </div>
                  </>
                )}
              </article>
            );
          })}
        </section>

        {/* Recent feed */}
        <section className="mt-6">
          <h2 className="mb-2 text-xl font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Recent</h2>
          <div className="space-y-3">
            {recent.map((r) => (
              <article key={(r as any)._id?.toString?.()} className="rounded-md border border-[var(--color-border)] p-3">
                <div className="mb-1 text-xs text-foreground/70">{label(r.roundup_type)} • {new Date(r.period_start as any).toLocaleDateString()} – {new Date(r.period_end as any).toLocaleDateString()}</div>
                <h3 className="text-base font-semibold">
                  <Link href={`/roundups/${(r as any).slug || (r as any)._id?.toString?.()}`} className="hover:underline">{r.title}</Link>
                </h3>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
