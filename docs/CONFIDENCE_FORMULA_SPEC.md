# SwingDesk Confidence Formula Spec

Status: proposal for review.

This document defines the proposed scoring formula for Scoring V2. It turns the glass-house scoring philosophy into executable rules.

## Prime Directive

A stock should never receive an actionable confidence score unless SwingDesk can explain exactly why, from fresh data, using only signals valid for the selected strategy.

Confidence is not a vibe. It is a bounded, auditable score produced from:

```text
eligibility gates
strategy signal profile
signal contributions
penalties
caps
variant-specific calibration
data-quality limits
```

## Big Picture Math Tree

```text
Ticker enters scoring
|
+-- Market data math
|   |
|   +-- price = latest valid trade/quote/bar close
|   +-- previous_close = prior regular-session close
|   +-- session_open = current regular-session open when needed
|   +-- day_pct = (price - previous_close) / previous_close * 100
|   +-- gap_pct = (premarket_or_open_price - previous_close) / previous_close * 100
|   +-- daily_dollar_volume = close_price * daily_share_volume
|   +-- average_daily_dollar_volume = median(daily_dollar_volume over recent usable sessions)
|
+-- Liquidity gates
|   |
|   +-- price >= 2.00
|   +-- average_daily_dollar_volume >= 5,000,000
|
+-- Volume math
|   |
|   +-- cumulative_time_matched_volume =
|   |     today's cumulative volume through current time
|   |     /
|   |     median cumulative volume through same time over prior 20 usable sessions
|   |
|   +-- premarket_relative_volume =
|   |     today's premarket cumulative volume through current premarket time
|   |     /
|   |     median premarket cumulative volume through same premarket time over prior 20 usable sessions
|   |
|   +-- recent_block_volume_acceleration =
|   |     today's volume in most recent completed comparison block
|   |     /
|   |     median volume for same clock block over prior 20 usable sessions
|   |
|   +-- volume_baseline_authority =
|         1.00 if usable_sessions >= 20
|         0.50 if 10 <= usable_sessions < 20
|         0.00 if usable_sessions < 10
|
+-- Momentum/relative-strength math
|   |
|   +-- rsi = 100 - (100 / (1 + relative_strength_index_rs))
|   +-- relative_strength_index_rs = average_gain / average_loss
|   +-- stock_return_n = (price_now - price_n_sessions_ago) / price_n_sessions_ago * 100
|   +-- benchmark_return_n = (benchmark_now - benchmark_n_sessions_ago) / benchmark_n_sessions_ago * 100
|   +-- relative_strength_delta = stock_return_n - benchmark_return_n
|   +-- sector_relative_strength_delta = sector_return_n - benchmark_return_n
|
+-- Support/resistance math
|   |
|   +-- nearest_resistance = most relevant recent swing high / range high / channel high
|   +-- nearest_support = most relevant recent swing low / range low / channel low
|   +-- resistance_distance_pct = (nearest_resistance - price) / price * 100
|   +-- support_distance_pct = (price - nearest_support) / price * 100
|   +-- breakout_pct = (price - nearest_resistance) / nearest_resistance * 100
|   +-- open_air_pct = resistance_distance_pct when no meaningful resistance is nearby
|
+-- Intraday structure math
|   |
|   +-- vwap = sum(typical_price * volume) / sum(volume)
|   +-- typical_price = (high + low + close) / 3
|   +-- vwap_delta_pct = (price - vwap) / vwap * 100
|   +-- intraday_range_pct = (intraday_high - intraday_low) / price * 100
|
+-- Volatility/extension math
|   |
|   +-- true_range = max(high - low, abs(high - previous_close), abs(low - previous_close))
|   +-- atr = average(true_range over N sessions)
|   +-- atr_pct = atr / price * 100
|   +-- squeeze_width_pct = (upper_band - lower_band) / middle_band * 100
|   +-- squeeze_percentile = percentile_rank(squeeze_width_pct over recent history)
|
+-- Hard gates
|   |
|   +-- if any required gate fails:
|   |     blocked = true
|   |     actionable = false
|   |     final_score = null or non-actionable diagnostic score
|   |
|   +-- earnings_day_block:
|         no open/hold through earnings day unless strategy explicitly allows it
|
+-- Signal scoring
|   |
|   +-- signal_quality = -1.0 to +1.0
|   +-- signal_weight = current isolated variant weight for that signal
|   +-- active_signal_points = signal_quality * signal_weight * 35
|   +-- secondary_signal_points = signal_quality * signal_weight * 35 * secondary_authority
|   +-- secondary_authority default = 0.40
|   +-- total_signal_points = sum(active_signal_points) + sum(secondary_signal_points)
|
+-- Confidence score
|   |
|   +-- base_score = 50
|   +-- raw_score = base_score + total_signal_points + small_penalties
|   +-- capped_score = min(raw_score, lowest_applicable_data_quality_cap)
|   +-- final_score = clamp(round(capped_score), 0, 100)
|   +-- actionable = final_score >= strategy_action_floor AND blocked == false
|
+-- Expected move
|   |
|   +-- similar_setup_median_move =
|   |     median realized move from prior closed trades with same strategy,
|   |     similar score band, similar gap direction, and similar volume regime
|   |
|   +-- volume_multiplier_cap = min(max(cumulative_time_matched_volume, 0.5), 2.5)
|   +-- volume_adjusted_gap_component = abs(gap_pct) * volume_multiplier_cap
|   +-- recent_intraday_range_component = intraday_range_pct
|   |
|   +-- expected_move =
|         0.40 * atr_pct
|       + 0.25 * similar_setup_median_move
|       + 0.20 * volume_adjusted_gap_component
|       + 0.15 * recent_intraday_range_component
|
+-- Learning/weight update math
|   |
|   +-- raw_weight_delta = learning_rate * outcome_signal_credit
|   +-- bounded_weight_delta = clamp(raw_weight_delta, -0.02, +0.02)
|   +-- adjusted_weight = clamp(old_weight + bounded_weight_delta, signal_floor, signal_ceiling)
|   +-- normalized_weight = adjusted_weight / sum(all_adjusted_weights)
|
+-- Context output
    |
    +-- gates passed/failed
    +-- signal rows
    +-- confluence tags, context-only in V2
    +-- data freshness
    +-- Vector/Nova or variant differences
```

