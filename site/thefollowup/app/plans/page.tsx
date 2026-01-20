import { PricingTable, SignInButton, SignUpButton } from "@clerk/nextjs";
import { auth, clerkClient, currentUser } from "@clerk/nextjs/server";
import type { Metadata } from "next";
import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { buildLocaleKey, formatLocaleLabel, normalizeLocaleValue } from "@/lib/locales";
import { getLocaleSubscriptionsCollection } from "@/lib/mongo";

type Tier = "free" | "supporter" | "moderator" | "admin";

export const metadata: Metadata = {
  title: "Plans · The Follow Up",
  description: "Compare Free and Supporter plans for The Follow Up.",
};

function normalizeTier(tier: unknown): Tier {
  if (tier === "supporter" || tier === "moderator" || tier === "admin") return tier;
  return "free";
}

async function defaultLocaleFromHeaders() {
  const headerList = await headers();
  const city =
    headerList.get("x-vercel-ip-city") ||
    headerList.get("x-geo-city") ||
    headerList.get("x-city") ||
    "";
  const province =
    headerList.get("x-vercel-ip-region") ||
    headerList.get("x-geo-region") ||
    headerList.get("x-region") ||
    "";
  const country =
    headerList.get("x-vercel-ip-country") ||
    headerList.get("x-geo-country") ||
    headerList.get("x-country") ||
    "";
  if (!city && !province && !country) {
    return null;
  }
  return {
    city,
    province,
    country,
  };
}

async function saveLocale(formData: FormData) {
  "use server";

  const { userId } = await auth();
  if (!userId) {
    redirect("/sign-in");
  }

  const client = await clerkClient();
  const user = await client.users.getUser(userId);
  const tier = normalizeTier(user.publicMetadata?.tier);
  if (tier !== "supporter") {
    return;
  }

  const country = normalizeLocaleValue(formData.get("country") as string | null);
  const province = normalizeLocaleValue(formData.get("province") as string | null);
  const county = normalizeLocaleValue(formData.get("county") as string | null);
  const city = normalizeLocaleValue(formData.get("city") as string | null);
  const township = normalizeLocaleValue(formData.get("township") as string | null);

  const subdivisions = township ? { township } : null;
  const location = {
    country,
    province,
    county,
    city,
    subdivisions,
  };
  const locationKey = buildLocaleKey(location);
  const now = new Date();
  const locales = await getLocaleSubscriptionsCollection();

  await locales.updateOne(
    { user_id: userId },
    {
      $set: {
        tier,
        location,
        location_key: locationKey,
        source: "user",
        active: true,
        updated_at: now,
      },
      $setOnInsert: {
        created_at: now,
      },
    },
    { upsert: true },
  );

  revalidatePath("/plans");
}

async function clearLocale() {
  "use server";

  const { userId } = await auth();
  if (!userId) {
    redirect("/sign-in");
  }

  const locales = await getLocaleSubscriptionsCollection();
  await locales.updateOne(
    { user_id: userId },
    {
      $set: {
        active: false,
        updated_at: new Date(),
      },
    },
  );

  revalidatePath("/plans");
}

