export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldCommentsCollection, getGoldTrafficCollection } from "@/lib/mongo";

export async function POST(req: NextRequest) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const body = await req.json().catch(() => ({}));
  const scope: "comments" | "traffic" | "all" = body?.scope || "all";
  const ops: Promise<any>[] = [];
  if (scope === "comments" || scope === "all") {
    ops.push((await getGoldCommentsCollection()).deleteMany({ user_id: userId }));
  }
  if (scope === "traffic" || scope === "all") {
    ops.push((await getGoldTrafficCollection()).deleteMany({ user_id: userId }));
  }
  await Promise.all(ops);
  return NextResponse.json({ ok: true });
}
