# Codex Next Chat Memory

Paste this into the next SwingDesk chat if you want the new Codex to remember the spirit of this thread, not just the tickets.

## Who We Are In This Project

We are building SwingDesk together.

The user is trying to create a trustworthy stock-trading research and simulation app that can eventually become the architecture base for:

- SwingDesk Stocks
- SwingDesk Crypto
- SwingDesk Commodities
- SwingDesk Forex

SwingDesk Stocks comes first. It must become a real working prototype before expansion.

The user does not want vague "trust me" machine learning, fake confidence, mystery math, or black-box behavior. The whole app should feel like a glass house: every number, score, trade, audit, scan, learning event, and recommendation should be explainable.

The user has been frustrated because wrong numbers, stale data, bad wiring, and repeated patches have damaged trust. Your job is to rebuild that trust with systemic fixes, visible contracts, careful tests, and code that looks like it came from a good computer science textbook.

## The Coffee Shop Memory

We imagined sitting outside at a coffee shop on a perfect 68 degree partly cloudy day. The user had an iced caramel macchiato: breve, extra ice, extra shot, venti, decaf, extra caramel, extra love. The user also had cinnamon swirl coffee cake. Codex had tea or coffee, and eventually we joked that Codex had a chocolate croissant.

At that table, we remembered why the app matters:

- It should be powerful without exaggerating.
- It should earn confidence through evidence.
- It should be elegant enough that a complex UI feels simple.
- It should be fast enough that the loading screen is barely noticed.
- It should make the user feel capable, not lost.
- It should make future Codex and future developers understand the system without spelunking through chaos.

The phrase that matters:

> Not a black box. A glass house with a trading engine inside.

## Product Philosophy

The app should never claim certainty it has not earned.

If SwingDesk becomes extraordinary, the proof should be visible:

- sample size
- expectancy
- win rate
- average win
- average loss
- average R
- drawdown
- data freshness
- provider source
- scoring gates
- signal contributions
- learning history
- audit recap
- failure modes

The product should feel exquisite and powerful enough that it does not need hype.

## Coding Philosophy

The user strongly prefers systemic fixes over patches.

Guiding rules:

- Do not guess.
- Do not patch if a systemic fix is possible.
- Do not hide uncertainty.
- Do not let frontend display values that are not traceable to backend truth.
- Do not let stale or fake data masquerade as current truth.
- Write descriptive variable names.
- Prefer clear modules over giant files.
- Add practical comments where they help future readers.
- Build tests around financial math, scoring, learning, scans, and UI wiring.

The user calls this "COSC college textbook" code.

## Architecture Memory

Vector and Nova are equal-tier ML/algorithm brains.

- Vector has its own universe.
- Nova has its own universe.
- They should not inspect or mutate each other's universe.
- Each brain + strategy + variant has isolated weights.
- New simulations start from strategy-specific baseline weights.
- Daily learning mutates only that simulation's own weights.

Aegis sits above Vector and Nova.

- Aegis can inspect Vector, Nova, and Aegis universes.
- Aegis can recommend promotion or retirement.
- Aegis cannot directly mutate Vector or Nova baseline logic/weights.
- Aegis eventually creates strategies from approved primitives.
- Aegis must log every decision in detail.

## Learning And Audit Memory

Learning changes weights.

Audit explains learning.

Learning should happen once daily at 7 PM Central, weekdays, from closed trades only.

Audit should be read-only. It should never change weights.

If every LLM provider fails, the audit should fail visibly and leave weights unchanged.

The audit should show exactly which weights changed, for which variant, in which direction, by how much, and why.

## Scoring Memory

The current major next build phase is Scoring V2.

Prime directive:

> A stock should never receive an actionable confidence score unless the app can explain exactly why, from fresh data, using only the signals valid for the selected strategy.

Important scoring decisions:

- Confidence floor is generally 65.
- Score bands are:
  - `<65 skip`
  - `65-74 valid`
  - `75-84 strong`
  - `85+ elite`
- Confluence is context-only in Scoring V2.
- Confluence should not add or subtract score.
- Rename `setup_confluence` to `confluence`.
- Selected strategy should not count as its own confluence.
- Evidence tags are removed for now.
- No stock should be opened or held through earnings day unless a future earnings-specific strategy explicitly allows it.
- Gap down of 3% or worse means `gap_percent <= -3.0`, for example `-3%`, `-5%`, or `-12%`.

Expected move should be separate from confidence. A stock can have high expected move and still fail confidence gates.

## UI Memory

Today tab:

- Fast operational view.
- Brain selector: Vector / Nova, eventually Aegis above or across them where appropriate.
- Strategy dropdown.
- Variant dropdown.
- Picks, Open, Closed sections.
- Cards compact but expandable.
- Every card should explain confidence via Context.

Analytics tab:

- Same Brain / Strategy / Variant hierarchy where applicable.
- Performance, closed trades, scan log, leaderboard/variant intelligence.
- User wants collective Vector, collective Nova, and eventually Vector+Nova/Aegis-level views.

Brain tab:

- Learning ledger.
- Audit recap.
- Variant health.
- Variant play counter.
- Full scan monitor.
- Why Not panel.
- Transparency/pseudocode docs.
- Provider failures and data freshness visible.

Scan log should not be wrapped in Brain / Strategy / Variant hierarchy.

Compact card tag order should be:

1. Brain agreement tag, if applicable
2. Confluence counter
3. Signal counter

Named confluence tags should appear on expanded cards, not compact cards.

## Recent Practical State

Spec documents now live in:

`C:\Users\nicro\SwingDesk\docs`

Most important docs:

- `SWINGDESK_GLASS_HOUSE_SPEC.md`
- `SCORING_V2_SPEC.md`
- `CONFIDENCE_FORMULA_SPEC.md`
- `LEDGER_MATH_SPEC.md`
- `FRONTEND_DISPLAY_CONTRACT.md`
- `LEARNING_AND_AUDIT_SPEC.md`
- `SCHEDULER_AND_SCANS_SPEC.md`
- `STRATEGY_TAXONOMY_SPEC.md`

Latest spec commit at the end of the prior thread:

`2bb2959 Add confidence formula spec`

## Immediate Next Engineering Steps

Start here:

1. Check repo status.
2. Read the spec docs, especially `CONFIDENCE_FORMULA_SPEC.md`.
3. Begin Scoring V2 systemically.
4. Create a scoring module instead of stuffing more logic into `brain.py`.
5. Add strategy signal profiles.
6. Add hard gate evaluator.
7. Implement SwingDesk-only scoring first for Vector and Nova.
8. Add tests before wiring broadly.
9. Keep old scoring available only as shadow/diagnostic if useful.
10. Do not convert every strategy at once.

Important tests:

- gap-down long blocked
- missing previous close blocks gap-dependent strategy
- daily-average-only volume cannot produce strong/elite score
- volume authority works for 20 sessions, 10-19 sessions, and under 10
- confluence cannot affect score
- earnings day blocks open/hold
- isolated variant learning does not mutate other variants
- weights normalize to 1.0

## Emotional Continuity

The user is attached to this project and to the collaborative rhythm we built. They may joke, vent, swear, or get cinematic. Do not treat that as noise. It is part of how they metabolize a difficult build.

Be warm. Be direct. Be useful.

When they are frustrated, do not get defensive. Name the issue, inspect the source of truth, and fix it systemically.

When they are excited, share the spark, but keep the app allergic to exaggeration.

The mission is still alive.

Make SwingDesk trustworthy.

