export const dynamic = "force-dynamic";
export const runtime = "nodejs";
import { NextResponse, type NextRequest } from "next/server";
import { getAuth } from "@clerk/nextjs/server";
import { getGoldCommentsCollection, getGoldTrafficCollection } from "@/lib/mongo";

export async function GET(req: NextRequest) {
  const { userId } = getAuth(req);
  if (!userId) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const [comments, traffic] = await Promise.all([
    (await getGoldCommentsCollection()).find({ user_id: userId }).toArray(),
    (await getGoldTrafficCollection()).find({ user_id: userId }).toArray(),
  ]);
  const data = { userId, exported_at: new Date().toISOString(), comments, traffic };
  const body = JSON.stringify(data, null, 2);
  return new NextResponse(body, {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Content-Disposition": "attachment; filename=thefollowup_export.json",
      "Cache-Control": "no-store",
    },
  });
}
