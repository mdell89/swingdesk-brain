import json
from collections import Counter


def _extract_signal_scores(payload):
    """Return score map from a persisted trade payload without importing brain.py."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except Exception:
            payload = {}
    if isinstance(payload, dict) and isinstance(payload.get("scores"), dict):
        return payload.get("scores") or {}
    return payload if isinstance(payload, dict) else {}


def _summarize_pick(pick):
    """Small pick snapshot for glass-house diagnostics."""
    if not pick:
        return {}
    return {
        "ticker": pick.get("ticker"),
        "confidence": pick.get("long_conf") or pick.get("confidence") or pick.get("nn_score"),
        "expected_move": pick.get("long_move") or pick.get("expected_move"),
        "day_change_pct": pick.get("day_change_pct") or pick.get("pct_change_prev_close"),
        "volume_ratio": pick.get("vol_ratio") or pick.get("volume_ratio"),
    }


def build_variant_ledger_proof(database, variant, snapshot=None, get_weights=None, filter_picks=None, select_picks=None, explain_strategy=None):
    """Return one variant's aliveness and ledger reconciliation proof."""
    variant = dict(variant)
    variant_id = variant["id"]
    portfolio_row = database.execute(
        "SELECT * FROM variant_portfolios WHERE variant_id=?", [variant_id]
    ).fetchone()
    portfolio = dict(portfolio_row) if portfolio_row else {}
    open_rows = [dict(r) for r in database.execute(
        "SELECT * FROM variant_virtual_trades WHERE variant_id=? AND outcome='open'", [variant_id]
    ).fetchall()]
    closed_rows = [dict(r) for r in database.execute("""
        SELECT * FROM variant_virtual_trades
        WHERE variant_id=?
          AND outcome!='open'
          AND outcome NOT IN ('archived_excess_open')
    """, [variant_id]).fetchall()]
    learned_rows = [dict(r) for r in database.execute("""
        SELECT DISTINCT trade_id
        FROM variant_learning_events
        WHERE variant_id=? AND trade_id IS NOT NULL
    """, [variant_id]).fetchall()]
    learned_trade_ids = {r["trade_id"] for r in learned_rows}

    cash = round(float(portfolio.get("cash") or 0), 4)
    stored_equity = round(float(portfolio.get("equity") or 0), 4)
    stored_open_value = round(float(portfolio.get("open_value") or 0), 4)
    stored_realized_pnl = round(float(portfolio.get("realized_pnl") or 0), 4)
    computed_open_value = round(sum(
        float(r.get("current_value") or r.get("invested_amount") or 0)
        for r in open_rows
    ), 4)
    computed_realized_pnl = round(sum(
        float(r.get("net_pnl") if r.get("net_pnl") is not None else r.get("gross_pnl") or 0)
        for r in closed_rows
    ), 4)
    computed_equity = round(cash + computed_open_value, 4)

    open_value_delta = round(stored_open_value - computed_open_value, 4)
    realized_delta = round(stored_realized_pnl - computed_realized_pnl, 4)
    equity_delta = round(stored_equity - computed_equity, 4)
    tolerance = 0.02
    ledger_ok = (
        abs(open_value_delta) <= tolerance and
        abs(realized_delta) <= tolerance and
        abs(equity_delta) <= tolerance and
        int(portfolio.get("open_count") or 0) == len(open_rows) and
        int(portfolio.get("closed_count") or 0) == len(closed_rows)
    )

    source_count = strategy_qualified = selected_count = 0
    selected_tickers = []
    source_sample = []
    qualified_sample = []
    no_pick_reasons = []
    evaluation_state = "no_snapshot"
    evaluation_issues = []
    if snapshot and get_weights and filter_picks and select_picks:
        source = snapshot["nova_payload"].get("recommended_longs") or snapshot["nova_payload"].get("longs") or []
        if variant.get("brain") != "Nova":
            source = snapshot["vector_payload"].get("longs") or snapshot["vector_payload"].get("recommended_longs") or []
        elif variant.get("brain") == "Nova":
            source = [p for p in source if p.get("nn_executable", True)]
        weights = get_weights(database, variant_id)
        qualified = filter_picks(source, variant, weights)
        selected = select_picks(qualified, variant.get("selection_mode"))
        source_count = len(source)
        strategy_qualified = len(qualified)
        selected_count = len(selected)
        selected_tickers = [p.get("ticker") for p in selected[:20]]
        source_sample = [_summarize_pick(p) for p in source[:5]]
        qualified_sample = [_summarize_pick(p) for p in qualified[:5]]
        evaluation_state = "selected" if selected else "evaluated_no_pick"
        if not source:
            evaluation_issues.append(f"{variant.get('brain')} source pick list is empty")
        if source and not qualified:
            evaluation_issues.append("No source picks matched this variant strategy filter")
            if explain_strategy:
                reason_counter = Counter()
                for pick in source:
                    explanation = explain_strategy(variant.get("strategy"), pick)
                    if explanation.get("matched"):
                        continue
                    reasons = explanation.get("reasons") or ["No strategy rule matched"]
                    reason_counter.update(reasons[:2])
                no_pick_reasons = [
                    {"reason": reason, "count": count}
                    for reason, count in reason_counter.most_common(6)
                ]
        if qualified and not selected:
            evaluation_issues.append("Strategy-qualified picks existed, but selection mode returned none")

    closed_unlearned = [
        r["id"] for r in closed_rows
        if r.get("sell_date") and r.get("id") not in learned_trade_ids
    ]
    open_missing_signal_scores = [
        r["id"] for r in open_rows
        if not _extract_signal_scores(r.get("signal_scores"))
    ]
    learned_open_trade_ids = sorted([
        trade_id for trade_id in learned_trade_ids
        if any(r.get("id") == trade_id for r in open_rows)
    ])
    if learned_open_trade_ids:
        learning_state = "open_trade_violation"
    elif closed_unlearned:
        learning_state = "pending_closed_trade_events"
    else:
        learning_state = "current"

    proof_issues = []
    if not portfolio:
        proof_issues.append("portfolio_missing")
    if not ledger_ok:
        proof_issues.append("ledger_mismatch")
    if learned_open_trade_ids:
        proof_issues.append("learning_event_points_to_open_trade")
    if evaluation_issues:
        proof_issues.extend(evaluation_issues)

    return {
        "variant_id": variant_id,
        "label": variant.get("label"),
        "brain": variant.get("brain"),
        "strategy": variant.get("strategy"),
        "execution_time": variant.get("execution_time"),
        "selection_mode": variant.get("selection_mode"),
        "lifecycle_status": portfolio.get("lifecycle_status"),
        "evaluation_state": evaluation_state,
        "source_count": source_count,
        "strategy_qualified": strategy_qualified,
        "selected_count": selected_count,
        "selected_tickers": selected_tickers,
        "evaluation": {
            "state": evaluation_state,
            "source_count": source_count,
            "strategy_qualified": strategy_qualified,
            "selected_count": selected_count,
            "selected_tickers": selected_tickers,
            "source_sample": source_sample,
            "qualified_sample": qualified_sample,
            "no_pick_reasons": no_pick_reasons,
        },
        "ledger_ok": ledger_ok,
        "ledger": {
            "cash": cash,
            "stored_equity": stored_equity,
            "computed_equity": computed_equity,
            "equity_delta": equity_delta,
            "stored_open_value": stored_open_value,
            "computed_open_value": computed_open_value,
            "open_value_delta": open_value_delta,
            "stored_realized_pnl": stored_realized_pnl,
            "computed_realized_pnl": computed_realized_pnl,
            "realized_pnl_delta": realized_delta,
            "stored_open_count": int(portfolio.get("open_count") or 0),
            "computed_open_count": len(open_rows),
            "stored_closed_count": int(portfolio.get("closed_count") or 0),
            "computed_closed_count": len(closed_rows),
            "tolerance": tolerance,
        },
        "learning": {
            "closed_trade_count": len(closed_rows),
            "learned_closed_trade_count": len([r for r in closed_rows if r.get("id") in learned_trade_ids]),
            "unlearned_closed_trade_count": len(closed_unlearned),
            "unlearned_closed_trade_ids": closed_unlearned[:25],
            "learned_open_trade_ids": learned_open_trade_ids[:25],
            "closed_trades_only": not learned_open_trade_ids,
            "state": learning_state,
            "open_missing_signal_score_count": len(open_missing_signal_scores),
            "open_missing_signal_score_ids": open_missing_signal_scores[:25],
        },
        "issues": proof_issues,
        "health": "ok" if not proof_issues else "attention",
    }


def proof_contract():
    """Human-readable contract surfaced by the glass-house endpoint."""
    return {
        "variant_alive": "Active variant has a portfolio and can evaluate the latest shared Vector/Nova snapshot.",
        "evaluation": "selected_count explains live picks; evaluated_no_pick rows include source/qualified counts and filter reasons when the source list was non-empty.",
        "ledger": "equity must equal cash plus open_value; open_value and realized_pnl must tie to variant_virtual_trades.",
        "learning": "daily learning may only consume closed trades with sell_date; every eligible closed trade must produce either a weight-change event or an explicit no-op event.",
        "audit": "audit is read-only recap; weights_before and weights_after in audit_log are expected to match.",
    }
