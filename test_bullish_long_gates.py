import unittest
import os
import sys
import tempfile
import types

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "swingdesk_bullish_gate_test.db")


class _FakeModule:
    def __init__(self, *args, **kwargs):
        pass
    def __call__(self, value):
        return value
    def eval(self):
        return self
    def state_dict(self):
        return {}
    def load_state_dict(self, _state):
        return self


fake_torch = types.ModuleType("torch")
fake_torch.tensor = lambda value, *args, **kwargs: value
fake_torch.nn = types.SimpleNamespace(
    Module=_FakeModule,
    Linear=_FakeModule,
    Dropout=_FakeModule,
    ReLU=_FakeModule,
    Sigmoid=_FakeModule,
)
fake_torch.optim = types.SimpleNamespace(Adam=_FakeModule)
sys.modules.setdefault("torch", fake_torch)
sys.modules.setdefault("torch.nn", fake_torch.nn)
sys.modules.setdefault("torch.optim", fake_torch.optim)

from brain import (
    calculate_confidence_score,
    estimate_overnight_move,
    is_long_pick_eligible,
    legacy_long_rsi_score,
    validate_quote_baselines,
)


class BullishLongGateTest(unittest.TestCase):
    def test_shared_long_gate_rejects_major_gap_down(self):
        pick = {
            "ticker": "LULU",
            "price": 100,
            "long_conf": 82,
            "long_move": 8,
            "overnight_gap_pct": -8.6,
            "day_change_pct": -8.6,
        }

        self.assertFalse(is_long_pick_eligible(pick))

    def test_shared_long_gate_rejects_major_red_day_even_without_gap(self):
        pick = {
            "ticker": "BITF",
            "price": 5,
            "long_conf": 82,
            "long_move": 8,
            "overnight_gap_pct": 0.5,
            "day_change_pct": -13.5,
        }

        self.assertFalse(is_long_pick_eligible(pick))

    def test_legacy_long_gap_math_does_not_reward_negative_gaps(self):
        weights = {
            "rsi_momentum": 0.15,
            "volume_surge": 0.15,
            "overnight_gap_probability": 0.18,
            "earnings_catalyst": 0.14,
            "support_resistance": 0.13,
            "relative_strength": 0.12,
            "sector_relative_strength": 0.10,
            "vwap_reclaim": 0.08,
            "volatility_squeeze": 0.05,
        }
        price_data = {
            "SPY": {"daily_history": []},
            "LULU": {
                "price": 100,
                "previous_close": 110,
                "open": 100,
                "gap_percent": -8.6,
                "day_change_percent": -8.6,
                "volume_ratio": 3.0,
                "daily_history": [],
            },
        }

        confidence = calculate_confidence_score("LULU", price_data, 55, {}, weights, "long")
        expected_move = estimate_overnight_move(price_data["LULU"], 68, False)
        neutral_gap_move = estimate_overnight_move({**price_data["LULU"], "gap_percent": 0}, 68, False)

        self.assertEqual(confidence, 0)
        self.assertEqual(expected_move, neutral_gap_move)

    def test_implausible_quote_baseline_is_not_actionable(self):
        quote = validate_quote_baselines({
            "ticker": "BITF",
            "price": 2.59,
            "previous_close": 1.0,
            "open": 2.59,
            "gap_percent": 159.0,
            "day_change_percent": 159.0,
        })

        self.assertTrue(quote["price_baseline_suspect"])
        self.assertFalse(is_long_pick_eligible({
            "ticker": "BITF",
            "price": quote["price"],
            "long_conf": 80,
            "long_move": 7,
            "gap_percent": quote["gap_percent"],
            "day_change_percent": quote["day_change_percent"],
            "price_baseline_suspect": quote["price_baseline_suspect"],
            "freshness_status": quote["freshness_status"],
        }))

    def test_daily_history_repairs_bad_previous_close(self):
        quote = validate_quote_baselines(
            {
                "ticker": "BITF",
                "price": 2.59,
                "previous_close": 1.0,
                "open": 2.55,
                "gap_percent": 155.0,
                "day_change_percent": 159.0,
            },
            [{"date": "2026-06-05", "close": 2.55}],
        )

        self.assertFalse(quote.get("price_baseline_suspect", False))
        self.assertAlmostEqual(quote["previous_close"], 2.55)
        self.assertAlmostEqual(quote["day_change_percent"], 1.568627450980386)

    def test_missing_previous_close_is_not_actionable_without_history_repair(self):
        quote = validate_quote_baselines({
            "ticker": "BITF",
            "price": 2.59,
            "previous_close": 2.59,
            "previous_close_missing": True,
            "open": 2.59,
        })

        self.assertTrue(quote["price_baseline_suspect"])
        self.assertFalse(is_long_pick_eligible({
            "ticker": "BITF",
            "price": quote["price"],
            "long_conf": 80,
            "long_move": 7,
            "previous_close_missing": True,
            "freshness_status": quote["freshness_status"],
            "price_baseline_suspect": True,
        }))

    def test_old_cached_premarket_spike_field_is_not_actionable(self):
        self.assertFalse(is_long_pick_eligible({
            "ticker": "BITF",
            "price": 2.59,
            "long_conf": 80,
            "long_move": 7,
            "pct_change_premarket": 159.0,
            "day_change_pct": 0.0,
            "gap_percent": 0.0,
        }))

    def test_mixed_premarket_baselines_are_quarantined(self):
        quote = validate_quote_baselines({
            "ticker": "ALB",
            "price": 149.84,
            "previous_close": 149.84,
            "open": 158.02,
            "gap_percent": 5.46,
            "premarket_change_percent": -3.6,
            "day_change_percent": 0.0,
        })

        self.assertTrue(quote["price_baseline_suspect"])
        self.assertIn("premarket", quote["price_baseline_suspect_reason"])
        self.assertFalse(is_long_pick_eligible({
            "ticker": "ALB",
            "price": quote["price"],
            "long_conf": 91,
            "long_move": 6.1,
            "rsi": 27.9,
            "price_baseline_suspect": quote["price_baseline_suspect"],
            "freshness_status": quote["freshness_status"],
        }))

    def test_severe_low_rsi_does_not_clear_broad_long_gate(self):
        self.assertFalse(is_long_pick_eligible({
            "ticker": "ALB",
            "price": 149.84,
            "long_conf": 91,
            "long_move": 6.1,
            "gap_percent": 1.0,
            "day_change_pct": 0.5,
            "rsi": 27.9,
        }))

    def test_legacy_long_rsi_sweet_spot_beats_oversold(self):
        self.assertEqual(legacy_long_rsi_score(55), 1.0)
        self.assertLess(legacy_long_rsi_score(42), legacy_long_rsi_score(55))
        self.assertEqual(legacy_long_rsi_score(28), 0.0)


if __name__ == "__main__":
    unittest.main()
