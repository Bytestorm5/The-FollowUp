import type { MetadataRoute } from "next";
import { absUrl } from "@/lib/seo";
import { getBronzeCollection, getSilverClaimsCollection, getSilverRoundupsCollection } from "@/lib/mongo";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: absUrl("/"), changeFrequency: "hourly", priority: 1.0 },
    { url: absUrl("/feed"), changeFrequency: "hourly", priority: 0.9 },
    { url: absUrl("/search"), changeFrequency: "weekly", priority: 0.6 },
    { url: absUrl("/roundups"), changeFrequency: "daily", priority: 0.7 },
    { url: absUrl("/fact_checks"), changeFrequency: "daily", priority: 0.7 },
    { url: absUrl("/countdowns"), changeFrequency: "hourly", priority: 0.8 },
  ];

  const maxItems = 5000;

  // Articles
  const artColl = await getBronzeCollection();
  const articles = await artColl
    .find({}, { projection: { slug: 1 }, sort: { inserted_at: -1 } })
    .limit(maxItems)
    .toArray();

  const articleUrls: MetadataRoute.Sitemap = articles.map((a: any) => ({
    url: absUrl(`/article/${a.slug || String(a._id)}`),
    changeFrequency: "weekly",
    priority: 0.8,
  }));

  // Claims
  const claimsColl = await getSilverClaimsCollection();
  const claims = await claimsColl
    .find({}, { projection: { slug: 1 }, sort: { _id: -1 } })
    .limit(maxItems)
    .toArray();

  const claimUrls: MetadataRoute.Sitemap = claims.map((c: any) => ({
    url: absUrl(`/claim/${c.slug || String(c._id)}`),
    changeFrequency: "daily",
    priority: 0.7,
  }));

  // Roundups
  const rColl = await getSilverRoundupsCollection();
  const roundups = await rColl
    .find({}, { projection: { slug: 1 }, sort: { period_end: -1 } })
    .limit(maxItems)
    .toArray();

  const roundupUrls: MetadataRoute.Sitemap = roundups.map((r: any) => ({
    url: absUrl(`/roundups/${r.slug || String(r._id)}`),
    changeFrequency: "weekly",
    priority: 0.6,
  }));

  return [...staticRoutes, ...articleUrls, ...claimUrls, ...roundupUrls];
}
