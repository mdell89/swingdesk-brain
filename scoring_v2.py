from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any


SCORING_ENGINE_VERSION = "scoring_v2"
FORMULA_VERSION = "2026-06-06"
DEFAULT_ACTION_FLOOR = 65
BASE_SCORE = 50
MAX_SIGNAL_POINTS = 35
SECONDARY_AUTHORITY = 0.40


@dataclass(frozen=True)
class SignalProfile:
    role: str
    baseline_weight: float
    learnable: bool = True
    label: str = ""


SWINGDESK_PROFILE = {
    "rsi_momentum": SignalProfile("active", 0.14, label="RSI Momentum"),
    "volume_surge": SignalProfile("active", 0.16, label="Volume Surge"),
    "overnight_gap_probability": SignalProfile("active", 0.14, label="Overnight Gap"),
    "relative_strength": SignalProfile("active", 0.13, label="Relative Strength"),
    "sector_relative_strength": SignalProfile("active", 0.10, label="Sector RS"),
    "support_resistance": SignalProfile("active", 0.12, label="Support/Resistance"),
    "vwap_reclaim": SignalProfile("active", 0.09, label="VWAP Reclaim"),
    "volatility_squeeze": SignalProfile("secondary", 0.07, label="Volatility Squeeze"),
    "earnings_catalyst": SignalProfile("secondary", 0.05, label="Earnings Catalyst"),
}

STRATEGY_PROFILES = {
    "SwingDesk": SWINGDESK_PROFILE,
}

REQUIRED_ACTIVE_SIGNALS = tuple(
    key for key, profile in SWINGDESK_PROFILE.items() if profile.role == "active"
)


def finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def confidence_band(score: int | None) -> str:
    if score is None or score < 65:
        return "skip"
    if score < 75:
        return "valid"
    if score < 85:
        return "strong"
    return "elite"


def average_daily_dollar_volume(data: dict[str, Any]) -> float | None:
    explicit = first_number(
        data,
        "average_daily_dollar_volume",
        "avg_daily_dollar_volume",
        "median_daily_dollar_volume",
    )
    if explicit is not None:
        return explicit

    average_volume = first_number(data, "average_volume", "avg_volume", "median_daily_volume")
    price = first_number(data, "price", "current_price", "last_price", "close")
    if average_volume is None or price is None:
        return None
    if average_volume <= 1:
        return None
    return average_volume * price


def normalize_signal_weights(strategy: str = "SwingDesk", weights: dict[str, Any] | None = None) -> dict[str, float]:
    profile = STRATEGY_PROFILES[strategy]
    raw = {}
    for key, signal_profile in profile.items():
        if signal_profile.role not in ("active", "secondary"):
            continue
        raw[key] = finite_number((weights or {}).get(key))
        if raw[key] is None:
            raw[key] = signal_profile.baseline_weight
    total = sum(max(value, 0.0) for value in raw.values())
    if total <= 0:
        return {
            key: signal_profile.baseline_weight
            for key, signal_profile in profile.items()
            if signal_profile.role in ("active", "secondary")
        }
    return {key: max(value, 0.0) / total for key, value in raw.items()}


def selected_strategy_confluence(confluence: Any, selected_strategy: str) -> list[str]:
    if isinstance(confluence, str):
        items = [part.strip() for part in confluence.split(",")]
    elif isinstance(confluence, (list, tuple, set)):
        items = [str(item).strip() for item in confluence]
    else:
        items = []
    seen = set()
    filtered = []
    selected = selected_strategy.strip().lower()
    for item in items:
        if not item or item.lower() == selected or item.lower() in seen:
            continue
        seen.add(item.lower())
        filtered.append(item)
    return filtered


