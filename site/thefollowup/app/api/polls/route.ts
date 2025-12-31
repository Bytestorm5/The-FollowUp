export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldPollsCollection, ObjectId } from "@/lib/mongo";

export async function GET(req: NextRequest) {
  const { userId } = getAuth(req);
  const { searchParams } = new URL(req.url);
  const postId = searchParams.get("postId");
  const postType = searchParams.get("postType") || "";
  if (!postId) return NextResponse.json({ error: "Missing postId" }, { status: 400 });
  const coll = await getGoldPollsCollection();
  const variants: any[] = [postId];
  try { variants.push(new ObjectId(postId)); } catch {}
  const [interesting, support] = await Promise.all([
    coll.countDocuments({ post_id: { $in: variants as any[] }, post_type: postType, interesting_yes: true }),
    coll.countDocuments({ post_id: { $in: variants as any[] }, post_type: postType, support_yes: true }),
  ]);
  const [interestingTotal, supportTotal] = await Promise.all([
    coll.countDocuments({ post_id: { $in: variants as any[] }, post_type: postType, interesting_yes: { $in: [true, false] } }),
    coll.countDocuments({ post_id: { $in: variants as any[] }, post_type: postType, support_yes: { $in: [true, false] } }),
  ]);
  // Include this user's current vote, if logged in
  let myInteresting: boolean | null = null;
  let mySupport: boolean | null = null;
  if (userId) {
    const mine = await coll.findOne({ user_id: userId, post_id: { $in: variants as any[] }, post_type: postType } as any, { projection: { interesting_yes: 1, support_yes: 1 } } as any);
    if (mine) {
      if (typeof (mine as any).interesting_yes === "boolean") myInteresting = !!(mine as any).interesting_yes;
      if (typeof (mine as any).support_yes === "boolean") mySupport = !!(mine as any).support_yes;
    }
  }
  return NextResponse.json({ interesting, interestingTotal, support, supportTotal, myInteresting, mySupport });
}

export async function POST(req: NextRequest) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const { postId, postType, interesting, support } = body || {} as { postId?: string; postType?: string; interesting?: boolean; support?: boolean };
  if (!postId || !postType || (typeof interesting !== "boolean" && typeof support !== "boolean")) {
    return NextResponse.json({ error: "Missing fields" }, { status: 400 });
  }
  const coll = await getGoldPollsCollection();
  const set: any = { updated_at: new Date() };
  if (typeof interesting === "boolean") set.interesting_yes = !!interesting;
  if (typeof support === "boolean") set.support_yes = !!support;
  await coll.updateOne(
    { user_id: userId, post_id: postId, post_type: String(postType) } as any,
    { $set: set, $setOnInsert: { created_at: new Date() } },
    { upsert: true }
  );
  return NextResponse.json({ ok: true });
}
