import { SignInButton, SignUpButton } from "@clerk/nextjs";
import { auth, clerkClient, currentUser } from "@clerk/nextjs/server";
import type { Metadata } from "next";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

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

async function updateTier(formData: FormData) {
  "use server";

  const { userId } = auth();
  if (!userId) {
    redirect("/sign-in");
  }

  const tier = formData.get("tier");
  if (tier !== "free" && tier !== "supporter") {
    return;
  }

  await clerkClient.users.updateUserMetadata(userId, {
    publicMetadata: { tier },
  });

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
  const primaryEmail =
    user?.emailAddresses?.find((address) => address.id === user.primaryEmailAddressId)?.emailAddress ||
    user?.emailAddresses?.[0]?.emailAddress;
  const email = primaryEmail || user?.username || user?.firstName;

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
        <div className="mt-8 rounded-lg border border-[var(--color-border)] bg-background/60 p-6">
          <h2 className="text-xl font-semibold text-foreground">Sign in to continue</h2>
          <p className="mt-2 text-sm text-foreground/80">
            Create an account or sign in to manage your membership tier.
          </p>
          <div className="mt-4 flex flex-wrap gap-3">
            <SignInButton mode="modal" redirectUrl="/account">
              <button className="rounded border border-[var(--color-border)] px-4 py-2 text-sm font-medium transition hover:bg-black/5">
                Sign in
              </button>
            </SignInButton>
            <SignUpButton mode="modal" redirectUrl="/account">
              <button className="rounded bg-primary/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary">
                Create account
              </button>
            </SignUpButton>
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
