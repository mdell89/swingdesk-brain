# SwingDesk Learning And Audit Spec

This document defines the roles of ML learning, audit recap, LLM providers, and the learning ledger.

## Prime Directive

Learning changes weights. Audit explains learning.

Audit must never pretend to learn, and learning must never happen from open trades.

## Learning Schedule

Daily learning should run automatically:

```text
7:00 PM Central
weekdays only
```

Learning should process closed trades in batches, not one trade at a time during the trading session.

The daily batch should consider only trades that became closed since the prior learning batch or that are explicitly eligible for rebuild.

## Eligible Learning Inputs

Learning may use:

- closed variant trades
- finalized entry data
- finalized exit data
- realized P&L
- outcome classification
- strategy ID
- variant ID
- brain ID
- signal snapshot at entry
- scoring engine version

Learning must not use:

- open trades
- picks that never opened
- stale/incomplete trade rows
- legacy retired trades
- unaudited manual backfill rows unless marked eligible
- context-only or disabled signals as learnable signals

## Learning Output

Every learning event must log:

- timestamp
- brain
- strategy
- variant
- trade ID or batch ID
- ticker
- outcome
- realized P&L percent
- old weights
- new weights
- changed signals
- direction of each change
- reason
- scoring engine version

If no weights change, the event should still explain why.

## Variant Isolation

Vector and Nova learn inside their own universes.

Vector cannot read Nova's universe to adjust Vector weights.

Nova cannot read Vector's universe to adjust Nova weights.

Aegis can read Vector/Nova/Aegis universes for recommendations but cannot mutate Vector/Nova weights directly.

## Signal Learning Rules

Learning may adjust only signals marked learnable in the selected strategy signal profile.

Rules:

- active learnable signals may adjust
- secondary learnable signals may adjust within lower bounds
- context-only signals may not adjust
- disabled signals may not adjust
- missing signal data may not be treated as neutral success or failure

## Audit Role

Audit is a read-only recap.

Audit should answer:

```text
Did learning run?
Which variants changed?
Which weights changed?
How much did they change?
Why did they change?
Which provider generated the recap?
Were there provider failures?
```

Audit should not be the authority that changes weights.

## LLM Provider Chain

Audit recap may call real LLM providers only.

Current provider order:

```text
ANTHROPIC_API_KEY
OPENAI_API_KEY
GROQ_API_KEY
MISTRAL_API_KEY
TOGETHER_API_KEY
OPENROUTER_API_KEY
XAI_API_KEY
PERPLEXITY_API_KEY
```

If every provider fails or is missing:

- audit fails visibly
- provider attempts are logged
- weights remain unchanged
- UI must not imply learning happened

## Audit UI

Audit history should be paginated.

Default display:

```text
2 audit entries per page
```

Audit summary text should be concise, but the user must be able to see the full learning ledger separately.

The Brain tab should include an expandable learning ledger showing full ML weight adjustments, paginated.

## Rebuilds And Corrections

If bad entry prices, stale prices, or scoring bugs are discovered, old learning events should not be silently overwritten.

Safe correction path:

1. Mark impacted rows with reason.
2. Recompute eligible closed trades.
3. Write rebuild learning events with a rebuild marker.
4. Preserve old rows for auditability unless explicitly archived.

## Scoring Version Boundary

Every learning event must carry `scoring_engine_version`.

Faulty pre-v2 data may later be hidden from default performance views by version filter, but should not be deleted until:

- backup exists
- migration has been tested
- active UI no longer depends on old rows
- user confirms archive/purge behavior

## Tests Required

Minimum tests:

- learning runs only from closed trades
- open trades are excluded
- legacy retired trades are excluded
- context-only/disabled signals cannot adjust
- audit does not change weights
- all provider failures produce visible failure
- audit history pagination works
- learning ledger pagination works
- scoring engine version is stored
