export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldTrafficCollection } from "@/lib/mongo";

export async function POST(req: NextRequest) {
  const { userId } = getAuth(req);
  // Only record for logged-in users
  if (!userId) return NextResponse.json({ ok: true });
  const body = await req.json().catch(() => ({}));
  const { postId, postType } = body || {};
  if (!postId || !postType) return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  const coll = await getGoldTrafficCollection();
  await coll.insertOne({ post_id: postId, post_type: String(postType), user_id: userId, entered_at: new Date() } as any);
  return NextResponse.json({ ok: true });
}