## Score Bands

Displayed confidence bands:

```text
<65      skip
65-74    valid
75-84    strong
85-100   elite
```

Actionable fresh picks:

```text
default minimum = 65
```

No strategy may show a fresh actionable pick below its configured floor unless the UI labels it as a non-actionable watchlist/fallback candidate.

## Formula Overview

Each strategy score follows this pipeline:

```text
1. Load strategy profile.
2. Validate required market data.
3. Run hard eligibility gates.
4. Build signal evidence rows.
5. Apply weighted signal contributions.
6. Apply penalties.
7. Attach confluence context.
8. Apply data-quality caps.
9. Apply variant-specific calibrated weights.
10. Produce score, label, and explanation.
```

## Output Contract

Every scoring call should return:

Illustrative example:

```json
{
  "ticker": "AMD",
  "strategy": "SwingDesk",
  "brain": "Vector",
  "score": 72,
  "score_band": "valid",
  "actionable": true,
  "blocked": false,
  "block_reasons": [],
  "caps_applied": [],
  "data_freshness": {
    "scan_completed_at": "2026-06-05T08:15:00-05:00",
    "provider": "massive",
    "freshness_status": "fresh"
  },
  "gates": [],
  "signals": [],
  "confluence": [],
  "brain_differentiators": [],
  "explanation": "short human-readable summary"
}
```

## Hard Eligibility Gates

Hard gates run before confidence math. If a required hard gate fails, the stock is blocked and should not receive an actionable long-pick score.

Common hard gates:

```text
fresh_data
valid_price
valid_previous_close
valid_session_open_when_needed
acceptable_liquidity
valid_direction
not_already_open_unless_scale_in_allowed
strategy_required_signals_present
no_strategy_disqualifying_pattern
```

Default hard-gate definitions:

fresh_data:

```text
latest completed full scan is inside strategy freshness window
premarket entry: latest completed full scan before entry slot
regular session: latest completed full scan <= 45 minutes old
```

valid_price:

```text
current/last price is finite, positive, timestamped, and not split-broken
```

valid_previous_close:

```text
previous close is finite and positive when gap/day-change logic is used
```

valid_session_open_when_needed:

