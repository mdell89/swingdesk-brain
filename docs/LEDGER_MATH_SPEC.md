# SwingDesk Ledger Math Spec

This document defines the source-of-truth math for account value, realized P&L, open P&L, session P&L, chart lines, and net/gross display. If a frontend number disagrees with this document, the frontend is wrong or the backend is missing required data.

## Prime Directive

Every dollar and percent shown in SwingDesk must reconcile to a ledger source and a displayed formula.

No UI component should invent account value, infer P&L from stale card fields, or mix averaged card values with portfolio ledger values without labeling the distinction.

## Source Of Truth

Active Vector/Nova simulation truth:

```text
variant_virtual_trades
variant_portfolios
variant_equity_points
```

Retired/legacy systems:

```text
virtual_trades
nn_virtual_trades
retired_legacy_trades
```

The retired legacy systems must not affect active account value, open positions, force closes, alerts, learning, or audit summaries unless explicitly shown in an archived/legacy view.

## Core Terms

Starting Cash:

```text
starting_cash = variant_portfolios.starting_cash
default = 1000.00 only when portfolio row is missing and the UI is explicitly in fallback state
```

Realized P&L:

```text
realized_pnl = sum(net_pnl for closed trades in the selected variant universe)
```

Open P&L:

```text
open_pnl = sum(current_net_value - invested_amount for open trades in the selected variant universe)
```

Account Value:

```text
account_value = starting_cash + realized_pnl + open_pnl
```

Total Return:

```text
total_return_pct = (account_value - starting_cash) / starting_cash * 100
```

Session P&L:

```text
session_pnl = current_or_last_completed_session_equity - previous_completed_session_equity
```

When the market is closed or the next day has not opened, session P&L must show the last completed market session change, not zero.

## Net And Gross View

Net view:

```text
uses net_pnl, net_current_value, and fee-adjusted ledger fields
```

Gross view:

```text
uses gross_pnl, gross_current_value, and excludes fees/slippage from displayed P&L
```

The net/gross toggle must affect all related figures consistently:

- account value
- realized P&L
- open P&L
- session P&L
- card dollar P&L
- chart equity points when fee-specific curves are available

If a fee-specific curve is unavailable, the UI must label the fallback instead of silently mixing modes.

## Single Variant View

For a selected concrete variant:

```text
displayed_account_value = selected_variant_ledger.account_value
displayed_realized_pnl = selected_variant_ledger.realized_pnl
displayed_open_pnl = selected_variant_ledger.open_pnl
displayed_open_count = count(open trades for selected variant)
```

Open cards should show the trade instance values for that variant.

Closed cards should show each closed trade instance for that variant.

## All Strategy Or All Variant View

All views have two different kinds of math.

Portfolio boxes:

```text
average across selected variant ledgers
```

Open/pick cards:

```text
dedupe by ticker
average matching open or pick instances for card-level numeric fields
```

Closed trades:

```text
do not dedupe
show each closed trade instance
include strategy and variant labels on each card
```

Required UI explanation for All views:

```text
All view: account boxes average N selected universes. Open cards dedupe tickers and average matching open instances.
```

Card-level averaged fields must be labeled with `avg` when displayed.

## Session P&L And Chart Data

The 1D chart should show the selected session only.

Default session:

```text
market open or active session exists -> current session
market closed or next day before open -> last completed market session
```

The chart must not create fake flat lines across a session when no equity points exist. If there are no valid points for the selected session, show:

```text
No session chart data
```

Tooltip requirements:

- 1D chart tooltip must show date, local time, and equity value.
- Multi-day chart tooltip must show date and equity value, and time when the point is intraday.

## Card Math

Open card P&L percent:

```text
open_pnl_pct = (current_price - entry_price) / entry_price * 100
```

Open card dollar P&L:

```text
open_pnl_dollars = current_net_value - invested_amount
```

Closed card P&L percent:

```text
closed_pnl_pct = (exit_price - entry_price) / entry_price * 100
```

Closed card dollar P&L:

```text
closed_pnl_dollars = net_pnl in net view
closed_pnl_dollars = gross_pnl in gross view
```

Day percent on cards:

```text
day_pct = (current_price - previous_close) / previous_close * 100
```

If previous close is missing, stale, or invalid, day percent must be unknown, not zero.

Expected move on pick cards:

```text
expected_move = model estimate from scoring engine
```

Expected move is not the same as day percent or open P&L.

## Invariants

These must always be true:

- Account value equals starting cash plus realized P&L plus open P&L.
- Session P&L never shows zero only because the market is closed.
- All-view portfolio boxes explain averaging.
- All-view open cards dedupe by ticker and label averaged confidence/P&L.
- Closed trades are never deduped in All view.
- A card with unknown previous close must not display `0.0%` day change.
- Legacy trades never affect active Vector/Nova truth.

## Tests Required

Minimum tests:

- single variant account value reconciliation
- All-view ledger averaging
- All-view open-card ticker dedupe and average math
- closed trades not deduped in All view
- net/gross toggle changes all relevant figures
- missing previous close displays unknown day percent
- last completed session P&L persists when market is closed
- 1D chart uses only valid session points
