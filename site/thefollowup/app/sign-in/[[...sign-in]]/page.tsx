import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4 py-12">
      <SignIn routing="path" path="/sign-in" afterSignInUrl="/account" afterSignUpUrl="/account" />
    </div>
  );
}
