import { notFound } from "next/navigation";
import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Link from "next/link";
import { getSilverRoundupsCollection, ObjectId } from "@/lib/mongo";
import PostPoll from "@/components/PostPoll";
import Comments from "@/components/Comments";
import TrackVisit from "@/components/TrackVisit";

function label(kind: string): string {
  return kind === "daily" ? "Daily" : kind === "weekly" ? "Weekly" : kind === "monthly" ? "Monthly" : kind === "yearly" ? "Yearly" : kind;
}

export default async function RoundupDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; // treat as slug when present
  const coll = await getSilverRoundupsCollection();
  // Try by slug first
  let doc = await coll.findOne({ slug: id } as any);
  if (!doc) {
    // Fallback: try ObjectId
    let _id: ObjectId | null = null;
    try { _id = new ObjectId(id); } catch { /* ignore */ }
    if (_id) {
      doc = await coll.findOne({ _id } as any);
    }
  }
  if (!doc) return notFound();

  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-6">
        <TrackVisit postId={String((doc as any)._id)} postType="roundup" />
        <div className="mb-3 text-xs text-foreground/70">
          <Link href="/roundups" className="hover:underline">Roundups</Link> / {label((doc as any).roundup_type)}
        </div>
        <h1 className="text-3xl font-semibold text-primary" style={{ fontFamily: "var(--font-serif)" }}>{doc.title}</h1>
        <div className="mt-1 text-xs text-foreground/60">
          {new Date(doc.period_start as any).toLocaleDateString()} – {new Date(doc.period_end as any).toLocaleDateString()}
        </div>
        <div className="mt-3">
          <PostPoll postId={String((doc as any)._id)} postType="roundup" showSupport={false} />
        </div>
        <article className="markdown mt-6 max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{doc.summary_markdown || ""}</ReactMarkdown>
        </article>
        {Array.isArray((doc as any).sources) && (doc as any).sources.length > 0 && (
          <section className="mt-8">
            <h2 className="mb-2 text-base font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Sources</h2>
            <ul className="list-disc pl-5 space-y-1 text-sm">
              {((doc as any).sources as string[]).map((u, i) => (
                <li key={i}>
                  <a href={u} target="_blank" rel="noopener noreferrer" className="underline text-primary">{u}</a>
                </li>
              ))}
            </ul>
          </section>
        )}
        {/* Comments */}
        <Comments postId={String((doc as any)._id)} postType="roundup" />
      </div>
    </div>
  );
}
