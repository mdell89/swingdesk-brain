import os
import sys
import tempfile
import types
import unittest

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.gettempdir(), "swingdesk_pick_integrity_test.db"))


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
    bullish_confirmation_reasons,
    is_long_pick_eligible,
    repair_quote_baselines_from_history,
)


class PickIntegrityTest(unittest.TestCase):
    def test_history_repair_does_not_overwrite_coherent_provider_previous_close(self):
        quote = {
            "price": 175.90,
            "previous_close": 184.58,
            "open": 183.39,
            "day_change_percent": -4.7025679921985075,
            "day_change_pct": -4.7025679921985075,
            "gap_percent": -0.6447069021562607,
            "previous_close_missing": False,
        }
        history = [
            {"date": "2026-06-05", "open": 170.0, "high": 180.0, "low": 168.0, "close": 175.90},
            {"date": "2026-06-08", "open": 170.0, "high": 180.0, "low": 168.0, "close": 175.90},
        ]

        repaired = repair_quote_baselines_from_history(dict(quote), history)

        self.assertEqual(repaired["previous_close"], 184.58)
        self.assertFalse(repaired.get("baseline_repaired_from_history", False))

    def test_legacy_long_pick_requires_real_bullish_confirmation(self):
        weak_context_only = {
            "ticker": "HSY",
            "price": 175.90,
            "open_price": 183.39,
            "prev_close": 184.58,
            "long_conf": 78,
            "long_move": 5.4,
            "day_change_pct": -4.7,
            "overnight_gap_pct": -0.6,
            "rsi": 50.0,
            "signal_scores": {
                "values": {
                    "support_resistance": {"signal": "open_air"},
                    "vwap_reclaim": {"dist": -4.08},
                }
            },
        }
        confirmed = {
            **weak_context_only,
            "ticker": "DXCM",
            "day_change_pct": 5.1,
            "overnight_gap_pct": 5.1,
            "pct_change_regular_open": 3.6,
        }

        self.assertEqual(bullish_confirmation_reasons(weak_context_only), [])
        self.assertFalse(is_long_pick_eligible(weak_context_only))
        self.assertTrue(bullish_confirmation_reasons(confirmed))
        self.assertTrue(is_long_pick_eligible(confirmed))


if __name__ == "__main__":
    unittest.main()
