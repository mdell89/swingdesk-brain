# SwingDesk Strategy Taxonomy Spec

This document defines the language and ownership boundaries for strategies, variants, signals, confluence, and brain agreement.

## Prime Directive

SwingDesk must never use strategy, method, confluence, signal, and variant as interchangeable words.

If the taxonomy is confused, scoring, learning, UI tags, and performance metrics become untrustworthy.

## Brain

A brain is a top-level simulation intelligence.

Current brains:

```text
Vector
Nova
Aegis
```

Vector and Nova are equal-tier ML/algorithm workers. Each has its own universe and sandbox. Vector and Nova should not inspect each other's internal universe.

Aegis sits above Vector and Nova. Aegis may inspect Vector, Nova, and Aegis universes. Aegis may recommend promotions/retirements, but cannot directly mutate Vector/Nova baseline logic or weights.

## Strategy

A strategy is a standalone trading system.

A strategy must define:

- entry rules
- exit rules
- required data
- scoring gates
- signal profile
- confluence behavior
- performance ledger
- active/inactive status

Examples of candidate strategies:

```text
SwingDesk
Darvas
Gap & Go
VWAP Reclaim
Vol Squeeze Breakout
Bull Flag
Pocket Pivot
Donchian
EMA 9/21 Trend Pullback
EMA 50 Trend Pullback
EMA 200 Trend Pullback
Bullish Mean Reversion
```

Strategies requiring audit before mature status:

- any method-derived strategy whose entry/exit rules are not faithful to the named setup
- EMA strategies until real EMA profile/scoring exists
- any strategy with more than 50% overlap against another active strategy

Removed or rejected from SwingDesk Stocks strategy list:

- Opening Range Hold, because it is intraday/day-trading oriented
- NR7 as standalone strategy, because it overlaps too strongly with volatility compression logic
- S&R as standalone strategy when it duplicates Darvas/support-resistance logic

## Variant

A variant is a controlled experiment inside a strategy.

Variant dimensions may include:

- entry time
- exit rule
- risk sizing
- selection mode
- filter strictness

Current priority: apply new exit-rule variants first to SwingDesk only. If a variant proves useful, Aegis may later recommend testing it elsewhere.

Approved SwingDesk exit-rule variants to consider:

- baseline: hold winners through existing session logic; target hit does not force exit
- target cashout: close when estimated target is hit, otherwise follow normal time/loss rules
- half carry: at the first 2:45 PM cutoff, sell 50% if the long thesis persists and carry the remaining 50% into the next regular session; sell the carried half early on meaningful reversal or by the next 2:45 PM cutoff.

Initial SwingDesk exit-mode matrix:

```text
2 engines (SwingDesk, SwingDesk V2)
x 2 brains (Vector, Nova)
x 4 entry times (05:00, 06:00, 07:00, 08:45)
x 3 exit modes (baseline, target_cashout, half_carry)
= 48 variants
```

Exit modes are mutually exclusive controlled experiments until evidence justifies testing combined modes.

Strategies with non-negotiable native exit rules may opt out of the generic SwingDesk exit-mode matrix, but the opt-out must be explicit in the strategy profile.

## Signal

A signal is a numeric or categorical input used by scoring.

Canonical signal examples:

```text
rsi_momentum
volume_surge
overnight_gap_probability
earnings_catalyst
support_resistance
relative_strength
sector_relative_strength
vwap_reclaim
volatility_squeeze
```

Every strategy must define a signal profile:

```text
signal_name:
  role: active | secondary | context_only | disabled
  learnable: true | false
  reason: short explanation
```

Rules:

- active signals can affect confidence
- secondary signals can affect confidence at lower authority
- context_only signals can appear in UI explanations but cannot affect confidence
- disabled signals are ignored
- only learnable active/secondary signals can be adjusted by ML

## Confluence

Use the name `confluence`, not `setup_confluence`.

Confluence is a contextual agreement tag. It may come from a standalone strategy or a meaningful non-strategy setup condition.

Confluence categories:

```text
strategy_agreement
setup_context
market_context
```

Examples:

```text
Darvas
VWAP Reclaim
Bull Flag
Support Bounce
Sector Leader
Unusual Volume
```

Open Air is not a confluence tag by itself. It is setup context meaning resistance is not nearby; it does not prove demand, a bounce, or a breakout.

Compact cards should show counters, not named confluence tags:

```text
[Nova] [2/10 confluence] [3/9 signals]
```

Expanded cards may show named confluence tags.

Named confluence tags should not include the currently selected strategy as if it were outside agreement. If SwingDesk is selected, SwingDesk should not appear as a confluence tag on its own cards.

## Brain Agreement Tags

Brain agreement tags show cross-brain alignment.

If Vector is selected and Nova also has the same ticker as a pick or open position, show:

```text
Nova
```

If Nova is selected and Vector also has the same ticker as a pick or open position, show:

```text
Vector
```

Brain agreement tags should appear leftmost among compact-card tags.

## Redundancy Rule

Two candidate strategies with more than roughly 50% entry/qualified-pick overlap should not both remain active unless they answer meaningfully different research questions.

Redundancy audit should compare:

- same-day qualified ticker overlap
- trade overlap
- signal profile overlap
- exit-rule overlap
- unique explanatory value

If two strategies are redundant, keep the clearer, more popular, or more profitable one after sufficient data.

## Tests Required

Minimum tests:

- selected strategy is excluded from its own confluence tags
- compact cards show counters, not named confluence tags
- expanded cards show named confluence tags
- brain agreement tags appear only when the other brain agrees
- disabled/context-only signals cannot affect confidence
- disabled/context-only signals cannot be learned
- removed strategies are not active execution strategies