```text
session open is finite and positive when intraday move logic is used
```

acceptable_liquidity:

```text
price >= 2.00
average daily dollar volume >= 5,000,000
```

The price floor is a safety gate, not an expectation that major-index tickers commonly trade under $2. It protects the simulation if the ticker universe expands, a bad ticker enters the list, a leveraged/low-quality instrument slips in, or provider data is split-broken.

Daily dollar volume:

```text
daily_dollar_volume = close_price * daily_share_volume
average_daily_dollar_volume = median daily_dollar_volume over recent usable sessions
```

valid_direction:

```text
long strategies require a long thesis
short/reversal logic must belong to an explicit short or reversal strategy
```

not_already_open_unless_scale_in_allowed:

```text
ticker cannot be a fresh pick if already open in the same variant unless the strategy explicitly supports scale-in
```

strategy_required_signals_present:

```text
all core active signals in the strategy profile are present or explicitly marked as unavailable with a cap
```

no_strategy_disqualifying_pattern:

```text
strategy-specific block, such as gap-down rejection for long momentum setups
```

earnings_day_block:

```text
Do not open or hold simulated stock trades through earnings day unless a future earnings-specific strategy explicitly allows it.
```

## Base Score

Actionable scoring starts from a neutral base only after hard gates pass.

Proposed base:

```text
base_score = 50
```

Reason:

- below 65 by default, so passing gates alone is not enough
- signals must prove the setup
- easier to explain than starting at 0 or 65

## Signal Contribution Model

Each strategy defines active signal weights that sum to 1.00 for that strategy.

Each active signal produces:

```text
signal_quality = -1.0 to +1.0
signal_weight = strategy-specific weight
signal_points = signal_quality * signal_weight * max_signal_points
```

Proposed:

```text
max_signal_points = 35
```

So active signals together can move a fully clean setup from 50 to as high as 85 before caps and variant-specific calibration.

Signal quality meanings:

```text
-1.0   strongly bearish / disqualifying for direction
-0.5   weak or negative
 0.0   neutral / no edge
 0.5   constructive
 1.0   strongly constructive
```

Missing active signal:

```text
no silent neutral
apply strategy data cap
show missing signal in explanation
```

Secondary signals:

```text
may contribute at reduced authority
default max authority = 40% of active signal authority
```

Context-only signals:

```text
visible only
no score impact
no learning impact
```

Disabled signals:

```text
not shown unless debug mode
no score impact
no learning impact
```

## Proposed Core Signal Weights By Strategy

These are initial baselines. ML can later adjust only learnable active/secondary signals.

### SwingDesk

SwingDesk is the broad momentum/continuation strategy.

```text
rsi_momentum                 active      0.14
volume_surge                 active      0.16
overnight_gap_probability    active      0.14
relative_strength            active      0.13
sector_relative_strength     active      0.10
support_resistance           active      0.12
vwap_reclaim                 active      0.09
volatility_squeeze           secondary   0.07
earnings_catalyst            secondary   0.05
```

SwingDesk hard rejection examples:

- major gap-down without reversal strategy support
- invalid previous close when gap is needed
- low liquidity
- already open in same variant unless scale-in variant exists

### Gap & Go

Gap & Go should care most about constructive gap, volume, liquidity, and early continuation.

```text
overnight_gap_probability    active      0.24
volume_surge                 active      0.20
relative_strength            active      0.14
vwap_reclaim                 active      0.12
rsi_momentum                 secondary   0.10
sector_relative_strength     secondary   0.08
earnings_catalyst            secondary   0.07
support_resistance           context     0.00
volatility_squeeze           context     0.00
```

Hard rejection examples:

- no positive gap for long setup
- gap-down long unless explicit reversal variant
- weak/unknown volume baseline with no catalyst

### VWAP Reclaim

VWAP Reclaim should focus on reclaim behavior, volume, and continuation quality.

```text
vwap_reclaim                 active      0.26
volume_surge                 active      0.18
relative_strength            active      0.14
rsi_momentum                 active      0.12
support_resistance           secondary   0.10
sector_relative_strength     secondary   0.08
overnight_gap_probability    secondary   0.07
earnings_catalyst            context     0.00
volatility_squeeze           context     0.00
```

Hard rejection examples:

