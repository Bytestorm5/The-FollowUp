"use client";

import { useEffect } from "react";

type Props = { postId: string; postType: string };

export default function TrackVisit({ postId, postType }: Props) {
  useEffect(() => {
    // Fire and forget; server records only when logged in
    fetch("/api/traffic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ postId, postType })
    }).catch(() => {});
  }, [postId, postType]);
  return null;
}
