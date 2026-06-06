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


if __name__ == "__main__":
    unittest.main()