export default async function PlansPage() {
  const user = await currentUser();
  const normalizedTier = normalizeTier(user?.publicMetadata?.tier);
  const canSetLocale = normalizedTier === "supporter";
  const defaultLocale = await defaultLocaleFromHeaders();
  let localeSubscription = null;

  if (user && canSetLocale) {
    const locales = await getLocaleSubscriptionsCollection();
    localeSubscription = await locales.findOne({ user_id: user.id, active: true });

    if (!localeSubscription && defaultLocale && (defaultLocale.country || defaultLocale.province)) {
      const now = new Date();
      const locationKey = buildLocaleKey({
        ...defaultLocale,
        county: "",
      });

      await locales.updateOne(
        { user_id: user.id },
        {
          $set: {
            tier: normalizedTier,
            location: {
              ...defaultLocale,
              county: "",
              subdivisions: null,
            },
            location_key: locationKey,
            source: "auto",
            active: true,
            updated_at: now,
          },
          $setOnInsert: {
            created_at: now,
          },
        },
        { upsert: true },
      );

      localeSubscription = {
        user_id: user.id,
        location: {
          ...defaultLocale,
          county: "",
          subdivisions: null,
        },
        location_key: locationKey,
        source: "auto",
        active: true,
      };
    }
  }

  const localeLabel = localeSubscription?.location
    ? formatLocaleLabel(localeSubscription.location)
    : defaultLocale
      ? formatLocaleLabel(defaultLocale)
      : "Unknown";
  const localeStatusLabel = localeSubscription?.source
    ? localeSubscription.source === "auto"
      ? "Auto-detected"
      : "Subscriber set"
    : "Not set";

  const inputsDisabled = !user || !canSetLocale;

  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <div className="space-y-3 text-center">
        <p className="text-xs uppercase tracking-[0.25em] text-primary">Plans</p>
        <h1 className="text-3xl font-semibold text-foreground" style={{ fontFamily: "var(--font-serif)" }}>
          Choose the plan that fits you
        </h1>
        <p className="text-sm text-foreground/75">
          Free for casual readers, Supporter for readers who want to fund more follow-ups. You can join or manage your
          plan anytime.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          {!user ? (
            <SignUpButton
              mode="modal"
              forceRedirectUrl="/plans"
              signInForceRedirectUrl="/plans"
              signInFallbackRedirectUrl="/plans"
            >
              <button className="rounded-md bg-primary/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary">
                Join
              </button>
            </SignUpButton>
          ) : (
            <SignInButton mode="modal" forceRedirectUrl="/plans" fallbackRedirectUrl="/plans">
              <button className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm font-medium hover:bg-black/5">
                Manage billing
              </button>
            </SignInButton>
          )}
        </div>
      </div>

      <div className="mt-8 rounded-lg border border-[var(--color-border)] bg-background/60 p-6 shadow-sm">
        <PricingTable />
      </div>

      <div className="mt-8 rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-lg font-semibold text-foreground">Local news coverage</h2>
            <p className="text-sm text-foreground/70">
              Paying subscribers can tailor local coverage by state and county. We default to your network location
              when available.
            </p>
          </div>
          <span className="rounded-full border border-[var(--color-border)] px-3 py-1 text-xs font-semibold uppercase tracking-wide text-primary">
            {localeStatusLabel}
          </span>
        </div>

        {!user ? (
          <div className="mt-4 rounded-md border border-[var(--color-border)] bg-background/70 p-4 text-sm text-foreground/80">
            <p className="font-medium text-foreground">Sign in to save a locale</p>
            <p className="mt-2 text-xs text-foreground/60">
              Sign in and upgrade to Supporter to store your location preference. We&apos;ll still auto-detect your city
              when possible.
            </p>
          </div>
        ) : !canSetLocale ? (
          <div className="mt-4 rounded-md border border-[var(--color-border)] bg-background/70 p-4 text-sm text-foreground/80">
            <p className="font-medium text-foreground">Supporter feature</p>
            <p className="mt-2 text-xs text-foreground/60">
              Upgrade to Supporter to save your county-level coverage preferences.
            </p>
          </div>
        ) : null}

        <div className="mt-4 rounded-md border border-[var(--color-border)] bg-background/70 p-4 text-sm text-foreground/80">
          <p className="font-medium text-foreground">Current locale</p>
          <p className="mt-1">{localeLabel}</p>
          <p className="mt-2 text-xs text-foreground/60">
            County is required to activate county-level scrapers. If we only detect your city, please enter the county
            to receive the most precise coverage.
          </p>
        </div>

        <form action={saveLocale} className="mt-4 grid gap-4 md:grid-cols-2">
          <label className="text-sm text-foreground/80">
            Country
            <input
              name="country"
              defaultValue={localeSubscription?.location?.country || defaultLocale?.country || ""}
              className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              placeholder="US"
              disabled={inputsDisabled}
            />
          </label>
          <label className="text-sm text-foreground/80">
            State / Province
            <input
              name="province"
              defaultValue={localeSubscription?.location?.province || defaultLocale?.province || ""}
              className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              placeholder="California"
              disabled={inputsDisabled}
            />
          </label>
          <label className="text-sm text-foreground/80">
            County
            <input
              name="county"
              defaultValue={localeSubscription?.location?.county || ""}
              className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              placeholder="Santa Clara"
              disabled={inputsDisabled}
            />
          </label>
          <label className="text-sm text-foreground/80">
            City (auto-detected if possible)
            <input
              name="city"
              defaultValue={localeSubscription?.location?.city || defaultLocale?.city || ""}
              className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              placeholder="San Jose"
              disabled={inputsDisabled}
            />
          </label>
          <label className="text-sm text-foreground/80">
            Township (advanced, optional)
            <input
              name="township"
              defaultValue={(localeSubscription?.location?.subdivisions as { township?: string } | null)?.township || ""}
              className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60"
              placeholder="Downtown"
              disabled={inputsDisabled}
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="submit"
              disabled={inputsDisabled}
              className="w-full rounded-md bg-primary/90 px-4 py-2 text-sm font-semibold text-white hover:bg-primary disabled:cursor-not-allowed disabled:opacity-60"
            >
              Save locale
            </button>
          </div>
        </form>

        <form action={clearLocale} className="mt-4 flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={inputsDisabled}
            className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-foreground/70 hover:bg-black/5 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Clear locale preference
          </button>
          {!user && (
            <SignInButton mode="modal" forceRedirectUrl="/plans" fallbackRedirectUrl="/plans">
              <button className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm font-medium hover:bg-black/5">
                Sign in
              </button>
            </SignInButton>
          )}
          {user && !canSetLocale && (
            <SignUpButton
              mode="modal"
              forceRedirectUrl="/plans"
              signInForceRedirectUrl="/plans"
              signInFallbackRedirectUrl="/plans"
            >
              <button className="rounded-md bg-primary/90 px-4 py-2 text-sm font-semibold text-white hover:bg-primary">
                Upgrade to Supporter
              </button>
            </SignUpButton>
          )}
        </form>
      </div>
    </div>
  );
}
