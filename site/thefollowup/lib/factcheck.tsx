import React from "react";
import { mapVerdictDisplay } from "@/lib/verdict";

export type FactVerdict =
  | "True"
  | "False"
  | "Tech Error"
  | "Close"
  | "Misleading"
  | "Unverifiable"
  | "Unclear";

const EXPLANATIONS: Record<string, string> = {
  "true": "Evidence from credible sources supports the statement as accurate.",
  "false": "Credible evidence contradicts the statement.",
  "tech error": "Verification couldn’t be completed due to a technical issue accessing sources. A retry is needed.",
  "close": "The statement is not 100% exact but close enough for a reasonable person (e.g., claimed 70% vs. actual 65%).",
  "misleading": "Facts are technically correct but framed in a way that likely leads to a wrong impression.",
  "unverifiable": "The statement can’t be verified or falsified (e.g., opinion, intent, or unfalsifiable claims).",
  "unclear": "Evidence is incomplete or still developing; a future update may resolve it.",
};

function normalize(raw?: string): string {
  const v = String(raw || "").trim().toLowerCase();
  if (!v) return "";
  if (v === "complete" || v === "succeeded") return "true";
  if (v === "failed" || v === "failure") return "false";
  if (v === "in_progress" || v === "in progress" || v === "pending" || v === "complicated") return "unclear";
  return v.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function toTitleCaseKey(norm: string): FactVerdict | undefined {
  const map: Record<string, FactVerdict> = {
    "true": "True",
    "false": "False",
    "tech error": "Tech Error",
    "close": "Close",
    "misleading": "Misleading",
    "unverifiable": "Unverifiable",
    "unclear": "Unclear",
  };
  return map[norm];
}

export function getVerdictInfo(raw?: string):
  | { key: FactVerdict; label: string; color: string; icon: React.ReactNode; explanation: string; slug: string }
  | undefined {
  const norm = normalize(raw);
  const key = toTitleCaseKey(norm);
  if (!key) return undefined;
  const disp = mapVerdictDisplay(key);
  const explanation = EXPLANATIONS[norm] || "";
  const slug = norm.replace(/\s+/g, "-");
  return { key, label: disp.label, color: disp.color, icon: disp.icon, explanation, slug };
}

export function getVerdictSlug(raw?: string): string | undefined {
  return getVerdictInfo(raw)?.slug;
}

export function verdictFilterOptions(): { value: string; label: string }[] {
  return [
    { value: "", label: "All" },
    { value: "true", label: "True" },
    { value: "close", label: "Close" },
    { value: "misleading", label: "Misleading" },
    { value: "unverifiable", label: "Unverifiable" },
    { value: "unclear", label: "Unclear" },
    { value: "false", label: "False" },
    { value: "tech-error", label: "Tech Error" },
  ];
}
