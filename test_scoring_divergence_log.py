import os
import sys
import tempfile
import types
import unittest

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.gettempdir(), "swingdesk_divergence_test.db"))


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
    build_scoring_divergence_row,
    get_database,
    initialize_database,
    insert_scoring_divergence_rows,
)
from scoring_v2 import score_stock_v2


class ScoringDivergenceLogTest(unittest.TestCase):
    def setUp(self):
        initialize_database()
        db = get_database()
        db.execute("DELETE FROM scoring_divergence_log")
        db.commit()
        db.close()

    def test_legacy_only_row_persists_v2_caps(self):
        v2_input = {
            "ticker": "MS",
            "direction": "long",
            "price": 100.0,
            "previous_close": 97.0,
            "open": 99.0,
            "gap_percent": 2.0,
            "day_change_percent": 3.1,
            "average_daily_dollar_volume": None,
            "freshness_status": "fresh",
            "scan_completed_at": "2026-06-07T08:45:00-05:00",
            "provider": "test",
            "rsi": 58.0,
            "daily_average_relative_volume": 1.0,
            "vwap_delta_pct": 1.0,
            "days_to_earnings": 99,
        }
        shadow = score_stock_v2(v2_input, strategy="SwingDesk", brain="Vector")
        shadow["input_snapshot"] = v2_input
        pick = {
            "ticker": "MS",
            "price": 100.0,
            "open_price": 99.0,
            "prev_close": 97.0,
            "day_change_pct": 3.1,
            "overnight_gap_pct": 2.0,
            "long_conf": 85,
            "long_move": 6.0,
            "rsi": 58.0,
            "vol_ratio": 1.0,
            "scoring_v2_shadow": shadow,
            "signal_values_for_observation": {"volume_surge": 1.0},
            "fired_signals_for_observation": ["rsi_momentum"],
        }

        row = build_scoring_divergence_row(
            42,
            "2026-06-07T08:45:00-05:00",
            "manual_shared",
            pick,
            "Vector",
            "swingdesk_vector_0845_all",
            selected_tickers=["MS"],
            executable_tickers=["MS"],
            open_tickers=set(),
        )

        self.assertEqual(row["agreement_category"], "legacy_only")
        self.assertEqual(row["legacy_actionable"], 1)
        self.assertEqual(row["v2_actionable"], 0)
        self.assertIn("liquidity_unknown", row["v2_caps_applied"])

        self.assertEqual(insert_scoring_divergence_rows([row]), 1)
        db = get_database()
        saved = db.execute("SELECT agreement_category, split_cause, v2_caps_applied FROM scoring_divergence_log WHERE ticker='MS'").fetchone()
        db.close()

        self.assertEqual(saved["agreement_category"], "legacy_only")
        self.assertTrue(saved["split_cause"])
        self.assertIn("liquidity_unknown", saved["v2_caps_applied"])


if __name__ == "__main__":
    unittest.main()
