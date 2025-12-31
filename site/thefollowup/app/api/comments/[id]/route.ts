export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldCommentsCollection, ObjectId } from "@/lib/mongo";

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id } = await ctx.params;
  const coll = await getGoldCommentsCollection();
  const body = await req.json().catch(() => ({}));
  const { text, reaction } = body || {} as { text?: string; reaction?: 1 | -1 | 0 };
  // Support both ObjectId and string _id just in case
  let oid: ObjectId | null = null; try { oid = new ObjectId(id); } catch {}
  const doc = await coll.findOne({ $or: [ ...(oid ? [{ _id: oid } as any] : []), { _id: id as any } ] } as any);
  if (!doc) return NextResponse.json({ error: "Not found" }, { status: 404 });
  if (text && doc.user_id !== userId) return NextResponse.json({ error: "Forbidden" }, { status: 403 });

  const update: any = {};
  if (typeof text === "string") {
    update.$set = { ...(update.$set || {}), text: text.slice(0, 5000), updated_at: new Date() };
  }
  if (reaction !== undefined) {
    const prev = (doc as any).reactions_by?.[userId] as 1 | -1 | undefined;
    const next = reaction === 0 ? undefined : reaction; // 0 clears reaction
    const likes = (doc.likes || 0) - (prev === 1 ? 1 : 0) + (next === 1 ? 1 : 0);
    const dislikes = (doc.dislikes || 0) - (prev === -1 ? 1 : 0) + (next === -1 ? 1 : 0);
    const reactions_by = { ...(doc.reactions_by || {}) } as Record<string, 1 | -1>;
    if (next === undefined) delete reactions_by[userId]; else reactions_by[userId] = next;
    update.$set = { ...(update.$set || {}), likes, dislikes, reactions_by };
  }
  if (!update.$set) return NextResponse.json({ ok: true });
  await coll.updateOne({ $or: [ ...(oid ? [{ _id: oid } as any] : []), { _id: id as any } ] } as any, update);
  const fresh = await coll.findOne({ $or: [ ...(oid ? [{ _id: oid } as any] : []), { _id: id as any } ] } as any);
  return NextResponse.json({ item: fresh });
}

export async function DELETE(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const { id } = await ctx.params;
  const coll = await getGoldCommentsCollection();
  let oid: ObjectId | null = null; try { oid = new ObjectId(id); } catch {}
  const doc = await coll.findOne({ $or: [ ...(oid ? [{ _id: oid } as any] : []), { _id: id as any } ] } as any);
  if (!doc) return NextResponse.json({ error: "Not found" }, { status: 404 });
  if ((doc as any).user_id !== userId) return NextResponse.json({ error: "Forbidden" }, { status: 403 });
  await coll.deleteOne({ $or: [ ...(oid ? [{ _id: oid } as any] : []), { _id: id as any } ] } as any);
  return NextResponse.json({ ok: true });
}
