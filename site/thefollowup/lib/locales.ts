export type LocaleSubdivision = Record<string, string | null | undefined>;

export interface LocaleInput {
  country?: string | null;
  province?: string | null;
  county?: string | null;
  city?: string | null;
  subdivisions?: LocaleSubdivision | null;
}

export function normalizeLocaleValue(value?: string | null): string {
  return String(value || "").trim();
}

export function buildLocaleKey(locale: LocaleInput): string {
  const baseParts = [locale.country, locale.province, locale.county].map(normalizeLocaleValue);
  const subdivisions = locale.subdivisions || {};
  const subdivisionParts = Object.keys(subdivisions)
    .sort()
    .map((key) => `${key}:${normalizeLocaleValue(subdivisions[key])}`);
  return [...baseParts, ...subdivisionParts]
    .filter((part) => part.length > 0)
    .join("|")
    .toLowerCase();
}

export function formatLocaleLabel(locale: LocaleInput): string {
  const parts = [locale.city, locale.county, locale.province, locale.country]
    .map(normalizeLocaleValue)
    .filter(Boolean);
  if (parts.length === 0) return "Unknown";
  return parts.join(", ");
}
