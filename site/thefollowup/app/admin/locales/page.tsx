import { currentUser } from "@clerk/nextjs/server";
import path from "path";
import fs from "fs";
import { redirect } from "next/navigation";
import { getLocaleSubscriptionsCollection } from "@/lib/mongo";
import { buildLocaleKey, formatLocaleLabel, normalizeLocaleValue } from "@/lib/locales";

export const dynamic = "force-dynamic";

type ScrapeLocaleMetadata = {
  country?: string;
  province?: string;
  county?: string;
  subdivisions?: Record<string, string | null> | null;
  folder: string;
};

function loadScrapeLocaleMetadata(): ScrapeLocaleMetadata[] {
  const scrapeRoot = path.resolve(process.cwd(), "..", "..", "service", "scripts", "scrape");
  if (!fs.existsSync(scrapeRoot)) return [];

  const entries = fs.readdirSync(scrapeRoot, { withFileTypes: true });
  const locales: ScrapeLocaleMetadata[] = [];

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const folder = path.join(scrapeRoot, entry.name);
    const metaPath = path.join(folder, "locale.json");
    if (!fs.existsSync(metaPath)) continue;
    try {
      const raw = fs.readFileSync(metaPath, "utf-8");
      const json = JSON.parse(raw) as Omit<ScrapeLocaleMetadata, "folder">;
      locales.push({
        country: normalizeLocaleValue(json.country),
        province: normalizeLocaleValue(json.province),
        county: normalizeLocaleValue(json.county),
        subdivisions: json.subdivisions || null,
        folder: entry.name,
      });
    } catch (error) {
      console.warn(`Failed to read locale metadata for ${entry.name}`, error);
    }
  }

  return locales;
}

export default async function LocaleDashboardPage() {
  const user = await currentUser();
  const tier = user?.publicMetadata?.tier;
  if (!user || (tier !== "admin" && tier !== "moderator")) {
    redirect("/");
  }

  const locales = await getLocaleSubscriptionsCollection();
  const pending = await locales
    .aggregate([
      { $match: { active: true } },
      {
        $group: {
          _id: {
            country: "$location.country",
            province: "$location.province",
            county: "$location.county",
            subdivisions: "$location.subdivisions",
          },
          subscribers: { $sum: 1 },
          latest: { $max: "$updated_at" },
        },
      },
      {
        $sort: {
          subscribers: -1,
          "_id.country": 1,
          "_id.province": 1,
          "_id.county": 1,
        },
      },
    ])
    .toArray();

  const scrapeLocales = loadScrapeLocaleMetadata();
  const scrapeLocaleMap = new Map(
    scrapeLocales.map((locale) => [buildLocaleKey(locale), locale.folder]),
  );

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="space-y-2">
        <p className="text-xs uppercase tracking-[0.25em] text-primary">Admin</p>
        <h1 className="text-3xl font-semibold text-foreground" style={{ fontFamily: "var(--font-serif)" }}>
          Local coverage dashboard
        </h1>
        <p className="text-sm text-foreground/70">
          Track requested locales and confirm scraper folders before they go live. Each locale entry is deduplicated
          across supporters.
        </p>
      </div>

      <div className="mt-6 overflow-hidden rounded-lg border border-[var(--color-border)] bg-background/60">
        <table className="w-full text-sm">
          <thead className="bg-background/70 text-left text-xs uppercase tracking-wide text-foreground/60">
            <tr>
              <th className="px-4 py-3">Locale</th>
              <th className="px-4 py-3">Subscribers</th>
              <th className="px-4 py-3">Latest request</th>
              <th className="px-4 py-3">Scraper folder</th>
            </tr>
          </thead>
          <tbody>
            {pending.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-sm text-foreground/70" colSpan={4}>
                  No pending locale requests yet.
                </td>
              </tr>
            ) : (
              pending.map((row) => {
                const locale = {
                  country: row._id?.country,
                  province: row._id?.province,
                  county: row._id?.county,
                  subdivisions: row._id?.subdivisions,
                };
                const key = buildLocaleKey(locale);
                const scraperFolder = scrapeLocaleMap.get(key);
                const latest = row.latest ? new Date(row.latest).toLocaleString() : "Unknown";

                return (
                  <tr key={key} className="border-t border-[var(--color-border)]">
                    <td className="px-4 py-3 font-medium text-foreground">{formatLocaleLabel(locale)}</td>
                    <td className="px-4 py-3 text-foreground/80">{row.subscribers}</td>
                    <td className="px-4 py-3 text-foreground/70">{latest}</td>
                    <td className="px-4 py-3">
                      {scraperFolder ? (
                        <span className="rounded-full bg-green-100 px-2 py-1 text-xs font-semibold text-green-800">
                          {scraperFolder}
                        </span>
                      ) : (
                        <span className="rounded-full bg-yellow-100 px-2 py-1 text-xs font-semibold text-yellow-800">
                          Needs folder
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
