import unittest

from scoring_v2 import (
    explain_brain_difference,
    normalize_signal_weights,
    score_stock_v2,
)


def clean_setup(**overrides):
    data = {
        "ticker": "AMD",
        "price": 100.0,
        "previous_close": 96.0,
        "gap_percent": 4.0,
        "average_daily_dollar_volume": 50_000_000,
        "freshness_status": "fresh",
        "scan_completed_at": "2026-06-05T08:15:00-05:00",
        "provider": "massive",
        "rsi": 61.0,
        "time_matched_relative_volume": 2.2,
        "volume_baseline_sessions": 20,
        "recent_block_volume_acceleration": 1.5,
        "relative_strength_delta": 4.0,
        "sector_relative_strength_delta": 2.0,
        "support_resistance_signal": "open_air",
        "vwap_delta_pct": 1.2,
        "hv_ratio": 0.62,
        "days_to_earnings": 8,
        "atr_percent": 4.0,
        "similar_setup_median_move": 5.0,
        "intraday_range_pct": 3.0,
        "confluence": ["SwingDesk", "Darvas", "Darvas", "Open Air"],
    }
    data.update(overrides)
    return data


class ScoringV2Test(unittest.TestCase):
    def test_valid_gap_up_momentum_can_pass(self):
        result = score_stock_v2(clean_setup())

        self.assertFalse(result["blocked"])
        self.assertTrue(result["actionable"])
        self.assertGreaterEqual(result["score"], 65)
        self.assertEqual(result["score_band"], "valid")
        self.assertEqual(result["data_freshness"]["freshness_status"], "fresh")

    def test_gap_down_long_is_blocked(self):
        result = score_stock_v2(clean_setup(gap_percent=-3.0))

        self.assertTrue(result["blocked"])
        self.assertFalse(result["actionable"])
        self.assertIsNone(result["score"])
        self.assertIn("gap down of 3% or worse", " ".join(result["block_reasons"]))

    def test_missing_previous_close_blocks_gap_dependent_strategy(self):
        result = score_stock_v2(clean_setup(previous_close=None))

        self.assertTrue(result["blocked"])
        self.assertFalse(result["actionable"])
        self.assertIn("previous close missing or invalid", result["block_reasons"])

    def test_earnings_day_blocks_open_or_hold(self):
        result = score_stock_v2(clean_setup(days_to_earnings=0))

        self.assertTrue(result["blocked"])
        self.assertFalse(result["actionable"])
        self.assertIn("earnings day blocks open/hold", result["block_reasons"])

    def test_daily_average_only_volume_cannot_create_strong_or_elite_score(self):
        result = score_stock_v2(clean_setup(
            time_matched_relative_volume=None,
            daily_average_relative_volume=8.0,
        ))

        self.assertFalse(result["blocked"])
        self.assertLessEqual(result["score"], 72)
        self.assertEqual(result["score_band"], "valid")
        self.assertIn("daily_average_volume_only", {cap["name"] for cap in result["caps_applied"]})

    def test_volume_authority_tiers(self):
        full = score_stock_v2(clean_setup(volume_baseline_sessions=20))
        provisional = score_stock_v2(clean_setup(volume_baseline_sessions=12))
        insufficient = score_stock_v2(clean_setup(volume_baseline_sessions=4))

        self.assertNotIn("provisional_volume_baseline", {cap["name"] for cap in full["caps_applied"]})
        self.assertIn("provisional_volume_baseline", {cap["name"] for cap in provisional["caps_applied"]})
        self.assertLessEqual(provisional["score"], 79)
        self.assertIn("insufficient_volume_baseline", {cap["name"] for cap in insufficient["caps_applied"]})
        self.assertLessEqual(insufficient["score"], 74)

        volume_rows = {
            "full": next(row for row in full["signals"] if row["signal_id"] == "volume_surge"),
            "provisional": next(row for row in provisional["signals"] if row["signal_id"] == "volume_surge"),
            "insufficient": next(row for row in insufficient["signals"] if row["signal_id"] == "volume_surge"),
        }
        self.assertEqual(volume_rows["full"]["authority"], 1.0)
        self.assertEqual(volume_rows["provisional"]["authority"], 0.5)
        self.assertEqual(volume_rows["insufficient"]["authority"], 0.0)

    def test_confluence_is_context_only_and_excludes_selected_strategy(self):
        base = clean_setup(confluence=[])
        with_confluence = clean_setup(confluence=["SwingDesk", "Darvas", "VWAP Reclaim", "Darvas"])

        base_result = score_stock_v2(base)
        confluence_result = score_stock_v2(with_confluence)

        self.assertEqual(base_result["score"], confluence_result["score"])
        self.assertEqual(confluence_result["confluence"], ["Darvas", "VWAP Reclaim"])
        self.assertEqual(confluence_result["confluence_count"], 2)

    def test_confluence_cannot_override_hard_gate(self):
        result = score_stock_v2(clean_setup(
            gap_percent=-5.0,
            confluence=["Darvas", "VWAP Reclaim", "Open Air", "Pocket Pivot"],
        ))

        self.assertTrue(result["blocked"])
        self.assertFalse(result["actionable"])
        self.assertEqual(result["confluence_count"], 4)

    def test_missing_active_signal_caps_score(self):
        result = score_stock_v2(clean_setup(relative_strength_delta=None))

        self.assertFalse(result["blocked"])
        self.assertLessEqual(result["score"], 74)
        self.assertIn("missing_active_signal", {cap["name"] for cap in result["caps_applied"]})

    def test_expected_move_is_separate_from_confidence(self):
        result = score_stock_v2(clean_setup(gap_percent=-4.0))

        self.assertTrue(result["blocked"])
        self.assertIsNone(result["score"])
        self.assertGreater(result["expected_move"], 0)
        self.assertIn("confidence_score_used", result["expected_move_detail"]["components"])

    def test_weights_normalize_to_one(self):
        weights = normalize_signal_weights("SwingDesk", {"volume_surge": 10.0, "rsi_momentum": 5.0})

        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertGreater(weights["volume_surge"], weights["rsi_momentum"])

    def test_vector_nova_difference_explanation_uses_isolated_weights(self):
        vector = score_stock_v2(clean_setup(), brain="Vector")
        nova = score_stock_v2(
            clean_setup(),
            brain="Nova",
            weights={
                "volume_surge": 0.30,
                "vwap_reclaim": 0.18,
                "rsi_momentum": 0.08,
                "overnight_gap_probability": 0.10,
                "relative_strength": 0.10,
                "sector_relative_strength": 0.08,
                "support_resistance": 0.08,
                "volatility_squeeze": 0.05,
                "earnings_catalyst": 0.03,
            },
        )

        explanation = explain_brain_difference(vector, nova)

        self.assertTrue(explanation["material"])
        self.assertIn("Vector", explanation["summary"])
        self.assertTrue(any(row["signal_id"] == "volume_surge" for row in explanation["rows"]))


if __name__ == "__main__":
    unittest.main()
