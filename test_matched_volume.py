import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.gettempdir(), "swingdesk_matched_volume_test.db"))


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
    build_scoring_v2_shadow_input,
    calculate_matched_volume_from_bars,
)


def et_timestamp(day, hour, minute):
    dt = datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo("America/New_York"))
    return dt.timestamp()


class MatchedVolumeTest(unittest.TestCase):
    def test_premarket_relative_volume_uses_same_premarket_window(self):
        today = datetime(2026, 6, 8).date()
        bars = [
            {"timestamp": et_timestamp(today, 4, 0), "volume": 1_000},
            {"timestamp": et_timestamp(today, 4, 5), "volume": 1_500},
            {"timestamp": et_timestamp(today, 9, 30), "volume": 99_000},
        ]
        for i, volume in enumerate([900, 1_000, 1_100], start=1):
            day = today - timedelta(days=i)
            bars.extend([
                {"timestamp": et_timestamp(day, 4, 0), "volume": volume / 2},
                {"timestamp": et_timestamp(day, 4, 5), "volume": volume / 2},
                {"timestamp": et_timestamp(day, 9, 30), "volume": 50_000},
            ])

        result = calculate_matched_volume_from_bars(
            bars,
            {"date": today, "start": time(4, 0), "cutoff": time(4, 10), "window": "premarket"},
        )

        self.assertEqual(result["volume_source"], "premarket_time_matched")
        self.assertEqual(result["volume_baseline_sessions"], 3)
        self.assertAlmostEqual(result["premarket_cumulative_volume"], 2_500)
        self.assertAlmostEqual(result["premarket_baseline_median_volume"], 1_000)
        self.assertAlmostEqual(result["premarket_relative_volume"], 2.5)

    def test_regular_time_matched_volume_uses_regular_window(self):
        today = datetime(2026, 6, 8).date()
        bars = [
            {"timestamp": et_timestamp(today, 9, 30), "volume": 4_000},
            {"timestamp": et_timestamp(today, 9, 35), "volume": 2_000},
            {"timestamp": et_timestamp(today, 4, 0), "volume": 20_000},
        ]
        for i, volume in enumerate([2_000, 3_000, 4_000], start=1):
            day = today - timedelta(days=i)
            bars.extend([
                {"timestamp": et_timestamp(day, 9, 30), "volume": volume / 2},
                {"timestamp": et_timestamp(day, 9, 35), "volume": volume / 2},
                {"timestamp": et_timestamp(day, 4, 0), "volume": 30_000},
            ])

        result = calculate_matched_volume_from_bars(
            bars,
            {"date": today, "start": time(9, 30), "cutoff": time(9, 40), "window": "regular"},
        )

        self.assertEqual(result["volume_source"], "regular_time_matched")
        self.assertEqual(result["volume_baseline_sessions"], 3)
        self.assertAlmostEqual(result["regular_cumulative_volume"], 6_000)
        self.assertAlmostEqual(result["regular_baseline_median_volume"], 3_000)
        self.assertAlmostEqual(result["time_matched_relative_volume"], 2.0)

    def test_v2_shadow_input_carries_matched_volume_fields(self):
        payload = build_scoring_v2_shadow_input(
            "COO",
            {
                "price": 95,
                "previous_close": 90,
                "open": 94,
                "gap_percent": 4,
                "day_change_percent": 2,
                "volume_ratio": 1.1,
                "premarket_relative_volume": 2.2,
                "time_matched_relative_volume": 1.8,
                "volume_source": "regular_time_matched",
                "volume_baseline_sessions": 20,
                "premarket_cumulative_volume": 100_000,
                "premarket_baseline_median_volume": 50_000,
                "regular_cumulative_volume": 80_000,
                "regular_baseline_median_volume": 40_000,
            },
            58,
            {},
        )

        self.assertEqual(payload["premarket_relative_volume"], 2.2)
        self.assertEqual(payload["time_matched_relative_volume"], 1.8)
        self.assertEqual(payload["volume_source"], "regular_time_matched")
        self.assertEqual(payload["volume_baseline_sessions"], 20)
        self.assertEqual(payload["premarket_baseline_median_volume"], 50_000)
        self.assertEqual(payload["regular_baseline_median_volume"], 40_000)


if __name__ == "__main__":
    unittest.main()
