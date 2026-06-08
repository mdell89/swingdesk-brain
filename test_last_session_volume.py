import os
import sys
import tempfile
import types
import unittest

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.gettempdir(), "swingdesk_volume_test.db"))


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

from brain import apply_volume_context_from_history


class LastSessionVolumeTest(unittest.TestCase):
    def test_closed_market_uses_last_completed_session_volume(self):
        history = [
            {"date": "2026-06-01", "volume": 1_000_000},
            {"date": "2026-06-02", "volume": 1_000_000},
            {"date": "2026-06-03", "volume": 1_000_000},
            {"date": "2026-06-04", "volume": 1_000_000},
            {"date": "2026-06-05", "volume": 3_000_000},
        ]
        quote = {"price": 20, "volume": 0, "volume_ratio": 1.0}

        result = apply_volume_context_from_history(quote, history, market_open=False)

        self.assertEqual(result["volume_source"], "last_session")
        self.assertEqual(result["volume"], 3_000_000)
        self.assertEqual(result["volume_baseline_sessions"], 4)
        self.assertAlmostEqual(result["volume_ratio"], 3.0)

    def test_open_market_keeps_live_volume_context_when_present(self):
        history = [
            {"date": "2026-06-01", "volume": 1_000_000},
            {"date": "2026-06-02", "volume": 1_000_000},
            {"date": "2026-06-03", "volume": 1_000_000},
        ]
        quote = {"price": 20, "volume": 500_000}

        result = apply_volume_context_from_history(quote, history, market_open=True)

        self.assertEqual(result["volume_source"], "live")
        self.assertEqual(result["volume_baseline_sessions"], 3)
        self.assertAlmostEqual(result["volume_ratio"], 0.5)


if __name__ == "__main__":
    unittest.main()
