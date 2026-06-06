# Scoring V2 Spec

This document defines the scoring overhaul. Do not build or modify scoring behavior in ways that conflict with this spec. If the design changes, update this file first.

## Prime Directive

A stock should never receive a confidence score unless SwingDesk can explain exactly why, from fresh data, using only the signals that are valid for the selected strategy.

No unknown, stale, neutral, missing, or fallback data should silently inflate confidence.

## Pipeline

```text
Raw market data
  |
  +-- Provider/data freshness validation
  |
  +-- Strategy eligibility gates
  |     pass -> continue
  |     fail -> reject with reason, no actionable score
  |
  +-- Strategy signal profile
  |     active learnable signals
  |     active non-learnable signals
  |     context-only signals
  |     disabled signals
  |
  +-- Signal evaluation
  |
  +-- Weighted score calculation
  |
  +-- Penalties and risk adjustments
  |
  +-- Confidence band
  |
  +-- Explanation payload
  |
  +-- Optional backend-only shadow comparison
```

## Confidence Bands

```text
85+    elite
75-84  strong
65-74  valid
<65    skip
```

There should be no hidden fallback floor unless it is documented and displayed. If a strategy has a special lower floor, the UI legend must say so.

## Eligibility Gates

Gates are must-pass rules before scoring can produce an actionable pick.

Every strategy must define gates. Common gates:

- data is fresh enough for the decision window
- ticker has valid price
- ticker has valid previous close/open where needed
- liquidity is acceptable
- direction is valid
- no disqualifying gap pattern for the strategy
- enough required signals exist
- ticker is not already open unless scale-in is explicitly allowed

Gate terms must be concrete in code:

```text
fresh data
  scan completed inside the strategy's allowed freshness window
  default: <= 45 minutes old during active scan windows
  strict entry execution default: latest completed full scan before the entry slot

valid price
  finite positive price
  timestamp present or inherited from a fresh completed scan
  price source recorded
  not zero, null, NaN, stale, split-broken, or wildly inconsistent with nearby bars

valid previous close/open
  finite positive previous close when gap/day-change is used
  finite positive session open when intraday move is used
  unavailable values must block or downgrade strategy logic that depends on them

acceptable liquidity
  default prototype floor: price >= $2 and average daily dollar volume >= $5M
  strategy may raise the floor
  low-liquidity names may be context-only until we define penny/small-cap rules

valid direction
  long strategy must have a long thesis
  short strategies are disabled until explicitly designed
  reversal logic must be explicitly owned by a reversal strategy

enough required signals
  every core signal for the strategy has either valid data or an explicit fallback rule
  missing core data cannot silently become neutral confidence
```

Example SwingDesk long rejection:

```text
Rejected: major gap down without reversal confirmation
```

That ticker should not receive a long-pick confidence score under SwingDesk momentum logic.

## Strategy Signal Profiles

Every strategy must own its own signal profile. No strategy should blindly inherit the full canonical signal list unless that is truly part of the strategy design.

Signal profile entry:

```text
signal_id
  role: core | secondary | context_only | disabled
  learnable: true | false
  baseline_weight
  max_weight
  display_label
  display_context_rule
  reason
```

Roles:

- core: central to the strategy; can strongly affect score.
- secondary: useful but lower authority.
- context_only: visible to user, cannot affect score or learning.
- disabled: ignored entirely for that strategy.

Learnable signals:

- Only active signals marked `learnable: true` can be adjusted by daily learning.
- Context-only and disabled signals must never be adjusted.

## Volume Rules

Time-matched relative volume is the primary volume signal during active market windows.

```text
time_matched_relative_volume =
  today's cumulative volume through current time
  /
  median cumulative volume through same time over last 20 comparable sessions
```

This metric answers: "Is this ticker trading more volume than it normally has by this same point in the same market window?"

Comparable sessions:

- Same ticker.
- Same market window: premarket compares only to prior premarket windows; regular session compares only to prior regular sessions.
- Most recent 20 usable sessions by default.
- Minimum usable baseline: 10 sessions. Below 10, volume is context-only and cannot strongly boost confidence.
- Exclude holidays, half-days, halted sessions, split-broken sessions, and provider-corrupted volume when detectable.
- Prefer the median baseline instead of the mean because one extreme news day can distort averages.

Premarket uses a separate premarket baseline.

```text
premarket_relative_volume =
  today's premarket cumulative volume through current time
  /
  median premarket cumulative volume through same time over last 20 comparable sessions
```

Example: at 8:15 AM Central, premarket relative volume compares today's cumulative premarket volume from 4:00 AM Eastern through 9:15 AM Eastern against the median cumulative premarket volume from 4:00 AM Eastern through 9:15 AM Eastern across the prior 20 usable sessions.

Regular-session example: at 11:00 AM Eastern, regular-session relative volume compares today's cumulative regular-session volume from 9:30 AM Eastern through 11:00 AM Eastern against the median cumulative regular-session volume from 9:30 AM Eastern through 11:00 AM Eastern across the prior 20 usable sessions.

After close, full-day volume can be compared to full-day average or median.

Volume baseline details:

