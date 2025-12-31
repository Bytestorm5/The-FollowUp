"use client";

import { useEffect, useState } from "react";
import { useUser, SignInButton } from "@clerk/nextjs";

type Props = { postId: string; postType: string; showInteresting?: boolean; showSupport?: boolean };

export default function PostPoll({ postId, postType, showInteresting = true, showSupport = true }: Props) {
  const { user } = useUser();
  const [interesting, setInteresting] = useState<boolean | null>(null);
  const [support, setSupport] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<{ interesting?: number; interestingTotal?: number; support?: number; supportTotal?: number }>({});

  async function fetchResults() {
    const r = await fetch(`/api/polls?postId=${encodeURIComponent(postId)}&postType=${encodeURIComponent(postType)}`, { cache: "no-store", credentials: "include" });
    if (r.ok) {
      const data = await r.json();
      setResults(data);
      // Preload current user's choices, if any
      if (typeof data.myInteresting === "boolean") setInteresting(!!data.myInteresting);
      if (typeof data.mySupport === "boolean") setSupport(!!data.mySupport);
    }
  }

  useEffect(() => { fetchResults(); }, [postId, postType]);

  async function submitPartial(payload: Partial<{ interesting: boolean; support: boolean }>) {
    setBusy(true);
    try {
      const r = await fetch(`/api/polls`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ postId, postType, ...payload }),
      });
      if (r.ok) await fetchResults();
    } finally {
      setBusy(false);
    }
  }

  const iYes = results.interesting || 0; const iTot = results.interestingTotal || 0;
  const sYes = results.support || 0; const sTot = results.supportTotal || 0;

  // Logged-out view: compact single line showing results and a prompt to join
  if (!user) {
    const parts: string[] = [];
    if (showInteresting) parts.push(`Interesting: ${iYes}/${iTot}`);
    if (showSupport) parts.push(`Support: ${sYes}/${sTot}`);
    return (
      <section className="mt-3 rounded-md border px-3 py-2">
        <div className="flex items-center justify-between gap-3 text-xs sm:text-sm">
          <span className="text-foreground/80">{parts.join(" • ")}</span>
          <span className="flex items-center gap-2 text-foreground/60">
            <span>Log in to vote</span>
            <SignInButton mode="modal" withSignUp asChild>
              <button className="rounded-full border px-2 py-0.5 text-xs hover:bg-black/5">Join</button>
            </SignInButton>
          </span>
        </div>
      </section>
    );
  }

  // Logged-in interactive view
  return (
    <section className="mt-3 rounded-md border p-3">
      <div className="text-sm font-semibold">Quick poll</div>
      <div className="mt-2 space-y-2">
        {showInteresting && (
          <>
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm">Is this interesting / useful to know?</div>
              <div className="flex items-center gap-2">
                <button disabled={busy} onClick={() => { setInteresting(true); submitPartial({ interesting: true }); }} className={`rounded-full border px-3 py-1 text-xs sm:text-sm ${interesting === true ? "bg-primary/90 text-white" : "hover:bg-black/5"}`}>Yes</button>
                <button disabled={busy} onClick={() => { setInteresting(false); submitPartial({ interesting: false }); }} className={`rounded-full border px-3 py-1 text-xs sm:text-sm ${interesting === false ? "bg-primary/90 text-white" : "hover:bg-black/5"}`}>No</button>
              </div>
            </div>
            <div className="text-[11px] text-foreground/60">Yes: {iYes} / {iTot}</div>
          </>
        )}

        {showSupport && (
          <>
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm">Do you support the actions/statements of this article?</div>
              <div className="flex items-center gap-2">
                <button disabled={busy} onClick={() => { setSupport(true); submitPartial({ support: true }); }} className={`rounded-full border px-3 py-1 text-xs sm:text-sm ${support === true ? "bg-primary/90 text-white" : "hover:bg-black/5"}`}>Yes</button>
                <button disabled={busy} onClick={() => { setSupport(false); submitPartial({ support: false }); }} className={`rounded-full border px-3 py-1 text-xs sm:text-sm ${support === false ? "bg-primary/90 text-white" : "hover:bg-black/5"}`}>No</button>
              </div>
            </div>
            <div className="text-[11px] text-foreground/60">Yes: {sYes} / {sTot}</div>
          </>
        )}
      </div>
    </section>
  );
}
