"use client";

import Plot from "react-plotly.js";

type TSPoint = { x: string[]; y: number[] };

function lineTrace(name: string, pts: TSPoint, color?: string) {
  return {
    type: "scatter",
    mode: "lines+markers",
    name,
    x: pts.x,
    y: pts.y,
    line: { color },
    marker: { size: 6 },
  } as any;
}

export default function StatsCharts({
  data,
}: {
  data: {
    times: string[];
    scrape?: { inserted: number[]; updated: number[] };
    enrich?: Record<string, number[]>; // priority 1..5
    claims?: Record<string, number[]>; // priority 1..5
    updatesByVerdict?: Record<string, number[]>;
    updatesByType?: Record<string, number[]>;
  };
}) {
  const layoutBase = {
    autosize: true,
    margin: { l: 40, r: 10, t: 30, b: 40 },
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    xaxis: { title: "Run Time" },
    yaxis: { title: "Count" },
  } as any;

  return (
    <div className="space-y-8">
      {data.scrape && (
        <div>
          <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Scrape: Inserted vs Updated</h2>
          <Plot
            data={[
              lineTrace("Inserted", { x: data.times, y: data.scrape.inserted }, "#16a34a"),
              lineTrace("Updated", { x: data.times, y: data.scrape.updated }, "#2563eb"),
            ]}
            layout={{ ...layoutBase }}
            style={{ width: "100%", height: 320 }}
            useResizeHandler
          />
        </div>
      )}

      {data.enrich && (
        <div>
          <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Article Priority (Enrichment)</h2>
          <Plot
            data={Object.entries(data.enrich).map(([k, series]) => lineTrace(`P${k}`, { x: data.times, y: series }))}
            layout={{ ...layoutBase }}
            style={{ width: "100%", height: 320 }}
            useResizeHandler
          />
        </div>
      )}

      {data.claims && (
        <div>
          <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Claims by Priority</h2>
          <Plot
            data={Object.entries(data.claims).map(([k, series]) => lineTrace(`P${k}`, { x: data.times, y: series }))}
            layout={{ ...layoutBase }}
            style={{ width: "100%", height: 320 }}
            useResizeHandler
          />
        </div>
      )}

      {data.updatesByVerdict && (
        <div>
          <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Updates by Verdict</h2>
          <Plot
            data={Object.entries(data.updatesByVerdict).map(([k, series]) => lineTrace(k, { x: data.times, y: series }))}
            layout={{ ...layoutBase }}
            style={{ width: "100%", height: 320 }}
            useResizeHandler
          />
        </div>
      )}

      {data.updatesByType && (
        <div>
          <h2 className="text-lg font-semibold" style={{ fontFamily: "var(--font-serif)" }}>Updates by Type</h2>
          <Plot
            data={Object.entries(data.updatesByType).map(([k, series]) => lineTrace(k, { x: data.times, y: series }))}
            layout={{ ...layoutBase }}
            style={{ width: "100%", height: 320 }}
            useResizeHandler
          />
        </div>
      )}
    </div>
  );
}