- no VWAP reclaim evidence
- stale intraday bars
- price below VWAP without reclaim pattern

### Darvas

Darvas should focus on box breakout, resistance, trend, and volume confirmation.

```text
support_resistance           active      0.28
volume_surge                 active      0.18
relative_strength            active      0.16
sector_relative_strength     secondary   0.10
rsi_momentum                 secondary   0.08
volatility_squeeze           secondary   0.08
overnight_gap_probability    context     0.00
vwap_reclaim                 context     0.00
earnings_catalyst            context     0.00
```

Hard rejection examples:

- no box/high breakout structure
- resistance overhead too close unless breakout already confirmed
- weak volume on breakout

### Vol Squeeze Breakout

Vol Squeeze should focus on compression, breakout, and confirming expansion.

```text
volatility_squeeze           active      0.28
volume_surge                 active      0.18
support_resistance           active      0.14
relative_strength            active      0.12
rsi_momentum                 secondary   0.10
sector_relative_strength     secondary   0.08
vwap_reclaim                 secondary   0.06
overnight_gap_probability    context     0.00
earnings_catalyst            context     0.00
```

Hard rejection examples:

- no compression evidence
- no breakout/expansion evidence
- volume unknown when breakout confirmation is required

### Bull Flag

Bull Flag should focus on prior impulse, orderly pullback, continuation, and volume.

```text
rsi_momentum                 active      0.18
relative_strength            active      0.18
volume_surge                 active      0.16
support_resistance           active      0.12
vwap_reclaim                 secondary   0.10
sector_relative_strength     secondary   0.10
volatility_squeeze           secondary   0.06
overnight_gap_probability    context     0.00
earnings_catalyst            context     0.00
```

Hard rejection examples:

- no prior impulse
- pullback breaks structure
- continuation not confirmed

### Pocket Pivot

Pocket Pivot should focus on institutional-style volume signature.

```text
volume_surge                 active      0.30
relative_strength            active      0.16
rsi_momentum                 active      0.12
support_resistance           active      0.12
vwap_reclaim                 secondary   0.10
sector_relative_strength     secondary   0.08
volatility_squeeze           context     0.00
overnight_gap_probability    context     0.00
earnings_catalyst            context     0.00
```

Hard rejection examples:

- no pocket-pivot volume signature
- price structure not constructive

### Donchian

Donchian should focus on channel breakout and trend continuation.

```text
support_resistance           active      0.24
relative_strength            active      0.18
volume_surge                 active      0.14
rsi_momentum                 active      0.12
sector_relative_strength     secondary   0.10
volatility_squeeze           secondary   0.08
vwap_reclaim                 context     0.00
overnight_gap_probability    context     0.00
earnings_catalyst            context     0.00
```

Hard rejection examples:

- no channel breakout
- no valid lookback channel

### EMA Trend Pullback

EMA strategies should not be trusted until EMA indicators exist.

Planned profiles:

```text
EMA 9/21 Trend Pullback
EMA 50 Trend Pullback
EMA 200 Trend Pullback
```

Required new signals:

```text
ema_alignment
ema_distance
ema_reclaim
trend_regime
```

Until those exist, EMA strategies should stay inactive or shadow-only.

## Signal Quality Rules

### RSI Momentum

RSI should not mean "higher is always better."

Proposed long momentum interpretation:

```text
45-55    neutral
55-65    constructive momentum
65-72    strong but watch extension
>72      extended, cap upside unless breakout volume is exceptional
35-45    reset only if trend/support structure remains intact
<35      weak unless explicit mean-reversion strategy
```

Context labels:

```text
neutral
momentum
extended
constructive reset
weak
```

### Volume

Primary volume evidence:

```text
cumulative time-matched volume
recent-block burst volume
```

Daily-average volume is fallback/context.

Suggested quality:

```text
time_matched >= 2.0x       +1.0
time_matched 1.5x-1.99x    +0.7
time_matched 1.2x-1.49x    +0.4
time_matched 0.8x-1.19x     0.0
time_matched <0.8x         -0.4
unknown                     cap, not neutral
```

Burst volume:

```text
burst >= 2.0x              +0.5 confirmation
burst 1.3x-1.99x           +0.25 confirmation
burst <0.8x                -0.25 drag
```

