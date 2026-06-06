import os
import sqlite3
import sys
import tempfile
import types
import unittest

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "swingdesk_learning_guardrails_test.db")

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
    LEARNING_SIGNAL_GUARDRAILS,
    apply_learning_guardrails,
    canonical_signal_weights,
    learn_variant_from_closed_trade,
)


def make_database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE variant_signal_weights (
            variant_id TEXT PRIMARY KEY,
            brain TEXT,
            weights_json TEXT NOT NULL,
            baseline_weights_json TEXT NOT NULL,
            learning_revision INTEGER DEFAULT 0,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE variant_learning_events (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            trade_id TEXT,
            timestamp TEXT NOT NULL,
            outcome TEXT,
            actual_move REAL,
            weights_before TEXT NOT NULL,
            weights_after TEXT NOT NULL,
            reasoning TEXT DEFAULT '[]'
        );
    """)
    return db


class LearningGuardrailTest(unittest.TestCase):
    def test_guardrails_cap_active_signal_daily_move(self):
        before = canonical_signal_weights()
        proposed = {**before, "rsi_momentum": before["rsi_momentum"] + 0.20}

        after, notes = apply_learning_guardrails(before, proposed)

        self.assertLessEqual(after["rsi_momentum"], before["rsi_momentum"] + 0.020001)
        self.assertTrue(any("rsi_momentum guardrailed" in note for note in notes))
        self.assertAlmostEqual(sum(after.values()), 1.0, places=5)

    def test_guardrails_cap_secondary_signal_more_tightly(self):
        before = canonical_signal_weights()
        proposed = {**before, "volatility_squeeze": before["volatility_squeeze"] + 0.20}

        after, _ = apply_learning_guardrails(before, proposed)

        self.assertLessEqual(after["volatility_squeeze"], before["volatility_squeeze"] + 0.010001)
        self.assertAlmostEqual(sum(after.values()), 1.0, places=5)

    def test_learning_uses_closed_trade_scores_inside_guardrails(self):
        db = make_database()
        before = canonical_signal_weights()
        db.execute("""
            INSERT INTO variant_signal_weights
            (variant_id, brain, weights_json, baseline_weights_json)
            VALUES ('v1', 'Vector', ?, ?)
        """, [__import__("json").dumps(before), __import__("json").dumps(before)])
        trade = {
            "id": "t1",
            "variant_id": "v1",
            "signal_scores": '{"scores":{"rsi_momentum":1.0,"volume_surge":1.0,"overnight_gap_probability":1.0,"earnings_catalyst":1.0,"support_resistance":1.0,"relative_strength":1.0,"sector_relative_strength":1.0,"vwap_reclaim":1.0,"volatility_squeeze":1.0}}',
        }

        status = learn_variant_from_closed_trade(db, trade, "hit", 20)
        row = db.execute("SELECT weights_json FROM variant_signal_weights WHERE variant_id='v1'").fetchone()
        after = __import__("json").loads(row["weights_json"])

        self.assertEqual(status, "updated")
        for key, rule in LEARNING_SIGNAL_GUARDRAILS.items():
            self.assertLessEqual(after[key], before[key] + rule["daily_delta_cap"] + 0.000001)


if __name__ == "__main__":
    unittest.main()
