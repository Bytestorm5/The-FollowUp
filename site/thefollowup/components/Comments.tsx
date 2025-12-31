"use client";

import { useEffect, useMemo, useState } from "react";
import { useUser, SignInButton } from "@clerk/nextjs";

type Props = { postId: string; postType: string };

type Comment = {
  _id: string;
  user_id: string;
  display_name?: string | null;
  text: string;
  created_at: string;
  updated_at?: string;
  likes?: number;
  dislikes?: number;
  reactions_by?: Record<string, 1 | -1>;
};

export default function Comments({ postId, postType }: Props) {
  const { user } = useUser();
  const [items, setItems] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const myId = user?.id;

  async function load() {
    setLoading(true);
    try {
      const r = await fetch(`/api/comments?postId=${encodeURIComponent(postId)}&postType=${encodeURIComponent(postType)}`, { cache: "no-store", credentials: "include" });
      const j = await r.json();
      setItems((j.items || []).map((x: any) => ({ ...x, _id: String(x._id) })));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [postId, postType]);

  async function submit() {
    const t = text.trim(); if (!t) return;
    setText("");
    const r = await fetch(`/api/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ postId, postType, text: t, displayName: user?.fullName || user?.username })
    });
    if (r.ok) load();
  }

  async function saveEdit(id: string, newText: string) {
    const r = await fetch(`/api/comments/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ text: newText }) });
    if (r.ok) load();
  }

  async function react(id: string, value: 1 | -1 | 0) {
    const r = await fetch(`/api/comments/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify({ reaction: value }) });
    if (r.ok) load();
  }

  return (
    <section className="mt-8">
      <h2 className="text-lg font-semibold">Comments</h2>
      {/* Editor */}
      <div className="mt-3 rounded-md border p-3">
        {myId ? (
          <div>
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} className="w-full resize-y rounded-md border p-2 text-sm" placeholder="Write a comment…" />
            <div className="mt-2 flex justify-end">
              <button onClick={submit} className="rounded-md bg-primary/90 px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary">Post</button>
            </div>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-3 text-sm text-foreground/70">
            <span>Only logged-in users can comment.</span>
            <SignInButton mode="modal" withSignUp>
              <button className="rounded-full bg-primary/90 px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary">Join</button>
            </SignInButton>
          </div>
        )}
      </div>

      {/* List */}
      <div className="mt-4 space-y-3">
        {loading ? <div className="text-sm text-foreground/60">Loading…</div> : null}
        {!loading && items.length === 0 ? <div className="text-sm text-foreground/60">No comments yet.</div> : null}
        {items.map((c) => {
          const mine = myId && c.user_id === myId;
          return (
            <CommentRow key={c._id} c={c} mine={!!mine} onSave={saveEdit} onReact={react} />
          );
        })}
      </div>
    </section>
  );
}

function CommentRow({ c, mine, onSave, onReact }: { c: Comment; mine: boolean; onSave: (id: string, text: string) => void; onReact: (id: string, v: 1 | -1 | 0) => void; }) {
  const { user } = useUser();
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(c.text);
  const myReaction: 1 | -1 | 0 = (c.reactions_by && user?.id && (c.reactions_by[user.id] as any)) || 0;

  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="flex items-center justify-between">
        <div className="font-medium">{c.display_name || c.user_id}</div>
        <div className="text-xs text-foreground/60">{new Date(c.created_at).toLocaleString()}</div>
      </div>
      <div className="mt-2">
        {editing ? (
          <div>
            <textarea value={val} onChange={(e) => setVal(e.target.value)} rows={3} className="w-full resize-y rounded-md border p-2 text-sm" />
            <div className="mt-2 flex gap-2">
              <button onClick={() => { onSave(c._id, val); setEditing(false); }} className="rounded-md bg-primary/90 px-3 py-1 text-xs font-semibold text-white">Save</button>
              <button onClick={() => { setVal(c.text); setEditing(false); }} className="rounded-md border px-3 py-1 text-xs">Cancel</button>
            </div>
          </div>
        ) : (
          <p className="whitespace-pre-wrap leading-relaxed">{c.text}</p>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button
          aria-label={myReaction === 1 ? "Remove like" : "Like"}
          onClick={() => onReact(c._id, myReaction === 1 ? 0 : 1)}
          className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${myReaction === 1 ? "bg-primary/90 text-white" : "hover:bg-black/5"}`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v10h10a3 3 0 0 0 3-3v-7z"/>
            <path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
          <span>{c.likes || 0}</span>
        </button>
        <button
          aria-label={myReaction === -1 ? "Remove dislike" : "Dislike"}
          onClick={() => onReact(c._id, myReaction === -1 ? 0 : -1)}
          className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${myReaction === -1 ? "bg-primary/90 text-white" : "hover:bg-black/5"}`}
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M10 15v4a3 3 0 0 0 3 3l4-9V3H7a3 3 0 0 0-3 3v7z"/>
            <path d="M17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
          </svg>
          <span>{c.dislikes || 0}</span>
        </button>
        {mine && !editing && (
          <>
            <button onClick={() => setEditing(true)} className="ml-auto rounded-full border px-2 py-0.5 text-xs hover:bg-black/5">Edit</button>
            <button
              onClick={async () => {
                if (!confirm("Delete this comment?")) return;
                await fetch(`/api/comments/${c._id}`, { method: "DELETE", credentials: "include" });
                location.reload();
              }}
              className="rounded-full border px-2 py-0.5 text-xs text-red-600 hover:bg-red-50"
            >
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}
