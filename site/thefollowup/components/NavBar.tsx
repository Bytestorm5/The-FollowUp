import Link from "next/link";

export default function NavBar() {
  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <div className="mx-auto max-w-5xl px-4">
        <nav
          aria-label="Primary"
          className="fade-border-b mx-auto mt-4 flex h-14 w-full max-w-xl items-center justify-center gap-8 rounded-full bg-background/80 px-6 shadow-sm ring-1 ring-black/[.06] backdrop-blur"
        >
          {/* Placeholder Logo */}
          <Link href="/" className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-full bg-primary/90" />
            <span className="text-sm tracking-wide text-primary">THE FOLLOW UP</span>
          </Link>

          <div className="h-5 w-px bg-black/10" aria-hidden="true" />

          <Link href="/feed" className="text-sm font-medium text-foreground hover:opacity-80">
            Feed
          </Link>
          <Link href="#" className="text-sm font-medium text-foreground hover:opacity-80">
            Countdowns
          </Link>
          <Link href="#" className="text-sm font-medium text-foreground hover:opacity-80">
            About
          </Link>
        </nav>
      </div>
    </header>
  );
}
