import { PricingTable, SignInButton, SignUpButton } from "@clerk/nextjs";
import { auth, clerkClient, currentUser } from "@clerk/nextjs/server";
import type { Metadata } from "next";
import { revalidatePath } from "next/cache";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { getLocaleSubscriptionsCollection } from "@/lib/mongo";
import { buildLocaleKey, formatLocaleLabel, normalizeLocaleValue } from "@/lib/locales";

type Tier = "free" | "supporter" | "moderator" | "admin";

const publicTiers: Array<{
  id: Extract<Tier, "free" | "supporter">;
  name: string;
  price: string;
  description: string;
  features: string[];
}> = [
  {
    id: "free",
    name: "Free",
    price: "$0",
    description: "Read the latest follow-ups without creating a billable subscription.",
    features: [
      "Full access to public articles",
      "Email updates when follow-ups publish",
      "Participate in public discussions (coming soon)",
    ],
  },
  {
    id: "supporter",
    name: "Supporter",
    price: "$5/mo or $50/yr",
    description: "Keep The Follow Up independent with a recurring contribution.",
    features: [
      "Everything in Free",
      "Priority access to new features",
      "Support the newsroom with a predictable contribution",
    ],
  },
];

const internalTiers: Array<{
  id: Extract<Tier, "moderator" | "admin">;
  name: string;
  description: string;
}> = [
  {
    id: "moderator",
    name: "Moderator",
    description: "Internal role for content and community moderation. Assigned manually.",
  },
  {
    id: "admin",
    name: "Admin",
    description: "Internal role for operations, billing, and staff tooling. Assigned manually.",
  },
];

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

async function updateTier(formData: FormData) {
  "use server";

  const { userId } = await auth();
  if (!userId) {
    redirect("/sign-in");
  }

  const tier = formData.get("tier");
  if (tier !== "free" && tier !== "supporter") {
    return;
  }

  const client = await clerkClient();

  await client.users.updateUserMetadata(userId, {
    publicMetadata: { tier },
  });

  revalidatePath("/account");
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

  revalidatePath("/account");
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

  revalidatePath("/account");
}

export const metadata: Metadata = {
  title: "Account & Access · The Follow Up",
  description: "Sign in with Clerk and choose the membership tier that fits you.",
};

