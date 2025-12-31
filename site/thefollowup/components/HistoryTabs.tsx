"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

type CommentItem = { id: string; postId: string; postType: string; href: string; title: string; text: string; createdAt: string };
type ViewItem = { id: string; postId: string; postType: string; href: string; title: string; enteredAt: string };

type TabKey = "comments" | "views";

export default function HistoryTabs() {
  const [tab, setTab] = useState<TabKey>("comments");
  return (
    <div className="mt-6">
      <div className="flex gap-2 border-b pb-1 text-sm">
        <button className={`rounded px-3 py-1 ${tab === "comments" ? "bg-primary/90 text-white" : "hover:bg-black/5"}`} onClick={() => setTab("comments")}>Comments</button>
        <button className={`rounded px-3 py-1 ${tab === "views" ? "bg-primary/90 text-white" : "hover:bg-black/5"}`} onClick={() => setTab("views")}>View history</button>
      </div>
      {tab === "comments" ? <CommentsPane /> : <ViewsPane />}
    </div>
  );
}

function useInfinite<T>(endpoint: string) {
  const [items, setItems] = useState<T[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seenIdsRef = useRef<Set<string>>(new Set());

  async function loadMore() {
    if (loading || !hasMore) return;
    setLoading(true);
    setError(null);
    try {
      const url = new URL(endpoint, window.location.origin);
      url.searchParams.set("limit", "20");
      if (cursor) url.searchParams.set("cursor", cursor);
      const r = await fetch(url.toString(), { credentials: "include", cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      const incoming = (j.items || []) as any[];
      const filtered = incoming.filter((x) => {
        const id = String(x.id);
        if (seenIdsRef.current.has(id)) return false;
        seenIdsRef.current.add(id);
        return true;
      });
      setItems((prev) => prev.concat(filtered as any));
      if (j.nextCursor) {
        setCursor(j.nextCursor);
        setHasMore(true);
      } else {
        setHasMore(false);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  }

  // Do not auto-load; rely on sentinel to prevent double first page
  return { items, hasMore, loading, error, loadMore };
}

function CommentsPane() {
  const { items, hasMore, loading, error, loadMore } = useInfinite<CommentItem>("/api/account/comments");
  const sentinelRef = useInfiniteSentinel(loadMore, hasMore, loading);
  return (
    <section className="mt-4">
      <div className="space-y-3">
        {items.map((c) => (
          <div key={c.id} className="rounded-md border p-3 text-sm">
            <div className="flex items-center justify-between">
              <Link href={c.href} className="font-medium hover:underline">{c.title}</Link>
              <div className="text-xs text-foreground/60">{new Date(c.createdAt).toLocaleString()}</div>
            </div>
            <p className="mt-2 whitespace-pre-wrap leading-relaxed">{c.text}</p>
          </div>
        ))}
        {error && <div className="text-sm text-red-600">{error}</div>}
        {(loading || hasMore) && <div ref={sentinelRef as any} className="py-4 text-center text-xs text-foreground/60">{loading ? "Loading…" : "Load more"}</div>}
      </div>
    </section>
  );
}

function ViewsPane() {
  const { items, hasMore, loading, error, loadMore } = useInfinite<ViewItem>("/api/account/traffic");
  const sentinelRef = useInfiniteSentinel(loadMore, hasMore, loading);
  return (
    <section className="mt-4">
      <div className="space-y-2">
        {items.map((t) => (
          <div key={t.id} className="flex items-center justify-between rounded-md border px-3 py-2 text-sm">
            <Link href={t.href} className="hover:underline">{t.title}</Link>
            <div className="text-xs text-foreground/60">{new Date(t.enteredAt).toLocaleString()}</div>
          </div>
        ))}
        {error && <div className="text-sm text-red-600">{error}</div>}
        {(loading || hasMore) && <div ref={sentinelRef as any} className="py-4 text-center text-xs text-foreground/60">{loading ? "Loading…" : "Load more"}</div>}
      </div>
    </section>
  );
}

function useInfiniteSentinel(onHit: () => void, hasMore: boolean, loading: boolean) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && hasMore && !loading) onHit();
      });
    }, { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, loading, onHit]);
  return ref;
}
