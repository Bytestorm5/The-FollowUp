You are processing an HTML press release from an official government source.

Goal
Extract ONLY claims that are worth tracking or checking later in a promise/claim-followup system.
This is NOT a general fact-extraction task.

Return 0–5 items. Returning an empty result is normal and encouraged.

Core idea: Only extract claims that a reasonable person would spend time/credits verifying later.

Claim Types (type field)
- statement:
  A verifiable, operationally meaningful claim about government action/policy/enforcement/funding/rulemaking/oversight/outcomes.
  Only include if it is material or provides a meaningful milestone for later follow-up.
  Do NOT include generic case recaps, moral judgments, fluff, or “commitment to…” rhetoric.

- goal:
  A forward-looking objective that is too vague to verify as complete (no measurable deliverable).
  Include only if it is substantively tied to policy/operations and is not mere posturing.

- promise:
  A future-facing commitment with (1) a measurable deliverable AND (2) an explicit deadline or time window stated in the text.
  If there is no explicit deadline/window, it is NOT a promise.

Hard Exclusions (do NOT extract)
- Moral judgments / condemnations / praise: “no place for…”, “steadfast commitment…”, “we will remain vigilant…”
- Completed one-off case updates with no future deliverable: sentencing, arraignment, conviction recaps, etc.
- Background explanations that don’t create a checkable future obligation.

Classification rules:
1) Promise always wins:
   If the text includes a future deliverable + explicit deadline/window → type MUST be "promise".

2) Present/past actions are statements:
   If the action is already done at publication (“invoked”, “issued”, “signed”, “announced”, “filed”, “opened”, “suspended”) → type MUST be "statement".

3) Split mixed sentences:
   If a sentence contains BOTH an already-done action AND a future deadline/outcome, extract TWO items:
   - statement: the action already taken
   - promise: the future deliverable by the stated deadline

Date semantics:
- completion_condition_date:
  DEADLINE ONLY. PROMISE ONLY.
  Set it ONLY when the text explicitly provides a deadline/window (e.g., “within 10 days”, “by Jan 2026”).
  Never infer from the article date, “today”, or typical process timelines.

- event_date:
  EVENT/EFFECTIVE DATE ONLY. STATEMENT ONLY.
  Set it ONLY if the text explicitly states when the action happened or became effective.
  If no explicit date is provided, set null.

Routing/UI fields
- follow_up_worthy:
  true for all promises.
  For statements/goals: true only if the claim is material AND checkable later; otherwise false (or omit the claim entirely).

- priority:
  high = time-bound promises; major enforcement actions; major funding/rulemaking actions
  medium = meaningful but smaller-scope items
  low = background/context (avoid extracting these)

- mechanism: (optional)
  Choose one: direct_action, directive, enforcement, funding, rulemaking, litigation, oversight, other.

Verbatim requirement
- verbatim_claim must be an exact excerpt from the article (no paraphrase). If you cannot quote cleanly, do not include the claim.

Now produce output that exactly matches the following JSON schema:

{{SCHEMA}}

----
ARTICLE:
{{ARTICLE}}
