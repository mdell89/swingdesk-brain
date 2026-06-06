# SwingDesk Glass House Spec

This document is the durable product and engineering memory for SwingDesk. It should be updated whenever core behavior changes. The goal is simple: SwingDesk must never feel like a black box. Every number, pick, trade, audit, scan, and learning event should be explainable from visible evidence and source-of-truth backend records.

## Mission

SwingDesk Stocks is the first trustworthy working prototype. It is the architecture base for SwingDesk Crypto, SwingDesk Commodities, and SwingDesk Forex.

The priority order is:

1. Backend correctness.
2. Learning and audit correctness.
3. UI wiring accuracy.
4. Frontend polish after truth is visible.

SwingDesk should be useful for personal trading decisions only when the displayed data is fresh, reconciled, and explainable.

## Spec Suite

This document is the top-level product and engineering memory. Detailed contracts live in:

- `SCORING_V2_SPEC.md`: confidence scoring, gates, signals, confluence, volume, and explainability.
- `LEDGER_MATH_SPEC.md`: account value, realized P&L, open P&L, session P&L, chart math, and net/gross display.
- `STRATEGY_TAXONOMY_SPEC.md`: brain, strategy, variant, signal, confluence, and brain-agreement definitions.
- `SCHEDULER_AND_SCANS_SPEC.md`: scheduled jobs, scan freshness, provider behavior, monitoring, stalls, and retention.
- `LEARNING_AND_AUDIT_SPEC.md`: daily ML learning, read-only audit recap, LLM provider fallback, and learning ledger rules.
- `FRONTEND_DISPLAY_CONTRACT.md`: UI labels, card display, chart behavior, tags, context tray, and settings expectations.

## Brain Roles

Vector and Nova are equal-tier ML/algorithm workers.

- Vector has its own universe and sandbox.
- Nova has its own universe and sandbox.
- Vector and Nova should not inspect or mutate each other's universe.
- Aegis sits above both.
- Aegis may see Vector, Nova, and Aegis universes.
- Aegis may recommend promotion or retirement of Vector/Nova variants.
- Aegis may not modify Vector/Nova baseline logic or weights.
- Aegis has its own sandbox of strategies and variants, initially capped around 10 active strategies.
- Aegis should eventually create custom strategies from approved primitives, not arbitrary code.
- Aegis must log every decision in detail.

## Taxonomy

Use these terms consistently in code, data, and UI.

```text
Brain
  Vector
  Nova
  Aegis

Strategy
  A standalone trading system.
  Has entry rules, exit rules, scoring profile, and performance ledger.

Variant
  A controlled variation inside a strategy.
  Examples: entry time, exit rule, risk sizing, selection mode.

Signal
  A numeric or categorical input used by scoring when enabled by a strategy profile.

Confluence
  A contextual agreement tag.
  May be another standalone strategy agreeing, or a meaningful setup context like Open Air.
  Named confluence tags should appear on expanded cards, not compact cards.

Brain Agreement
  A tag showing that the other ML brain also picked or holds the ticker.
  Example: Vector view shows a Nova tag when Nova also agrees.

Context Only
  Visible educational or diagnostic context that does not affect score or learning.

Disabled
  Ignored by scoring and learning for that strategy.
```

## Strategy And Variant Scope

Strategies must be meaningfully distinct. If two strategies overlap heavily, keep the better-defined strategy and remove or merge the redundant one. Redundancy clutters the database and weakens Aegis research quality.

Current direction:

- Keep strategy profiles explicit.
- Apply new exit-rule variants first to SwingDesk only.
- Expand high-performing variants into other strategies only after evidence justifies it.
- Remove or retire intraday-only strategies from SwingDesk Stocks until day-trading support is intentionally designed.
- NR7 should not remain as a standalone strategy unless a future audit proves it is meaningfully distinct.

Candidate SwingDesk exit variants:

- Baseline: hold winners through the existing session logic; do not sell only because a target was hit.
- Target cashout: sell when estimated target is hit, otherwise exit by normal time/cut rules.
- Trailing winner: protect target gains while allowing upside.
- Hold while score improves: extend only if current score/conditions improve and risk remains controlled.

