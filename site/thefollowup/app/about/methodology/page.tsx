import Link from "next/link";
import { mapVerdictDisplay } from "@/lib/verdict";

export const dynamic = "force-dynamic";

export default function MethodologyPage() {
  return (
    <div className="min-h-screen w-full bg-background text-foreground">
      <div className="mx-auto max-w-3xl px-4 py-8">
        <div className="dateline mb-1">Fact-checking approach</div>
        <h1 className="text-3xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>
          Methodology
        </h1>
        <hr className="mt-4" />
        <section className="prose prose-neutral mt-6 max-w-none leading-relaxed">
          <h2 className="mt-8 text-xl font-semibold tracking-tight" style={{ fontFamily: "var(--font-serif)" }}>Fact Check Categorization</h2>
          <ul className="mt-4 space-y-5">
            <li>
              {(() => { const d = mapVerdictDisplay("True"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Evidence from credible, preferably primary sources supports the statement as accurate.</div>
              For example: the Federal Register shows a final rule published on the stated date; Treasury/agency disbursement data matches the amounts and recipients claimed.
            </li>
            <li>
              {(() => { const d = mapVerdictDisplay("Close"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Not 100% exact but close enough for a reasonable person.</div>
              For example, a leader may claim "GDP has increased by 2.3%" when the actual growth was 2.25%. This is to help catch "good-faith" inaccuracies where something may be simplified for brevity, or where something was mildly exaggerated.
            </li>
            <li>
              {(() => { const d = mapVerdictDisplay("Misleading"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Technically correct but framed in a misleading way.</div>
              For example: touting a "record funding increase" in nominal dollars while inflation-adjusted funding fell; citing a selective timeframe to claim "record-low unemployment" while omitting a recent uptick.
            </li>
            <li>
              {(() => { const d = mapVerdictDisplay("Unverifiable"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Not verifiable or falsifiable (e.g., opinion, intent, or unfalsifiable claims).</div>
              For example: statements of intent ("we will hold bad actors accountable") without measurable criteria; subjective claims ("the best program") without objective standards.
            </li>
            <li>
              {(() => { const d = mapVerdictDisplay("Unclear"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Evidence is incomplete or developing; future updates may clarify.</div>
              For example: an investigation is announced but no report exists yet; a draft rule is proposed and the final policy scope is still undetermined.
            </li>
            <li>
              {(() => { const d = mapVerdictDisplay("False"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Credible evidence contradicts the statement.</div>
              For example: a claim says a program ended, but the agency’s official site still lists current enrollment; a statement says a law was struck down, but court dockets show no such ruling.
            </li>
            <li>
              {(() => { const d = mapVerdictDisplay("Tech Error"); return (
                <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-wide" style={{ color: d.color }}>
                  {d.icon}
                  <span>{d.label}</span>
                </div>
              );})()}
              <div>Verification couldn’t be completed due to technical access/rendering issues.</div>
              For example: the primary source website is down or heavily rate-limited; the official PDF is corrupted or requires login and an alternate source is pending.
              <br/>We typically try to revisit any issues classified as Tech Errors, though its not always possible to resolve.
            </li>
          </ul>
        </section>
      </div>
    </div>
  );
}
