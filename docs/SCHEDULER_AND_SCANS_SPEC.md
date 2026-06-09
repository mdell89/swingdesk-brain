# SwingDesk Scheduler And Scans Spec

This document defines scheduled jobs, scan freshness, provider behavior, monitoring cadence, stall handling, and scan-log retention.

## Prime Directive

SwingDesk should never make a trading decision from unknown, stale, partial, or failed scan data without labeling or blocking that decision.

Every scan should leave enough trail to answer:

```text
What ran?
When did it run?
What data source did it use?
How many tickers were attempted?
How many succeeded?
Which tickers failed?
Was the result fresh enough for a decision?
```

## Time Zone

All schedules are defined in America/Chicago wall-clock time unless explicitly stated otherwise.

The scheduler must use timezone-aware Central time so daylight saving time does not shift jobs by one hour.

Market-data calculations that depend on exchange session windows should use US/Eastern exchange time.

## Full Scan Schedule

Shared comprehensive scans should run around the active decision windows.

Expected scan categories:

```text
pre_market
regular
post_market
manual
```

Premarket cadence:

```text
4:00 AM to 8:00 AM Central, every 30 minutes
8:15 AM Central final premarket scan
```

Regular-session cadence:

```text
8:30 AM to 2:30 PM Central, every 30 minutes
```

Post-market cadence:

```text
3:00 PM to 6:00 PM Central, every 30 minutes
```

## Pick Queue

Unlock:

```text
4:00 AM Central
```

Lock:

```text
8:25 AM Central
```

The lock prevents late scan churn from rewriting the committed premarket pick queue immediately before opening execution.

Every scheduled entry slot must also have an entry-specific decision snapshot.

```text
04:55 lock -> 05:00 entry variants
05:55 lock -> 06:00 entry variants
06:55 lock -> 07:00 entry variants
08:25 lock -> 08:45 entry variants
```

The lock stores the exact Vector, Nova, and Scoring V2 candidate payloads that may be opened by the corresponding entry job.

Execution must use the locked snapshot for its entry slot. If the locked snapshot is missing, stale, incomplete, or pair-mismatched, execution must skip and write a visible refusal reason.

## Variant Entry Jobs

Known entry jobs:

```text
5:00 AM Central
6:00 AM Central
7:00 AM Central
8:45 AM Central
regular-session strategy variants where explicitly defined
```

Variant execution should use the locked eligible shared scan for its entry slot, not an in-progress or stalled scan.

If no fresh completed shared scan exists, the variant should skip or block with a visible reason.

## Scan Freshness

Decision freshness defaults:

```text
premarket entry decisions: latest completed full scan before the entry slot
regular-session decisions: completed full scan no older than 45 minutes
monitoring-only P&L updates: latest quote/bar data from provider chain
```

Each pick/open decision should be able to display:

```text
Decision based on scan completed at HH:MM CT
```

## Monitor Scans

Simulated open-position monitoring:

```text
regular session: every 3 minutes by default
extended hours: around every 5 minutes
```

Monitoring should update open-position price, P&L, status context, and sell-rule checks.

Monitoring should recalculate confidence/context only when the required data is available and the strategy profile supports dynamic confidence.

Real broker-connected trading must use a separate real-time or near-real-time path later. It should not blindly inherit the simulated monitoring cadence.

## Provider Chain

Provider selection must prefer trustworthy, structured market-data providers over scraping or fragile free endpoints.

Provider behavior must log:

- provider name
- endpoint/type of data
- success/failure
- error code/message
- timestamp
- whether fallback was used

Provider data should be cached by data type and ticker:

```text
quote cache
intraday bars cache
daily bars cache
news cache
profile cache
```

Quote data alone is not enough for indicators that require bars. Time-matched volume, RSI, VWAP context, and recent-block volume require intraday bars.

## Cache Rules

Cache entries must include:

- fetched_at timestamp
- provider
- data type
- ticker or universe key
- freshness policy

No stale cache row should silently pass as fresh data.

## Stall Handling

A comprehensive scan is stalled when it remains active beyond its expected time window without progress.

Stalled scan requirements:

- marked visibly in scan log
- does not become a decision source
- does not overwrite the last successful completed scan
- records last scanned ticker/count if available
- records failed/pending tickers if available

The UI should never show an empty pick list merely because an in-progress scan temporarily cleared state.

## Scan Log Retention

Raw scan telemetry:

```text
retain 30 days
```

Summaries:

```text
retain up to 3 months by default
extend to 6 months only if Aegis/regime analysis needs it
```

Raw scan data older than 30 days should be pruned automatically.

## Scan Log UI

Scan log should not be wrapped in the Brain/Strategy/Variant hierarchy. It is operational infrastructure, not a variant-specific performance view.

Scan log should be paginated.

Full scan monitor should show:

- current status
- count scanned / total
- current ticker names being scanned when available
- last successful full scan
- current stalled/failure state
- failed ticker visibility

## Tests Required

Minimum tests:

- scheduler uses Central timezone
- full scans write completed/stalled status correctly
- in-progress/stalled scans cannot become decision source
- variant entry uses latest fresh completed full scan
- monitor cadence is separate from full scan cadence
- scan log pagination works
- scan retention prunes raw telemetry older than 30 days
- cache freshness is enforced per data type
