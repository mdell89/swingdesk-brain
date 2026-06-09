# SwingDesk Frontend Display Contract

This document defines what the frontend may show and what each displayed number means.

## Prime Directive

The UI must not make backend truth look simpler than it is.

When values are averaged, stale, unavailable, provisional, or aggregate, the UI must label them plainly.

## Top Header

Account value:

```text
selected ledger account_value
```

Total return:

```text
(account_value - starting_cash) / starting_cash
```

Inline text under account value:

```text
TOTAL RETURN +X.XX% +$Y.YY (realized + open)
```

Session P&L:

```text
active market: current session P&L
market closed / before next open: last completed session P&L
```

Session P&L label:

```text
Session P&L - current session
Session P&L - last session
Session P&L - unavailable
```

No session P&L should show `$0.00` just because no current market session is active.

## Performance Chart

Default timeframe:

```text
1D
```

1D chart:

- uses the selected/current session when active
- uses the last completed session when market is closed or before next open
- shows no fake line when no valid points exist
- tooltip includes date, local time, and equity value

Other charts:

- use historical equity points for the selected brain/strategy/variant
- tooltip includes date and equity value
- include time when points are intraday

## Brain/Strategy/Variant Controls

Today and Analytics should share the same hierarchy where applicable:

```text
Brain: Aegis / Vector / Nova
Strategy: All / strategy name
Variant: All / variant name
```

Scan Log should not be wrapped in this hierarchy.

Aegis visual style:

- same control style as Vector/Nova
- gold accent
- full-width parent button may sit above Vector/Nova when showing cross-brain aggregate views

## Summary Boxes

Open P&L:

```text
selected ledger open_pnl
```

Realized:

```text
selected ledger realized_pnl
```

PDT:

```text
day trades used / allowed
```

Open:

```text
count of open trades in selected universe
```

When All is selected:

- boxes may average selected universes
- explanatory muted text is required

## Pick Cards

Pick cards show candidates, not open trades.

Required fields:

- ticker
- day percent or unknown
- expected move
- confidence
- brain agreement tag when applicable
- confluence counter
- signal counter

Expected move is the model estimate, not the day percent.

Pick confidence must be actionable under the selected strategy floor unless the UI explicitly labels the pick as fallback/provisional.

Card percent labels:

```text
DAY / %CHG
  = current or scan price versus the prior completed regular-session close.
  = never postmarket-only movement.
  = unknown when previous close is missing, stale, suspect, or invalid.

GAP
  = session/premarket reference price versus the prior completed regular-session close.
  = separate from DAY.

POST
  = optional explicit postmarket-only movement versus the current day's regular-session close.
  = must never populate DAY / %CHG.
```

V2 watchlists should hide rows with expected move below 3.0% unless the UI is in an explicit diagnostic/debug mode.

## Open Cards

Open cards show active simulated positions.

Required fields:

- ticker
- day percent or unknown
- open P&L percent
- open P&L dollars
- current confidence
- status text
- brain agreement tag when applicable
- confluence counter
- signal counter

If the card is aggregated from multiple open instances, show `avg` beside confidence/P&L where applicable and explain the aggregation in expanded state.

## Closed Cards

Closed cards show closed trade instances.

Closed trades are not deduped in All view.

When All is selected, closed cards must include:

- brain
- strategy
- variant
- opened date/time
- closed date/time
- entry
- exit
- reason
- net/gross P&L according to toggle

## Tags

Compact card tag order:

```text
[Brain agreement] [confluence counter] [signal counter]
```

Evidence tags are removed for now and should not display until redesigned.

Named confluence tags appear on expanded cards only.

The selected strategy should not appear as its own confluence tag.

## Context Tray

Context should explain confidence without confusing percentage tiles.

Preferred row style:

```text
Signal name | value | status | reason
```

Examples:

```text
RSI | 58 | constructive reset | cooled without breaking trend
Volume | 1.8x | strong | time-matched
Burst | 2.4x | active | last 15m block
Gap | -12.6% | rejected | gap-down fails long momentum gate
Day change | -8.6% | rejected | down 3% or more versus prior close fails broad bullish long gate
```

The tray should show:

- strategy gates passed/failed
- active signal contributions
- context-only signals when useful
- why Vector/Nova differed when both exist
- data freshness timestamp

## News Links

If a news item opens externally, that behavior is acceptable.

Full in-app article reading requires either:

- a permitted full-text source/API
- a browser/reader behavior that respects source restrictions

Do not scrape or reproduce full articles without permission.

## Settings

Ticker banner visibility should be user-toggleable.

When hidden, the ticker banner space should collapse so the page moves up.

## Tests Required

Minimum tests:

- account header labels total return and session P&L clearly
- 1D chart defaults to daily
- 1D tooltip includes time
- no fake chart line when session data is unavailable
- All-view cards show averaged labels
- closed trades include strategy/variant in All view
- evidence tags are hidden
- selected strategy is excluded from compact/expanded confluence tags
- ticker banner hide setting collapses space
