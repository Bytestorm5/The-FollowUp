export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldTrafficCollection, getBronzeCollection, getSilverClaimsCollection, getSilverRoundupsCollection, ObjectId } from "@/lib/mongo";

function linkFor(type: string, id: string): string {
  if (type === "article") return `/article/${id}`;
  if (type === "claim" || type === "fact_check") return `/claim/${id}`;
  if (type === "roundup") return `/roundups/${id}`;
  return "/";
}

export async function GET(req: NextRequest) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { searchParams } = new URL(req.url);
  const limit = Math.min(parseInt(searchParams.get("limit") || "20", 10) || 20, 50);
  const cursor = searchParams.get("cursor");

  const coll = await getGoldTrafficCollection();
  const query: any = { user_id: userId };
  let cursorId: ObjectId | null = null;
  if (cursor) { try { cursorId = new ObjectId(cursor); query._id = { $lt: cursorId }; } catch {} }

  const raw = await coll.find(query).sort({ _id: -1 }).limit(limit + 1).toArray();
  const hasMore = raw.length > limit;
  const page = hasMore ? raw.slice(0, limit) : raw;

  const artIds: string[] = []; const claimIds: string[] = []; const roundupIds: string[] = [];
  for (const t of page as any[]) {
    const ty = t.post_type; const id = String(t.post_id);
    if (ty === "article") artIds.push(id);
    else if (ty === "claim" || ty === "fact_check") claimIds.push(id);
    else if (ty === "roundup") roundupIds.push(id);
  }
  function toObjectIds(ids: string[]): ObjectId[] { const out: ObjectId[] = []; for (const s of ids) { try { out.push(new ObjectId(s)); } catch {} } return out; }
  const [artDocs, claimDocs, roundupDocs] = await Promise.all([
    artIds.length ? (await getBronzeCollection()).find({ _id: { $in: toObjectIds(artIds) } } as any, { projection: { _id: 1, title: 1 } } as any).toArray() : [],
    claimIds.length ? (await getSilverClaimsCollection()).find({ _id: { $in: toObjectIds(claimIds) } } as any, { projection: { _id: 1, claim: 1 } } as any).toArray() : [],
    roundupIds.length ? (await getSilverRoundupsCollection()).find({ _id: { $in: toObjectIds(roundupIds) } } as any, { projection: { _id: 1, title: 1 } } as any).toArray() : [],
  ]);
  const titleMap = new Map<string, string>();
  for (const d of artDocs as any[]) titleMap.set(String(d._id), d.title || "Article");
  for (const d of claimDocs as any[]) titleMap.set(String(d._id), d.claim || "Claim");
  for (const d of roundupDocs as any[]) titleMap.set(String(d._id), d.title || "Roundup");

  const items = page.map((t: any) => ({
    id: String(t._id),
    postId: String(t.post_id),
    postType: String(t.post_type),
    href: linkFor(String(t.post_type), String(t.post_id)),
    title: titleMap.get(String(t.post_id)) || `${t.post_type} · ${String(t.post_id)}`,
    enteredAt: t.entered_at,
  }));

  const nextCursor = hasMore ? String(raw[limit]._id) : null;
  return NextResponse.json({ items, nextCursor });
}
