import type { NextConfig } from "next";

const clerkPublishableKey =
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ||
  process.env.CLERK_PUBLISHABLE_KEY ||
  "pk_test_Y2xlcmsuZGV2LmV4YW1wbGUuY29tJA==";

const nextConfig: NextConfig = {
  env: {
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: clerkPublishableKey,
    CLERK_PUBLISHABLE_KEY: clerkPublishableKey,
  },
};

export default nextConfig;
