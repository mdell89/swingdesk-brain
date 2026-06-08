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
    derive_relative_strength_values,
    derive_sector_relative_strength_values,
    five_day_return_pct,
    filter_scoring_v2_variant_rows,
)


def et_timestamp(day, hour, minute):
    dt = datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo("America/New_York"))
    return dt.timestamp()


class MatchedVolumeTest(unittest.TestCase):
    def test_raw_five_day_rs_values_are_exact_scan_inputs(self):
        history = [{"close": value} for value in [100, 101, 102, 103, 110]]
        self.assertAlmostEqual(five_day_return_pct(history), 10.0)

        price_data = {
            "AAPL": {"daily_history": [{"close": value} for value in [100, 100, 100, 100, 110]]},
            "SPY": {"daily_history": [{"close": value} for value in [100, 100, 100, 100, 105]]},
            "XLK": {"daily_history": [{"close": value} for value in [100, 100, 100, 100, 112]]},
        }
        rs = derive_relative_strength_values("AAPL", price_data)

        self.assertEqual(rs["stock_5d"], 10.0)
        self.assertEqual(rs["spy_5d"], 5.0)
        self.assertEqual(rs["delta"], 5.0)
        sector = derive_sector_relative_strength_values("AAPL", price_data)
        self.assertEqual(sector["etf"], "XLK")
        self.assertEqual(sector["etf_5d"], 12.0)
        self.assertEqual(sector["spy_5d"], 5.0)
        self.assertEqual(sector["delta"], 7.0)

    def test_v2_prefers_scan_raw_rs_delta_over_score_fallback(self):
        payload = build_scoring_v2_shadow_input(
            "ABC",
            {
                "price": 50,
                "previous_close": 48,
                "open": 49,
                "gap_percent": 2,
                "day_change_percent": 1,
                "relative_strength_delta": 4.25,
                "sector_relative_strength_delta": 1.75,
                "stock_5d_return": 7.5,
                "spy_5d_return": 3.25,
                "sector_etf": "XLK",
                "sector_etf_5d_return": 5.0,
                "sector_spy_5d_return": 3.25,
            },
            58,
            {},
            signal_scores={"relative_strength": 0.2, "sector_relative_strength": 0.2},
        )

        self.assertEqual(payload["relative_strength_delta"], 4.25)
        self.assertEqual(payload["sector_relative_strength_delta"], 1.75)
        self.assertEqual(payload["relative_strength_source"], "scan_raw_delta")
        self.assertEqual(payload["sector_relative_strength_source"], "scan_raw_delta")
        self.assertEqual(payload["stock_5d_return"], 7.5)
        self.assertEqual(payload["sector_etf"], "XLK")

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

    def test_last_session_volume_becomes_completed_session_v2_input(self):
        payload = build_scoring_v2_shadow_input(
            "MS",
            {
                "price": 120,
                "previous_close": 118,
                "open": 119,
                "gap_percent": 2,
                "day_change_percent": 1,
                "volume_ratio": 2.4,
                "volume_source": "last_session",
                "volume_baseline_sessions": 20,
            },
            60,
            {},
        )

        self.assertEqual(payload["completed_session_relative_volume"], 2.4)
        self.assertEqual(payload["daily_average_relative_volume"], 2.4)

    def test_signal_score_fallback_fills_missing_rs_deltas(self):
        payload = build_scoring_v2_shadow_input(
            "APTV",
            {
                "price": 80,
                "previous_close": 78,
                "open": 79,
                "gap_percent": 2,
                "day_change_percent": 1,
                "volume_ratio": 1.5,
                "volume_source": "last_session",
                "volume_baseline_sessions": 20,
            },
            58,
            {},
            signal_values={
                "relative_strength": {"stock_5d": None, "spy_5d": None},
                "sector_relative_strength": {"etf_5d": None, "spy_5d": None},
            },
            signal_scores={
                "relative_strength": 0.75,
                "sector_relative_strength": 0.5,
            },
        )

        self.assertEqual(payload["relative_strength_delta"], 1.0)
        self.assertEqual(payload["sector_relative_strength_delta"], 0.0)
        self.assertEqual(payload["relative_strength_source"], "legacy_score_fallback")
        self.assertEqual(payload["sector_relative_strength_source"], "legacy_score_fallback")

    def test_v2_swingdesk_preview_uses_v2_actionability_not_legacy_move_gate(self):
        rows = [
            {
                "ticker": "MRVL",
                "v2_actionable": True,
                "v2_score": 66,
                "legacy_confidence": 71,
                "legacy_expected_move": 1.2,
                "long_move": 1.2,
                "gap_percent": 1.0,
                "day_change_percent": 0.5,
            },
            {
                "ticker": "LOW",
                "v2_actionable": False,
                "v2_score": 64,
                "legacy_confidence": 80,
                "legacy_expected_move": 7.0,
            },
        ]

        selected = filter_scoring_v2_variant_rows(
            rows,
            {"strategy": "SwingDesk", "brain": "Vector", "execution_time": "08:45", "selection_mode": "All"},
        )

        self.assertEqual([row["ticker"] for row in selected], ["MRVL"])


if __name__ == "__main__":
    unittest.main()