Burst confirms volume; it should not replace cumulative time-matched volume for primary scoring.

### Gap

For long momentum strategies:

```text
positive gap with volume/catalyst        constructive
small positive gap without volume         mild
flat/no gap                               neutral
major gap-down                            reject unless reversal strategy
huge gap-up without structure             extension cap
```

Suggested default:

```text
gap_percent <= -3.0 blocks Gap & Go and broad long momentum unless reversal support exists
  note: this means a gap down of 3% or worse, such as -3%, -5%, or -12%.
gap_up > +15% applies extension cap unless volume/catalyst/context is elite
```

### Relative Strength

Relative strength should compare ticker performance against SPY/QQQ and relevant sector over a defined window.

Proposed:

```text
stock outperforming index and sector      constructive
stock outperforming index only            mild
stock lagging index and sector            drag
unknown                                   cap, not neutral
```

### Sector Relative Strength

Sector RS should answer whether the ticker's sector is helping or hurting the setup.

Labels:

```text
strong tailwind
neutral
weak drag
unknown
```

### Support/Resistance

S&R should measure whether price has room and structure.

Constructive:

- breakout over resistance
- support held
- open air above
- Darvas/channel breakout

Negative:

- price capped by nearby resistance
- failed breakout
- support broken

### VWAP Reclaim

VWAP Reclaim should require intraday bars.

Constructive:

- price reclaimed VWAP
- reclaim held for confirmation window
- volume supports reclaim

Negative:

- price below VWAP
- reclaim failed

### Volatility Squeeze

Constructive:

- compression detected
- breakout direction aligns with strategy
- volume confirms expansion

Negative:

- no compression
- breakdown instead of breakout

### Earnings Catalyst

Earnings should be context or secondary unless the strategy explicitly trades catalysts.

Constructive:

- known catalyst
- price/volume confirms

Negative:

- earnings risk without confirmation
- stale/unreliable catalyst data

## Confluence Rules

Confluence is context-only in Scoring V2.

Reason:

- simpler math
- less risk of fake confidence inflation
- cleaner learning, because ML adjusts signal weights rather than tag counts
- confluence remains valuable as glass-house explanation and cross-strategy agreement

Rules:

- confluence does not add points
- confluence does not subtract points
- selected strategy does not count as its own confluence
- duplicate/near-identical confluence should be deduped
- every displayed confluence must faithfully reflect a real condition or outside strategy agreement
- confluence cannot make a blocked setup actionable

Confluence counters:

```text
strategy/context confluence counter separate from signal counter
```

## Penalties

Penalties apply after signal contributions, but Scoring V2 should prefer gates and caps over large free-floating penalties.

Penalty philosophy:

```text
hard failure      -> block
data weakness     -> cap
mild drag         -> small penalty
signal evidence   -> signal_quality from -1.0 to +1.0
```

Suggested default penalties should stay small:

```text
stale data                      block or cap, not free penalty
provisional volume baseline      cap, optional -2
missing secondary signal          -1 to -2
missing active signal             cap, not simple penalty
low liquidity                     block
major adverse gap                 block for long momentum
overextended without volume       cap, optional -3 to -5
near resistance                   cap or -3 to -5
sector drag                       -2 to -4
```

## Data-Quality Caps

Caps prevent fake precision and suspicious 90%+ scores from weak/incomplete data.

Proposed caps:

```text
missing active signal                    max 74
provisional volume baseline only          max 79
daily-average volume only                 max 72
unknown previous close when gap needed    block
unknown sector RS                         max 84
unknown relative strength                 max 82
no intraday bars for intraday strategy     block
stale scan                                max 64 or block
fresh data but no volume baseline         max 74
```

Elite score requirement:

```text
score >= 85 requires:
  fresh scan
  valid previous close/open where needed
  no missing active signals
  full-strength or clearly exceptional provisional volume evidence
  at least one strong primary signal
  no hard gate warnings
```

## Variant-Specific Calibration

Vector and Nova may differ, but the difference must be explainable through isolated variant-specific weights and calibration.

Proposed model:

```text
base strategy formula is shared
each brain + strategy + variant has its own weight universe
new simulations start from the same hardcoded baseline for that strategy
daily learning mutates only that simulation's own weights
final score is produced from the selected simulation's current weights
```

