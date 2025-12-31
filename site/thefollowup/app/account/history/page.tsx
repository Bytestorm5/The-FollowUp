import { currentUser } from "@clerk/nextjs/server";
import Link from "next/link";
import AccountHistoryControls from "@/components/AccountHistoryControls";
import HistoryTabs from "@/components/HistoryTabs";

export const dynamic = "force-dynamic";

function postLink(postType: string, postId: any): string {
  const id = String(postId);
  if (postType === "article") return `/article/${id}`;
  if (postType === "claim" || postType === "fact_check") return `/claim/${id}`;
  if (postType === "roundup") return `/roundups/${id}`;
  return `/`;
}

export default async function AccountHistoryPage() {
  const user = await currentUser();
  if (!user) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-2xl font-semibold">History</h1>
        <p className="mt-2 text-sm text-foreground/70">Please sign in to view your history.</p>
      </div>
    );
  }
  // Client-rendered tabs handle fetching & pagination

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Your activity</h1>
        <AccountHistoryControls />
      </div>

      <HistoryTabs />
    </div>
  );
}
