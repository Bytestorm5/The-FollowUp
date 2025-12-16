"use client";

import { useEffect, useMemo, useState } from "react";

function pad(n: number) {
  return String(n);
}

function diffParts(target: Date, now: Date) {
  let delta = Math.max(0, Math.floor((target.getTime() - now.getTime()) / 1000));
  const years = Math.floor(delta / (365 * 24 * 3600));
  delta -= years * 365 * 24 * 3600;
  const months = Math.floor(delta / (30 * 24 * 3600));
  delta -= months * 30 * 24 * 3600;
  const days = Math.floor(delta / (24 * 3600));
  delta -= days * 24 * 3600;
  const hours = Math.floor(delta / 3600);
  delta -= hours * 3600;
  const minutes = Math.floor(delta / 60);
  delta -= minutes * 60;
  const seconds = delta;
  return { years, months, days, hours, minutes, seconds };
}

export default function Countdown({ targetISO }: { targetISO: string }) {
  const target = useMemo(() => new Date(targetISO), [targetISO]);
  const [now, setNow] = useState<Date>(new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const { years, months, days, hours, minutes, seconds } = diffParts(target, now);
  const parts: string[] = [];
  if (years) parts.push(`${pad(years)} year${years !== 1 ? "s" : ""}`);
  if (months) parts.push(`${pad(months)} month${months !== 1 ? "s" : ""}`);
  if (days) parts.push(`${pad(days)} day${days !== 1 ? "s" : ""}`);
  if (hours || parts.length) parts.push(`${pad(hours)} hour${hours !== 1 ? "s" : ""}`);
  if (minutes || parts.length) parts.push(`${pad(minutes)} minute${minutes !== 1 ? "s" : ""}`);
  parts.push(`${pad(seconds)} second${seconds !== 1 ? "s" : ""}`);

  return <span>{parts.join(", ")}</span>;
}
