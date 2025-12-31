"use client";

import { useState } from "react";

export default function AccountHistoryControls() {
  const [busy, setBusy] = useState(false);

  async function download() {
    setBusy(true);
    try {
      const r = await fetch("/api/account/export", { credentials: "include" });
      if (r.ok) {
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "thefollowup_export.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      }
    } finally {
      setBusy(false);
    }
  }

  async function deleteScope(scope: "comments" | "traffic") {
    if (!confirm(`Delete all ${scope} history? This cannot be undone.`)) return;
    setBusy(true);
    try {
      const r = await fetch("/api/account/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ scope }),
      });
      if (r.ok) location.reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex gap-2">
      <button onClick={download} disabled={busy} className="rounded-md border px-3 py-1.5 text-xs sm:text-sm hover:bg-black/5 disabled:opacity-50">Download data</button>
      <button onClick={() => deleteScope("comments")} disabled={busy} className="rounded-md border px-3 py-1.5 text-xs sm:text-sm hover:bg-black/5 disabled:opacity-50">Delete comments</button>
      <button onClick={() => deleteScope("traffic")} disabled={busy} className="rounded-md border px-3 py-1.5 text-xs sm:text-sm hover:bg-black/5 disabled:opacity-50">Delete views</button>
    </div>
  );
}