def first_number(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        number = finite_number(data.get(key))
        if number is not None:
            return number
    return None


def data_freshness(data: dict[str, Any]) -> dict[str, Any]:
    scan_completed_at = data.get("scan_completed_at") or data.get("source_scan_time") or data.get("scan_time")
    provider = data.get("provider") or data.get("price_provider") or data.get("source")
    explicit_status = data.get("freshness_status")
    status = explicit_status or ("fresh" if scan_completed_at else "unknown")
    return {
        "scan_completed_at": scan_completed_at,
        "provider": provider,
        "freshness_status": status,
    }


def gate_row(name: str, passed: bool, reason: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "reason": reason}


def cap_row(name: str, max_score: int, reason: str) -> dict[str, Any]:
    return {"name": name, "max_score": int(max_score), "reason": reason}


def signal_row(
    signal_id: str,
    role: str,
    quality: float | None,
    value: Any,
    status: str,
    reason: str,
    weight: float = 0.0,
    points: float = 0.0,
    authority: float = 1.0,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "role": role,
        "quality": None if quality is None else round(float(quality), 4),
        "value": value,
        "status": status,
        "reason": reason,
        "weight": round(float(weight), 6),
        "authority": round(float(authority), 4),
        "points": round(float(points), 4),
    }


def evaluate_gates(data: dict[str, Any], strategy: str, direction: str, open_tickers: set[str] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    gates = []
    block_reasons = []
    price = first_number(data, "price", "current_price", "last_price", "close")
    previous_close = first_number(data, "previous_close", "prev_close")
    gap_percent = first_number(data, "gap_percent", "gap_pct", "overnight_gap_pct")
    day_change_percent = first_number(data, "day_change_percent", "day_change_pct", "pct_change_prev_close")
    avg_dollar_volume = average_daily_dollar_volume(data)
    ticker = str(data.get("ticker") or "").upper()
    open_tickers = open_tickers or set()

    freshness = data_freshness(data)
    fresh_passed = freshness["freshness_status"] not in ("stale", "failed", "missing")
    gates.append(gate_row("fresh_data", fresh_passed, f"freshness status is {freshness['freshness_status']}"))

    price_passed = price is not None and price > 0
    gates.append(gate_row("valid_price", price_passed, "price is finite and positive" if price_passed else "price missing or invalid"))

    prev_passed = previous_close is not None and previous_close > 0
    gates.append(gate_row("valid_previous_close", prev_passed, "previous close supports gap/day math" if prev_passed else "previous close missing or invalid"))

    liquidity_passed = bool(
        price is not None
        and price >= 2.0
        and (avg_dollar_volume is None or avg_dollar_volume >= 5_000_000)
    )
    liquidity_reason = (
        "price and average daily dollar volume pass prototype floor"
        if liquidity_passed and avg_dollar_volume is not None
        else "liquidity proof missing; score capped until ADV is available"
        if liquidity_passed
        else "price or average daily dollar volume below required floor"
    )
    gates.append(gate_row(
        "acceptable_liquidity",
        liquidity_passed,
        liquidity_reason,
    ))

    direction_passed = direction == "long"
    gates.append(gate_row("valid_direction", direction_passed, "long thesis is enabled" if direction_passed else "short/reversal strategies are disabled"))

    already_open = ticker in {str(item).upper() for item in open_tickers}
    already_open_passed = not already_open
    gates.append(gate_row("not_already_open_unless_scale_in_allowed", already_open_passed, "ticker not already open in this variant" if already_open_passed else "ticker already open in this variant"))

    gap_passed = not (gap_percent is not None and gap_percent <= -3.0)
    gates.append(gate_row("no_strategy_disqualifying_pattern", gap_passed, "no major gap-down long rejection" if gap_passed else "gap down of 3% or worse blocks broad long momentum"))

    red_day_passed = not (day_change_percent is not None and day_change_percent <= -3.0)
    gates.append(gate_row("bullish_day_change_floor", red_day_passed, "no major red-day long rejection" if red_day_passed else "red day of 3% or worse blocks broad long momentum"))

    days_to_earnings = first_number(data, "days_to_earnings", "earnings_days")
    earnings_day = bool(data.get("earnings_day")) or days_to_earnings == 0
    earnings_passed = not earnings_day
    gates.append(gate_row("earnings_day_block", earnings_passed, "not earnings day" if earnings_passed else "earnings day blocks open/hold"))

    for gate in gates:
        if not gate["passed"]:
            block_reasons.append(gate["reason"])
    return gates, block_reasons


def rsi_signal(data: dict[str, Any]) -> dict[str, Any]:
    rsi = first_number(data, "rsi", "rsi_momentum")
    if rsi is None:
        return signal_row("rsi_momentum", "active", None, None, "missing", "RSI missing; active signal cannot silently become neutral")
    if 55 <= rsi <= 65:
        quality, status = 0.7, "momentum"
    elif 45 <= rsi < 55:
        quality, status = 0.0, "neutral"
    elif 65 < rsi <= 72:
        quality, status = 0.4, "extended"
    elif 35 <= rsi < 45:
        quality, status = 0.2, "constructive reset"
    elif rsi < 35:
        quality, status = -0.5, "weak"
    else:
        quality, status = -0.2, "overextended"
    return signal_row("rsi_momentum", "active", quality, rsi, status, f"RSI {rsi:g} interpreted for long momentum")


def volume_signal(data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    caps = []
    sessions = int(first_number(data, "volume_baseline_sessions", "usable_volume_sessions") or 0)
    time_matched = first_number(
        data,
        "time_matched_relative_volume",
        "premarket_relative_volume",
        "completed_session_relative_volume",
        "last_session_relative_volume",
    )
    burst = first_number(data, "recent_block_volume_acceleration", "burst_volume_ratio")
    daily_average = first_number(data, "daily_average_relative_volume", "volume_ratio", "vol_ratio")

    if time_matched is None:
        if daily_average is None:
            caps.append(cap_row("missing_active_signal", 74, "volume baseline missing"))
            return signal_row("volume_surge", "active", None, None, "missing", "volume baseline missing; no silent boost"), caps
        quality = min(max((daily_average - 1.0) / 2.0, -0.4), 0.4)
        caps.append(cap_row("daily_average_volume_only", 72, "daily-average volume is fallback/context only"))
        return signal_row("volume_surge", "active", quality, daily_average, "daily avg", "daily-average volume cannot create a strong/elite score", authority=0.33), caps

    if sessions >= 20:
        authority = 1.0
        status = "completed session" if first_number(data, "completed_session_relative_volume", "last_session_relative_volume") is not None else "full baseline"
    elif sessions >= 10:
        authority = 0.5
        status = "provisional"
        caps.append(cap_row("provisional_volume_baseline", 79, "10-19 usable comparable sessions reduce volume authority"))
    else:
        authority = 0.0
        status = "insufficient"
        caps.append(cap_row("insufficient_volume_baseline", 74, "under 10 comparable sessions makes volume context-only"))

    if time_matched >= 2.0:
        quality = 1.0
    elif time_matched >= 1.5:
        quality = 0.7
    elif time_matched >= 1.2:
        quality = 0.4
    elif time_matched >= 0.8:
        quality = 0.0
    else:
        quality = -0.4

    if burst is not None:
        if burst >= 2.0:
            quality += 0.2
        elif burst >= 1.3:
            quality += 0.1
        elif burst < 0.8:
            quality -= 0.1
    quality = clamp(quality * authority, -1.0, 1.0)
    detail = (
        "completed-session relative volume with baseline authority"
        if first_number(data, "completed_session_relative_volume", "last_session_relative_volume") is not None
        else "time-matched relative volume with baseline authority"
    )
    return signal_row("volume_surge", "active", quality, time_matched, status, detail, authority=authority), caps


def gap_signal(data: dict[str, Any]) -> dict[str, Any]:
    gap = first_number(data, "gap_percent", "gap_pct", "overnight_gap_pct")
    if gap is None:
        return signal_row("overnight_gap_probability", "active", None, None, "missing", "gap requires valid previous close")
    if gap <= -3.0:
        quality, status = -1.0, "rejected"
    elif gap > 15.0:
        quality, status = 0.1, "extension cap"
    elif gap >= 3.0:
        quality, status = 0.7, "constructive"
    elif gap > 0:
        quality, status = 0.3, "mild"
    else:
        quality, status = 0.0, "neutral"
    return signal_row("overnight_gap_probability", "active", quality, gap, status, "gap evaluated for long momentum")


def delta_signal(data: dict[str, Any], signal_id: str, *keys: str) -> dict[str, Any]:
    delta = first_number(data, *keys)
    if delta is None:
        return signal_row(signal_id, "active", None, None, "missing", f"{signal_id} missing; active signal is capped")
    if delta >= 3:
        quality, status = 0.8, "strong"
    elif delta >= 1:
        quality, status = 0.4, "constructive"
    elif delta > -1:
        quality, status = 0.0, "neutral"
    elif delta > -3:
        quality, status = -0.3, "drag"
    else:
        quality, status = -0.6, "weak"
    return signal_row(signal_id, "active", quality, delta, status, f"{signal_id} delta measured against benchmark")


def support_resistance_signal(data: dict[str, Any]) -> dict[str, Any]:
    sr = data.get("sr_analysis") if isinstance(data.get("sr_analysis"), dict) else {}
    score = first_number(data, "support_resistance_score")
    signal = sr.get("signal") or data.get("support_resistance_signal")
    if score is None and finite_number(sr.get("score")) is not None:
        score = finite_number(sr.get("score"))
    if score is None and not signal:
        return signal_row("support_resistance", "active", None, None, "missing", "support/resistance structure missing")
    if score is None:
        quality_map = {
            "open_air": 0.7,
            "breakout": 0.7,
            "support_bounce": 0.5,
            "near_support": 0.3,
            "neutral": 0.0,
            "at_resistance": -0.4,
            "failed_breakout": -0.6,
            "support_broken": -0.7,
        }
        quality = quality_map.get(str(signal), 0.0)
    else:
        quality = clamp((score - 0.5) * 2.0, -1.0, 1.0)
    return signal_row("support_resistance", "active", quality, signal or score, str(signal or "measured"), "support/resistance room and structure")


def vwap_signal(data: dict[str, Any]) -> dict[str, Any]:
    score = first_number(data, "vwap_reclaim_score")
    dist = first_number(data, "vwap_delta_pct", "vwap_dist")
    if score is not None:
        quality = clamp((score - 0.5) * 2.0, -1.0, 1.0)
        return signal_row("vwap_reclaim", "active", quality, score, "measured", "VWAP reclaim score supplied")
    if dist is None:
        return signal_row("vwap_reclaim", "active", None, None, "missing", "VWAP data missing")
    if dist >= 1:
        quality, status = 0.6, "confirmed"
    elif dist >= 0:
        quality, status = 0.3, "above VWAP"
    else:
        quality, status = -0.4, "below VWAP"
    return signal_row("vwap_reclaim", "active", quality, dist, status, "VWAP distance evaluated for continuation")


def squeeze_signal(data: dict[str, Any]) -> dict[str, Any]:
    score = first_number(data, "volatility_squeeze_score")
    hv_ratio = first_number(data, "hv_ratio", "volatility_ratio")
    if score is not None:
        quality = clamp((score - 0.5) * 2.0, -1.0, 1.0)
        return signal_row("volatility_squeeze", "secondary", quality, score, "measured", "volatility squeeze score supplied")
    if hv_ratio is None:
        return signal_row("volatility_squeeze", "secondary", None, None, "missing", "volatility squeeze missing")
    if hv_ratio < 0.5:
        quality, status = 0.8, "extreme compression"
    elif hv_ratio < 0.7:
        quality, status = 0.6, "compression"
    elif hv_ratio < 0.9:
        quality, status = 0.3, "mild compression"
    elif hv_ratio < 1.1:
        quality, status = 0.0, "neutral"
    else:
        quality, status = -0.2, "expanded"
    return signal_row("volatility_squeeze", "secondary", quality, hv_ratio, status, "secondary compression context")


def earnings_signal(data: dict[str, Any]) -> dict[str, Any]:
    days = first_number(data, "days_to_earnings", "earnings_days")
    if days is None:
        return signal_row("earnings_catalyst", "secondary", 0.0, None, "unknown", "earnings catalyst unknown; no score boost")
    if days <= 0:
        quality, status = -1.0, "blocked"
    elif days <= 3:
        quality, status = -0.2, "risk"
    elif days <= 7:
        quality, status = 0.2, "catalyst window"
    else:
        quality, status = 0.0, "distant"
    return signal_row("earnings_catalyst", "secondary", quality, days, status, "earnings is secondary/context unless strategy explicitly trades catalysts")


def evaluate_signals(data: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    caps = []
    volume, volume_caps = volume_signal(data)
    caps.extend(volume_caps)
    signals = [
        rsi_signal(data),
        volume,
        gap_signal(data),
        delta_signal(data, "relative_strength", "relative_strength_delta", "rs_delta"),
        delta_signal(data, "sector_relative_strength", "sector_relative_strength_delta", "sector_rs_delta"),
        support_resistance_signal(data),
        vwap_signal(data),
        squeeze_signal(data),
        earnings_signal(data),
    ]

    for row in signals:
        if row["role"] == "active" and row["quality"] is None:
            caps.append(cap_row("missing_active_signal", 74, f"{row['signal_id']} is missing"))
    return signals, caps


def apply_signal_points(signals: list[dict[str, Any]], weights: dict[str, float], strategy: str) -> list[dict[str, Any]]:
    profile = STRATEGY_PROFILES[strategy]
    rows = []
    for row in signals:
        signal_id = row["signal_id"]
        role = profile.get(signal_id, SignalProfile("disabled", 0.0)).role
        if role == "disabled":
            continue
        quality = row["quality"]
        weight = weights.get(signal_id, 0.0)
        role_authority = SECONDARY_AUTHORITY if role == "secondary" else 1.0
        data_authority = finite_number(row.get("authority"))
        if data_authority is None:
            data_authority = 1.0
        authority = role_authority * data_authority
        points = 0.0 if quality is None else float(quality) * weight * MAX_SIGNAL_POINTS * role_authority
        updated = dict(row)
        updated["role"] = role
        updated["weight"] = round(weight, 6)
        updated["authority"] = round(authority, 4)
        updated["points"] = round(points, 4)
        rows.append(updated)
    return rows


def expected_move(data: dict[str, Any], score: int | None) -> dict[str, Any]:
    price = first_number(data, "price", "current_price", "last_price", "close") or 0.0
    atr_percent = first_number(data, "atr_percent", "atr_pct")
    if atr_percent is None:
        atr = first_number(data, "atr")
        atr_percent = (atr / price * 100) if atr is not None and price > 0 else 0.0
    similar = first_number(data, "similar_setup_median_move") or 0.0
    gap = abs(first_number(data, "gap_percent", "gap_pct", "overnight_gap_pct") or 0.0)
    volume = first_number(data, "time_matched_relative_volume", "premarket_relative_volume", "volume_ratio") or 1.0
    volume_multiplier_cap = clamp(volume, 0.5, 2.5)
    volume_adjusted_gap_component = gap * volume_multiplier_cap
    intraday_range = first_number(data, "intraday_range_pct", "recent_intraday_range_pct") or 0.0
    move = (
        0.40 * atr_percent
        + 0.25 * similar
        + 0.20 * volume_adjusted_gap_component
        + 0.15 * intraday_range
    )
    cap = first_number(data, "expected_move_cap") or 25.0
    provisional = similar == 0.0
    return {
        "expected_move": round(clamp(move, 0.0, cap), 2),
        "provisional": provisional,
        "components": {
            "atr_percent": round(atr_percent, 4),
            "similar_setup_median_move": round(similar, 4),
            "volume_adjusted_gap_component": round(volume_adjusted_gap_component, 4),
            "recent_intraday_range_component": round(intraday_range, 4),
            "confidence_score_used": score,
        },
    }


def score_stock_v2(
    data: dict[str, Any],
    strategy: str = "SwingDesk",
    brain: str = "Vector",
    weights: dict[str, Any] | None = None,
    open_tickers: set[str] | None = None,
) -> dict[str, Any]:
    if strategy not in STRATEGY_PROFILES:
        raise ValueError(f"unsupported Scoring V2 strategy: {strategy}")

    ticker = str(data.get("ticker") or "").upper()
    direction = str(data.get("direction") or "long").lower()
    normalized_weights = normalize_signal_weights(strategy, weights)
    gates, block_reasons = evaluate_gates(data, strategy, direction, open_tickers=open_tickers)
    raw_signals, signal_caps = evaluate_signals(data)
    signals = apply_signal_points(raw_signals, normalized_weights, strategy)

    caps = list(signal_caps)
    freshness = data_freshness(data)
    if freshness["freshness_status"] == "stale":
        caps.append(cap_row("stale_scan", 64, "stale scan cannot be actionable"))
    if average_daily_dollar_volume(data) is None:
        caps.append(cap_row("liquidity_unknown", 64, "average daily dollar volume is missing; review only"))

    raw_score = BASE_SCORE + sum(row["points"] for row in signals)
    cap_limit = min([cap["max_score"] for cap in caps], default=100)
    capped_score = min(raw_score, cap_limit)
    blocked = bool(block_reasons)
    score = None if blocked else int(round(clamp(capped_score, 0, 100)))
    actionable = bool(score is not None and score >= DEFAULT_ACTION_FLOOR and not blocked)
    confluence = selected_strategy_confluence(data.get("confluence") or data.get("confluence_methods"), strategy)
    move = expected_move(data, score)

    if blocked:
        explanation = f"{ticker or 'Ticker'} blocked: {block_reasons[0]}"
    elif actionable:
        explanation = f"{ticker} passed as {confidence_band(score)} with confidence {score}"
    else:
        explanation = f"{ticker} skipped with confidence {score}"

    return {
        "ticker": ticker,
        "strategy": strategy,
        "brain": brain,
        "scoring_engine_version": SCORING_ENGINE_VERSION,
        "formula_version": FORMULA_VERSION,
        "score": score,
        "score_band": confidence_band(score),
        "actionable": actionable,
        "blocked": blocked,
        "block_reasons": block_reasons,
        "caps_applied": caps,
        "data_freshness": freshness,
        "gates": gates,
        "signals": signals,
        "confluence": confluence,
        "confluence_count": len(confluence),
        "brain_differentiators": [],
        "expected_move": move["expected_move"],
        "expected_move_detail": move,
        "weights": normalized_weights,
        "raw_score": round(raw_score, 4),
        "capped_score": None if blocked else round(capped_score, 4),
        "explanation": explanation,
    }


def explain_brain_difference(vector_score: dict[str, Any], nova_score: dict[str, Any]) -> dict[str, Any]:
    vector_value = vector_score.get("score")
    nova_value = nova_score.get("score")
    if vector_value == nova_value and vector_score.get("blocked") == nova_score.get("blocked"):
        return {"material": False, "summary": "Vector and Nova did not materially differ.", "rows": []}

    rows = []
    vector_signals = {row["signal_id"]: row for row in vector_score.get("signals", [])}
    nova_signals = {row["signal_id"]: row for row in nova_score.get("signals", [])}
    for signal_id in sorted(set(vector_signals) | set(nova_signals)):
        vector_row = vector_signals.get(signal_id, {})
        nova_row = nova_signals.get(signal_id, {})
        weight_delta = round(float(nova_row.get("weight") or 0) - float(vector_row.get("weight") or 0), 6)
        point_delta = round(float(nova_row.get("points") or 0) - float(vector_row.get("points") or 0), 4)
        if abs(weight_delta) >= 0.001 or abs(point_delta) >= 0.1:
            rows.append({
                "signal_id": signal_id,
                "vector_weight": vector_row.get("weight"),
                "nova_weight": nova_row.get("weight"),
                "weight_delta": weight_delta,
                "point_delta": point_delta,
            })
    return {
        "material": True,
        "summary": f"Vector {vector_value} vs Nova {nova_value}; differences come from isolated weights, gates, and caps.",
        "rows": rows,
    }
