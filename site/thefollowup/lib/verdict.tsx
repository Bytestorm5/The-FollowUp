import React from "react";

export type VerdictDisplay = {
  label: string;
  color: string; // CSS color or CSS var
  bg?: string;
  icon: React.ReactNode;
};

const Check = (props: any) => (
  <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" {...props}>
    <path d="M16.704 5.29a1 1 0 0 1 .006 1.414l-7.25 7.333a1 1 0 0 1-1.438.006L3.29 9.99A1 1 0 1 1 4.71 8.57l3.03 3.016 6.544-6.613a1 1 0 0 1 1.42.317z"/>
  </svg>
);
const Cross = (props: any) => (
  <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" {...props}>
    <path d="M11.414 10l3.536-3.536a1 1 0 0 0-1.414-1.414L10 8.586 6.464 5.05A1 1 0 1 0 5.05 6.464L8.586 10l-3.536 3.536a1 1 0 1 0 1.414 1.414L10 11.414l3.536 3.536a1 1 0 0 0 1.414-1.414L11.414 10z"/>
  </svg>
);
const Warn = (props: any) => (
  <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" {...props}>
    <path d="M10 2a1 1 0 0 1 .894.553l7 14A1 1 0 0 1 17 18H3a1 1 0 0 1-.894-1.447l7-14A1 1 0 0 1 10 2zm0 12a1 1 0 1 0 0 2 1 1 0 0 0 0-2zm-1-6v4a1 1 0 1 0 2 0V8a1 1 0 1 0-2 0z"/>
  </svg>
);
const Info = (props: any) => (
  <svg className="inline-block h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" {...props}>
    <path d="M10 2a8 8 0 100 16 8 8 0 000-16zM9 9h2v6H9V9zm0-4h2v2H9V5z"/>
  </svg>
);

// Map verdict strings (case-insensitive) to display settings
export function mapVerdictDisplay(raw?: string): VerdictDisplay {
  const v = (raw || "").trim();
  const lc = v.toLowerCase();

  // New categories
  if (lc === "true") return { label: "True", color: "var(--color-status-succeeded)", icon: <Check style={{ color: "var(--color-status-succeeded)" }} /> };
  if (lc === "false") return { label: "False", color: "var(--color-status-failed)", icon: <Cross style={{ color: "var(--color-status-failed)" }} /> };
  if (lc === "tech error" || lc === "tech_error") return { label: "Tech Error", color: "var(--color-status-pending)", icon: <Warn style={{ color: "var(--color-status-pending)" }} /> };
  if (lc === "close") return { label: "Close", color: "var(--color-status-succeeded)", icon: <Info style={{ color: "var(--color-status-succeeded)" }} /> };
  if (lc === "misleading") return { label: "Misleading", color: "var(--color-accent)", icon: <Warn style={{ color: "var(--color-accent)" }} /> };
  if (lc === "unverifiable") return { label: "Unverifiable", color: "var(--color-status-pending)", icon: <Info style={{ color: "var(--color-status-pending)" }} /> };
  if (lc === "unclear") return { label: "Unclear", color: "var(--color-status-pending)", icon: <Info style={{ color: "var(--color-status-pending)" }} /> };

  // Legacy categories
  if (lc === "complete") return { label: "True", color: "var(--color-status-succeeded)", icon: <Check style={{ color: "var(--color-status-succeeded)" }} /> };
  if (lc === "failed") return { label: "False", color: "var(--color-status-failed)", icon: <Cross style={{ color: "var(--color-status-failed)" }} /> };
  if (lc === "in_progress") return { label: "Complicated", color: "var(--color-status-pending)", icon: <Warn style={{ color: "var(--color-status-pending)" }} /> };

  // Default fallback
  return { label: v || "Unclear", color: "var(--color-status-pending)", icon: <Info style={{ color: "var(--color-status-pending)" }} /> };
}
