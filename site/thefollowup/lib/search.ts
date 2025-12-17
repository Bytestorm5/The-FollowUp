import { getSilverClaimsCollection, getSilverUpdatesCollection } from "./mongo";

export function parseISODate(value?: string | string[]): Date | null {
  if (!value) return null;
  const s = Array.isArray(value) ? value[0] : value;
  const t = s?.trim();
  if (!t) return null;
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? null : d;
}

export async function searchClaimIdsByText(q: string): Promise<Set<string>> {
  const indexName = process.env.MONGO_SEARCH_INDEX || "default";
  const ids = new Set<string>();
  if (!q || !q.trim()) return ids;
  try {
    const claimsColl = await getSilverClaimsCollection();
    const updatesColl = await getSilverUpdatesCollection();

    const claimMatches = await claimsColl
      .aggregate([
        { $search: { index: indexName, text: { query: q, path: ["claim", "verbatim_claim"], fuzzy: {}, matchCriteria: "any" } } },
        { $project: { _id: 1 } },
      ])
      .toArray();

    const updateMatches = await updatesColl
      .aggregate([
        { $search: { index: indexName, text: { query: q, path: ["model_output", "claim_text"], fuzzy: {}, matchCriteria: "any" } } },
        { $project: { claim_id: 1 } },
        { $group: { _id: "$claim_id" } },
      ])
      .toArray();

    for (const d of claimMatches) ids.add(String(d._id));
    for (const d of updateMatches) ids.add(String(d._id));
  } catch {
    // If Atlas Search is not enabled, let caller fallback to substring matching
  }
  return ids;
}
