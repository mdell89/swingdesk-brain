import os
import sys
import tempfile
import types
import unittest

os.environ["SWINGDESK_DISABLE_STARTUP_TASKS"] = "1"
os.environ["DATABASE_PATH"] = os.path.join(tempfile.gettempdir(), "swingdesk_scan_control_test.db")


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
    SCAN_CONTROL_KEY,
    get_database,
    get_scan_control_settings,
    get_scan_ticker_friction_summary,
    record_scan_ticker_friction,
    should_run_scheduled_comprehensive_scan,
    update_scan_control_settings,
)


class ScanControlTest(unittest.TestCase):
    def setUp(self):
        db = get_database()
        db.execute("DELETE FROM app_state WHERE key=?", [SCAN_CONTROL_KEY])
        db.execute("DELETE FROM scan_events WHERE job_type='comprehensive'")
        db.commit()
        db.close()

    def test_defaults_and_update_are_normalized(self):
        self.assertEqual(get_scan_control_settings()["scan_frequency_minutes"], 30)

        settings = update_scan_control_settings({
            "scheduled_scans_paused": True,
            "scan_frequency_minutes": 120,
        })

        self.assertTrue(settings["scheduled_scans_paused"])
        self.assertEqual(settings["scan_frequency_minutes"], 120)
        self.assertEqual(get_scan_control_settings()["scan_frequency_minutes"], 120)

    def test_scheduled_scan_pause_blocks_scheduler(self):
        update_scan_control_settings({"scheduled_scans_paused": True})

        allowed, reason = should_run_scheduled_comprehensive_scan("pre_market_test")

        self.assertFalse(allowed)
        self.assertEqual(reason, "scheduled_scans_paused")

    def test_ticker_friction_summary_counts_repeat_offenders(self):
        record_scan_ticker_friction(101, "manual_shared", "ALB", "fetching_prices", "quote_missing", provider="massive", reason="no quote")
        record_scan_ticker_friction(102, "manual_shared", "ALB", "fetching_history", "daily_history_missing", provider="massive,twelve_data", reason="no candles")
        record_scan_ticker_friction(102, "manual_shared", "MRVL", "fetching_prices", "price_baseline_suspect", reason="bad baseline")

        summary = get_scan_ticker_friction_summary(limit=5, days=7)
        offenders = summary["repeat_offenders"]

        self.assertEqual(offenders[0]["ticker"], "ALB")
        self.assertEqual(offenders[0]["event_count"], 2)
        self.assertEqual(offenders[0]["scan_count"], 2)
        self.assertEqual(offenders[0]["latest_failure_type"], "daily_history_missing")


if __name__ == "__main__":
    unittest.main()
