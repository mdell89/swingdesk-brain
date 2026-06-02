# SwingDesk Taxonomy

SwingDesk uses three related concepts that must stay distinct.

## Confluence Method

A confluence method is descriptive evidence. It says a stock resembles a known setup, but it does not automatically mean SwingDesk is running a full standalone strategy for that setup.

Examples:

- Darvas
- Gap & Go
- VWAP Reclaim
- Inside Day
- NR7
- Bull Flag
- Pocket Pivot
- Vol Squeeze Breakout

Confluence methods appear as card tags and support confidence/context explanations.

## Strategy

A strategy is a standalone trading system. It must have its own entry rules, exit rules, performance ledger, and explainability contract before it should be treated as a true independent simulation universe.

`SwingDesk` is the primary strategy while the stock prototype is being hardened.

Some confluence methods may eventually become standalone strategies, but they must be audited first. Until then, they should be understood as method lenses or experimental strategy filters, not automatically faithful textbook implementations.

## Variant

A variant is a controlled experiment inside a strategy.

Examples:

- Brain: Vector or Nova
- Entry time: 05:00, 06:00, 07:00, 08:45, regular-session
- Exit rule: baseline, target cashout, trailing winner, hold while score improves
- Selection mode: legacy All/Top 1/Top 3 dimension, currently only All is active
- Risk sizing or future filters

## Simulation Universe

The database table `strategy_variants` stores simulation universes. The table name is historical. A row combines strategy/method label, brain, entry time, selection mode, exit mode, and portfolio ledger.

Do not assume every row in `strategy_variants` is a fully independent standalone strategy. Some rows currently represent confluence-method filters run through shared simulation plumbing.

## Current Expansion Rule

New exit variants should first apply only to the primary SwingDesk 8:45 universes:

- SwingDesk / Vector / 08:45
- SwingDesk / Nova / 08:45

After the exit plumbing, ledger math, learning logs, and UI hierarchy are proven, the best exit variants can be selectively tested on audited standalone strategies.