There should not be an arbitrary final "brain bonus." Differences should come from:

- different learned signal weights
- different variant rule settings
- different caps triggered by that variant's required data
- different strategy profile if comparing different strategies

Vector/Nova difference display:

```text
Vector 69 vs Nova 82 because Nova weighted volume and VWAP higher; Vector capped score due to weaker RS.
```

## Expected Move

Expected move should not be confused with confidence.

Expected move should be a separate estimate using:

- recent volatility
- average true range or intraday range
- gap size
- volume acceleration
- historical move after similar setup
- strategy profile

Confidence answers:

```text
How trustworthy is the setup?
```

Expected move answers:

```text
How large might the move be?
```

Proposed first formula:

Illustrative equation:

```text
expected_move =
  0.40 * atr_percent
+ 0.25 * similar_setup_median_move
+ 0.20 * volume_adjusted_gap_component
+ 0.15 * recent_intraday_range_component
```

Component definitions:

```text
atr_percent =
  average_true_range / current_price * 100

similar_setup_median_move =
  median realized move from prior closed trades with same strategy, similar score band, similar gap direction, and similar volume regime

volume_adjusted_gap_component =
  abs(gap_percent) * volume_multiplier_cap

recent_intraday_range_component =
  recent_high_low_range / current_price * 100
```

Guardrails:

- Expected move is capped by strategy.
- Expected move cannot be negative for long picks; bearish/reversal expectations require their own future strategy.
- If similar setup history is thin or unavailable, use ATR and range components only and label the estimate provisional.
- Expected move should not make a pick actionable if confidence gates fail.

## Learning Rules

Learning may adjust:

- active learnable signal weights
- secondary learnable signal weights
- variant-specific signal weights and calibration parameters

Learning may not adjust:

- hard gates without explicit strategy-version migration
- context-only signals
- disabled signals
- confluence definitions
- score band thresholds unless explicitly versioned

Learning should be bounded:

```text
single daily adjustment per signal <= 2 percentage points
signal weight floor/ceiling defined per strategy
weights renormalize after adjustment
```

Illustrative learning example:

```text
before:
  rsi_momentum   0.14
  volume_surge   0.16
  other weights  0.70
  total          1.00

daily learning:
  rsi_momentum wants +0.02
  volume_surge wants -0.01

after raw adjustment:
  rsi_momentum   0.16
  volume_surge   0.15
  other weights  0.70
  total          1.01

after renormalization:
  all weights are proportionally adjusted so total = 1.00
```

Renormalization is a constraint, not a patch. It keeps the strategy's total signal budget fixed so one signal cannot grow without reducing the relative authority of the others.

## Versioning

Every scored pick/trade must store:

```text
scoring_engine_version = "scoring_v2"
strategy_profile_version
formula_version
provider_snapshot
signal_snapshot
gate_snapshot
cap_snapshot
```

Old data should be treated as:

```text
legacy_pre_v2
```

## Implementation Order

Build in this order:

1. Create scoring module boundaries.
2. Define strategy profiles in structured data.
3. Implement gate evaluator.
4. Implement signal evaluators.
5. Implement confidence combiner.
6. Implement cap/penalty layer.
7. Attach confluence context.
8. Implement variant-specific calibration layer.
9. Return full scoring explanation object.
10. Wire one strategy first: SwingDesk.
11. Add tests.
12. Shadow-run against current scoring.
13. Promote to displayed scoring after review.

## First Production Scope

To get scoring logic running before the weekend ends, start with:

```text
SwingDesk only
Vector and Nova
fresh picks only
open-position dynamic context optional
closed-trade relearning unchanged until v2 scoring is stamped
```

Then add other strategies once the core pattern is proven.

## Tests Required

Minimum tests:

- blocked major gap-down long momentum receives no actionable score
- missing previous close blocks gap-dependent strategy
- missing active signal caps score
- daily-average-only volume cannot produce strong/elite score
- 20-session volume baseline can produce full-strength volume score
- 10-19 session volume baseline is provisional and capped
- under-10 session volume baseline cannot boost score
- selected strategy is excluded from its own confluence tag and confluence counter
- confluence cannot override hard gate
- score >= 85 requires all elite requirements
- Vector/Nova difference explanation is present when scores differ materially
- expected move is separate from confidence
