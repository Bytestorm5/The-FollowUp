"use client";

import Link from "next/link";
import { useState, useEffect } from "react";

export default function NavBar() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <div className="mx-auto max-w-5xl px-4">
        {/* Mobile bar */}
        <div className="mt-3 flex h-12 items-center justify-between rounded-full bg-background/80 px-4 ring-1 ring-black/[.06] backdrop-blur lg:hidden">
          <button aria-label="Open menu" aria-expanded={open} aria-controls="mobile-drawer" onClick={() => setOpen(true)} className="flex flex-col gap-1">
            <span className="block h-0.5 w-6 bg-foreground" />
            <span className="block h-0.5 w-6 bg-foreground" />
            <span className="block h-0.5 w-6 bg-foreground" />
          </button>
          <Link href="/" className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-full bg-primary/90" />
            <span className="text-sm tracking-wide text-primary">THE FOLLOW UP</span>
          </Link>
          <div className="w-6" />
        </div>

        {/* Desktop nav */}
        <nav
          aria-label="Primary"
          className="fade-border-b mx-auto mt-4 hidden h-14 w-full max-w-2xl items-center justify-center gap-8 rounded-full bg-background/80 px-8 shadow-sm ring-1 ring-black/[.06] backdrop-blur lg:flex"
        >
          <Link href="/" className="flex items-center gap-2">
            <div className="h-6 w-6 rounded-full bg-primary/90" />
            <span className="text-sm tracking-wide text-primary">THE FOLLOW UP</span>
          </Link>

          <div className="h-5 w-px bg-black/10" aria-hidden="true" />

          <Link href="/feed" className="text-sm font-medium text-foreground hover:opacity-80">Feed</Link>
          <Link href="/fact_checks" className="text-sm font-medium text-foreground hover:opacity-80">Fact Checks</Link>
          <div className="relative inline-block group">
            <Link href="/countdowns" className="text-sm font-medium text-foreground hover:opacity-80">Countdowns</Link>
            <div className="invisible absolute left-1/2 top-full z-50 w-44 -translate-x-1/2 rounded-md border border-[var(--color-border)] bg-background p-1 text-sm opacity-0 shadow-md transition group-hover:visible group-hover:opacity-100 group-hover:pointer-events-auto">
              <Link href="/countdowns/past" className="block rounded px-3 py-2 hover:bg-black/5">Past Countdowns</Link>
            </div>
          </div>
          <div className="relative inline-block group">
            <Link href="/about" className="text-sm font-medium text-foreground hover:opacity-80">About</Link>
          </div>
        </nav>
      </div>

      {/* Overlay */}
      {open && <div className="fixed inset-0 z-40 bg-black/40 lg:hidden" onClick={() => setOpen(false)} aria-hidden />}

      {/* Drawer */}
      <aside
        id="mobile-drawer"
        className={`fixed inset-y-0 left-0 z-50 w-72 transform bg-background p-4 shadow-lg ring-1 ring-black/[.06] transition-transform duration-300 lg:hidden ${open ? "translate-x-0" : "-translate-x-full"}`}
        role="dialog"
        aria-modal="true"
      >
        <div className="mb-4 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2" onClick={() => setOpen(false)}>
            <div className="h-6 w-6 rounded-full bg-primary/90" />
            <span className="text-sm tracking-wide text-primary">THE FOLLOW UP</span>
          </Link>
          <button aria-label="Close menu" onClick={() => setOpen(false)}>
            <span className="block h-0.5 w-6 rotate-45 bg-foreground" />
          </button>
        </div>
        <nav className="flex flex-col gap-2 text-sm">
          <Link href="/feed" className="rounded px-2 py-2 hover:bg-black/5" onClick={() => setOpen(false)}>Feed</Link>
          <Link href="/fact_checks" className="rounded px-2 py-2 hover:bg-black/5" onClick={() => setOpen(false)}>Fact Checks</Link>
          <div className="mt-2 font-semibold text-foreground/80">Countdowns</div>
          <Link href="/countdowns" className="rounded px-2 py-2 hover:bg-black/5" onClick={() => setOpen(false)}>Active Countdowns</Link>
          <Link href="/countdowns/past" className="rounded px-2 py-2 hover:bg-black/5" onClick={() => setOpen(false)}>Past Countdowns</Link>
          <Link href="/about" className="rounded px-2 py-2 hover:bg-black/5" onClick={() => setOpen(false)}>About</Link>
        </nav>
      </aside>
    </header>
  );
}
