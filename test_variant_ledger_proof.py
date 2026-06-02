import sqlite3
import unittest

from glass_proof import build_variant_ledger_proof


def make_database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE variant_portfolios (
            variant_id TEXT PRIMARY KEY,
            starting_cash REAL DEFAULT 1000.0,
            cash REAL DEFAULT 1000.0,
            equity REAL DEFAULT 1000.0,
            realized_pnl REAL DEFAULT 0.0,
            open_value REAL DEFAULT 0.0,
            open_count INTEGER DEFAULT 0,
            closed_count INTEGER DEFAULT 0,
            win_count INTEGER DEFAULT 0,
            loss_count INTEGER DEFAULT 0,
            max_equity REAL DEFAULT 1000.0,
            max_drawdown_pct REAL DEFAULT 0.0,
            lifecycle_status TEXT DEFAULT 'active',
            recommended_status TEXT DEFAULT 'active',
            lifecycle_reasons TEXT DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE variant_virtual_trades (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            outcome TEXT DEFAULT 'open',
            sell_date TEXT,
            invested_amount REAL,
            current_value REAL,
            actual_move REAL,
            gross_pnl REAL,
            net_pnl REAL
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


class VariantLedgerProofTest(unittest.TestCase):
    def test_reconciles_clean_variant_ledger(self):
        db = make_database()
        db.execute("""
            INSERT INTO variant_portfolios
            (variant_id, cash, equity, realized_pnl, open_value, open_count, closed_count)
            VALUES ('v1', 990, 1001.5, 2.5, 11.5, 1, 1)
        """)
        db.execute("""
            INSERT INTO variant_virtual_trades
            (id, variant_id, outcome, invested_amount, current_value)
            VALUES ('open1', 'v1', 'open', 10, 11.5)
        """)
        db.execute("""
            INSERT INTO variant_virtual_trades
            (id, variant_id, outcome, sell_date, gross_pnl, net_pnl)
            VALUES ('closed1', 'v1', 'hit', '2026-06-01', 3.0, 2.5)
        """)
        db.execute("""
            INSERT INTO variant_learning_events
            (id, variant_id, trade_id, timestamp, outcome, actual_move, weights_before, weights_after)
            VALUES ('learn1', 'v1', 'closed1', '2026-06-01T19:00:00', 'hit', 8.0, '{}', '{}')
        """)

        proof = build_variant_ledger_proof(db, {"id": "v1", "brain": "Vector", "strategy": "SwingDesk"})

        self.assertEqual(proof["health"], "ok")
        self.assertTrue(proof["ledger_ok"])
        self.assertEqual(proof["ledger"]["computed_equity"], 1001.5)
        self.assertTrue(proof["learning"]["closed_trades_only"])
        self.assertEqual(proof["learning"]["unlearned_closed_trade_count"], 0)

    def test_flags_ledger_mismatch_and_learning_on_open_trade(self):
        db = make_database()
        db.execute("""
            INSERT INTO variant_portfolios
            (variant_id, cash, equity, realized_pnl, open_value, open_count, closed_count)
            VALUES ('v1', 990, 1000, 0, 10, 1, 0)
        """)
        db.execute("""
            INSERT INTO variant_virtual_trades
            (id, variant_id, outcome, invested_amount, current_value)
            VALUES ('open1', 'v1', 'open', 10, 12)
        """)
        db.execute("""
            INSERT INTO variant_learning_events
            (id, variant_id, trade_id, timestamp, outcome, actual_move, weights_before, weights_after)
            VALUES ('badlearn', 'v1', 'open1', '2026-06-01T19:00:00', 'miss', -5.0, '{}', '{}')
        """)

        proof = build_variant_ledger_proof(db, {"id": "v1", "brain": "Vector", "strategy": "SwingDesk"})

        self.assertEqual(proof["health"], "attention")
        self.assertFalse(proof["ledger_ok"])
        self.assertIn("ledger_mismatch", proof["issues"])
        self.assertIn("learning_event_points_to_open_trade", proof["issues"])
        self.assertFalse(proof["learning"]["closed_trades_only"])


if __name__ == "__main__":
    unittest.main()
