"use client";

import { useEffect } from "react";

declare global {
  interface Window {
    adsbygoogle: unknown[];
  }
}

type Props = {
  adSlot: string;                 // data-ad-slot
  adClient?: string;              // optional if you put client in the script URL
  format?: string;                // data-ad-format (e.g. "auto")
  layout?: string;
  responsive?: "true" | "false";  // data-full-width-responsive
  style?: React.CSSProperties;    // allow custom sizing
};

export default function AdsenseAd({
  adSlot,
  adClient, // if you want it here instead
  format = "auto",
  layout = undefined,
  responsive = "true",
  style = { display: "block" },
}: Props) {
  useEffect(() => {
    try {
      // push after mount so the ins tag exists
      (window.adsbygoogle = window.adsbygoogle || []).push({});
    } catch (e) {
      // Ad blockers or duplicate pushes can throw; safe to ignore
      // console.warn(e);
    }
  }, []);

  return (
    <ins
      className="adsbygoogle"
      style={style}
      data-ad-client={adClient} // optional
      data-ad-slot={adSlot}
      data-ad-format={format}
      {...(layout ? { "data-ad-layout": layout } : {})}
      data-full-width-responsive={responsive}
    />
  );
}