- Regular-session time-matched volume should use exchange time, 9:30 AM to 4:00 PM Eastern.
- Premarket time-matched volume should use a separate exchange-time window, 4:00 AM to 9:30 AM Eastern.
- Premarket needs separate logic because premarket liquidity, participation, spreads, and volume curves are structurally different from regular-session trading.
- The calculation should be cumulative through the current time bucket, not a standalone hourly block.
- Preferred bucket: 5-minute bars when provider limits allow it.
- Acceptable fallback bucket: 15-minute bars.
- Hourly buckets are too coarse for primary scoring, but may be used for a compact educational display if needed.

Recent-block volume acceleration:

```text
recent_block_volume_acceleration =
  today's volume in the most recent completed 15-minute block
  /
  median volume for the same 15-minute clock block over the prior 20 usable sessions
```

This metric answers: "Is volume accelerating right now compared with this exact part of the day?"

- Use completed 15-minute blocks by default.
- Fallback to 30-minute blocks when provider limits or missing bars make 15-minute blocks unreliable.
- Do not use 60-minute blocks for primary scoring; they are too slow to detect actionable intraday volume changes.
- Recent-block acceleration may confirm or strengthen a setup, but should not override a failed strategy gate by itself.
- For premarket, compare only against prior premarket blocks with the same clock time.

Daily-average volume fallback:

- May carry limited context weight when time-matched volume is unavailable.
- During active market hours, its authority should be no more than one-third of time-matched volume authority.
- It must not be the deciding boost by itself.
- It should be labeled clearly as `daily avg`.
- If both cumulative time-matched volume and recent-block acceleration are available, daily-average volume should be display/context only.

Display examples:

```text
Volume 1.8x · time-matched
Volume 0.9x · daily avg
Volume unknown · no baseline
```

## Context Display V2

Replace confusing percent tiles with readable evidence rows.

Preferred structure:

```text
Eligibility
  Data fresh · 8:30 AM scan
  Direction valid · long
  Gap quality passed

Signal Read
  RSI 62 · momentum
  Volume 1.8x · time-matched
  Gap +4.2% · constructive
  Sector RS weak · drag
  VWAP reclaim · confirmed

Confluence
  Darvas agrees
  Open Air present
  Nova agrees

Decision
  Passed as valid pick
  Confidence 74
  Boosts: volume, VWAP, gap
  Penalties: sector drag
```

Context rows should be short enough to scan and clear enough to teach.

## RSI Context

RSI should be interpreted through the strategy profile.

Examples:

```text
RSI 52 · neutral
RSI 62 · momentum
RSI 71 · extended
RSI 38 · reset
```

For SwingDesk momentum, moderate strength can be constructive. For mean reversion, lower RSI may be constructive. For Gap & Go, RSI may be context-only.

`reset` means RSI cooled off from an overextended condition into a healthier range without fully breaking the setup. It is potentially constructive for continuation strategies only when price/volume structure remains intact.

## Sector Relative Strength Context

Sector RS compares the stock's sector tailwind to the broader market.

Display examples:

```text
Sector RS strong · tailwind
Sector RS weak · drag
Sector RS neutral · no edge
Sector RS unknown · missing data
```

The exact calculation must be documented in code when implemented. A good default is sector ETF return over the selected lookback minus SPY return over the same lookback.

## Confluence

Use the name `confluence`, not `setup_confluence`.

Confluence can include:

- strategy agreement
- setup context
- brain agreement

Compact cards should show counters and highest-value tags only:

```text
[Nova] [2/10 confluence] [3/9 signals]
```

Named confluence tags should appear on expanded cards, not compact cards, unless a future UI decision explicitly changes that.

## Vector/Nova Difference Explanation

When Vector and Nova disagree or score differently, Context should eventually explain why.

Examples:

```text
Vector rejected: gap quality failed.
Nova accepted: VWAP reclaim and volume baseline passed.

Vector 68: sector drag and weak volume.
Nova 82: neural adjustment rewarded similar prior winners.
```

This explanation should come from structured score payloads, not hand-written guesses.

## Shadow Mode

Shadow mode is backend-only.

It may log:

- old score
- new score
- score delta
- old decision
- new decision
- reason for difference

Shadow mode should not clutter the UI. It exists to prevent invisible rewiring mistakes during migration.

## Scoring Engine Versioning

Every pick, open trade, closed trade, learning event, and performance calculation should carry a scoring engine version.

Proposed version:

```text
v2_strategy_profiles
```

After v2 is stable, old faulty performance data should disappear from normal UI by filtering to the current scoring version. Old rows should be archived first, not blindly deleted.

Safe reset sequence:

1. Add `scoring_engine_version`.
2. Mark old trades/data as `legacy_pre_v2`.
3. Archive old closed trades/performance rows.
4. Filter live UI to v2 performance only.
5. Keep admin/debug access to legacy archive.
6. Purge only after backup and verification.

## Tests Required Before Trust

Minimum test cases:

- major gap-down long under SwingDesk fails eligibility
- valid gap-up momentum can pass
- missing RS/sector data does not inflate confidence
- disabled signals cannot affect score
- context-only signals cannot affect score
- disabled/context-only signals cannot be learned
- Darvas does not rely on irrelevant RSI-heavy logic
- volume daily-average fallback has limited authority
- time-matched volume can strongly affect score
- All view aggregates only valid actionable contributors
- Context explanation matches backend score payload