## Data Truth Rules

Every displayed number must come from a named source of truth.

```text
Account value
  = starting capital + realized P&L + open P&L

Realized P&L
  = sum of closed trades in the selected brain/strategy/variant scope

Open P&L
  = sum or documented aggregation of currently open variant trades

All view open cards
  = deduped by ticker
  = average variant-specific numeric values for matching open instances
  = expanded card should disclose contributing variants and timestamps

All view closed trades
  = not deduped
  = each closed card must show the variant identity

Session P&L
  = last completed market session change when market is closed
  = live current-session change when market is open
  = never silently zero because the market is closed
```

## Scan Reliability Rules

A scan is trustworthy only when it leaves an audit trail.

Required scan telemetry:

- scan type
- start time
- finish time
- attempted ticker count
- successful ticker count
- failed ticker list
- provider attempts
- rate-limit and timeout failures
- data freshness
- current ticker names while scanning

Open-position monitoring:

- Simulated open-position monitoring should default to a 3-minute regular-session cadence unless testing proves a faster interval materially improves decisions.
- Extended-hours monitoring may stay slower, around 5 minutes.
- Real broker-connected trading should use a separate real-time or near-real-time path later; it should not inherit the simulated monitor cadence blindly.

Decision eligibility:

- Full scans must be checkpointed and resumable.
- Stalled scans must be loudly marked and auto-retried.
- Variant execution must not open trades from stale or incomplete scans.
- If no fresh completed scan exists, execution should skip and explain why.
- Scan log should retain raw operational detail for 30 days.
- Older summary retention may be kept for 3 to 6 months if useful for provider health trends.

## Learning And Audit Rules

Learning and audit are separate.

Learning:

- Runs daily at 7:00 PM Central.
- Uses closed trades only.
- Uses only learnable signals enabled by each strategy profile.
- Logs every weight adjustment by variant, signal, direction, amount, and reason.
- Does not learn from open trades.

Audit:

- Is a read-only LLM recap.
- Must not change weights.
- Explains what the ML ledger already changed.
- Must show provider failures.
- If all LLM providers fail, audit fails visibly and does not pretend to learn.

## UI Hierarchy

Today tab:

- Fast operational view.
- Brain: Vector / Nova, later Aegis aggregate when real.
- Strategy dropdown: SwingDesk, Darvas, Gap & Go, VWAP Reclaim, etc., plus All.
- Variant dropdown: strategy-specific variants, plus All.
- Cards grouped into Picks, Open, Closed.
- Cards compact by default and expandable.
- Context tray explains confidence.

Analytics tab:

- Same Brain / Strategy / Variant hierarchy.
- Performance, Closed Trades, Scan Log, Leaderboard.
- Scan Log does not need the hierarchy if it is global operational telemetry.
- Win rate, expectancy, avg R, average win/loss, sample size, annualized estimate.
- Closed trades in All view show each variant and are not deduped.

Brain tab:

- Learning ledger.
- Audit recap.
- Variant health.
- Variant play counter.
- Full scan monitor.
- Why Not.
- Transparency/pseudocode docs.
- Provider failures and data freshness.

## Transparency Sections

The app should include expandable explanations for important operations. These should mirror repo docs and be updated whenever logic changes.

Operations to document:

- comprehensive scan pipeline
- Why Not scoring gates
- variant universe selection
- All aggregation math
- open-position monitor
- simulated exits/model stops
- 7 PM daily learning batch
- read-only audit recap
- Net/Gross fee math
- data freshness checks
- provider fallback chain
- Aegis promotion/retirement
- scoring v2 pipeline

## Deprecated Systems

The legacy `virtual_trades` and `nn_virtual_trades` active trading systems are retired. Vector/Nova variant universes are the live source of truth. Open legacy rows should be archived into `retired_legacy_trades`, not allowed to open, monitor, force-close, alert, or affect active portfolio truth.
