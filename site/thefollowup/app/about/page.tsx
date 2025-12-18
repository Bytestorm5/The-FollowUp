export const dynamic = "force-static";

export default function AboutPage() {
  return (
    <div className="min-h-screen w-full bg-background text-foreground">
  <div className="mx-auto max-w-3xl px-4 py-8">
    <div className="dateline mb-1">About</div>
    <h1
      className="text-3xl font-semibold tracking-tight"
      style={{ fontFamily: "var(--font-serif)" }}
    >
      Mission
    </h1>
    <hr className="mt-4" />

    <p className="mt-6 text-foreground/80">
      Modern politics runs on headlines. Leaders announce bold plans, enjoy the
      news cycle, and move on long before anyone checks whether those promises
      were kept. When the actual policy turns out to be impractical, unpopular, or
      inconvenient, leaders walk it back quietly, in hopes that it'll fade into the background noise.
    </p>

    <p className="mt-6 text-foreground/80">
      This tactic isn’t new, but it has become supercharged by an information
      environment built to overwhelm us. The increasingly popular strategy of{" "}
      <a className="underline" href="https://en.wikipedia.org/wiki/Flood_the_zone">
        “flooding the zone”
      </a>{" "}
      makes it nearly impossible for ordinary people to keep track of what was
      said, when it was supposed to happen, and what the outcome actually was.
      As a result, many of us end up relying on fragmented social media feeds,
      vulnerable to manipulation by algorithms and corporate incentives we do
      not control.
    </p>

    <p className="mt-6 text-foreground/80">
      <span className="font-semibold">The Follow Up</span> exists as an attempt 
      to restore memory and accountability. We systematically log concrete promises made to the press, and perform regular check-ins to determine if they've been delivered on. 
      We aim to capture as much of the "zone" as possible, and from there we can begin to systematically sift what's important from what's not.
    </p>

    <p className="mt-6 text-foreground/80">
      In an era of disposable headlines, The Follow Up is built around a simple idea:
      <span className="font-semibold"> if they said it, we should remember it.</span>
    </p>
    <h2
      className="text-2xl font-semibold tracking-tight mt-6"
      style={{ fontFamily: "var(--font-serif)" }}
    >
      Note on AI Usage
    </h2>
    <p className="mt-6 text-foreground/80">
        We utilize AI for much of the processing and fact checking done by the Follow Up. 
        While this is hopefully very obvious, we do feel it's important to state this explicity; too frequently, organizations try to sneak it past you and say "see! it wasn't so bad!"
    </p>
    <p className="mt-6 text-foreground/80">
        We know many people are uncomfortable with AI, in large part directly because of how strongly large companies push it. 
        Despite this, we believe this it is an immensely valuable tool that we all, collectively, would be foolish to reject.
    </p>
    <p className="mt-6 text-foreground/80">
        The difference, which we hope is apparent, is that we are not <i>dogmatic</i> on AI. 
        It is <i>just</i> a tool, one that is fallible and one that can break.
        This is why we split our processing into well-defined, bounded tasks. 
        One of the biggest mistakes people make in the AI industry is throwing extremely unspecified problems at AI models, under some false hope of a higher intelligence within.
    </p>
    <p className="mt-6 text-foreground/80">
        As time goes on, we hope to be able to introduce more ways to "check and balance" the AI with human feedback, and if funding allows, our own models informed by human review.
        But that's a long ways away. This is an individual project built between a million other tasks, and a single person can only do so much.
    </p>
  </div>
</div>

  );
}