export default async function AccountPage() {
  const user = await currentUser();
  const normalizedTier = normalizeTier(user?.publicMetadata?.tier);
  const isInternalTier = normalizedTier === "moderator" || normalizedTier === "admin";
  const canSetLocale = normalizedTier === "supporter";
  const defaultLocale = user ? await defaultLocaleFromHeaders() : null;
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

  const primaryEmail =
    user?.emailAddresses?.find((address) => address.id === user.primaryEmailAddressId)?.emailAddress ||
    user?.emailAddresses?.[0]?.emailAddress;
  const email = primaryEmail || user?.username || user?.firstName;
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

  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <div className="space-y-3">
        <p className="text-xs uppercase tracking-[0.25em] text-primary">Account</p>
        <h1 className="text-3xl font-semibold text-foreground" style={{ fontFamily: "var(--font-serif)" }}>
          Sign in and manage your access
        </h1>
        <p className="max-w-3xl text-sm text-foreground/80">
          Use Clerk to sign in securely and choose the service tier that fits you. Free and Supporter are
          self-serve. Moderator and Admin are internal roles that we assign manually when we invite team members.
        </p>
      </div>

      {!user ? (
        <div className="mt-8 space-y-6">
          <div className="rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
            <h2 className="text-xl font-semibold text-foreground">Choose a plan to get started</h2>
            <p className="mt-2 text-sm text-foreground/80">
              Join to follow promises and support our newsroom. You can view all plans below, and returning readers can
              sign in from the same Join flow.
            </p>
            <div className="mt-4">
              <SignUpButton
                mode="modal"
                forceRedirectUrl="/account"
                signInForceRedirectUrl="/account"
                signInFallbackRedirectUrl="/account"
              >
                <button className="w-full rounded-md bg-primary/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary sm:w-auto">
                  Join
                </button>
              </SignUpButton>
            </div>
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-lg font-semibold text-foreground">Plans</h3>
                <p className="text-sm text-foreground/70">Free and Supporter plans are open to everyone.</p>
              </div>
              <SignInButton mode="modal" forceRedirectUrl="/account" fallbackRedirectUrl="/account">
                <button className="rounded-md border border-[var(--color-border)] px-3 py-2 text-sm font-medium hover:bg-black/5">
                  Already joined? Sign in
                </button>
              </SignInButton>
            </div>
            <div className="mt-4">
              <PricingTable />
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-8 space-y-6">
          <div className="rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
            <div className="flex flex-wrap items-center gap-3">
              <div>
                <p className="text-sm font-semibold text-foreground">Signed in</p>
                <p className="text-sm text-foreground/70">{email}</p>
              </div>
              <span className="inline-flex items-center rounded-full border border-[var(--color-border)] px-3 py-1 text-xs font-semibold uppercase tracking-wide text-primary">
                {normalizedTier}
              </span>
              {isInternalTier && (
                <span className="rounded-full bg-yellow-100 px-3 py-1 text-xs font-semibold text-yellow-900">
                  Internal role (assigned manually)
                </span>
              )}
            </div>
            <p className="mt-3 text-sm text-foreground/75">
              Free and Supporter are self-serve plans. Moderator and Admin are internal roles that we tag manually.
              If you need an internal role, please contact the team.
            </p>
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h3 className="text-lg font-semibold text-foreground">Plans</h3>
                <p className="text-sm text-foreground/70">Compare tiers or change your membership.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <SignUpButton
                  mode="modal"
                  forceRedirectUrl="/account"
                  signInForceRedirectUrl="/account"
                  signInFallbackRedirectUrl="/account"
                >
                  <button className="rounded-md bg-primary/90 px-3 py-2 text-sm font-semibold text-white hover:bg-primary">
                    Manage plan
                  </button>
                </SignUpButton>
                <SignInButton mode="modal" forceRedirectUrl="/account" fallbackRedirectUrl="/account">
                  <button className="rounded-md border border-[var(--color-border)] px-3 py-2 text-sm font-medium hover:bg-black/5">
                    Update billing
                  </button>
                </SignInButton>
              </div>
            </div>
            <div className="mt-4">
              <PricingTable />
            </div>
          </div>

          {canSetLocale && (
            <div className="rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-foreground">Local news coverage</h3>
                  <p className="text-sm text-foreground/70">
                    Paying subscribers can tailor local coverage by state and county. We default to your network
                    location when available.
                  </p>
                </div>
                <span className="rounded-full border border-[var(--color-border)] px-3 py-1 text-xs font-semibold uppercase tracking-wide text-primary">
                  {localeStatusLabel}
                </span>
              </div>

              <div className="mt-4 rounded-md border border-[var(--color-border)] bg-background/70 p-4 text-sm text-foreground/80">
                <p className="font-medium text-foreground">Current locale</p>
                <p className="mt-1">{localeLabel}</p>
                <p className="mt-2 text-xs text-foreground/60">
                  County is required to activate county-level scrapers. If we only detect your city, please enter the
                  county to receive the most precise coverage.
                </p>
              </div>

              <form action={saveLocale} className="mt-4 grid gap-4 md:grid-cols-2">
                <label className="text-sm text-foreground/80">
                  Country
                  <input
                    name="country"
                    defaultValue={localeSubscription?.location?.country || defaultLocale?.country || ""}
                    className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm"
                    placeholder="US"
                  />
                </label>
                <label className="text-sm text-foreground/80">
                  State / Province
                  <input
                    name="province"
                    defaultValue={localeSubscription?.location?.province || defaultLocale?.province || ""}
                    className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm"
                    placeholder="California"
                  />
                </label>
                <label className="text-sm text-foreground/80">
                  County
                  <input
                    name="county"
                    defaultValue={localeSubscription?.location?.county || ""}
                    className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm"
                    placeholder="Santa Clara"
                  />
                </label>
                <label className="text-sm text-foreground/80">
                  City (auto-detected if possible)
                  <input
                    name="city"
                    defaultValue={localeSubscription?.location?.city || defaultLocale?.city || ""}
                    className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm"
                    placeholder="San Jose"
                  />
                </label>
                <label className="text-sm text-foreground/80">
                  Township (advanced, optional)
                  <input
                    name="township"
                    defaultValue={(localeSubscription?.location?.subdivisions as { township?: string } | null)?.township || ""}
                    className="mt-1 w-full rounded-md border border-[var(--color-border)] bg-background px-3 py-2 text-sm"
                    placeholder="Downtown"
                  />
                </label>
                <div className="flex items-end gap-2">
                  <button
                    type="submit"
                    className="w-full rounded-md bg-primary/90 px-4 py-2 text-sm font-semibold text-white hover:bg-primary"
                  >
                    Save locale
                  </button>
                </div>
              </form>

              <form action={clearLocale} className="mt-4">
                <button
                  type="submit"
                  className="rounded-md border border-[var(--color-border)] px-4 py-2 text-sm font-medium text-foreground/70 hover:bg-black/5"
                >
                  Clear locale preference
                </button>
              </form>
            </div>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {publicTiers.map((tier) => {
              const isCurrent = normalizedTier === tier.id;
              const disabled = isInternalTier || isCurrent;

              return (
                <div
                  key={tier.id}
                  className="rounded-lg border border-[var(--color-border)] bg-background/60 p-5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-foreground">{tier.name}</p>
                      <p className="text-2xl font-semibold text-primary">{tier.price}</p>
                    </div>
                    {isCurrent ? (
                      <span className="rounded-full bg-green-100 px-3 py-1 text-xs font-semibold text-green-800">
                        Current
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-2 text-sm text-foreground/75">{tier.description}</p>
                  <ul className="mt-3 space-y-1 text-sm text-foreground/80">
                    {tier.features.map((feature) => (
                      <li key={feature} className="flex items-center gap-2">
                        <span className="h-1.5 w-1.5 rounded-full bg-primary/80" aria-hidden />
                        <span>{feature}</span>
                      </li>
                    ))}
                  </ul>
                  <form action={updateTier} className="mt-4">
                    <input type="hidden" name="tier" value={tier.id} />
                    <button
                      type="submit"
                      disabled={disabled}
                      className={`w-full rounded-md px-4 py-2 text-sm font-semibold transition ${
                        disabled
                          ? "cursor-not-allowed border border-[var(--color-border)] text-foreground/50"
                          : tier.id === "supporter"
                            ? "bg-primary/90 text-white hover:bg-primary"
                            : "border border-[var(--color-border)] text-foreground hover:bg-black/5"
                      }`}
                    >
                      {isInternalTier
                        ? "Managed internally"
                        : isCurrent
                          ? "Current tier"
                          : tier.id === "supporter"
                            ? "Upgrade to Supporter"
                            : "Stay on Free"}
                    </button>
                    {tier.id === "supporter" && (
                      <p className="mt-2 text-xs text-foreground/70">
                        Billing is handled outside this prototype. Selecting Supporter tags your account so we can
                        honor your contribution level.
                      </p>
                    )}
                  </form>
                </div>
              );
            })}
          </div>

          <div className="rounded-lg border border-[var(--color-border)] bg-background/60 p-5">
            <h3 className="text-lg font-semibold text-foreground">Internal roles</h3>
            <p className="mt-1 text-sm text-foreground/75">
              Moderator and Admin roles are not purchasable. We tag them manually inside Clerk when inviting team
              members. If your work requires one of these roles, contact the editorial team.
            </p>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {internalTiers.map((tier) => {
                const isCurrent = normalizedTier === tier.id;
                return (
                  <div
                    key={tier.id}
                    className="rounded border border-[var(--color-border)] bg-background/50 p-4"
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-semibold text-foreground">{tier.name}</p>
                        <p className="text-sm text-foreground/70">{tier.description}</p>
                      </div>
                      {isCurrent && (
                        <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-semibold text-blue-800">
                          You&apos;re tagged
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
