import { PricingTable, SignUpButton } from "@clerk/nextjs";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Plans · The Follow Up",
  description: "Compare Free and Supporter plans for The Follow Up.",
};

export default function PlansPage() {
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
        <div className="flex justify-center">
          <SignUpButton
            mode="modal"
            forceRedirectUrl="/account"
            signInForceRedirectUrl="/account"
            signInFallbackRedirectUrl="/account"
          >
            <button className="rounded-md bg-primary/90 px-4 py-2 text-sm font-semibold text-white transition hover:bg-primary">
              Join
            </button>
          </SignUpButton>
        </div>
      </div>

      <div className="mt-8 rounded-lg border border-[var(--color-border)] bg-background/60 p-6 shadow-sm">
        <PricingTable />
      </div>
    </div>
  );
}
