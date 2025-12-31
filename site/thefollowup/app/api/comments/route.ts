export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldCommentsCollection, ObjectId } from "@/lib/mongo";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const postId = searchParams.get("postId");
  const postType = searchParams.get("postType") || "";
  if (!postId) return NextResponse.json({ error: "Missing postId" }, { status: 400 });
  const coll = await getGoldCommentsCollection();
  const variants: any[] = [postId];
  try { variants.push(new ObjectId(postId)); } catch {}
  const items = await coll
    .find({ post_id: { $in: variants as any[] }, post_type: postType, $or: [{ held_for_review: { $exists: false } }, { held_for_review: false }] })
    .sort({ created_at: -1, _id: -1 })
    .toArray();
  return NextResponse.json({ items });
}

export async function POST(req: NextRequest) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const { postId, postType, text, displayName } = body || {};
  if (!postId || !postType || !text || typeof text !== "string") {
    return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  }
  const coll = await getGoldCommentsCollection();
  const doc = {
    post_id: postId,
    post_type: String(postType),
    user_id: userId,
    display_name: displayName || null,
    text: text.slice(0, 5000),
    created_at: new Date(),
    held_for_review: false,
    likes: 0,
    dislikes: 0,
    reactions_by: {},
  } as any;
  const res = await coll.insertOne(doc);
  return NextResponse.json({ insertedId: res.insertedId, item: { ...doc, _id: res.insertedId } });
}
