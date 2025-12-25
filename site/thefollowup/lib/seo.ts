export function getSiteUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_SITE_URL || process.env.SITE_URL;
  try {
    if (envUrl) {
      const u = new URL(envUrl);
      return u.origin;
    }
  } catch {}
  return "https://thefollowup.example";
}

export function absUrl(path: string): string {
  const base = getSiteUrl().replace(/\/$/, "");
  const p = (path || "/").startsWith("/") ? path : `/${path}`;
  return `${base}${p}`;
}
