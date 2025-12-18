import Link from "next/link";

export default function NavBar() {
  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <div className="mx-auto max-w-5xl px-4">
        <nav
          aria-label="Primary"
          className="fade-border-b mx-auto mt-4 flex h-14 w-full max-w-2xl items-center justify-center gap-8 rounded-full bg-background/80 px-8 shadow-sm ring-1 ring-black/[.06] backdrop-blur"
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
          <Link href="/fact_checks" className="text-sm font-medium text-foreground hover:opacity-80">
            Fact Checks
          </Link>
          <div className="relative inline-block group">
            <Link href="/countdowns" className="text-sm font-medium text-foreground hover:opacity-80">
              Countdowns
            </Link>
            <div className="invisible absolute left-1/2 top-full z-50 w-44 -translate-x-1/2 rounded-md border border-[var(--color-border)] bg-background p-1 text-sm opacity-0 shadow-md transition group-hover:visible group-hover:opacity-100 group-hover:pointer-events-auto">
              <Link href="/countdowns/past" className="block rounded px-3 py-2 hover:bg-black/5">
                Past Countdowns
              </Link>
            </div>
          </div>
          <Link href="/about" className="text-sm font-medium text-foreground hover:opacity-80">
              About
            </Link>
        </nav>
      </div>
    </header>
  );
}
