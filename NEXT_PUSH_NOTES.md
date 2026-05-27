# Next Push Notes

## Push Order

### Push 1: Urgent Trade Execution Recovery

- Fix the no-open-trades failure first.
- Add a manual/admin recovery endpoint that converts today's cached picks into open positions as if bought at `08:45:00`.
- Use queue buy amounts first, then fallback sizing after queue amounts are exhausted.
- Make execution idempotent so rerunning the recovery cannot duplicate positions.
- Add explicit execution diagnostics to `app_state`:
  - last execution attempted time
  - last execution success time
  - cached pick count at execution
  - opened count
  - skipped count
  - last error
- Surface execution status in the UI so missing opens are visible immediately.
- Add strong logging around `execute_opening_positions()`.

### Push 2: Scheduled Job Reliability

- Wrap every scheduled job in a shared safe runner.
- Persist scheduler failures instead of only logging them.
- Add dashboard-visible scheduler health:
  - last scan
  - last queue lock
  - last open execution
  - last monitor pass
  - last force close
  - last audit
  - last NN scan
- Prevent silent scheduler drift or missed execution windows.
- Add an automatic "missed open execution" detector after `08:45:00` CST when picks exist but open positions do not.

### Push 3: Close Reason Accuracy And Closed Trade Detail

- Fix close labels so `forced_close` only displays as forced close when profitable and closed at the 2:45 PM rule.
- Display loss exits as `Losses cut`, `Stop loss`, or similar accurate wording.
- Display profitable reversal/sell-signal exits as `Reversal close` or similar accurate wording.
- Expand closed trade cards with stored decision data:
  - entry/exit
  - gross/net P&L
  - confidence and lock-in confidence
  - signal scores
  - fired signals
  - raw signal values
  - confluence methods
  - queue amount/source
  - reason text
- Add closed trade sorting and filters:
  - sector
  - close type
  - alphabetical
  - % gain
  - total P&L
  - confidence
  - date
  - method count
  - model source

### Push 4: NN Trade Lifecycle Separation

- Give NN its own pick execution path.
- Create NN open positions from NN picks.
- Close NN positions into `nn_virtual_trades`.
- Add NN closed trade display and analytics.
- Stop treating crude closed trades as the long-term source of truth for NN training.
- Allow crude history only as marked bootstrap training data during transition.

### Push 5: Feature Snapshot Foundation

- Add canonical feature snapshots for candidates, crude trades, and NN trades.
- Store raw features and normalized derived scores at decision time.
- Make crude algo, NN, UI, and closed cards read from the same decision snapshot.
- Use this snapshot for explainability and later model debugging.

### Push 6: Brain Tab Redesign

- Split Brain into crude algo and NN views.
- Crude view should show signal weights, score composition, audits, and feature family explanations.
- NN view should show feature inputs, training status, training history, model stats, and NN-specific trade outcomes.
- Brain tab should show more than signal weights; it should expose the actual data flow.

### Push 7: Stock Card Layout And Journal UX

- Normalize top control heights:
  - Make the hex nut control visually match the color toggle at minimum.
  - Preferred direction: make hex nut, color toggle, and net-view toggle share the same control height for a cleaner toolbar rhythm.
  - Keep icon glyphs optically centered inside their hit areas.
- Restore exact midpoint alignment for decimal dots, triangle apexes, and the journal/bookmark button.
- Treat the stock cards as a strict grid:
  - `OPEN P&L` header must align with the `OPEN P&L` values.
  - `OPEN P&L` values should always render to one decimal place.
  - The `OPEN P&L` decimal point must always sit on the same vertical axis as the expand triangle apex.
  - The expand triangle apex must use the same vertical axis on every card.
  - Keep the confidence delta tag format as-is.
  - Keep `+$0.00` style dollar values; do not over-optimize tiny cent display.
- Keep `on target` on one line. If it wraps, fix the Journal/status grid spacing instead of changing the wording.
- Make the journal button visibly populate Personal or show an error if it fails.
- Clean up missing/blank stock-card columns.
- Restore any useful expanded-card metrics removed in recent pushes.
- Verify on mobile viewport screenshots before shipping.

### Push 8: Win-Rate Filters And Calibration

- Add hard macro/event filters:
  - CPI
  - FOMC
  - jobs report
  - ticker earnings tonight/tomorrow
- Add volatility sanity checks.
- Add trend alignment.
- Add gap-size filter.
- Add ticker quality score.
- Add regime-dependent confidence thresholds.
- Add confidence calibration once enough outcomes exist.

### Push 9: LLM Fallback Chain

- Add Claude primary self-audit.
- Add Gemini/Groq/OpenRouter fallback support for audit JSON.
- Validate every fallback response strictly.
- Keep existing weights if all providers fail.
- Log provider used, failure reason, and audit outcome.
- Keep LLMs advisory only; never make trade execution depend on LLM availability.

## Feature Snapshot Architecture

- Add a canonical `feature_snapshot` for every candidate and executed trade.
- Store both raw feature values and derived normalized scores at decision time.
- Use the same snapshot as the source of truth for crude algo, NN, closed trade cards, and Brain tab display.

## Crude Algo

- Keep the crude system as a weighted signal model, but feed it richer feature families through composed numeric scores.
- Do not force crude algo to consume raw mixed-type features directly.
- Example: support/resistance should become a composed score using:
  - S&R state: open air, support floor, at resistance, neutral, unknown
  - Distance to nearest resistance
  - Distance to nearest support
  - ATR-adjusted room to run
  - Expected move before resistance
  - Break above/below recent supply or demand zones

## Neural Network

- Give NN its own pick generation, buy execution, open positions, and closed trade history.
- Stop training NN only on crude-selected trades long term, because that creates crude-algo selection bias.
- NN should train on its own closed trades once enough NN-specific outcomes exist.
- During transition, allow crude trade history as bootstrap data, but mark it as bootstrap/source data.

## Shared Data Principle

- Both methods should see the same market snapshot, but not necessarily in the same shape:
  - Crude algo reads normalized signal scores.
  - NN reads expanded encoded features.
  - UI displays the same snapshot so the data flow is inspectable.

## Remove Or De-Emphasize Weak Features

- Remove the 5 padding-zero NN inputs.
- De-emphasize or remove `lock_in_confidence` as an NN feature because it can make NN imitate crude confidence.
- De-emphasize or remove `expected_move` as an NN feature because it is derived from crude confidence.
- Treat sector one-hot carefully until there is more training data, because it can overfit.
- Treat news sentiment as optional/low-weight unless the source quality is reliable.
- Ignore `direction` as a meaningful NN feature until short trades are actually enabled.

## UI / Explainability

- Brain tab should show feature families and snapshots, not only crude signal weights.
- Closed trade expanded cards should show the exact feature snapshot that fed the decision.
- Split Brain tab into crude algo and NN views so each model's inputs, weights/features, training history, and outcomes are clear.
