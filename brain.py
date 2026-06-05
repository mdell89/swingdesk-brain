"""
brain.py — Overnight Swing Desk Backend v23 (Push 51)
════════════════════════════════════════════════════════
Trading Engine with Self-Regulating Queue System

Changes in Push 51:
  - Fix RSI to use Wilder's smoothed moving average — matches TradingView, Finviz,
    and all standard implementations. Previous simple average diverged at extremes
    where the 40/65 scoring thresholds fire.
  - Remove dead duplicate fetch_current_prices definition — first copy was silently
    shadowed by the second. Eliminates confusion for anyone reading the code.
  - Fix dynamic confidence during monitoring — both primary and NN monitors now pull
    daily_history from scan cache so RSI/S&R/RS/Sector RS/Squeeze compute from real
    data instead of always returning neutral 0.5. Sell decisions based on confidence
    changes during the day are now meaningful for the first time.

Previous (Push 50):
  - Fix minutes_until_forced_close() to return 0 instead of negative after 2:45 PM
    — prevents downstream logic from using meaningless negative values
  - Add end-of-day equity snapshot job at 2:50 PM CST for all active variants
    — ensures every variant has a daily equity baseline for frontend Day's P&L
    — glass house principle: Day's P&L should always show real daily change
  - Add SIGTERM/atexit graceful shutdown handler — if Railway deploys after 2:45 PM,
    emergency force-close runs before the process dies, preventing positions from
    staying open overnight due to deploy timing

Previous (Push 49):
  - Remove refresh_variant_open_quotes from /api/variant/<id> — eliminates 20-second
    variant switch delay caused by live Finnhub calls per open position
  - Fix execution-time signal snapshot: now reads cached price data (with daily_history)
    from scan cache instead of building empty-history dict. All 9 signals now stored
    correctly on every trade, enabling the learning loop to actually learn from
    S&R, RS, Sector RS, and Squeeze outcomes for the first time.

Previous (Push 48):
  - Fix CDT timezone: replaced hardcoded TIMEZONE_OFFSET with zoneinfo ZoneInfo("America/Chicago")
    — current_time_cst() now handles CST/CDT automatically year-round
  - Fix daily_history cache stripping: cache now stores full price data including daily_history
    — restores all 9 signals (S&R, RS, Sector RS, Squeeze, RSI) from cached data
  - Guard buy_price=0 at execution: skip trade insert if no valid price available
  - Force-close price fallback chain: live fetch → quote cache (10min) → stored current_value → flag
    — notifications now use fee_quote net_pnl, not raw pre-fee calculation
    — buy_price=0 guard added to force-close path
  - Sector system: get_sector() now checks DB cache before SECTOR_MAP
    — fetch_and_cache_sector() fetches from Finnhub company profile
    — /api/backfill-sectors endpoint for one-time universe-wide sector mapping

Previous (Push 47b):
  - Switched from Twelve Data to Finnhub (free tier, 60 calls/min, no daily limit)
  - fetch_finnhub_quote(): single ticker quote — price, prev_close, OHLCV
  - fetch_finnhub_candles(): daily OHLCV history for RSI + confluence scoring
  - fetch_price_data(): cache-first strategy — loads from app_state cache,
    refreshes max 60 tickers per scan cycle from Finnhub
  - fetch_current_prices(): Finnhub quote per open position ticker
  - fetch_twelve_data_live(): now wraps Finnhub quote calls (renamed for compat)
  - enrich_with_live_prices(): Finnhub quotes for extended hours enrichment
  - FINNHUB_KEY env var required in Railway

Previous (Push 47):
  - FULL Twelve Data migration — yfinance removed from all critical paths
  - fetch_twelve_data_batch(): new batch OHLCV fetcher (up to 120 tickers/call)
    includes daily_history for confluence scoring — no separate history fetch
  - fetch_twelve_data_live(): new batch quote fetcher for monitoring
    one call per cycle for all open positions combined
  - fetch_price_data(): now uses Twelve Data exclusively
  - fetch_current_prices(): now uses Twelve Data exclusively
  - calculate_rsi_batch(): uses pre-fetched daily_history — zero extra API calls
  - enrich_price_data_with_history(): no-op when history already in price_data
  - enrich_with_live_prices(): uses Twelve Data live quotes instead of fast_info
  - check_upcoming_earnings(): uses Twelve Data earnings calendar
  - check_52w_breakouts(): uses daily_history already in price_data — zero extra calls
  - monitor dynamic confidence: reuses fetched price — no extra fetch_price_data call
  - TWELVE_DATA_KEY env var required in Railway

Previous (Push 46):
  - run_comprehensive_scan: excludes open position tickers — monitor owns those
    eliminates DB lock conflicts between scan and monitor writes
  - monitor: allows after-hours price writes (pre/post market + evenings)
    skips sell decisions outside regular market hours
    weekends still fully skipped
  - scheduler: dynamic monitor interval — 2.5 min regular hours, 5 min extended
  - Day 2 confidence time-decay: confidence tightens as 2:45 PM approaches
    decay multiplier: 1.0 at open → 0.6 at close (40% reduction over sell day)
  - Telegram bot infrastructure: send_telegram_notification() added
    NOTIFY_PROVIDER=telegram env var switches from Twilio to Telegram
    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID required in Railway env vars
    test-notification and notification-settings updated for both providers
  - notification-settings: returns provider, telegram_configured, twilio_configured

Previous (Push 45d):
  - get_database: timeout=30 + PRAGMA busy_timeout=30000 — fixes database locked errors
    monitor and scans were competing causing monitor to never write prices
  - fetch_current_prices: returns {ticker: {price, day_change_pct}} dicts
    Alpha Vantage fallback when fast_info returns nothing
  - monitor: reads price dict, writes day_change_percent to virtual_trades
  - banner-prices: ^VIX fix, switched to fast_info per ticker (no batch download)
  - day_change_percent: new column on virtual_trades, returned from open-positions-dynamic

Previous (Push 44b):
  - 8:15 AM CST pre-market scan added to scheduler
  - 8:25 AM CST queue lock-in — freezes pick queue before open
  - Twilio SMS notifications on position close (any reason)
  - /api/notification-settings GET+POST
  - /api/test-notification POST
  - enrich_with_live_prices: pre/post market price override via yf.fast_info
    gap_percent recalculated in pre-market, day_change in post-market
    covers both sessions with single is_extended_hours() check

Previous (Push 38):
  - compute_signal_scores: adds "values" dict with raw measurements per indicator
    (RSI value, volume ratio, gap %, days to earnings, S&R signal, RS diff,
     sector ETF name + diff, VWAP mode + distance, HV ratio)

Previous (Push 36):
  - /api/reset-weights: POST endpoint to write 9-signal default weights to DB
  - initialize_database: detects + fills missing weight keys in existing weights JSON
  - perf-history: seed point uses last trading weekday date, fixes 1D chart weekend bug
  - get_queue_status: returns dynamic fallback amount instead of hardcoded DEFAULT_INVESTMENT

Previous (Push 35):
  - Relative Strength vs Market: 5-day stock return vs SPY scoring indicator
  - Sector Relative Strength: 5-day sector ETF vs SPY scoring indicator
  - VWAP Distance/Reclaim: institutional conviction signal + 9th confluence method
  - Historical Volatility Ratio/Squeeze: compression detection + 10th confluence method
  - Scoring engine expanded 5 → 9 indicators, weights rebalanced
  - Confluence methods expanded 8 → 10, X/8 → X/10
  - weights_history schema: 4 new indicator columns added
  - Audit prompt updated for all 9 indicators
  - DB migration for new weight columns

Previous (Push 34):
  - Support & Resistance: ATR-14 adaptive swing pivot detection + zone clustering
  - S&R added as 6th scoring indicator, replacing sector_rotation ghost weight
  - sector_rotation weight migrated → support_resistance on DB startup
  - weights_history schema: sector_rotation column kept, support_resistance added
  - calculate_confidence_score: real 5-signal scoring, multiplier recalibrated to 110
  - calculate_method_confluence: S&R added as 8th method
  - method-stats API: S&R included in methods list
  - enrich_price_data_with_history: 30d → 60d for meaningful pivot history
  - Audit prompt updated: explains S&R signal to Claude for weight learning
  - All backfill endpoints updated to use support_resistance column
  - 1D chart / Day's P&L weekend fix: prior-day close used as baseline anchor

Architecture:
    - Comprehensive scans every 30 min during pre/post market (~1,500 tickers)
    - 5-minute targeted monitoring on candidates + open positions
    - FIFO queue system for position sizing (compounding)
    - Dynamic sell engine with real-time decision making
    - Force-close deadline at 2:45 PM CST

Queue System:
    The queue is a FIFO (first-in, first-out) list of dollar amounts.
    When a trade closes (sold or covered), its ending value (original
    investment + profit/loss) is appended to the back of the queue.
    When a new trade opens, it takes the next available amount from
    the front of the queue. If the queue is empty, it falls back to
    the default amount ($10.00).

    This creates a naturally self-regulating position sizing system:
    - Winning streaks → queue amounts grow → larger future positions
    - Losing streaks → queue amounts shrink → smaller future positions
    - No manual intervention needed — risk scales automatically
    - No floors or ceilings — pure compounding in both directions

    When multiple trades close simultaneously (e.g., force-close at
    2:45 PM), their queue order is randomized to avoid systematic
    bias. Similarly, when multiple candidates appear on the same scan,
    queue amounts are assigned in randomized order.

Confidence Floor:
    Only stocks scoring 65% confidence or higher are considered.
    Nothing below 65% is logged, traded, or stored. This keeps the
    database clean and ensures the brain only learns from predictions
    it has meaningful conviction about.
"""

import os, json, sqlite3, time, logging, threading, random, math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from glass_proof import build_variant_ledger_proof as build_variant_ledger_proof_core, proof_contract
import torch
import torch.nn as nn
import torch.optim as optim

load_dotenv()

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_KEY") or os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY")
GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
MISTRAL_API_KEY      = os.getenv("MISTRAL_API_KEY")
TOGETHER_API_KEY     = os.getenv("TOGETHER_API_KEY")
OPENROUTER_API_KEY   = os.getenv("OPENROUTER_API_KEY")
XAI_API_KEY          = os.getenv("XAI_API_KEY")
PERPLEXITY_API_KEY   = os.getenv("PERPLEXITY_API_KEY")
ALPHA_VANTAGE_KEY    = os.getenv("ALPHA_VANTAGE_KEY")
MASSIVE_API_KEY      = os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
DATABASE_PATH        = Path(os.environ.get("DATABASE_PATH", "/app/data/portfolio_brain.db"))
DEFAULT_INVESTMENT   = 10.00     # Fallback when queue is empty
STARTING_PORTFOLIO_VALUE = 1000.0
CONFIDENCE_FLOOR     = 65        # Minimum confidence to recommend/trade
MIN_EXPECTED_MOVE    = 5.0       # Minimum predicted overnight move (%)
MAX_LONG_PICKS       = 20        # Maximum long recommendations per scan
MAX_SHORT_PICKS      = 10        # Maximum short recommendations per scan
MIN_VOLUME_RATIO     = 1.2       # Minimum volume activity to confirm a real setup
MAX_ALL_VARIANT_OPEN_POSITIONS = 50
SCAN_EVENT_RETENTION_DAYS = 30   # Raw operational scan telemetry retention
ARCHIVED_VARIANT_OUTCOMES = ("archived_excess_open",)
MODEL_STOP_LOSS_REASON = "model_stop_loss"
LEGACY_STOP_LOSS_REASONS = {"stop_loss", MODEL_STOP_LOSS_REASON}
MONITOR_INTERVAL     = 300       # 5 minutes in seconds
SCAN_BATCH_SIZE      = 100       # Tickers per yfinance batch call

STOCK_FEE_MODEL_VERSION = "sd_stock_conservative_stress_v1"
STOCK_BUY_FRICTION_RATE = 0.001      # 0.10% buy-side spread/slippage buffer
STOCK_SELL_FRICTION_RATE = 0.001     # 0.10% sell-side spread/slippage buffer
SEC_SECTION_31_RATE = 20.60 / 1_000_000.0  # Sell-side notional fee, as of 2026-04-04.
FINRA_TAF_PER_SHARE = 0.000195       # Sell-side equity TAF.
FINRA_TAF_CAP = 9.79

CRYPTO_FEE_MODEL_VERSION = "sd_crypto_conservative_stress_v1"
CRYPTO_BUY_FRICTION_RATE = 0.01      # Pinned for SDCrypto: 1.00% buy-side friction.
CRYPTO_SELL_FRICTION_RATE = 0.01     # Pinned for SDCrypto: 1.00% sell-side friction.

FEE_MODEL_COLUMN_DEFINITIONS = [
    "fee_model_version TEXT",
    "entry_fee REAL DEFAULT 0.0",
    "entry_slippage REAL DEFAULT 0.0",
    "exit_fee REAL DEFAULT 0.0",
    "exit_slippage REAL DEFAULT 0.0",
    "total_fees REAL DEFAULT 0.0",
    "gross_current_value REAL",
    "share_quantity REAL",
]
FEE_MODEL_COLUMNS = [column_definition.split()[0] for column_definition in FEE_MODEL_COLUMN_DEFINITIONS]
FEE_MODEL_INSERT_COLUMNS = ", ".join(FEE_MODEL_COLUMNS)
FEE_MODEL_INSERT_PLACEHOLDERS = ", ".join(["?"] * len(FEE_MODEL_COLUMNS))
FEE_MODEL_UPDATE_SET = ", ".join([f"{column}=?" for column in FEE_MODEL_COLUMNS])

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

_monitor_singleflight_lock = threading.Lock()
_comprehensive_scan_lock = threading.Lock()

# ── NEURAL NETWORK ────────────────────────────────────────────────────────────
# SwingDeskNet: feedforward NN for overnight swing trade prediction
# Input: ~46 features (9 signal scores + raw values + metadata + news sentiment)
# Architecture: 46 → 32 → 16 → 1, ReLU activations, dropout(0.3), sigmoid output
# Trains nightly on closed virtual_trades. Runs inference every scan cycle.
# model.train() during audit, model.eval() during live scanning.

NN_INPUT_SIZE  = 46   # Updated if feature set changes
NN_HIDDEN1     = 32
NN_HIDDEN2     = 16
NN_DROPOUT     = 0.3
NN_CONFIDENCE_FLOOR = 65  # Same floor as crude algo
NN_MODEL_KEY   = "nn_model_weights"  # app_state key for persisted weights
NN_SCAN_STATUS_KEY = "nn_scan_status"
_nn_scan_thread_lock = threading.Lock()

class SwingDeskNet(nn.Module):
    """
    Feedforward neural network for overnight swing trade prediction.
    Output: probability 0.0-1.0 that a trade will be a hit.
    Dropout(0.3) active during training, disabled during inference (model.eval()).
    """
    def __init__(self, input_size=NN_INPUT_SIZE):
        super(SwingDeskNet, self).__init__()
        self.fc1     = nn.Linear(input_size, NN_HIDDEN1)
        self.drop1   = nn.Dropout(NN_DROPOUT)
        self.fc2     = nn.Linear(NN_HIDDEN1, NN_HIDDEN2)
        self.drop2   = nn.Dropout(NN_DROPOUT)
        self.fc3     = nn.Linear(NN_HIDDEN2, 1)
        self.relu    = nn.ReLU()
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        x = self.relu(self.fc1(x))
        x = self.drop1(x)
        x = self.relu(self.fc2(x))
        x = self.drop2(x)
        x = self.sigmoid(self.fc3(x))
        return x

# Global model instance — loaded at startup, updated nightly
_nn_model = SwingDeskNet()
_nn_model.eval()  # Start in eval mode

def save_nn_weights():
    """Persist model weights to DB so they survive Railway restarts."""
    try:
        db = get_database()
        weights = {k: v.tolist() for k, v in _nn_model.state_dict().items()}
        db.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
            [NN_MODEL_KEY, json.dumps(weights)])
        db.close()
        log.info("NN weights saved to DB")
    except Exception as e:
        log.error(f"Failed to save NN weights: {e}")

def load_nn_weights():
    """Load persisted model weights from DB on startup."""
    global _nn_model
    try:
        db = get_database()
        row = db.execute("SELECT value FROM app_state WHERE key=?", [NN_MODEL_KEY]).fetchone()
        db.close()
        if row:
            weights = json.loads(row["value"])
            state_dict = {k: torch.tensor(v) for k, v in weights.items()}
            _nn_model.load_state_dict(state_dict)
            _nn_model.eval()
            log.info("NN weights loaded from DB")
        else:
            log.info("No saved NN weights found — starting with random initialization")
    except Exception as e:
        log.warning(f"Could not load NN weights: {e} — using random init")

SECTOR_LIST = ["Tech", "Finance", "Energy", "Healthcare", "Industrial",
               "Consumer", "Defense", "Auto", "Crypto", "Other"]

SR_SIGNAL_MAP = {
    "open_air": (1, 0, 0),
    "open_air+support_floor": (1, 1, 0),
    "resistance_in_range": (0, 0, 1),
    "at_resistance": (0, 0, 1),
    "neutral": (0, 0, 0),
    "unknown": (0, 0, 0),
}

def extract_nn_features(trade_row):
    """
    Extract and normalize all ~46 input features from a virtual_trades row.
    Returns a list of floats ready for torch.tensor(), or None if data insufficient.

    Feature groups:
      [0-8]   9 signal scores (float 0-1)
      [9-14]  raw RSI, volume_ratio, gap_percent, days_to_earnings, vwap_dist, hv_ratio
      [15-17] sr_signal binary flags: is_open_air, has_support_floor, is_at_resistance
      [18-19] vwap_is_real, direction (long=1)
      [20]    lock_in_confidence normalized (/ 99)
      [21]    expected_move normalized (/ 25)
      [22]    day_change_percent normalized (/ 10, clipped)
      [23]    broke_52w_high binary
      [24]    broke_52w_days_ago normalized (/ 7, 0 if none)
      [25]    weekend_hold binary
      [26]    stock_5d_return normalized (/ 20, clipped)
      [27]    spy_5d_return normalized (/ 20, clipped)
      [28]    sector_etf_5d_return normalized (/ 20, clipped)
      [29-38] sector one-hot (10 categories)
      [39]    news_sentiment_score (float -1 to 1, 0 if unknown)
      [40]    news_article_count normalized (/ 5, clipped at 1)
      [41-45] 5 padding zeros (reserved for future signals)
    """
    try:
        # Parse signal_scores JSON
        sig_raw = trade_row.get("signal_scores") or "{}"
        if isinstance(sig_raw, str):
            sig_data = json.loads(sig_raw)
        else:
            sig_data = sig_raw
        scores = sig_data.get("scores", {})
        values = sig_data.get("values", {})
        scores = canonicalize_signal_map(scores)
        values = canonicalize_signal_map(values)

        # [0-8] Signal scores
        f = [
            float(scores.get("rsi_momentum", 0.5)),
            float(scores.get("volume_surge", 0.5)),
            float(scores.get("overnight_gap_probability", 0.5)),
            float(scores.get("earnings_catalyst", 0.5)),
            float(scores.get("support_resistance", 0.5)),
            float(scores.get("relative_strength", 0.5)),
            float(scores.get("sector_relative_strength", 0.5)),
            float(scores.get("vwap_reclaim", 0.5)),
            float(scores.get("volatility_squeeze", 0.5)),
        ]

        # [9] RSI raw
        f.append(min(float(values.get("rsi_momentum", 50)) / 100.0, 1.0))

        # [10] volume_ratio
        f.append(min(float(values.get("volume_surge", 1.0)) / 5.0, 1.0))

        # [11] gap_percent
        gap = float(values.get("overnight_gap_probability", 0))
        f.append(max(min(gap / 10.0, 1.0), -1.0))

        # [12] days_to_earnings
        dte = values.get("earnings_catalyst")
        f.append(min(float(dte) / 30.0, 1.0) if dte is not None else 1.0)

        # [13] vwap_dist
        vwap_val = values.get("vwap_reclaim", {})
        vwap_dist = vwap_val.get("dist", 0) if isinstance(vwap_val, dict) else 0
        f.append(max(min(float(vwap_dist or 0) / 5.0, 1.0), -1.0))

        # [14] hv_ratio
        hv = values.get("volatility_squeeze")
        f.append(max(min(float(hv) / 2.0, 1.0), 0.0) if hv is not None else 0.5)

        # [15-17] sr_signal binary flags
        sr_val = values.get("support_resistance", {})
        sr_signal = sr_val.get("signal", "unknown") if isinstance(sr_val, dict) else "unknown"
        is_open_air, has_support_floor, is_at_resistance = SR_SIGNAL_MAP.get(sr_signal, (0, 0, 0))
        f.extend([float(is_open_air), float(has_support_floor), float(is_at_resistance)])

        # [18] vwap_is_real
        vwap_mode = vwap_val.get("mode", "proxy") if isinstance(vwap_val, dict) else "proxy"
        f.append(1.0 if vwap_mode == "real" else 0.0)

        # [19] direction
        f.append(1.0 if trade_row.get("direction", "long") == "long" else 0.0)

        # [20] lock_in_confidence
        f.append(min(float(trade_row.get("lock_in_confidence") or trade_row.get("confidence", 65)) / 99.0, 1.0))

        # [21] expected_move
        f.append(min(float(trade_row.get("expected_move", 5)) / 25.0, 1.0))

        # [22] day_change_percent
        f.append(max(min(float(trade_row.get("day_change_percent", 0)) / 10.0, 1.0), -1.0))

        # [23] broke_52w_high
        f.append(1.0 if trade_row.get("broke_52w_high_days_ago") is not None else 0.0)

        # [24] broke_52w_days_ago
        days_ago = trade_row.get("broke_52w_high_days_ago")
        f.append(float(days_ago) / 7.0 if days_ago else 0.0)

        # [25] weekend_hold
        f.append(float(trade_row.get("weekend_hold", 0) or 0))

        # [26-28] 5d returns
        rs_val = values.get("relative_strength", {})
        stock_5d = rs_val.get("stock_5d", 0) if isinstance(rs_val, dict) else 0
        spy_5d = rs_val.get("spy_5d", 0) if isinstance(rs_val, dict) else 0
        sector_val = values.get("sector_relative_strength", {})
        etf_5d = sector_val.get("etf_5d", 0) if isinstance(sector_val, dict) else 0
        f.append(max(min(float(stock_5d or 0) / 20.0, 1.0), -1.0))
        f.append(max(min(float(spy_5d or 0) / 20.0, 1.0), -1.0))
        f.append(max(min(float(etf_5d or 0) / 20.0, 1.0), -1.0))

        # [29-38] sector one-hot
        sector = trade_row.get("sector", "Other") or "Other"
        for s in SECTOR_LIST:
            f.append(1.0 if sector == s else 0.0)

        # [39] news_sentiment_score
        f.append(float(trade_row.get("news_sentiment_score", 0) or 0))

        # [40] news_article_count
        f.append(min(float(trade_row.get("news_article_count", 0) or 0) / 5.0, 1.0))

        # [41-45] reserved padding
        f.extend([0.0, 0.0, 0.0, 0.0, 0.0])

        # Validate length
        assert len(f) == NN_INPUT_SIZE, f"Feature vector length {len(f)} != {NN_INPUT_SIZE}"

        # Replace any NaN/inf with 0.5
        f = [0.5 if (v != v or abs(v) == float("inf")) else v for v in f]

        return f

    except Exception as e:
        log.debug(f"Feature extraction failed: {e}")
        return None

def train_neural_network():
    """
    Nightly training job — trains SwingDeskNet on all closed virtual_trades.
    Called after Claude audit. Uses model.train() with dropout active.
    Persists updated weights to DB when done.
    Min 10 closed trades required to train.
    """
    global _nn_model
    try:
        db = get_database()
        closed = [dict(r) for r in db.execute(
            "SELECT * FROM virtual_trades WHERE outcome != 'open' AND signal_scores IS NOT NULL AND signal_scores != '{}'"
        ).fetchall()]
        db.close()

        if len(closed) < 10:
            log.info(f"NN training skipped — only {len(closed)} closed trades (need 10+)")
            return

        # Build feature matrix and labels
        X, y = [], []
        for trade in closed:
            features = extract_nn_features(trade)
            if features is None:
                continue
            label = 1.0 if trade.get("outcome") == "hit" else 0.0
            X.append(features)
            y.append(label)

        if len(X) < 10:
            log.info(f"NN training skipped — only {len(X)} usable samples after feature extraction")
            return

        X_tensor = torch.tensor(X, dtype=torch.float32)
        y_tensor = torch.tensor(y, dtype=torch.float32).unsqueeze(1)

        # Class balance check — log win rate going into training
        win_rate = sum(y) / len(y)
        log.info(f"NN training: {len(X)} samples, {win_rate:.1%} win rate")

        # Training setup
        _nn_model.train()
        optimizer = optim.Adam(_nn_model.parameters(), lr=0.001, weight_decay=1e-4)
        criterion = nn.BCELoss()

        # Train for 200 epochs — small dataset trains fast
        for epoch in range(200):
            optimizer.zero_grad()
            output = _nn_model(X_tensor)
            loss = criterion(output, y_tensor)
            loss.backward()
            optimizer.step()

        _nn_model.eval()
        final_loss = loss.item()
        log.info(f"NN training complete — final loss: {final_loss:.4f}")
        save_nn_weights()

    except Exception as e:
        log.error(f"NN training error: {e}")
        _nn_model.eval()  # Always return to eval mode

def nn_score_ticker(price_data_row, direction="long"):
    """
    Score a single ticker using the trained NN model.
    Returns confidence integer 0-99, same scale as crude algo.
    Requires signal_scores already computed — call compute_signal_scores first.
    Uses model.eval() — dropout disabled, full network active.
    """
    try:
        _nn_model.eval()
        features = extract_nn_features(price_data_row)
        if features is None:
            return 0
        x = torch.tensor([features], dtype=torch.float32)
        with torch.no_grad():
            prob = _nn_model(x).item()
        # Scale probability to 0-99 confidence score
        # prob 0.65+ → confidence 65+, prob 1.0 → confidence 99
        confidence = int(prob * 99)
        return confidence
    except Exception as e:
        log.debug(f"NN scoring error: {e}")
        return 0

# ── TIME UTILITIES ────────────────────────────────────────────────────────────
def current_time_cst():
    """Returns current time in US/Central — handles CST/CDT automatically."""
    return datetime.now(ZoneInfo("America/Chicago")).replace(tzinfo=None)

def is_weekday():
    """Returns True if today is a weekday (Mon-Fri)."""
    return current_time_cst().weekday() < 5

def is_market_open():
    """Returns True during regular market hours (8:30 AM - 3:00 PM CST)."""
    now = current_time_cst()
    minute_of_day = now.hour * 60 + now.minute
    return now.weekday() < 5 and (8 * 60 + 30) <= minute_of_day < (15 * 60)

def market_session_state(now=None):
    """Return a display-safe market state for session-scoped P&L labels."""
    now = now or current_time_cst()
    minute_of_day = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "weekend"
    if minute_of_day < (8 * 60 + 30):
        return "premarket"
    if minute_of_day < (15 * 60):
        return "open"
    return "afterhours"

def minutes_until_forced_close():
    """Returns minutes remaining until the 2:45 PM CST forced close. Returns 0 after 2:45 PM."""
    now = current_time_cst()
    close_time = now.replace(hour=14, minute=45, second=0)
    return max(0, int((close_time - now).total_seconds() / 60))

def stock_regulatory_sell_fee(sell_notional, share_quantity):
    """Return SEC + FINRA sell-side regulatory fees for a stock liquidation."""
    sell_notional = max(float(sell_notional or 0), 0.0)
    share_quantity = max(float(share_quantity or 0), 0.0)
    sec_fee = sell_notional * SEC_SECTION_31_RATE
    finra_taf = min(share_quantity * FINRA_TAF_PER_SHARE, FINRA_TAF_CAP)
    return {
        "sec_fee": round(sec_fee, 6),
        "finra_taf": round(finra_taf, 6),
        "regulatory_fee": round(sec_fee + finra_taf, 6),
    }

def calculate_stock_fee_model(invested_amount, buy_price, mark_price=None, direction="long"):
    """
    Conservative mark-to-liquidation model for SwingDesk stocks.

    Gross values show pure price movement. Net values include 0.10% entry
    friction, 0.10% exit friction, and sell-side SEC/FINRA fees.
    """
    invested = max(float(invested_amount or 0), 0.0)
    buy = max(float(buy_price or 0), 0.0001)
    mark = max(float(mark_price if mark_price is not None else buy), 0.0001)
    direction = (direction or "long").lower()

    entry_friction = invested * STOCK_BUY_FRICTION_RATE
    net_entry_notional = max(invested - entry_friction, 0.0)
    share_quantity = net_entry_notional / buy

    if direction == "short":
        gross_pnl = invested * ((buy - mark) / buy)
        gross_value = invested + gross_pnl
        pre_exit_value = net_entry_notional * (1 + ((buy - mark) / buy))
    else:
        gross_value = invested * (mark / buy)
        gross_pnl = gross_value - invested
        pre_exit_value = share_quantity * mark

    pre_exit_value = max(pre_exit_value, 0.0)
    exit_friction = pre_exit_value * STOCK_SELL_FRICTION_RATE
    reg = stock_regulatory_sell_fee(pre_exit_value, share_quantity)
    exit_fee = exit_friction + reg["regulatory_fee"]
    net_value = max(pre_exit_value - exit_fee, 0.0)
    net_pnl = net_value - invested

    return {
        "fee_model_version": STOCK_FEE_MODEL_VERSION,
        "gross_current_value": round(gross_value, 4),
        "net_current_value": round(net_value, 4),
        "gross_pnl": round(gross_pnl, 4),
        "net_pnl": round(net_pnl, 4),
        "entry_fee": 0.0,
        "entry_slippage": round(entry_friction, 6),
        "exit_fee": round(reg["regulatory_fee"], 6),
        "exit_slippage": round(exit_friction, 6),
        "total_fees": round(entry_friction + exit_fee, 6),
        "share_quantity": round(share_quantity, 8),
        "sec_fee": reg["sec_fee"],
        "finra_taf": reg["finra_taf"],
    }

def calculate_crypto_fee_model(invested_amount, buy_price, mark_price=None, direction="long"):
    """Pinned SDCrypto conservative stress model for later crypto universes."""
    invested = max(float(invested_amount or 0), 0.0)
    buy = max(float(buy_price or 0), 0.00000001)
    mark = max(float(mark_price if mark_price is not None else buy), 0.00000001)
    direction = (direction or "long").lower()
    entry_cost = invested * CRYPTO_BUY_FRICTION_RATE
    net_entry = max(invested - entry_cost, 0.0)
    if direction == "short":
        gross_pnl = invested * ((buy - mark) / buy)
        gross_value = invested + gross_pnl
        pre_exit_value = net_entry * (1 + ((buy - mark) / buy))
    else:
        gross_value = invested * (mark / buy)
        gross_pnl = gross_value - invested
        pre_exit_value = net_entry * (mark / buy)
    pre_exit_value = max(pre_exit_value, 0.0)
    exit_cost = pre_exit_value * CRYPTO_SELL_FRICTION_RATE
    net_value = max(pre_exit_value - exit_cost, 0.0)
    return {
        "fee_model_version": CRYPTO_FEE_MODEL_VERSION,
        "gross_current_value": round(gross_value, 4),
        "net_current_value": round(net_value, 4),
        "gross_pnl": round(gross_pnl, 4),
        "net_pnl": round(net_value - invested, 4),
        "entry_fee": 0.0,
        "entry_slippage": round(entry_cost, 6),
        "exit_fee": 0.0,
        "exit_slippage": round(exit_cost, 6),
        "total_fees": round(entry_cost + exit_cost, 6),
    }

# ── TICKER UNIVERSE ───────────────────────────────────────────────────────────
def fee_model_values(fee_quote):
    """Return fee model fields in database column order."""
    return [fee_quote.get(column) for column in FEE_MODEL_COLUMNS]

def fetch_sp500_tickers():
    """
    Fetch S&P 500 ticker list from a GitHub-hosted CSV.
    Wikipedia blocks Railway's IP with 403; GitHub is reliable and fast.
    Falls back to empty list so build_ticker_universe() can handle gracefully.
    """
    try:
        import urllib.request
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
        with urllib.request.urlopen(url, timeout=10) as response:
            content = response.read().decode()
        tickers = []
        for line in content.strip().split("\n")[1:]:
            ticker = line.split(",")[0].strip()
            if ticker:
                tickers.append(ticker.replace(".", "-"))
        log.info(f"Fetched {len(tickers)} S&P 500 tickers from GitHub")
        return tickers
    except Exception as error:
        log.warning(f"S&P 500 fetch failed: {error}")
        return []

def fetch_nasdaq100_tickers():
    """
    Return a hardcoded Nasdaq 100 ticker list.
    Wikipedia and most free APIs block Railway; hardcoding is bulletproof.
    This list changes only a few times per year — update manually as needed.
    """
    return [
        "ADBE","ADP","ABNB","ALGN","GOOGL","GOOG","AMZN","AMD","AMGN","AAPL",
        "AMAT","APP","ASML","TEAM","ADSK","AZN","AXON","BIIB","BKNG","AVGO",
        "CDNS","CDW","CHTR","CTAS","CSCO","CCEP","CTSH","CMCSA","CEG","COP",
        "CSGP","COST","CRWD","CSX","DDOG","DXCM","FANG","DLTR","DASH","EA",
        "EXC","FAST","META","FTNT","GEHC","GILD","HON","IDXX","INTC","INTU",
        "ISRG","KDP","KLAC","KHC","LRCX","LULU","MRVL","MELI","MCHP","MU",
        "MSFT","MNST","MDLZ","MDB","NFLX","NVDA","NXPI","ORLY","ON","PCAR",
        "PLTR","PANW","PAYX","PYPL","PEP","QCOM","REGN","ROP","ROST","CRM",
        "SBUX","SMCI","SNPS","TTWO","TMUS","TSLA","TXN","TTD","VRSK","VRTX",
        "WBD","WDAY","ARM","MSTR","COIN","HOOD","SOFI","RIVN",
    ]

# High-volatility and popular retail tickers not always in major indices
HIGH_VOLATILITY_TICKERS = [
    "GME","AMC","BB","NOK","SOFI","MSTR","CVNA","HOOD","RBLX","SNAP",
    "RIVN","LCID","IONQ","RGTI","COIN","PLTR","SMCI","SNDL","TLRY",
    "OPEN","CLOV","SPCE","MARA","RIOT","BITF","HUT",
    "UPST","AFRM","DKNG","PENN","STEM","PLUG","FCEL","BE",
    "CHPT","BLNK","QS","WKHS",
    "SPY","QQQ","IWM","DIA","ARKK","ARKG","ARKF","ARKW",
    "XLF","XLK","XLE","XLV","XLI","XLP","XLY","XLB","XLRE","XLC","XLU",
    "SOXL","TQQQ","SQQQ","UVXY",
]

# Liquid momentum names outside the core index lists that SwingDesk should still watch.
# This is intentionally separate from HIGH_VOLATILITY_TICKERS so additions are auditable.
MOMENTUM_EXPANSION_TICKERS = [
    "FLNC",
]
UNIVERSE_VERSION = "2026-06-01-momentum-expansion-1"

# Sector classification for each ticker
SECTOR_MAP = {
    "NVDA":"Tech","META":"Tech","AMD":"Tech","TSLA":"Auto","AMZN":"Consumer",
    "MSFT":"Tech","PLTR":"Tech","SOFI":"Finance","MSTR":"Finance","JPM":"Finance",
    "BAC":"Finance","COIN":"Crypto","GOOGL":"Tech","GOOG":"Tech","AAPL":"Tech",
    "NFLX":"Consumer","PYPL":"Finance","HOOD":"Finance","RBLX":"Consumer",
    "SNAP":"Tech","UBER":"Consumer","LYFT":"Consumer","RIVN":"Auto","LCID":"Auto",
    "GME":"Consumer","AMC":"Consumer","SMCI":"Tech","IONQ":"Tech","XOM":"Energy",
    "RGTI":"Tech","INTC":"Tech","MU":"Tech","QCOM":"Tech","ARM":"Tech",
    "AVGO":"Tech","TSM":"Tech","ORCL":"Tech","CRM":"Tech","SNOW":"Tech",
    "DDOG":"Tech","NET":"Tech","CRWD":"Tech","ZS":"Tech","PANW":"Tech",
    "SHOP":"Consumer","ROKU":"Tech","SPOT":"Consumer","ABNB":"Consumer",
    "DASH":"Consumer","BB":"Tech","NOK":"Tech","TLRY":"Consumer",
    "SPY":"ETF","QQQ":"ETF","IWM":"ETF","DIA":"ETF","ARKK":"ETF","ARKG":"ETF",
    "XLF":"ETF","XLK":"ETF","XLE":"ETF","XLV":"ETF","MARA":"Crypto",
    "RIOT":"Crypto","DKNG":"Consumer","PLUG":"Energy","FCEL":"Energy",
    "FLNC":"Energy",
    "LLY":"Healthcare","UNH":"Healthcare","JNJ":"Healthcare","PFE":"Healthcare",
    "ABBV":"Healthcare","MRK":"Healthcare","V":"Finance","MA":"Finance",
    "GS":"Finance","BLK":"Finance","WFC":"Finance","PG":"Consumer",
    "KO":"Consumer","PEP":"Consumer","WMT":"Consumer","COST":"Consumer",
    "HD":"Consumer","LOW":"Consumer","BA":"Industrial","CAT":"Industrial",
    "GE":"Industrial","HON":"Industrial","RTX":"Defense","NOC":"Defense",
}

def get_sector(ticker):
    """Return sector for ticker. Checks DB cache first, then SECTOR_MAP, then 'Other'."""
    try:
        db = get_database()
        row = db.execute("SELECT value FROM app_state WHERE key=?",
            [f"sector_{ticker}"]).fetchone()
        db.close()
        if row and row["value"] and row["value"] != "Other":
            return row["value"]
    except Exception:
        pass
    return SECTOR_MAP.get(ticker, "Other")

def fetch_and_cache_sector(ticker):
    """
    Fetch sector from Finnhub company profile and cache in DB permanently.
    Falls back to SECTOR_MAP then 'Other'.
    """
    if not FINNHUB_KEY:
        return SECTOR_MAP.get(ticker, "Other")
    try:
        import urllib.request
        url = f"{FINNHUB_BASE}/stock/profile2?symbol={ticker}&token={FINNHUB_KEY}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        finnhub_industry = data.get("finnhubIndustry") or ""
        industry_map = {
            "Technology": "Tech", "Semiconductors": "Tech",
            "Software": "Tech", "Internet": "Tech", "Hardware": "Tech",
            "Financial Services": "Finance", "Banks": "Finance",
            "Insurance": "Finance", "Asset Management": "Finance",
            "Energy": "Energy", "Oil & Gas": "Energy", "Utilities": "Energy",
            "Healthcare": "Healthcare", "Biotechnology": "Healthcare",
            "Pharmaceuticals": "Healthcare", "Medical Devices": "Healthcare",
            "Industrials": "Industrial", "Aerospace": "Defense",
            "Defense": "Defense", "Consumer Cyclical": "Consumer",
            "Consumer Defensive": "Consumer", "Retail": "Consumer",
            "Automotive": "Auto", "Electric Vehicles": "Auto",
            "Crypto": "Crypto", "Digital Assets": "Crypto",
            "Communication Services": "Tech", "Media": "Consumer",
            "Real Estate": "Finance", "Materials": "Industrial",
        }
        sector = "Other"
        for key, val in industry_map.items():
            if key.lower() in finnhub_industry.lower():
                sector = val
                break
        db = get_database()
        db.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
            [f"sector_{ticker}", sector])
        db.commit()
        db.close()
        return sector
    except Exception as e:
        log.debug(f"Sector fetch failed for {ticker}: {e}")
        return SECTOR_MAP.get(ticker, "Other")

def build_ticker_universe():
    """
    Build the full ticker universe by combining S&P 500, Nasdaq 100,
    and high-volatility additions. Caches the list daily to avoid
    redundant Wikipedia fetches.
    """
    database = get_database()
    cached_universe = database.execute("SELECT value FROM app_state WHERE key='universe'").fetchone()
    cached_date = database.execute("SELECT value FROM app_state WHERE key='universe_date'").fetchone()
    cached_version = database.execute("SELECT value FROM app_state WHERE key='universe_version'").fetchone()
    today = current_time_cst().strftime("%Y-%m-%d")

    if cached_universe and cached_date and cached_date["value"] == today and cached_version and cached_version["value"] == UNIVERSE_VERSION:
        database.close()
        tickers = json.loads(cached_universe["value"])
        log.info(f"Using cached universe: {len(tickers)} tickers")
        return tickers

    sp500 = fetch_sp500_tickers()
    nasdaq100 = fetch_nasdaq100_tickers()
    combined = list(dict.fromkeys(sp500 + nasdaq100 + HIGH_VOLATILITY_TICKERS + MOMENTUM_EXPANSION_TICKERS))

    if len(combined) < 100:
        if cached_universe:
            combined = json.loads(cached_universe["value"])
            log.warning(f"Fetch failed, using previous cache: {len(combined)} tickers")
        else:
            combined = HIGH_VOLATILITY_TICKERS
            log.warning(f"No cache available, using high-vol tickers only: {len(combined)}")
    else:
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('universe',?)", [json.dumps(combined)])
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('universe_date',?)", [today])
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('universe_version',?)", [UNIVERSE_VERSION])
        database.commit()

    database.close()
    log.info(f"Universe built: {len(combined)} tickers")
    return combined

# ── DATABASE ──────────────────────────────────────────────────────────────────
def get_database():
    """Open a connection to the SQLite database with WAL mode enabled.
    timeout=30 prevents 'database is locked' errors when monitor and scans compete."""
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=30)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.row_factory = sqlite3.Row
    return connection

def initialize_database():
    """
    Create all required tables and seed default values.
    Safe to call multiple times — uses IF NOT EXISTS.
    """
    database = get_database()
    database.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            name TEXT,
            date TEXT NOT NULL,
            direction TEXT NOT NULL,
            confidence INTEGER,
            expected_move REAL,
            entry_price REAL,
            sell_time_window TEXT,
            reasoning TEXT,
            sector TEXT,
            rsi REAL,
            volume_ratio REAL,
            weights_snapshot TEXT,
            outcome TEXT DEFAULT 'pending',
            actual_move REAL,
            actual_sell_price REAL,
            gross_pnl REAL,
            net_pnl REAL,
            logged_at TEXT,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS virtual_trades (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            buy_time TEXT,
            buy_price REAL,
            sell_date TEXT,
            sell_time TEXT,
            sell_price REAL,
            invested_amount REAL DEFAULT 10.0,
            current_value REAL,
            confidence INTEGER,
            expected_move REAL,
            actual_move REAL,
            gross_pnl REAL,
            net_pnl REAL,
            fee REAL DEFAULT 0.0,
            fee_model_version TEXT,
            entry_fee REAL DEFAULT 0.0,
            entry_slippage REAL DEFAULT 0.0,
            exit_fee REAL DEFAULT 0.0,
            exit_slippage REAL DEFAULT 0.0,
            total_fees REAL DEFAULT 0.0,
            gross_current_value REAL,
            share_quantity REAL,
            outcome TEXT DEFAULT 'open',
            sector TEXT,
            reasoning TEXT,
            closed_days INTEGER DEFAULT 1,
            sell_reason TEXT,
            sell_sentiment_history TEXT,
            intraday_high_pct REAL,
            intraday_low_pct REAL,
            status TEXT DEFAULT 'recommended',
            queue_position INTEGER
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            audit_success INTEGER DEFAULT 1,
            audit_provider TEXT,
            provider_attempts TEXT,
            weights_before TEXT,
            weights_after TEXT,
            reasoning TEXT,
            summary TEXT,
            total_predictions INTEGER,
            resolved_count INTEGER,
            hit_count INTEGER,
            miss_count INTEGER,
            win_rate REAL
        );

        CREATE TABLE IF NOT EXISTS weights_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            rsi_momentum REAL,
            volume_surge REAL,
            overnight_gap_probability REAL,
            earnings_catalyst REAL,
            sector_rotation REAL,
            support_resistance REAL,
            relative_strength REAL,
            sector_relative_strength REAL,
            vwap_reclaim REAL,
            volatility_squeeze REAL,
            win_rate REAL,
            total_resolved INTEGER,
            audit_reasoning TEXT
        );

        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS scan_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT NOT NULL,
            scan_type TEXT,
            ticker_count INTEGER,
            picks_json TEXT
        );

        CREATE TABLE IF NOT EXISTS scan_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_type TEXT NOT NULL,
            job_type TEXT DEFAULT 'scan',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT DEFAULT 'running',
            tickers_attempted INTEGER DEFAULT 0,
            tickers_updated INTEGER DEFAULT 0,
            picks_count INTEGER DEFAULT 0,
            provider_summary TEXT DEFAULT '{}',
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS strategy_variants (
            -- Historical table name. Each row is a simulation universe:
            -- strategy/method label + brain + entry time + selection mode + exit mode.
            -- Not every row is a fully independent standalone strategy.
            id TEXT PRIMARY KEY,
            strategy TEXT NOT NULL,
            brain TEXT NOT NULL,
            execution_time TEXT,
            selection_mode TEXT,
            exit_mode TEXT,
            label TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS signal_observations (
            id TEXT PRIMARY KEY,
            scan_event_id INTEGER,
            scan_time TEXT NOT NULL,
            scan_type TEXT,
            strategy TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            brain TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT DEFAULT 'long',
            sector TEXT,
            price REAL,
            confidence INTEGER,
            confidence_bin TEXT,
            expected_move REAL,
            selected INTEGER DEFAULT 0,
            executable INTEGER DEFAULT 0,
            rank INTEGER,
            signal_scores TEXT DEFAULT '{}',
            signal_values TEXT DEFAULT '{}',
            fired_signals TEXT DEFAULT '[]',
            confluence_count INTEGER DEFAULT 0,
            confluence_methods TEXT DEFAULT '[]',
            regime_context TEXT DEFAULT '{}',
            context_json TEXT DEFAULT '{}',
            outcome TEXT DEFAULT 'pending',
            actual_move REAL,
            resolved_at TEXT
        );

        CREATE TABLE IF NOT EXISTS variant_portfolios (
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
            created_at TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS variant_signal_weights (
            variant_id TEXT PRIMARY KEY,
            brain TEXT NOT NULL,
            weights_json TEXT NOT NULL,
            baseline_weights_json TEXT NOT NULL,
            learning_revision INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS variant_virtual_trades (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            strategy TEXT NOT NULL,
            brain TEXT NOT NULL,
            ticker TEXT NOT NULL,
            direction TEXT DEFAULT 'long',
            buy_date TEXT NOT NULL,
            buy_time TEXT,
            buy_price REAL,
            current_price REAL,
            day_change_percent REAL,
            invested_amount REAL,
            current_value REAL,
            confidence INTEGER,
            expected_move REAL,
            outcome TEXT DEFAULT 'open',
            sell_date TEXT,
            sell_time TEXT,
            sell_price REAL,
            actual_move REAL,
            gross_pnl REAL,
            net_pnl REAL,
            fee_model_version TEXT,
            entry_fee REAL DEFAULT 0.0,
            entry_slippage REAL DEFAULT 0.0,
            exit_fee REAL DEFAULT 0.0,
            exit_slippage REAL DEFAULT 0.0,
            total_fees REAL DEFAULT 0.0,
            gross_current_value REAL,
            share_quantity REAL,
            sell_reason TEXT,
            sector TEXT,
            reasoning TEXT,
            signal_scores TEXT DEFAULT '{}',
            source_scan_time TEXT,
            source_rank INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS variant_equity_points (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            equity REAL NOT NULL,
            cash REAL,
            open_value REAL,
            realized_pnl REAL,
            open_count INTEGER DEFAULT 0,
            closed_count INTEGER DEFAULT 0,
            note TEXT
        );

        CREATE TABLE IF NOT EXISTS variant_lifecycle_reviews (
            id TEXT PRIMARY KEY,
            variant_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            recommended_status TEXT NOT NULL,
            current_status TEXT,
            reasons TEXT DEFAULT '[]',
            metrics_json TEXT DEFAULT '{}',
            applied INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS variant_learning_events (
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

        CREATE TABLE IF NOT EXISTS provider_health (
            provider TEXT PRIMARY KEY,
            status TEXT DEFAULT 'active',
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            rate_limit_count INTEGER DEFAULT 0,
            timeout_count INTEGER DEFAULT 0,
            missing_count INTEGER DEFAULT 0,
            last_success_at TEXT,
            last_failure_at TEXT,
            cooldown_until TEXT,
            last_error TEXT
        );

        CREATE TABLE IF NOT EXISTS position_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id TEXT NOT NULL,
            check_time TEXT NOT NULL,
            price REAL,
            pnl_percent REAL,
            sentiment TEXT,
            ticker TEXT
        );

        CREATE TABLE IF NOT EXISTS candidates (
            ticker TEXT PRIMARY KEY,
            direction TEXT,
            first_seen TEXT,
            last_seen TEXT,
            confidence INTEGER,
            expected_move REAL,
            monitoring INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS nn_virtual_trades (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            buy_time TEXT,
            buy_price REAL,
            sell_date TEXT,
            sell_time TEXT,
            sell_price REAL,
            invested_amount REAL DEFAULT 10.0,
            current_value REAL,
            confidence INTEGER,
            nn_confidence INTEGER,
            expected_move REAL,
            actual_move REAL,
            gross_pnl REAL,
            net_pnl REAL,
            fee REAL DEFAULT 0.0,
            fee_model_version TEXT,
            entry_fee REAL DEFAULT 0.0,
            entry_slippage REAL DEFAULT 0.0,
            exit_fee REAL DEFAULT 0.0,
            exit_slippage REAL DEFAULT 0.0,
            total_fees REAL DEFAULT 0.0,
            gross_current_value REAL,
            share_quantity REAL,
            outcome TEXT DEFAULT 'open',
            sector TEXT,
            reasoning TEXT,
            sell_reason TEXT,
            intraday_high_pct REAL,
            intraday_low_pct REAL,
            dynamic_confidence INTEGER,
            dynamic_estimate REAL,
            weekend_hold INTEGER DEFAULT 0,
            confluence_count INTEGER DEFAULT 0,
            confluence_methods TEXT DEFAULT '[]',
            signal_scores TEXT DEFAULT '{}',
            lock_in_confidence INTEGER,
            last_price_updated TEXT,
            day_change_percent REAL,
            news_sentiment_score REAL,
            news_article_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS personal_trades (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            direction TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            buy_price REAL,
            current_price REAL,
            shares REAL DEFAULT 1.0,
            invested_amount REAL,
            current_value REAL,
            pnl_percent REAL,
            pnl_dollars REAL,
            sector TEXT,
            notes TEXT,
            source TEXT DEFAULT 'manual',
            source_portfolio TEXT,
            added_at TEXT,
            last_updated TEXT
        );

        /*
         * Trade Queue — Self-Regulating Position Sizing
         * ═══════════════════════════════════════════════
         * Each row represents a dollar amount available for the next trade.
         * When a trade closes, its ending value (investment + P&L) is appended.
         * When a new trade opens, the oldest available amount is consumed.
         *
         * The queue naturally self-regulates:
         *   - Winning trades add larger amounts → future positions grow
         *   - Losing trades add smaller amounts → future positions shrink
         *   - No manual intervention, floors, or ceilings needed
         *
         * If the queue is empty when a trade needs to open, the system
         * falls back to DEFAULT_INVESTMENT ($10.00).
         */
        CREATE TABLE IF NOT EXISTS trade_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            source_trade_id TEXT,
            created_at TEXT NOT NULL,
            consumed INTEGER DEFAULT 0,
            consumed_by_trade_id TEXT,
            consumed_at TEXT
        );

        /*
         * Extended Runner Tracking
         * ════════════════════════
         * Tracks positions the user continues holding after the brain sells.
         * Brain sells at its target; user may choose to hold for larger gains.
         * This table records the divergence for educational display.
         */
        CREATE TABLE IF NOT EXISTS extended_runners (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            buy_date TEXT NOT NULL,
            buy_price REAL,
            brain_sell_date TEXT,
            brain_sell_price REAL,
            brain_pnl_percent REAL,
            current_price REAL,
            current_pnl_percent REAL,
            invested_amount REAL DEFAULT 10.0,
            status TEXT DEFAULT 'running',
            last_updated TEXT
        );

        /*
         * Darvas Box Silent Tracking
         * ══════════════════════════
         * Silently records which stocks would have been picked by the Darvas Box
         * method each day, and tracks their outcomes. No UI, no virtual trades,
         * no position monitoring — just data collection for future comparison
         * against the custom brain's performance.
         *
         * Must be built within 60 days of brain launch (2026-05-23) to enable
         * retroactive 5-minute data backfill via yfinance.
         */
        CREATE TABLE IF NOT EXISTS darvas_picks (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            entry_price REAL,
            week_high REAL,
            volume_ratio REAL,
            would_have_bought INTEGER DEFAULT 1,
            outcome TEXT DEFAULT 'open',
            actual_move REAL,
            logged_at TEXT
        );

        CREATE TABLE IF NOT EXISTS method_signals (
            id TEXT PRIMARY KEY,
            method TEXT NOT NULL,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            entry_price REAL,
            outcome TEXT DEFAULT 'open',
            actual_move REAL,
            logged_at TEXT
        );

        CREATE TABLE IF NOT EXISTS day_trades (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            buy_time TEXT,
            sell_time TEXT,
            logged_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_signal_observations_scan ON signal_observations(scan_event_id);
        CREATE INDEX IF NOT EXISTS idx_signal_observations_variant ON signal_observations(strategy, variant_id, scan_time);
        CREATE INDEX IF NOT EXISTS idx_signal_observations_ticker ON signal_observations(ticker, scan_time);
        CREATE INDEX IF NOT EXISTS idx_signal_observations_confidence ON signal_observations(confidence_bin, outcome);
        CREATE INDEX IF NOT EXISTS idx_variant_trades_variant ON variant_virtual_trades(variant_id, outcome);
        CREATE INDEX IF NOT EXISTS idx_variant_trades_ticker ON variant_virtual_trades(ticker, buy_date);
        CREATE INDEX IF NOT EXISTS idx_variant_equity_variant ON variant_equity_points(variant_id, timestamp);
    """)

    # Add new columns to weights_history if upgrading from earlier schema
    for wh_col in [
        "support_resistance REAL",
        "relative_strength REAL",
        "sector_relative_strength REAL",
        "vwap_reclaim REAL",
        "volatility_squeeze REAL",
    ]:
        try:
            database.execute(f"ALTER TABLE weights_history ADD COLUMN {wh_col}")
        except:
            pass  # Column already exists

    # Add audit proof fields if upgrading from the earlier trust-me audit ledger.
    for audit_col in [
        "audit_success INTEGER DEFAULT 1",
        "audit_provider TEXT",
        "provider_attempts TEXT",
    ]:
        try:
            database.execute(f"ALTER TABLE audit_log ADD COLUMN {audit_col}")
        except:
            pass  # Column already exists
    try:
        database.execute("""
            UPDATE audit_log
            SET audit_success=0
            WHERE lower(COALESCE(summary, '')) LIKE 'audit failed:%'
               OR lower(COALESCE(summary, '')) LIKE '%no configured llm provider%'
               OR lower(COALESCE(summary, '')) LIKE 'local audit recorded%'
        """)
    except:
        pass

    # Add new columns to virtual_trades if upgrading from earlier schema
    for column_definition in [
        "closed_days INTEGER DEFAULT 1",
        "sell_reason TEXT",
        "sell_sentiment_history TEXT",
        "intraday_high_pct REAL",
        "intraday_low_pct REAL",
        "status TEXT DEFAULT 'recommended'",
        "queue_position INTEGER",
        "dynamic_confidence INTEGER",
        "dynamic_estimate REAL",
        "weekend_hold INTEGER DEFAULT 0",
        "confluence_count INTEGER DEFAULT 0",
        "confluence_methods TEXT DEFAULT '[]'",
        "signal_scores TEXT DEFAULT '{}'",
        "lock_in_confidence INTEGER",
        "last_price_updated TEXT",
        "day_change_percent REAL",
        "news_sentiment_score REAL",
        "news_article_count INTEGER DEFAULT 0",
        "broke_52w_high_days_ago INTEGER",
        "entry_price_source TEXT",
        "entry_integrity_status TEXT",
        "entry_integrity_note TEXT",
        "pct_change_prev_close REAL",
        "pct_change_premarket REAL",
        "pct_change_regular_open REAL",
        "pct_change_entry REAL",
    ] + FEE_MODEL_COLUMN_DEFINITIONS:
        try:
            column_name = column_definition.split()[0]
            database.execute(f"ALTER TABLE virtual_trades ADD COLUMN {column_definition}")
        except:
            pass  # Column already exists

    # Add new columns to nn_virtual_trades if upgrading from earlier schema
    for column_definition in [
        "dynamic_confidence INTEGER",
        "dynamic_estimate REAL",
        "weekend_hold INTEGER DEFAULT 0",
        "confluence_count INTEGER DEFAULT 0",
        "confluence_methods TEXT DEFAULT '[]'",
        "signal_scores TEXT DEFAULT '{}'",
        "lock_in_confidence INTEGER",
        "last_price_updated TEXT",
        "day_change_percent REAL",
        "news_sentiment_score REAL",
        "news_article_count INTEGER DEFAULT 0",
    ] + FEE_MODEL_COLUMN_DEFINITIONS:
        try:
            database.execute(f"ALTER TABLE nn_virtual_trades ADD COLUMN {column_definition}")
        except:
            pass  # Column already exists

    # Keep the variant trade ledger schema aligned with the fields written by
    # universe openings, execution recovery, card tags, and confidence context.
    for column_definition in [
        "current_price REAL",
        "day_change_percent REAL",
        "last_price_updated TEXT",
        "entry_price_source TEXT",
        "entry_integrity_status TEXT",
        "entry_integrity_note TEXT",
        "confluence_count INTEGER DEFAULT 0",
        "confluence_methods TEXT DEFAULT '[]'",
    ] + FEE_MODEL_COLUMN_DEFINITIONS:
        try:
            database.execute(f"ALTER TABLE variant_virtual_trades ADD COLUMN {column_definition}")
        except:
            pass  # Column already exists

    now_iso = current_time_cst().isoformat()
    default_variants = [
        ("swingdesk_vector_0845_all", "SwingDesk", "Vector", "08:45", "All", "time_or_thesis", "SwingDesk / Vector / 8:45"),
        ("swingdesk_nova_0845_all", "SwingDesk", "Nova", "08:45", "All", "time_or_thesis", "SwingDesk / Nova / 8:45"),
        ("swingdesk_vector_0500_all", "SwingDesk", "Vector", "05:00", "All", "time_or_thesis", "SwingDesk / Vector / 5:00"),
        ("swingdesk_nova_0500_all", "SwingDesk", "Nova", "05:00", "All", "time_or_thesis", "SwingDesk / Nova / 5:00"),
        ("swingdesk_vector_0600_all", "SwingDesk", "Vector", "06:00", "All", "time_or_thesis", "SwingDesk / Vector / 6:00"),
        ("swingdesk_nova_0600_all", "SwingDesk", "Nova", "06:00", "All", "time_or_thesis", "SwingDesk / Nova / 6:00"),
        ("swingdesk_vector_0700_all", "SwingDesk", "Vector", "07:00", "All", "time_or_thesis", "SwingDesk / Vector / 7:00"),
        ("swingdesk_nova_0700_all", "SwingDesk", "Nova", "07:00", "All", "time_or_thesis", "SwingDesk / Nova / 7:00"),
        ("darvas_vector_reg_all", "Darvas", "Vector", "reg", "All", "strategy_exit", "Darvas / Vector / Reg"),
        ("darvas_nova_reg_all", "Darvas", "Nova", "reg", "All", "strategy_exit", "Darvas / Nova / Reg"),
        ("gap_go_vector_reg_all", "Gap & Go", "Vector", "reg", "All", "strategy_exit", "Gap & Go / Vector / Reg"),
        ("gap_go_nova_reg_all", "Gap & Go", "Nova", "reg", "All", "strategy_exit", "Gap & Go / Nova / Reg"),
        ("vwap_reclaim_vector_reg_all", "VWAP Reclaim", "Vector", "reg", "All", "strategy_exit", "VWAP Reclaim / Vector / Reg"),
        ("vwap_reclaim_nova_reg_all", "VWAP Reclaim", "Nova", "reg", "All", "strategy_exit", "VWAP Reclaim / Nova / Reg"),
        ("inside_day_vector_reg_all", "Inside Day", "Vector", "reg", "All", "strategy_exit", "Inside Day / Vector / Reg"),
        ("inside_day_nova_reg_all", "Inside Day", "Nova", "reg", "All", "strategy_exit", "Inside Day / Nova / Reg"),
        ("bull_flag_vector_reg_all", "Bull Flag", "Vector", "reg", "All", "strategy_exit", "Bull Flag / Vector / Reg"),
        ("bull_flag_nova_reg_all", "Bull Flag", "Nova", "reg", "All", "strategy_exit", "Bull Flag / Nova / Reg"),
        ("pocket_pivot_vector_reg_all", "Pocket Pivot", "Vector", "reg", "All", "strategy_exit", "Pocket Pivot / Vector / Reg"),
        ("pocket_pivot_nova_reg_all", "Pocket Pivot", "Nova", "reg", "All", "strategy_exit", "Pocket Pivot / Nova / Reg"),
        ("vol_squeeze_breakout_vector_reg_all", "Vol Squeeze Breakout", "Vector", "reg", "All", "strategy_exit", "Vol Squeeze Breakout / Vector / Reg"),
        ("vol_squeeze_breakout_nova_reg_all", "Vol Squeeze Breakout", "Nova", "reg", "All", "strategy_exit", "Vol Squeeze Breakout / Nova / Reg"),
        ("relative_strength_pullback_vector_reg_all", "Relative Strength Pullback", "Vector", "reg", "All", "strategy_exit", "Relative Strength Pullback / Vector / Reg"),
        ("relative_strength_pullback_nova_reg_all", "Relative Strength Pullback", "Nova", "reg", "All", "strategy_exit", "Relative Strength Pullback / Nova / Reg"),
        ("ema_trend_pullback_vector_reg_all", "EMA Trend Pullback", "Vector", "reg", "All", "strategy_exit", "EMA Trend Pullback / Vector / Reg"),
        ("ema_trend_pullback_nova_reg_all", "EMA Trend Pullback", "Nova", "reg", "All", "strategy_exit", "EMA Trend Pullback / Nova / Reg"),
    ]
    retired_strategies = ("Bullish Mean Reversion", "Donchian", "S&R Breakout", "NR7", "Opening Range Hold")
    database.execute(
        f"UPDATE strategy_variants SET status='retired', updated_at=? WHERE strategy IN ({','.join(['?'] * len(retired_strategies))})",
        [now_iso, *retired_strategies],
    )
    database.execute(
        f"""UPDATE variant_portfolios
            SET lifecycle_status='archived', recommended_status='retired',
                lifecycle_reasons=?, updated_at=?
            WHERE variant_id IN (
                SELECT id FROM strategy_variants WHERE strategy IN ({','.join(['?'] * len(retired_strategies))})
            )""",
        [json.dumps(["retired_strategy_family_replaced_for_locked_swingdesk_12"]), now_iso, *retired_strategies],
    )
    retired_variant_ids = (
        "swingdesk_vector_0845_top1", "swingdesk_nova_0845_top1",
        "swingdesk_vector_0500_top1", "swingdesk_nova_0500_top1",
        "swingdesk_vector_0600_top1", "swingdesk_nova_0600_top1",
        "swingdesk_vector_0700_top1", "swingdesk_nova_0700_top1",
        "swingdesk_vector_0845_top3", "swingdesk_nova_0845_top3",
    )
    database.execute(
        f"UPDATE strategy_variants SET status='retired', updated_at=? WHERE id IN ({','.join(['?'] * len(retired_variant_ids))})",
        [now_iso, *retired_variant_ids],
    )
    database.execute(
        f"""UPDATE variant_portfolios
            SET lifecycle_status='archived', recommended_status='retired',
                lifecycle_reasons=?, updated_at=?
            WHERE variant_id IN ({','.join(['?'] * len(retired_variant_ids))})""",
        [json.dumps(["top3_variant_retired_not_part_of_locked_architecture"]), now_iso, *retired_variant_ids],
    )
    for variant in default_variants:
        try:
            database.execute("""
                INSERT OR IGNORE INTO strategy_variants
                (id, strategy, brain, execution_time, selection_mode, exit_mode, label, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """, [*variant, now_iso, now_iso])
        except Exception as e:
            log.debug(f"strategy variant seed skipped: {e}")

    for variant in default_variants:
        database.execute(
            "UPDATE strategy_variants SET label=?, updated_at=? WHERE id=? AND selection_mode='All'",
            [variant[6], now_iso, variant[0]],
        )

    baseline_weights = canonical_signal_weights()
    database.execute(
        "INSERT OR IGNORE INTO app_state VALUES ('canonical_signal_weights', ?)",
        [json.dumps(baseline_weights)]
    )
    variant_rows = database.execute("SELECT id, brain FROM strategy_variants WHERE status='active'").fetchall()
    for row in variant_rows:
        try:
            database.execute("""
                INSERT OR IGNORE INTO variant_portfolios
                (variant_id, starting_cash, cash, equity, realized_pnl, open_value,
                 open_count, closed_count, win_count, loss_count, max_equity,
                 max_drawdown_pct, lifecycle_status, recommended_status, lifecycle_reasons,
                 created_at, updated_at)
                VALUES (?, 1000.0, 1000.0, 1000.0, 0.0, 0.0, 0, 0, 0, 0,
                        1000.0, 0.0, 'active', 'active', '[]', ?, ?)
            """, [row["id"], now_iso, now_iso])
            database.execute("""
                INSERT OR IGNORE INTO variant_signal_weights
                (variant_id, brain, weights_json, baseline_weights_json, learning_revision, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
            """, [row["id"], row["brain"], json.dumps(baseline_weights), json.dumps(baseline_weights), now_iso, now_iso])
            database.execute("""
                INSERT OR IGNORE INTO variant_equity_points
                (id, variant_id, timestamp, equity, cash, open_value, realized_pnl, open_count, closed_count, note)
                VALUES (?, ?, ?, 1000.0, 1000.0, 0.0, 0.0, 0, 0, 'seed')
            """, [f"{row['id']}_seed", row["id"], now_iso])
        except Exception as e:
            log.debug(f"variant universe seed skipped for {row['id']}: {e}")

    # Seed default signal weights if not already set
    existing_weights = database.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
    if not existing_weights:
        default_weights = canonical_signal_weights()
        database.execute("INSERT INTO app_state VALUES ('weights',?)", [json.dumps(default_weights)])
    else:
        # Migrate existing weights: fill in any missing keys with defaults
        try:
            w = json.loads(existing_weights["value"])
            changed = False
            # Rename sector_rotation → support_resistance
            if "sector_rotation" in w and "support_resistance" not in w:
                w["support_resistance"] = w.pop("sector_rotation")
                changed = True
            # Fill in any missing new indicator keys
            default_new_keys = {
                "support_resistance": 0.13,
                "relative_strength": 0.12,
                "sector_relative_strength": 0.10,
                "vwap_reclaim": 0.08,
                "volatility_squeeze": 0.05,
            }
            for key, default_val in default_new_keys.items():
                if key not in w:
                    # Redistribute weight from existing keys proportionally
                    w[key] = default_val
                    changed = True
            # Renormalize so weights sum to 1.0
            if changed:
                total = sum(w.values())
                if total > 0:
                    w = {k: round(v / total, 4) for k, v in w.items()}
                database.execute("INSERT OR REPLACE INTO app_state VALUES ('weights',?)", [json.dumps(w)])
                log.info(f"Migrated weights to 9-signal schema: {w}")
        except:
            pass

    database.commit()
    database.close()
    log.info(f"Database initialized at {DATABASE_PATH}")

def get_signal_weights():
    """Retrieve current signal weights from the database."""
    try:
        database = get_database()
        row = database.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
        database.close()
        if row:
            return json.loads(row["value"])
    except:
        pass
    return {
        "rsi_momentum": 0.15, "volume_surge": 0.15,
        "overnight_gap_probability": 0.18, "earnings_catalyst": 0.14,
        "support_resistance": 0.13, "relative_strength": 0.12,
        "sector_relative_strength": 0.10, "vwap_reclaim": 0.08,
        "volatility_squeeze": 0.05,
    }

def save_signal_weights(weights):
    """Persist updated signal weights to the database."""
    database = get_database()
    database.execute("INSERT OR REPLACE INTO app_state VALUES ('weights',?)", [json.dumps(weights)])
    database.commit()
    database.close()

def set_app_state(key, value):
    """Persist a small app_state value."""
    database = get_database()
    database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)", [key, value])
    database.commit()
    database.close()

def get_app_state_json(key, default=None):
    """Read a JSON app_state value, returning default if missing or invalid."""
    database = get_database()
    row = database.execute("SELECT value FROM app_state WHERE key=?", [key]).fetchone()
    database.close()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except Exception:
        return default

def get_app_state_value(key, default=None):
    """Read a raw app_state value."""
    database = get_database()
    row = database.execute("SELECT value FROM app_state WHERE key=?", [key]).fetchone()
    database.close()
    return row["value"] if row else default

def notification_enabled():
    try:
        return get_app_state_value("notify_on_close", "true") != "false"
    except Exception:
        return True

def record_monitor_status(**updates):
    """Persist the latest open-position monitor status for UI and alerting."""
    now = current_time_cst().isoformat()
    current = get_app_state_json("open_position_monitor_status", {}) or {}
    current.update(updates)
    current["updated_at"] = now
    set_app_state("open_position_monitor_status", json.dumps(current))
    return current

def get_monitor_status():
    status = get_app_state_json("open_position_monitor_status", {}) or {}
    last_monitor = get_app_state_json("last_open_position_monitor", {}) or {}
    if last_monitor and not status.get("last_success_at"):
        status["last_success_at"] = last_monitor.get("checked_at")
    return status

def prune_scan_history(retention_days=SCAN_EVENT_RETENTION_DAYS):
    """Delete raw scan telemetry older than the operational retention window."""
    cutoff = (current_time_cst() - timedelta(days=retention_days)).isoformat()
    database = get_database()
    scan_events_deleted = database.execute(
        "DELETE FROM scan_events WHERE started_at < ?",
        [cutoff],
    ).rowcount
    legacy_scan_cache_deleted = database.execute(
        "DELETE FROM scan_cache WHERE scan_time < ?",
        [cutoff],
    ).rowcount
    database.commit()
    database.close()
    result = {
        "retention_days": retention_days,
        "cutoff": cutoff,
        "scan_events_deleted": max(scan_events_deleted, 0),
        "legacy_scan_cache_deleted": max(legacy_scan_cache_deleted, 0),
    }
    if result["scan_events_deleted"] or result["legacy_scan_cache_deleted"]:
        log.info(f"Pruned raw scan history: {result}")
    return result

def begin_scan_event(scan_type, job_type="scan", tickers_attempted=0):
    """Create a durable scan/monitor event row and return its id."""
    database = get_database()
    cursor = database.execute("""
        INSERT INTO scan_events (scan_type, job_type, started_at, status, tickers_attempted)
        VALUES (?, ?, ?, 'running', ?)
    """, [scan_type, job_type, current_time_cst().isoformat(), int(tickers_attempted or 0)])
    database.commit()
    event_id = cursor.lastrowid
    database.close()
    return event_id

def finish_scan_event(event_id, status="success", tickers_updated=0, picks_count=0, provider_summary=None, error=None):
    """Mark a scan/monitor event as complete."""
    if not event_id:
        return
    database = get_database()
    database.execute("""
        UPDATE scan_events
        SET finished_at=?, status=?, tickers_updated=?, picks_count=?, provider_summary=?, error=?
        WHERE id=?
    """, [
        current_time_cst().isoformat(),
        status,
        int(tickers_updated or 0),
        int(picks_count or 0),
        json.dumps(provider_summary or {}),
        str(error)[:500] if error else None,
        event_id,
    ])
    database.commit()
    database.close()

def mark_stalled_scan_events(max_age_minutes=45, zero_progress_minutes=20):
    """Mark old running scan/monitor rows as stalled so freshness is never ambiguous."""
    cutoff = (current_time_cst() - timedelta(minutes=max_age_minutes)).isoformat()
    zero_cutoff = (current_time_cst() - timedelta(minutes=zero_progress_minutes)).isoformat()
    database = get_database()
    database.execute("""
        UPDATE scan_events
        SET status='stalled',
            finished_at=COALESCE(finished_at, ?),
            error=COALESCE(error, 'watchdog marked event stalled')
        WHERE status='running' AND started_at < ?
    """, [current_time_cst().isoformat(), cutoff])
    database.execute("""
        UPDATE scan_events
        SET status='stalled',
            finished_at=COALESCE(finished_at, ?),
            error=COALESCE(error, 'watchdog marked zero-progress event stalled')
        WHERE status='running'
          AND job_type='comprehensive'
          AND COALESCE(tickers_updated, 0)=0
          AND started_at < ?
    """, [current_time_cst().isoformat(), zero_cutoff])
    changed = database.total_changes
    database.commit()
    database.close()
    return changed

def mark_running_events_error(job_type, started_after, error):
    """Mark running events from the current job as errored after an exception."""
    database = get_database()
    database.execute("""
        UPDATE scan_events
        SET status='error',
            finished_at=COALESCE(finished_at, ?),
            error=?
        WHERE status='running' AND job_type=? AND started_at >= ?
    """, [current_time_cst().isoformat(), str(error)[:500], job_type, started_after])
    changed = database.total_changes
    database.commit()
    database.close()
    return changed

def get_running_comprehensive_scan():
    """Return the active comprehensive scan event, if one is already running."""
    mark_stalled_scan_events(max_age_minutes=12, zero_progress_minutes=8)
    database = get_database()
    row = database.execute("""
        SELECT * FROM scan_events
        WHERE job_type='comprehensive' AND status='running'
        ORDER BY started_at DESC LIMIT 1
    """).fetchone()
    database.close()
    return dict(row) if row else None

def record_provider_health(provider, ok, failure_type=None, error=None, cooldown_minutes=0):
    """Track provider reliability so noisy APIs can cool down or be benched."""
    now = current_time_cst()
    cooldown_until = (now + timedelta(minutes=cooldown_minutes)).isoformat() if cooldown_minutes else None
    database = get_database()
    database.execute("""
        INSERT OR IGNORE INTO provider_health (provider, status)
        VALUES (?, 'active')
    """, [provider])
    if ok:
        database.execute("""
            UPDATE provider_health
            SET status=CASE WHEN status IN ('cooldown','degraded') THEN 'active' ELSE status END,
                success_count=success_count+1,
                last_success_at=?,
                last_error=NULL,
                cooldown_until=NULL
            WHERE provider=?
        """, [now.isoformat(), provider])
    else:
        field = {
            "rate_limit": "rate_limit_count",
            "timeout": "timeout_count",
            "missing": "missing_count",
        }.get(failure_type)
        if field:
            database.execute(f"UPDATE provider_health SET {field}={field}+1 WHERE provider=?", [provider])
        status = "cooldown" if cooldown_minutes else "degraded"
        database.execute("""
            UPDATE provider_health
            SET status=?,
                failure_count=failure_count+1,
                last_failure_at=?,
                cooldown_until=COALESCE(?, cooldown_until),
                last_error=?
            WHERE provider=?
        """, [status, now.isoformat(), cooldown_until, str(error or failure_type or "unknown")[:300], provider])
        row = database.execute(
            "SELECT success_count, failure_count, rate_limit_count, timeout_count FROM provider_health WHERE provider=?",
            [provider]
        ).fetchone()
        if row:
            successes = int(row["success_count"] or 0)
            failures = int(row["failure_count"] or 0)
            total = successes + failures
            failure_rate = failures / max(total, 1)
            if failures >= 20 and failure_rate >= 0.7:
                database.execute("UPDATE provider_health SET status='benched', cooldown_until=NULL WHERE provider=?", [provider])
            elif failures >= 8 and failure_rate >= 0.5 and status != "cooldown":
                database.execute("UPDATE provider_health SET status='degraded' WHERE provider=?", [provider])
    database.commit()
    database.close()

def get_provider_health_map():
    """Return current provider health rows keyed by provider name."""
    try:
        database = get_database()
        rows = [dict(r) for r in database.execute("SELECT * FROM provider_health").fetchall()]
        database.close()
        return {r["provider"]: r for r in rows}
    except Exception:
        return {}

def provider_is_available(provider, health=None):
    """Skip providers that are disabled, retired, or still cooling down."""
    health = health or get_provider_health_map()
    row = health.get(provider)
    if not row:
        return True
    if row.get("status") in ("disabled", "retired", "benched"):
        return False
    cooldown = row.get("cooldown_until")
    if cooldown:
        try:
            if datetime.fromisoformat(cooldown) > current_time_cst():
                return False
        except Exception:
            return True
    return True

def record_open_execution_status(status):
    """Persist the latest open-position execution diagnostic payload."""
    payload = {
        **status,
        "recorded_at": current_time_cst().isoformat(),
    }
    set_app_state("last_open_execution", json.dumps(payload))
    for key in ("attempted_at", "success_at", "cached_pick_count", "opened_count", "skipped_count", "last_error"):
        if key in payload:
            set_app_state(f"open_execution_{key}", str(payload.get(key) if payload.get(key) is not None else ""))
    return payload

# ── TRADE QUEUE — Self-Regulating Position Sizing ─────────────────────────────
def get_dynamic_fallback_amount():
    """
    Calculate the fallback investment amount when the queue is empty.
    Uses 1% of total portfolio value. Floor is $1.00 (Cash App minimum).
    Falls back to DEFAULT_INVESTMENT until 10+ closed trades exist.
    """
    MINIMUM_FLOOR = 1.00
    HISTORY_THRESHOLD = 10
    database = get_database()
    closed_trades = database.execute(
        "SELECT COUNT(*) as count, COALESCE(SUM(net_pnl), 0) as total_pnl FROM virtual_trades WHERE outcome != 'open'"
    ).fetchone()
    database.close()
    if closed_trades["count"] < HISTORY_THRESHOLD:
        return DEFAULT_INVESTMENT
    portfolio_value = 1000.0 + float(closed_trades["total_pnl"] or 0)
    return max(round(portfolio_value * 0.01, 2), MINIMUM_FLOOR)

def get_next_queue_amount():
    """
    Retrieve the next available amount from the trade queue (FIFO).
    Returns the oldest unconsumed amount, or a dynamic fallback (1% of
    portfolio value) if the queue is empty.
    """
    database = get_database()
    next_amount = database.execute(
        "SELECT id, amount FROM trade_queue WHERE consumed = 0 ORDER BY id ASC LIMIT 1"
    ).fetchone()
    database.close()
    if next_amount:
        return next_amount["id"], next_amount["amount"]
    return None, get_dynamic_fallback_amount()

def consume_queue_amount(queue_id, consuming_trade_id):
    """
    Mark a queue entry as consumed by a specific trade.
    Called when a new position opens and takes an amount from the queue.
    """
    if queue_id is None:
        return  # Was a fallback amount, nothing to consume
    database = get_database()
    database.execute(
        "UPDATE trade_queue SET consumed = 1, consumed_by_trade_id = ?, consumed_at = ? WHERE id = ?",
        [consuming_trade_id, current_time_cst().isoformat(), queue_id]
    )
    database.commit()
    database.close()

QUEUE_MAX_ENTRIES = 100  # Sanity cap — normal operation stays well below this

def add_to_queue_on_connection(database, amount, source_trade_id):
    """
    Add a queue entry using an existing write connection.
    This avoids opening a second SQLite writer while a close transaction is active.
    """
    current_count = database.execute(
        "SELECT COUNT(*) as count FROM trade_queue WHERE consumed = 0"
    ).fetchone()["count"]

    if current_count < QUEUE_MAX_ENTRIES:
        database.execute(
            "INSERT INTO trade_queue (amount, source_trade_id, created_at) VALUES (?, ?, ?)",
            [round(amount, 4), source_trade_id, current_time_cst().isoformat()]
        )
    else:
        log.warning(f"Queue cap reached ({QUEUE_MAX_ENTRIES}) - skipping entry for {source_trade_id}")

def add_to_queue(amount, source_trade_id):
    """
    Add a completed trade's ending value to the back of the queue.
    Enforces a maximum of QUEUE_MAX_ENTRIES unconsumed entries to prevent
    runaway growth from bugs. In normal operation this cap is never hit.
    """
    database = get_database()
    current_count = database.execute(
        "SELECT COUNT(*) as count FROM trade_queue WHERE consumed = 0"
    ).fetchone()["count"]

    if current_count < QUEUE_MAX_ENTRIES:
        database.execute(
            "INSERT INTO trade_queue (amount, source_trade_id, created_at) VALUES (?, ?, ?)",
            [round(amount, 4), source_trade_id, current_time_cst().isoformat()]
        )
    else:
        log.warning(f"Queue cap reached ({QUEUE_MAX_ENTRIES}) — skipping entry for {source_trade_id}")

    database.commit()
    database.close()

def get_queue_status():
    """Return current queue state for API consumers."""
    database = get_database()
    available = database.execute("SELECT COUNT(*) as count, COALESCE(SUM(amount),0) as total FROM trade_queue WHERE consumed = 0").fetchone()
    total_ever = database.execute("SELECT COUNT(*) as count FROM trade_queue").fetchone()
    recent = [dict(row) for row in database.execute(
        "SELECT amount, source_trade_id, created_at, consumed FROM trade_queue ORDER BY id DESC LIMIT 20"
    ).fetchall()]
    next_amount = database.execute(
        "SELECT id, amount FROM trade_queue WHERE consumed = 0 ORDER BY id ASC LIMIT 1"
    ).fetchone()
    database.close()
    return {
        "available_count": available["count"],
        "available_total": round(available["total"], 2),
        "next_amount": round(next_amount["amount"], 2) if next_amount else None,
        "next_queue_id": next_amount["id"] if next_amount else None,
        "total_ever_queued": total_ever["count"],
        "default_fallback": get_dynamic_fallback_amount(),
        "recent_entries": recent,
    }

# ── PRICE DATA ────────────────────────────────────────────────────────────────
def get_nn_portfolio_value():
    """Return the NN portfolio value from its own closed/open trade ledger."""
    database = get_database()
    closed = database.execute(
        "SELECT COALESCE(SUM(net_pnl), 0) as total_pnl FROM nn_virtual_trades WHERE outcome != 'open'"
    ).fetchone()
    open_rows = database.execute(
        "SELECT invested_amount, current_value FROM nn_virtual_trades WHERE outcome='open'"
    ).fetchall()
    database.close()

    closed_pnl = float(closed["total_pnl"] or 0)
    open_pnl = 0.0
    for row in open_rows:
        invested = float(row["invested_amount"] or 0)
        current = float(row["current_value"] or invested)
        open_pnl += current - invested
    return STARTING_PORTFOLIO_VALUE + closed_pnl + open_pnl

def get_nn_investment_amount():
    """
    Independent NN position sizing.
    Uses 1% of the NN portfolio with a $1 floor.
    """
    return max(round(get_nn_portfolio_value() * 0.01, 2), 1.00)

def record_nn_open_execution_status(status):
    """Persist the latest NN open execution diagnostics for API/UI debugging."""
    payload = dict(status or {})
    payload.setdefault("attempted_at", current_time_cst().isoformat())
    set_app_state("last_nn_open_execution", json.dumps(payload))
    return payload

def record_nn_scan_status(**updates):
    """Persist lightweight NN scan status for non-blocking UI actions."""
    current = get_app_state_json(NN_SCAN_STATUS_KEY, {}) or {}
    current.update(updates)
    current["updated_at"] = current_time_cst().isoformat()
    set_app_state(NN_SCAN_STATUS_KEY, json.dumps(current))
    return current

def confidence_evidence_level(sample_size):
    """Human label for how much resolved history supports a confidence bucket."""
    n = int(sample_size or 0)
    if n >= 75:
        return "Strong"
    if n >= 30:
        return "Building"
    if n >= 10:
        return "Thin"
    return "New"

def confidence_evidence_bin(confidence):
    try:
        conf = int(round(float(confidence or 0)))
    except Exception:
        conf = 0
    if conf < 65:
        return (0, 64, "<65")
    if conf >= 85:
        return (85, 100, "85+")
    low = max(65, (conf // 5) * 5)
    high = low + 4
    return (low, high, f"{low}-{high}")

def build_confidence_evidence_cache():
    """
    Count resolved historical predictions by confidence bucket.
    This is sample-size context only; it does not change scoring.
    """
    bins = {}
    try:
        db = get_database()
        rows = [dict(r) for r in db.execute("""
            SELECT confidence, outcome, actual_move
            FROM predictions
            WHERE confidence IS NOT NULL
              AND outcome IN ('hit', 'miss')
        """).fetchall()]
        db.close()
    except Exception as exc:
        log.debug(f"confidence evidence unavailable: {exc}")
        rows = []

    for row in rows:
        low, high, label = confidence_evidence_bin(row.get("confidence"))
        bucket = bins.setdefault(label, {
            "bin": label,
            "bin_low": low,
            "bin_high": high,
            "sample_size": 0,
            "wins": 0,
            "losses": 0,
            "moves": [],
        })
        bucket["sample_size"] += 1
        if row.get("outcome") == "hit":
            bucket["wins"] += 1
        else:
            bucket["losses"] += 1
        if row.get("actual_move") is not None:
            bucket["moves"].append(float(row.get("actual_move") or 0))

    for bucket in bins.values():
        n = bucket["sample_size"]
        bucket["level"] = confidence_evidence_level(n)
        bucket["win_rate"] = round(bucket["wins"] / n * 100, 1) if n else None
        bucket["avg_move"] = round(sum(bucket["moves"]) / len(bucket["moves"]), 2) if bucket["moves"] else None
        bucket.pop("moves", None)
    return bins

def evidence_for_confidence(confidence, cache=None):
    low, high, label = confidence_evidence_bin(confidence)
    cache = cache if cache is not None else build_confidence_evidence_cache()
    evidence = dict(cache.get(label) or {
        "bin": label,
        "bin_low": low,
        "bin_high": high,
        "sample_size": 0,
        "wins": 0,
        "losses": 0,
        "win_rate": None,
        "avg_move": None,
        "level": "New",
    })
    evidence["description"] = (
        f"{evidence['level']} evidence: {evidence['sample_size']} resolved past picks "
        f"in the {label}% confidence bucket. This is sample-size context, not a scoring input."
    )
    return evidence

def attach_confidence_evidence(items, confidence_key="long_conf", cache=None):
    cache = cache if cache is not None else build_confidence_evidence_cache()
    for item in items or []:
        item["evidence"] = evidence_for_confidence(item.get(confidence_key), cache)
    return items

def build_regime_context(scan_type=None):
    """Small, structured market context placeholder for later Aegis analysis."""
    now = current_time_cst()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "weekday": now.strftime("%A"),
        "time_cst": now.strftime("%H:%M"),
        "scan_type": scan_type,
        "market_open": is_market_open(),
        "extended_hours": is_extended_hours(),
    }

def build_observation_context(stock_data=None, queue_locked=False):
    """Context-only data; these fields are logged but do not affect scoring."""
    stock_data = stock_data or {}
    return {
        "queue_locked": bool(queue_locked),
        "data_source": stock_data.get("source", "unknown"),
        "news_article_count": int(stock_data.get("news_article_count") or 0),
        "news_sentiment_score": float(stock_data.get("news_sentiment_score") or 0),
        "weather_context": None,
    }

def insert_signal_observations(rows):
    """Bulk insert signal observation rows without changing scoring behavior."""
    if not rows:
        return 0
    db = get_database()
    inserted = 0
    for row in rows:
        try:
            db.execute("""
                INSERT OR REPLACE INTO signal_observations
                (id, scan_event_id, scan_time, scan_type, strategy, variant_id, brain,
                 ticker, direction, sector, price, confidence, confidence_bin, expected_move,
                 selected, executable, rank, signal_scores, signal_values, fired_signals,
                 confluence_count, confluence_methods, regime_context, context_json,
                 outcome, actual_move, resolved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                row.get("id"),
                row.get("scan_event_id"),
                row.get("scan_time"),
                row.get("scan_type"),
                row.get("strategy", "SwingDesk"),
                row.get("variant_id"),
                row.get("brain"),
                row.get("ticker"),
                row.get("direction", "long"),
                row.get("sector"),
                row.get("price"),
                row.get("confidence"),
                row.get("confidence_bin"),
                row.get("expected_move"),
                int(bool(row.get("selected"))),
                int(bool(row.get("executable"))),
                row.get("rank"),
                json.dumps(row.get("signal_scores") or {}),
                json.dumps(row.get("signal_values") or {}),
                json.dumps(row.get("fired_signals") or []),
                int(row.get("confluence_count") or 0),
                json.dumps(row.get("confluence_methods") or []),
                json.dumps(row.get("regime_context") or {}),
                json.dumps(row.get("context_json") or {}),
                row.get("outcome", "pending"),
                row.get("actual_move"),
                row.get("resolved_at"),
            ])
            inserted += 1
        except Exception as exc:
            log.debug(f"signal observation skipped for {row.get('ticker')}: {exc}")
    db.commit()
    db.close()
    return inserted

def log_vector_signal_observations(scan_event_id, scan_type, price_data, scored_stocks, rsi_values,
                                   earnings_soon, weights, selected_tickers=None, executable_tickers=None,
                                   queue_locked=False):
    """Log one Vector observation per scored ticker from the shared scan snapshot."""
    scan_time = current_time_cst().isoformat()
    regime = build_regime_context(scan_type)
    selected_sequence = list(selected_tickers or [])
    selected_set = set(selected_sequence)
    executable_tickers = set(executable_tickers or [])
    ranked = {ticker: i + 1 for i, ticker in enumerate(selected_sequence)}
    rows = []
    for item in scored_stocks or []:
        ticker = item.get("ticker")
        if not ticker or ticker not in price_data:
            continue
        stock_data = price_data.get(ticker, {})
        rsi = rsi_values.get(ticker, item.get("rsi", 50.0))
        scores, fired, values = compute_signal_scores(ticker, price_data, rsi, earnings_soon, weights, "long")
        _, _, conf_bin = confidence_evidence_bin(item.get("long_conf"))
        rows.append({
            "id": f"{scan_event_id}:swingdesk_vector_0845_all:{ticker}:long",
            "scan_event_id": scan_event_id,
            "scan_time": scan_time,
            "scan_type": scan_type,
            "strategy": "SwingDesk",
            "variant_id": "swingdesk_vector_0845_all",
            "brain": "Vector",
            "ticker": ticker,
            "direction": "long",
            "sector": item.get("sector"),
            "price": item.get("price"),
            "confidence": item.get("long_conf"),
            "confidence_bin": conf_bin,
            "expected_move": item.get("long_move"),
            "selected": ticker in selected_set,
            "executable": ticker in executable_tickers,
            "rank": ranked.get(ticker),
            "signal_scores": scores,
            "signal_values": values,
            "fired_signals": fired,
            "confluence_count": item.get("confluence_count", 0),
            "confluence_methods": item.get("confluence_methods", []),
            "regime_context": regime,
            "context_json": build_observation_context(stock_data, queue_locked),
        })
    return insert_signal_observations(rows)

def log_nova_signal_observations(scan_event_id, scan_type, scored_rows, price_data, queue_locked=False):
    """Log Nova observations from the same shared scan snapshot."""
    if not scan_event_id:
        return 0
    scan_time = current_time_cst().isoformat()
    regime = build_regime_context(scan_type)
    selected = scored_rows[:MAX_LONG_PICKS] if scored_rows else []
    selected_tickers = {row.get("ticker") for row in selected}
    executable_tickers = {row.get("ticker") for row in scored_rows or [] if row.get("nn_executable")}
    ranked = {row.get("ticker"): i + 1 for i, row in enumerate(scored_rows or [])}
    rows = []
    for row in scored_rows or []:
        ticker = row.get("ticker")
        stock_data = price_data.get(ticker, {}) if ticker else {}
        _, _, conf_bin = confidence_evidence_bin(row.get("long_conf"))
        rows.append({
            "id": f"{scan_event_id}:swingdesk_nova_0845_all:{ticker}:long",
            "scan_event_id": scan_event_id,
            "scan_time": scan_time,
            "scan_type": scan_type,
            "strategy": "SwingDesk",
            "variant_id": "swingdesk_nova_0845_all",
            "brain": "Nova",
            "ticker": ticker,
            "direction": "long",
            "sector": row.get("sector"),
            "price": row.get("price"),
            "confidence": row.get("long_conf"),
            "confidence_bin": conf_bin,
            "expected_move": row.get("long_move"),
            "selected": ticker in selected_tickers,
            "executable": ticker in executable_tickers,
            "rank": ranked.get(ticker),
            "signal_scores": row.get("signal_scores_for_observation") or {},
            "signal_values": row.get("signal_values_for_observation") or {},
            "fired_signals": row.get("fired_signals_for_observation") or [],
            "confluence_count": row.get("confluence_count", 0),
            "confluence_methods": row.get("confluence_methods", []),
            "regime_context": regime,
            "context_json": build_observation_context(stock_data, queue_locked),
        })
    return insert_signal_observations(rows)

def get_nn_scan_status_payload():
    """Return shared Nova scan status with stale running states marked clearly."""
    status = get_app_state_json(NN_SCAN_STATUS_KEY, {}) or {}
    if status.get("status") == "running":
        running_scan = get_running_comprehensive_scan()
        if not running_scan:
            next_status = dict(status)
            next_status.update(
                status="stalled",
                started=False,
                already_running=False,
                finished_at=current_time_cst().isoformat(),
                error=status.get("error") or "Background shared scan no longer has a running scan event.",
            )
            status = record_nn_scan_status(**next_status)
    return status

def start_shared_scan_background(scan_type="manual_shared"):
    """
    Start a shared comprehensive scan in the background and return immediately.
    Nova is scored from that same snapshot; this endpoint must never resurrect
    a separate user-facing neural universe scan.
    """
    with _nn_scan_thread_lock:
        current = get_nn_scan_status_payload()
        if current.get("status") == "running":
            return {**current, "started": False, "already_running": True}
        running_scan = get_running_comprehensive_scan()
        if running_scan:
            return record_nn_scan_status(
                status="running",
                scan_type=running_scan.get("scan_type", scan_type),
                source="shared_comprehensive_scan",
                started=False,
                already_running=True,
                started_at=running_scan.get("started_at"),
                finished_at=None,
                total_scanned=running_scan.get("tickers_attempted", 0),
                qualified=0,
                picks=0,
                error=None,
                scan_event_id=running_scan.get("id"),
            )

        status = record_nn_scan_status(
            status="running",
            scan_type=scan_type,
            source="shared_comprehensive_scan",
            started=True,
            already_running=False,
            started_at=current_time_cst().isoformat(),
            finished_at=None,
            total_scanned=0,
            qualified=0,
            picks=0,
            error=None,
        )

        def worker():
            try:
                result = run_comprehensive_scan(scan_type=scan_type)
                if result.get("skipped"):
                    record_nn_scan_status(
                        status="stalled",
                        scan_type=scan_type,
                        source="shared_comprehensive_scan",
                        started=False,
                        already_running=False,
                        finished_at=current_time_cst().isoformat(),
                        total_scanned=0,
                        qualified=0,
                        picks=0,
                        error=result.get("reason") or "comprehensive scan skipped",
                    )
                    return
                nn_result = result.get("nn_picks", {}) or {}
                record_nn_scan_status(
                    status="complete",
                    scan_type=scan_type,
                    source="shared_comprehensive_scan",
                    started=False,
                    already_running=False,
                    finished_at=current_time_cst().isoformat(),
                    total_scanned=result.get("total_scanned", 0),
                    qualified=nn_result.get("qualified_count", 0),
                    picks=nn_result.get("picks", 0),
                    error=None,
                )
            except Exception as exc:
                log.error(f"Background shared Nova scan failed: {exc}")
                record_nn_scan_status(
                    status="error",
                    scan_type=scan_type,
                    source="shared_comprehensive_scan",
                    started=False,
                    already_running=False,
                    finished_at=current_time_cst().isoformat(),
                    error=str(exc),
                )

        threading.Thread(target=worker, daemon=True).start()
        return status

def start_nn_scan_background(scan_type="manual_shared_nova"):
    """Backward-compatible name for manual Nova refreshes; still runs the shared scan."""
    return start_shared_scan_background(scan_type=scan_type)

TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
TWELVE_DATA_BASE = "https://api.twelvedata.com"
FINNHUB_KEY = os.getenv("FINNHUB_KEY")
FINNHUB_BASE = "https://finnhub.io/api/v1"
MASSIVE_BASE = os.getenv("MASSIVE_BASE", "https://api.massive.com").rstrip("/")
QUOTE_CACHE_SECONDS = int(os.getenv("QUOTE_CACHE_SECONDS", "90"))
PROVIDER_CHAIN = [p.strip() for p in os.getenv(
    "PRICE_PROVIDER_CHAIN",
    "massive,finnhub,alpha_vantage,twelve_data"
).split(",") if p.strip()]

class ProviderCycle:
    """Per-job provider memory so a global failure is not retried for every ticker."""
    def __init__(self, purpose="quote", max_layers=4):
        self.purpose = purpose
        self.max_layers = max_layers
        self.unhealthy = set()
        self.attempts = {}
        self.successes = {}
        self.failures = {}
        self.errors = {}

    def record(self, provider, ok, failure_type=None, error=None, global_failure=False):
        self.attempts[provider] = self.attempts.get(provider, 0) + 1
        if ok:
            self.successes[provider] = self.successes.get(provider, 0) + 1
        else:
            self.failures[provider] = self.failures.get(provider, 0) + 1
            if error:
                self.errors[provider] = str(error)[:160]
            if global_failure:
                self.unhealthy.add(provider)
        if failure_type == "disabled":
            return
        record_provider_health(
            provider,
            ok,
            failure_type=failure_type,
            error=error,
            cooldown_minutes=15 if failure_type == "rate_limit" else (5 if global_failure else 0),
        )

    def summary(self):
        return {
            "purpose": self.purpose,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "errors": self.errors,
            "unhealthy_this_cycle": sorted(self.unhealthy),
        }

def _read_quote_cache(ticker, max_age_seconds=QUOTE_CACHE_SECONDS):
    try:
        database = get_database()
        row = database.execute("SELECT value FROM app_state WHERE key=?", [f"quote_cache_{ticker}"]).fetchone()
        database.close()
        if not row:
            return None
        cached = json.loads(row["value"])
        fetched_at = datetime.fromisoformat(cached.get("fetched_at"))
        if (current_time_cst() - fetched_at).total_seconds() > max_age_seconds:
            return None
        data = cached.get("data") or {}
        data["source"] = f"{data.get('source', 'cache')}_cache"
        data["cached_at"] = cached.get("fetched_at")
        return data
    except Exception:
        return None

def _write_quote_cache(ticker, data):
    try:
        database = get_database()
        database.execute(
            "INSERT OR REPLACE INTO app_state VALUES (?,?)",
            [f"quote_cache_{ticker}", json.dumps({"fetched_at": current_time_cst().isoformat(), "data": data})]
        )
        database.commit()
        database.close()
    except Exception:
        pass

def _normalize_quote(price, previous_close=None, open_price=None, high=None, low=None, source="unknown"):
    price = float(price)
    prev = float(previous_close if previous_close not in (None, 0) else price)
    open_value = float(open_price if open_price not in (None, 0) else price)
    high_value = float(high if high not in (None, 0) else price)
    low_value = float(low if low not in (None, 0) else price)
    return {
        "price": price,
        "open": open_value,
        "previous_close": prev,
        "high": high_value,
        "low": low_value,
        "volume": 0,
        "average_volume": 1,
        "volume_ratio": 1.0,
        "gap_percent": (open_value - prev) / max(prev, 0.01) * 100,
        "day_change_pct": (price - prev) / max(prev, 0.01) * 100,
        "day_change_percent": (price - prev) / max(prev, 0.01) * 100,
        "source": source,
    }

def _first_number(*values):
    """Return the first value that can be safely interpreted as a non-zero float."""
    for value in values:
        try:
            if value in (None, ""):
                continue
            number = float(value)
            if number != 0:
                return number
        except Exception:
            continue
    return None

def pct_from_baseline(price, baseline):
    """Return percent change from a baseline, or None when the baseline is unusable."""
    try:
        price = float(price)
        baseline = float(baseline)
        if baseline <= 0:
            return None
        return (price - baseline) / baseline * 100
    except Exception:
        return None

def previous_completed_close_from_history(history):
    """Return the most recent completed daily close before today's market date."""
    if not history:
        return None
    today = current_time_cst().strftime("%Y-%m-%d")
    dated_rows = [
        row for row in history
        if row.get("date") and row.get("date") < today and row.get("close") not in (None, 0)
    ]
    if dated_rows:
        return float(dated_rows[-1]["close"])
    if len(history) >= 2:
        return float(history[-2].get("close") or 0) or None
    return float(history[-1].get("close") or 0) or None

def repair_quote_baselines_from_history(quote, history):
    """Use completed candles to repair stale previous-close/open baselines."""
    if not quote or not history:
        return quote
    try:
        price = float(quote.get("price") or 0)
        completed_prev = previous_completed_close_from_history(history)
        if completed_prev:
            quote["previous_close"] = completed_prev
            quote["day_change_percent"] = pct_from_baseline(price, completed_prev) or 0
            quote["day_change_pct"] = quote["day_change_percent"]
            quote["gap_percent"] = pct_from_baseline(quote.get("open", price), completed_prev) or 0
            quote["baseline_repaired_from_history"] = True
            return quote
        current_prev = float(quote.get("previous_close") or 0)
        current_change = abs(pct_from_baseline(price, current_prev) or 0)
        close_candidates = [
            float(row.get("close"))
            for row in history[-3:]
            if row.get("close") not in (None, 0)
        ]
        better = [
            close for close in close_candidates
            if abs(pct_from_baseline(price, close) or 0) + 2 < current_change
        ]
        plausible = [
            close for close in better
            if abs(pct_from_baseline(price, close) or 0) <= 8
        ]
        if current_change >= 8 and plausible:
            repaired_prev = min(plausible, key=lambda close: abs(price - close))
            quote["previous_close"] = repaired_prev
            quote["day_change_percent"] = pct_from_baseline(price, repaired_prev) or 0
            quote["day_change_pct"] = quote["day_change_percent"]
            quote["gap_percent"] = pct_from_baseline(quote.get("open", price), repaired_prev) or 0
            quote["baseline_repaired_from_history"] = True
    except Exception:
        pass
    return quote

def canonical_signal_weights():
    """Protected original signal-weight baseline used to seed every universe."""
    return {
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

LEGACY_SIGNAL_KEY_ALIASES = {
    "overnight_gap": "overnight_gap_probability",
    "sector_rs": "sector_relative_strength",
}

def canonical_signal_key(key):
    """Return the canonical 9-signal key for persisted and legacy signal names."""
    return LEGACY_SIGNAL_KEY_ALIASES.get(key, key)

def signal_value(blob, canonical_key, default=0.5):
    """Read a signal score/value using both canonical and legacy names."""
    if not isinstance(blob, dict):
        return default
    legacy_keys = [k for k, v in LEGACY_SIGNAL_KEY_ALIASES.items() if v == canonical_key]
    for key in [canonical_key, *legacy_keys]:
        if key in blob:
            return blob.get(key)
    return default

def canonicalize_signal_map(blob):
    """Normalize persisted signal maps so ML, audit, and UI speak one vocabulary."""
    if not isinstance(blob, dict):
        return {}
    normalized = {}
    for key, value in blob.items():
        normalized[canonical_signal_key(key)] = value
    return normalized

def extract_signal_score_map(payload):
    """Return canonical signal scores from flat, nested, or JSON string payloads."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except Exception:
            payload = {}
    if isinstance(payload, dict) and isinstance(payload.get("scores"), dict):
        payload = payload.get("scores") or {}
    if not isinstance(payload, dict):
        return {}
    return canonicalize_signal_map(payload)

def split_price_context(ticker, price_context):
    """
    Accept either a full universe price map or a single ticker data row.
    Returns (universe_map, ticker_row) so every signal can use the right context.
    """
    if isinstance(price_context, dict) and isinstance(price_context.get(ticker), dict):
        return price_context, price_context.get(ticker) or {}
    row = price_context if isinstance(price_context, dict) else {}
    return {ticker: row}, row

def normalize_signal_weights(weights):
    baseline = canonical_signal_weights()
    merged = {k: float((weights or {}).get(k, v) or v) for k, v in baseline.items()}
    total = sum(max(v, 0.03) for v in merged.values())
    return {k: round(max(v, 0.03) / total, 4) for k, v in merged.items()}

def get_variant_signal_weights(database, variant_id):
    row = database.execute("SELECT weights_json FROM variant_signal_weights WHERE variant_id=?", [variant_id]).fetchone()
    if not row:
        return canonical_signal_weights()
    try:
        return normalize_signal_weights(json.loads(row["weights_json"] or "{}"))
    except Exception:
        return canonical_signal_weights()

def variant_weighted_signal_score(pick, weights):
    scores = pick.get("signal_scores_for_observation") or pick.get("signal_scores") or {}
    base_conf, _ = pick_confidence_and_move(pick)
    scores = extract_signal_score_map(scores)
    if not isinstance(scores, dict) or not scores:
        return float(base_conf)
    weighted = sum(float(scores.get(k, 0.5) or 0.5) * float(weights.get(k, 0)) for k in canonical_signal_weights())
    return round(base_conf * 0.65 + weighted * 100 * 0.35, 4)

def build_signal_payload_json_from_pick(pick, ticker, buy_price, weights, direction="long"):
    """Build the persisted signal payload used by UI context and daily learning."""
    raw_payload = pick.get("signal_scores") or {}
    raw_values = {}
    raw_fired = []
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload or "{}")
        except Exception:
            raw_payload = {}
    if isinstance(raw_payload, dict):
        raw_values = raw_payload.get("values") if isinstance(raw_payload.get("values"), dict) else {}
        raw_fired = raw_payload.get("fired") if isinstance(raw_payload.get("fired"), list) else []

    scores = extract_signal_score_map(raw_payload or pick.get("signal_scores_for_observation") or {})
    values = raw_values or pick.get("signal_values_for_observation") or {}
    fired = raw_fired or pick.get("fired_signals_for_observation") or [
        key for key, value in scores.items()
        if float(value or 0) >= 0.65
    ]
    if scores:
        return json.dumps({"scores": scores, "fired": fired, "values": values})

    open_price_data = {ticker: {
        "price": buy_price,
        "open": pick.get("open_price") or buy_price,
        "previous_close": pick.get("prev_close") or pick.get("previous_close") or buy_price,
        "volume_ratio": pick.get("vol_ratio", pick.get("volume_ratio", 1.0)),
        "gap_percent": pick.get("overnight_gap_pct", pick.get("gap_percent", 0)),
        "day_change_percent": pick.get("day_change_pct", pick.get("day_change_percent", 0)),
        "daily_history": pick.get("daily_history") or [],
    }}
    try:
        earnings = check_upcoming_earnings([ticker])
        computed_scores, computed_fired, computed_values = compute_signal_scores(
            ticker, open_price_data, pick.get("rsi", 50.0), earnings, weights, direction
        )
        return json.dumps({"scores": computed_scores, "fired": computed_fired, "values": computed_values})
    except Exception as signal_error:
        log.warning(f"Variant signal snapshot failed for {ticker}: {signal_error}")
        neutral_scores = {key: 0.5 for key in canonical_signal_weights()}
        return json.dumps({"scores": neutral_scores, "fired": [], "values": {}})

def learn_variant_from_closed_trade(database, trade_row, outcome, actual_move):
    """Learn from one resolved variant trade and always leave an audit trail."""
    variant_id = trade_row.get("variant_id")
    before = get_variant_signal_weights(database, variant_id)
    try:
        scores_blob = json.loads(trade_row.get("signal_scores") or "{}")
    except Exception:
        scores_blob = {}
    scores = scores_blob.get("scores") if isinstance(scores_blob, dict) else {}
    if not isinstance(scores, dict):
        scores = scores_blob if isinstance(scores_blob, dict) else {}
    scores = extract_signal_score_map(scores)
    after = dict(before)
    reasoning = []
    status = "updated"
    if scores:
        if outcome == "hit":
            direction = 1.0
        elif outcome == "partial":
            direction = 0.35
        else:
            direction = -1.0
        strength = min(abs(float(actual_move or 0)) / 10.0, 1.0)
        for key in canonical_signal_weights():
            signal_score = float(scores.get(key, 0.5) or 0.5)
            delta = direction * strength * (signal_score - 0.5) * 0.02
            if abs(delta) >= 0.0001:
                after[key] = after.get(key, before[key]) + delta
                reasoning.append(f"{key} {'rewarded' if delta > 0 else 'penalized'} from {outcome} trade")
        after = normalize_signal_weights(after)
        if not reasoning:
            status = "unchanged"
            reasoning.append("signal scores were neutral; weights unchanged")
    else:
        status = "missing_signal_scores"
        reasoning.append("closed trade had no signal score payload; weights unchanged")
    ts = current_time_cst().isoformat()
    if status == "updated":
        database.execute("""
            UPDATE variant_signal_weights
            SET weights_json=?, learning_revision=COALESCE(learning_revision, 0)+1, updated_at=?
            WHERE variant_id=?
        """, [json.dumps(after), ts, variant_id])
    database.execute("""
        INSERT OR REPLACE INTO variant_learning_events
        (id, variant_id, trade_id, timestamp, outcome, actual_move, weights_before, weights_after, reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [f"{trade_row.get('id')}_{int(time.time())}", variant_id, trade_row.get("id"), ts, outcome, actual_move, json.dumps(before), json.dumps(after), json.dumps(reasoning[:6])])
    return status

def classify_variant_outcome_from_pnl(pnl_percent):
    """Single source of truth for variant closed-trade labels from realized P&L."""
    pnl = float(pnl_percent or 0)
    if pnl >= MIN_EXPECTED_MOVE:
        return "hit"
    if pnl > 0:
        return "partial"
    return "miss"

def run_daily_variant_learning():
    """Apply variant ML once per day from closed trades that have not been learned yet."""
    database = get_database()
    try:
        rows = [dict(r) for r in database.execute("""
            SELECT t.*
            FROM variant_virtual_trades t
            LEFT JOIN variant_learning_events e ON e.trade_id = t.id
            WHERE t.outcome != 'open'
              AND t.sell_date IS NOT NULL
              AND e.trade_id IS NULL
            ORDER BY t.sell_date ASC, COALESCE(t.sell_time, '') ASC, t.id ASC
        """).fetchall()]
        learned = 0
        updated = 0
        unchanged = 0
        missing_signal_scores = 0
        for row in rows:
            outcome = row.get("outcome")
            actual_move = row.get("actual_move")
            if not row.get("variant_id") or outcome == "open":
                continue
            status = learn_variant_from_closed_trade(database, row, outcome, actual_move)
            learned += 1
            if status == "updated":
                updated += 1
            elif status == "missing_signal_scores":
                missing_signal_scores += 1
            else:
                unchanged += 1
        database.commit()
        return {
            "success": True,
            "learned": learned,
            "updated": updated,
            "unchanged": unchanged,
            "missing_signal_scores": missing_signal_scores,
            "eligible_closed_trades": len(rows),
        }
    except Exception as exc:
        database.rollback()
        log.error(f"Daily variant learning failed: {exc}")
        return {"success": False, "error": str(exc), "learned": 0}
    finally:
        database.close()

def rebuild_variant_learning_for_variants(database, variant_ids):
    """Replay ML weights from baseline after trade-history repairs.

    Repricing historical entries can change realized moves and outcomes. Leaving
    old learning events in place would preserve poisoned weight changes, so this
    helper resets affected variants to their baseline profile and replays every
    closed trade in chronological order.
    """
    rebuilt = []
    for variant_id in sorted({v for v in variant_ids if v}):
        weights_row = database.execute(
            "SELECT baseline_weights_json FROM variant_signal_weights WHERE variant_id=?",
            [variant_id],
        ).fetchone()
        if not weights_row:
            continue
        try:
            baseline = json.loads(weights_row["baseline_weights_json"] or "{}")
        except Exception:
            baseline = {}
        if not baseline:
            baseline = canonical_signal_weights()
        now = current_time_cst().isoformat()
        database.execute(
            """
            UPDATE variant_signal_weights
            SET weights_json=?, learning_revision=COALESCE(learning_revision, 0)+1, updated_at=?
            WHERE variant_id=?
            """,
            [json.dumps(normalize_signal_weights(baseline)), now, variant_id],
        )
        database.execute("DELETE FROM variant_learning_events WHERE variant_id=?", [variant_id])
        rows = [dict(r) for r in database.execute(
            """
            SELECT *
            FROM variant_virtual_trades
            WHERE variant_id=?
              AND outcome!='open'
              AND outcome!='archived_excess_open'
              AND sell_date IS NOT NULL
            ORDER BY sell_date ASC, COALESCE(sell_time, '') ASC, id ASC
            """,
            [variant_id],
        ).fetchall()]
        status_counts = {"updated": 0, "unchanged": 0, "missing_signal_scores": 0}
        for row in rows:
            status = learn_variant_from_closed_trade(
                database,
                row,
                row.get("outcome"),
                row.get("actual_move"),
            )
            status_counts[status] = status_counts.get(status, 0) + 1
        rebuilt.append({
            "variant_id": variant_id,
            "replayed_closed_trades": len(rows),
            "status_counts": status_counts,
        })
    return rebuilt

def build_entry_integrity(position, price_data):
    """Lightweight audit comparing stored entry against quote context."""
    buy_price = float(position.get("buy_price") or 0)
    prev_close = price_data.get("previous_close")
    regular_open = price_data.get("open")
    if buy_price <= 0:
        return "bad", "Entry price missing or zero"

    checks = []
    for label, baseline in (("prev close", prev_close), ("regular open", regular_open)):
        pct = pct_from_baseline(buy_price, baseline)
        if pct is not None:
            checks.append((label, pct))

    if not checks:
        return "unknown", "No quote baseline available for entry audit"

    largest = max(checks, key=lambda item: abs(item[1]))
    if abs(largest[1]) >= 8:
        return "review", f"Entry is {largest[1]:+.1f}% vs {largest[0]}"
    if abs(largest[1]) >= 4:
        return "watch", f"Entry is {largest[1]:+.1f}% vs {largest[0]}"
    return "ok", "Entry is within expected quote context"

def normalize_monitor_quote(raw, fallback_price=None):
    """Return a dict quote shape so monitor math never depends on provider quirks."""
    if isinstance(raw, dict):
        price = raw.get("price", fallback_price)
        quote = dict(raw)
    else:
        price = raw if raw is not None else fallback_price
        quote = {}
    try:
        price = float(price)
    except Exception:
        price = float(fallback_price or 0)
    quote["price"] = price
    quote.setdefault("previous_close", fallback_price or price)
    quote.setdefault("open", price)
    quote.setdefault("high", price)
    quote.setdefault("low", price)
    quote.setdefault("volume", 0)
    quote.setdefault("average_volume", 1)
    quote.setdefault("volume_ratio", 1.0)
    quote.setdefault("gap_percent", 0)
    quote.setdefault("day_change_pct", quote.get("day_change_percent", 0))
    quote.setdefault("day_change_percent", quote.get("day_change_pct", 0))
    quote.setdefault("source", "unknown")
    return quote

def monitor_baselines(position, price_data, pnl_percent):
    """Build safe percent baseline and entry-integrity fields for monitor writes."""
    return {
        "pct_prev_close": pct_from_baseline(price_data.get("price"), price_data.get("previous_close")),
        "pct_regular_open": pct_from_baseline(price_data.get("price"), price_data.get("open")),
        "pct_entry": pnl_percent,
        "entry_integrity": build_entry_integrity(position, price_data),
    }

def select_variant_picks(picks, selection_mode):
    """Apply a variant selection mode to a ranked pick list."""
    mode = (selection_mode or "All").lower().replace(" ", "")
    if mode in ("top1", "1"):
        return picks[:1]
    if mode in ("top3", "3"):
        return picks[:3]
    return picks

def cache_age_minutes(timestamp):
    parsed = _parse_iso(timestamp)
    if not parsed:
        return None
    return round((current_time_cst() - parsed).total_seconds() / 60, 1)

def variant_cache_snapshot(database, require_fresh=True, max_age_minutes=180):
    """Load the shared Vector/Nova cache pair and reject stale or incomplete manual runs."""
    status_row = database.execute("SELECT value FROM app_state WHERE key=?", [NN_SCAN_STATUS_KEY]).fetchone()
    scan_status = json.loads(status_row["value"]) if status_row and status_row["value"] else {}
    running_scan_refusal = None
    if scan_status.get("status") in ("queued", "running"):
        running_scan_refusal = {
            "success": False,
            "refused": True,
            "reason": "shared_scan_running",
            "message": "Shared scan is still running; using the latest completed shared cache when it is fresh enough.",
            "scan_status": scan_status,
        }

    vector_cached = database.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
    nova_cached = database.execute("SELECT value FROM app_state WHERE key='cached_nn_picks'").fetchone()
    vector_time_row = database.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    nova_time_row = database.execute("SELECT value FROM app_state WHERE key='cached_nn_picks_time'").fetchone()
    if not vector_cached or not nova_cached:
        return None, {
            "success": False,
            "refused": True,
            "reason": "missing_shared_cache",
            "message": "Both Vector and Nova caches are required so universes use one shared snapshot.",
            "vector_cached": bool(vector_cached),
            "nova_cached": bool(nova_cached),
        }

    vector_payload = json.loads(vector_cached["value"]) if vector_cached else {}
    nova_payload = json.loads(nova_cached["value"]) if nova_cached else {}
    vector_time = vector_time_row["value"] if vector_time_row else vector_payload.get("generated_at")
    nova_time = nova_time_row["value"] if nova_time_row else nova_payload.get("scan_time")
    vector_age = cache_age_minutes(vector_time)
    nova_age = cache_age_minutes(nova_time)
    if require_fresh and (
        vector_age is None or nova_age is None or
        vector_age > max_age_minutes or nova_age > max_age_minutes
    ):
        return None, {
            "success": False,
            "refused": True,
            "reason": "stale_shared_cache",
            "message": "Shared scan cache is stale; trigger /api/shared-scan-now before opening universe trades.",
            "vector_cache_time": vector_time,
            "nova_cache_time": nova_time,
            "vector_cache_age_minutes": vector_age,
            "nova_cache_age_minutes": nova_age,
        }
    vector_dt = _parse_iso(vector_time)
    nova_dt = _parse_iso(nova_time)
    cache_gap = None
    if vector_dt and nova_dt:
        cache_gap = round(abs((vector_dt - nova_dt).total_seconds()) / 60, 1)
    if require_fresh and (cache_gap is None or cache_gap > 15):
        return None, {
            "success": False,
            "refused": True,
            "reason": "cache_pair_mismatch",
            "message": "Vector and Nova caches are not from the same shared scan window.",
            "vector_cache_time": vector_time,
            "nova_cache_time": nova_time,
            "cache_gap_minutes": cache_gap,
        }

    snapshot = {
        "vector_payload": vector_payload,
        "nova_payload": nova_payload,
        "vector_cache_time": vector_time,
        "nova_cache_time": nova_time,
        "vector_cache_age_minutes": vector_age,
        "nova_cache_age_minutes": nova_age,
        "cache_gap_minutes": cache_gap,
        "scan_status": scan_status,
    }
    if running_scan_refusal:
        snapshot["cache_warning"] = running_scan_refusal
    return snapshot, None

def explain_variant_strategy_match(strategy, pick):
    """Explain one strategy filter decision for variant aliveness diagnostics."""
    strategy = (strategy or "SwingDesk").lower()
    day_change = float(pick.get("day_change_pct") or pick.get("pct_change_prev_close") or 0)
    regular_open_change = float(pick.get("pct_change_regular_open") or 0)
    gap = float(pick.get("overnight_gap_pct") or pick.get("gap_percent") or 0)
    volume = float(pick.get("vol_ratio") or pick.get("volume_ratio") or 1)
    rsi = float(pick.get("rsi") or 50)
    confidence, expected_move = pick_confidence_and_move(pick, "Vector")
    confluence = int(pick.get("confluence_count") or 0)
    methods = pick.get("confluence_methods") or []
    if not isinstance(methods, list):
        methods = []
    method_text = " ".join(str(m).lower() for m in methods)

    def result(matched, reasons=None, passes=None):
        return {
            "matched": bool(matched),
            "reasons": reasons or [],
            "passes": passes or [],
            "metrics": {
                "confidence": confidence,
                "expected_move": expected_move,
                "day_change_pct": day_change,
                "regular_open_change_pct": regular_open_change,
                "gap_pct": gap,
                "volume_ratio": volume,
                "rsi": rsi,
                "confluence_count": confluence,
            },
        }

    if strategy in ("nr7", "opening range hold"):
        return result(False, [f"{strategy} is retired from SwingDesk Stocks"])
    if strategy == "swingdesk":
        reasons = []
        if confidence < 65:
            reasons.append(f"confidence {confidence}% below 65%")
        if expected_move < 3:
            reasons.append(f"expected move {expected_move:.1f}% below 3.0%")
        return result(not reasons, reasons)
    if strategy == "darvas":
        reasons = []
        if not (confluence >= 1 or "52" in method_text or "breakout" in method_text):
            reasons.append("no breakout/confluence evidence")
        if day_change <= 1.5:
            reasons.append(f"day change {day_change:.1f}% not above 1.5%")
        if volume < 1.0:
            reasons.append(f"volume {volume:.2f}x below 1.0x")
        return result(not reasons, reasons)
    if strategy == "gap & go":
        reasons = []
        if gap < 2.5:
            reasons.append(f"gap {gap:.1f}% below 2.5%")
        if day_change <= 2:
            reasons.append(f"day change {day_change:.1f}% not above 2.0%")
        if volume < 1.1:
            reasons.append(f"volume {volume:.2f}x below 1.1x")
        return result(not reasons, reasons)
    if strategy == "vwap reclaim":
        scores = pick.get("signal_scores_for_observation") or pick.get("signal_scores") or {}
        scores = extract_signal_score_map(scores)
        vwap_score = float(scores.get("vwap_reclaim") or 0)
        matched = vwap_score >= 0.65 or "vwap" in method_text
        return result(matched, [] if matched else [f"VWAP score {vwap_score:.2f} below 0.65 and no VWAP method tag"])
    if strategy == "inside day":
        reasons = []
        if abs(gap) > 4:
            reasons.append(f"gap {gap:.1f}% outside inside-day range")
        if day_change <= 0.5:
            reasons.append(f"day change {day_change:.1f}% not above 0.5%")
        if volume < 0.8:
            reasons.append(f"volume {volume:.2f}x below 0.8x")
        if not 45 <= rsi <= 65:
            reasons.append(f"RSI {rsi:.0f} outside 45-65")
        return result(not reasons, reasons)
    if strategy == "bull flag":
        reasons = []
        if day_change <= 1:
            reasons.append(f"day change {day_change:.1f}% not above 1.0%")
        if regular_open_change <= -2:
            reasons.append(f"regular-open change {regular_open_change:.1f}% too weak")
        if not 45 <= rsi <= 70:
            reasons.append(f"RSI {rsi:.0f} outside 45-70")
        if confidence < 62:
            reasons.append(f"confidence {confidence}% below 62%")
        return result(not reasons, reasons)
    if strategy == "pocket pivot":
        reasons = []
        if volume < 1.4:
            reasons.append(f"volume {volume:.2f}x below 1.4x")
        if day_change <= 0.5:
            reasons.append(f"day change {day_change:.1f}% not above 0.5%")
        if confidence < 60:
            reasons.append(f"confidence {confidence}% below 60%")
        return result(not reasons, reasons)
    if strategy == "vol squeeze breakout":
        scores = pick.get("signal_scores_for_observation") or pick.get("signal_scores") or {}
        scores = extract_signal_score_map(scores)
        squeeze_score = float(scores.get("volatility_squeeze") or 0)
        reasons = []
        if squeeze_score < 0.5:
            reasons.append(f"volatility squeeze score {squeeze_score:.2f} below 0.50")
        if day_change <= 1:
            reasons.append(f"day change {day_change:.1f}% not above 1.0%")
        return result(not reasons, reasons)
    if strategy == "relative strength pullback":
        reasons = []
        if confidence < 62:
            reasons.append(f"confidence {confidence}% below 62%")
        if day_change <= 0:
            reasons.append(f"day change {day_change:.1f}% not positive")
        if regular_open_change > 1.5:
            reasons.append(f"regular-open change {regular_open_change:.1f}% too extended")
        if not 42 <= rsi <= 62:
            reasons.append(f"RSI {rsi:.0f} outside 42-62")
        if volume < 1.0:
            reasons.append(f"volume {volume:.2f}x below 1.0x")
        return result(not reasons, reasons)
    if strategy == "ema trend pullback":
        reasons = []
        if confidence < 62:
            reasons.append(f"confidence {confidence}% below 62%")
        if not -2.5 <= regular_open_change <= 1.0:
            reasons.append(f"regular-open change {regular_open_change:.1f}% outside pullback range")
        if day_change < -1.0:
            reasons.append(f"day change {day_change:.1f}% too weak")
        if not 45 <= rsi <= 60:
            reasons.append(f"RSI {rsi:.0f} outside 45-60")
        if volume < 0.9:
            reasons.append(f"volume {volume:.2f}x below 0.9x")
        return result(not reasons, reasons)
    return result(confidence >= 65, [] if confidence >= 65 else [f"confidence {confidence}% below 65%"])

def variant_strategy_matches(strategy, pick):
    """Lightweight bullish filters so universes do not all consume the same pick stream."""
    return explain_variant_strategy_match(strategy, pick).get("matched", False)

def filter_variant_strategy_picks(picks, variant, weights=None):
    filtered = [p for p in picks if variant_strategy_matches(variant.get("strategy"), p)]
    if weights:
        filtered.sort(key=lambda p: variant_weighted_signal_score(p, weights), reverse=True)
    return filtered

def pick_confidence_and_move(pick, brain="Vector"):
    confidence = pick.get("long_conf") or pick.get("confidence") or pick.get("nn_score") or 0
    expected_move = pick.get("long_move") or pick.get("expected_move") or 0
    try:
        confidence = int(round(float(confidence)))
    except Exception:
        confidence = 0
    try:
        expected_move = float(expected_move or 0)
    except Exception:
        expected_move = 0.0
    return confidence, expected_move

def is_long_pick_eligible(pick, open_tickers=None, confidence_floor=CONFIDENCE_FLOOR):
    """Shared Vector/Nova long-pick gate before ranking or variant selection."""
    if not pick or not pick.get("ticker"):
        return False
    if open_tickers and pick.get("ticker") in open_tickers:
        return False
    confidence, expected_move = pick_confidence_and_move(pick)
    volume = float(pick.get("vol_ratio") or pick.get("volume_ratio") or 1)
    price = float(pick.get("open_price") or pick.get("price") or pick.get("buy_price") or 0)
    return (
        price > 0
        and confidence >= confidence_floor
        and expected_move >= MIN_EXPECTED_MOVE
        and not pick.get("earnings_soon")
    )

def explain_long_pick_gate(row, open_tickers=None, confidence_floor=CONFIDENCE_FLOOR):
    """Return human-readable pass/fail reasons for the shared long-pick gate."""
    open_tickers = open_tickers or set()
    ticker = (row.get("ticker") or "").upper()
    confidence = int(round(float(row.get("confidence") or row.get("long_conf") or row.get("nn_score") or 0)))
    expected_move = float(row.get("expected_move") or row.get("long_move") or 0)
    values = row.get("signal_values") or row.get("values") or {}
    scores = row.get("signal_scores") or row.get("scores") or {}
    context = row.get("context_json") or {}
    volume = (
        values.get("volume_surge")
        if isinstance(values, dict) and values.get("volume_surge") is not None
        else row.get("vol_ratio") or row.get("volume_ratio") or 1
    )
    try:
        volume = float(volume or 1)
    except Exception:
        volume = 1.0
    price = float(row.get("price") or row.get("open_price") or 0)
    earnings_soon = bool(row.get("earnings_soon") or context.get("earnings_soon"))
    reasons = []
    passes = []
    if ticker in open_tickers:
        reasons.append("Already open, so it is hidden from fresh picks.")
    else:
        passes.append("No open position blocked it.")
    if price <= 0:
        reasons.append("No valid price was available.")
    else:
        passes.append(f"Valid price: ${price:.2f}.")
    if confidence < confidence_floor:
        reasons.append(f"Confidence {confidence}% is below the {confidence_floor}% pick floor.")
    else:
        passes.append(f"Confidence {confidence}% clears the {confidence_floor}% floor.")
    if expected_move < MIN_EXPECTED_MOVE:
        reasons.append(f"Expected move {expected_move:.1f}% is below the {MIN_EXPECTED_MOVE:.1f}% minimum.")
    else:
        passes.append(f"Expected move {expected_move:.1f}% clears the minimum.")
    if volume >= MIN_VOLUME_RATIO:
        passes.append(f"Volume ratio {volume:.2f}x clears the minimum.")
    else:
        passes.append(f"Volume ratio {volume:.2f}x is weak/neutral; it lowers score but no longer hard-blocks premarket picks.")
    if earnings_soon:
        reasons.append("Earnings are too close, so the setup is blocked.")
    else:
        passes.append("No near-term earnings block.")
    fired = row.get("fired_signals") or []
    if isinstance(fired, str):
        try:
            fired = json.loads(fired or "[]")
        except Exception:
            fired = []
    if not fired and isinstance(scores, dict):
        fired = [k for k, v in scores.items() if float(v or 0) >= 0.65]
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "passes": passes,
        "confidence": confidence,
        "confidence_floor": confidence_floor,
        "expected_move": expected_move,
        "expected_move_floor": MIN_EXPECTED_MOVE,
        "volume_ratio": volume,
        "volume_floor": MIN_VOLUME_RATIO,
        "price": price,
        "fired_signals": fired,
    }

def variant_investment_amount(portfolio):
    """Small starting allocation that compounds independently per universe."""
    equity = float(portfolio.get("equity") or 1000.0)
    cash = float(portfolio.get("cash") or equity)
    amount = max(1.0, round(equity * 0.01, 2))
    return min(amount, max(cash, 0.0))

def variant_open_position_cap(variant):
    mode = (variant.get("selection_mode") or "All").lower().replace(" ", "")
    if mode in ("top1", "1"):
        return 1
    if mode in ("top3", "3"):
        return 3
    return MAX_ALL_VARIANT_OPEN_POSITIONS

def update_variant_portfolio(database, variant_id, note="snapshot"):
    """Recalculate portfolio equity and lifecycle recommendation for one universe."""
    portfolio = database.execute("SELECT * FROM variant_portfolios WHERE variant_id=?", [variant_id]).fetchone()
    if not portfolio:
        return None
    open_rows = [dict(r) for r in database.execute(
        "SELECT * FROM variant_virtual_trades WHERE variant_id=? AND outcome='open'", [variant_id]
    ).fetchall()]
    closed_rows = [dict(r) for r in database.execute(
        "SELECT * FROM variant_virtual_trades WHERE variant_id=? AND outcome!='open' AND outcome NOT IN ('archived_excess_open')", [variant_id]
    ).fetchall()]
    starting_cash = float(portfolio["starting_cash"] or 1000.0)
    open_invested = sum(float(r.get("invested_amount") or 0) for r in open_rows)
    open_value = sum(float(r.get("current_value") or r.get("invested_amount") or 0) for r in open_rows)
    realized_pnl = sum(float(r.get("net_pnl") if r.get("net_pnl") is not None else r.get("gross_pnl") or 0) for r in closed_rows)
    cash = round(starting_cash + realized_pnl - open_invested, 4)
    equity = round(cash + open_value, 4)
    max_equity = max(float(portfolio["max_equity"] or 1000.0), equity)
    drawdown = 0.0 if max_equity <= 0 else round((max_equity - equity) / max_equity * 100, 2)
    wins = [r for r in closed_rows if float(r.get("actual_move") or 0) > 0]
    losses = [r for r in closed_rows if float(r.get("actual_move") or 0) <= 0]
    recommended_status, reasons = recommend_variant_lifecycle(
        closed_count=len(closed_rows),
        win_count=len(wins),
        equity=equity,
        max_drawdown_pct=drawdown,
    )
    now = current_time_cst().isoformat()
    database.execute("""
        UPDATE variant_portfolios
        SET cash=?, equity=?, open_value=?, realized_pnl=?, open_count=?, closed_count=?,
            win_count=?, loss_count=?, max_equity=?, max_drawdown_pct=?,
            recommended_status=?, lifecycle_reasons=?, updated_at=?
        WHERE variant_id=?
    """, [cash, equity, round(open_value, 4), round(realized_pnl, 4), len(open_rows), len(closed_rows),
          len(wins), len(losses), max_equity, drawdown, recommended_status, json.dumps(reasons), now, variant_id])
    point_id = f"{variant_id}_{int(time.time())}_{note}"
    database.execute("""
        INSERT OR REPLACE INTO variant_equity_points
        (id, variant_id, timestamp, equity, cash, open_value, realized_pnl, open_count, closed_count, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [point_id, variant_id, now, equity, cash, round(open_value, 4), round(realized_pnl, 4),
          len(open_rows), len(closed_rows), note])
    if reasons:
        database.execute("""
            INSERT OR REPLACE INTO variant_lifecycle_reviews
            (id, variant_id, timestamp, recommended_status, current_status, reasons, metrics_json, applied)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, [
            f"{variant_id}_{recommended_status}_{current_time_cst().strftime('%Y%m%d')}",
            variant_id, now, recommended_status, portfolio["lifecycle_status"],
            json.dumps(reasons),
            json.dumps({"closed_count": len(closed_rows), "win_count": len(wins), "equity": equity, "max_drawdown_pct": drawdown}),
        ])
    return {
        "variant_id": variant_id,
        "equity": equity,
        "open_count": len(open_rows),
        "closed_count": len(closed_rows),
        "recommended_status": recommended_status,
        "lifecycle_reasons": reasons,
    }

def classify_variant_equity_point(point):
    """Classify a variant equity point by source so charts do not infer from raw notes."""
    note = str((point or {}).get("note") or "").lower()
    if note == "seed":
        return "seed"
    if any(token in note for token in ("reprice", "repair", "backfill")):
        return "maintenance"
    if note == "eod_snapshot":
        return "eod"
    if note.startswith("monitor"):
        return "monitor"
    if note == "detail_refresh":
        return "monitor"
    if note.startswith("run_"):
        return "trade_execution"
    if note.startswith("no_strategy_picks"):
        return "evaluation"
    return "market"

def decorate_variant_equity_point(point):
    """Attach glass-house metadata to a variant equity point without mutating storage."""
    decorated = dict(point or {})
    point_type = classify_variant_equity_point(decorated)
    decorated["point_type"] = point_type
    decorated["chart_eligible"] = point_type != "maintenance"
    decorated["is_market_performance"] = point_type in {"monitor", "eod", "trade_execution", "market"}
    return decorated

def recommend_variant_lifecycle(closed_count, win_count, equity, max_drawdown_pct):
    """Deterministic lifecycle flags; Aegis explains, user approves movement."""
    reasons = []
    win_rate = (win_count / closed_count * 100) if closed_count else None
    status = "active"
    if closed_count >= 75 and (win_rate < 38 or equity < 750 or max_drawdown_pct > 25):
        status = "archive_candidate"
    elif closed_count >= 50 and (win_rate < 40 or equity < 825 or max_drawdown_pct > 18):
        status = "benched_recommended"
    elif closed_count >= 30 and (win_rate < 45 or equity < 900 or max_drawdown_pct > 12):
        status = "watchlist"
    if win_rate is not None:
        if closed_count >= 75 and win_rate < 38:
            reasons.append(f"win rate {win_rate:.1f}% below 38% after {closed_count} trades")
        elif closed_count >= 50 and win_rate < 40:
            reasons.append(f"win rate {win_rate:.1f}% below 40% after {closed_count} trades")
        elif closed_count >= 30 and win_rate < 45:
            reasons.append(f"win rate {win_rate:.1f}% below 45% after {closed_count} trades")
    if equity < 750 and closed_count >= 75:
        reasons.append("equity below $750")
    elif equity < 825 and closed_count >= 50:
        reasons.append("equity below $825")
    elif equity < 900 and closed_count >= 30:
        reasons.append("equity below $900")
    if max_drawdown_pct > 25 and closed_count >= 75:
        reasons.append("drawdown above 25%")
    elif max_drawdown_pct > 18 and closed_count >= 50:
        reasons.append("drawdown above 18%")
    elif max_drawdown_pct > 12 and closed_count >= 30:
        reasons.append("drawdown above 12%")
    return status, reasons


def _provider_quote(provider, ticker):
    """Fetch one quote and classify failures for the fallback router."""
    try:
        import urllib.parse
        import urllib.request
        provider = provider.lower()
        if provider in ("massive", "polygon"):
            if not MASSIVE_API_KEY:
                return None, "disabled", "missing MASSIVE_API_KEY", True
            params = urllib.parse.urlencode({
                "ticker": ticker,
                "type": "stocks",
                "limit": 1,
                "apiKey": MASSIVE_API_KEY,
            })
            urls = [
                f"{MASSIVE_BASE}/v3/snapshot?{params}",
                f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{urllib.parse.quote(ticker)}?apiKey={urllib.parse.quote(MASSIVE_API_KEY)}",
            ]
            last_error = None
            for url in urls:
                try:
                    with urllib.request.urlopen(url, timeout=8) as resp:
                        data = json.loads(resp.read())
                except Exception as exc:
                    last_error = exc
                    continue

                status_text = str(data.get("status") or data.get("error") or "").lower()
                if data.get("error") or status_text in ("error", "auth_failed"):
                    message = data.get("error") or data.get("message") or data.get("status")
                    failure = "rate_limit" if "limit" in str(message).lower() else "bad_response"
                    return None, failure, message, failure != "bad_response"

                snapshot = None
                results = data.get("results")
                if isinstance(results, list) and results:
                    snapshot = results[0]
                elif isinstance(results, dict):
                    snapshot = results
                elif isinstance(data.get("ticker"), dict):
                    snapshot = data["ticker"]
                elif any(isinstance(data.get(key), dict) for key in ("session", "day", "prevDay", "lastTrade")):
                    snapshot = data
                if not snapshot:
                    continue

                session = snapshot.get("session") or {}
                day = snapshot.get("day") or {}
                minute = snapshot.get("minute") or snapshot.get("min") or {}
                previous_day = snapshot.get("prevDay") or snapshot.get("prev_day") or {}
                last_trade = snapshot.get("lastTrade") or snapshot.get("last_trade") or {}
                last_quote = snapshot.get("lastQuote") or snapshot.get("last_quote") or {}

                price = _first_number(
                    session.get("price"),
                    snapshot.get("value"),
                    last_trade.get("p"),
                    last_trade.get("price"),
                    minute.get("c"),
                    minute.get("close"),
                    day.get("c"),
                    day.get("close"),
                    last_quote.get("p"),
                    last_quote.get("price"),
                )
                if not price:
                    continue
                previous_close = _first_number(
                    session.get("previous_close"),
                    previous_day.get("c"),
                    previous_day.get("close"),
                    day.get("vw"),
                    price,
                )
                open_price = _first_number(session.get("open"), day.get("o"), day.get("open"), price)
                high = _first_number(session.get("high"), day.get("h"), day.get("high"), price)
                low = _first_number(session.get("low"), day.get("l"), day.get("low"), price)
                quote = _normalize_quote(price, previous_close, open_price, high, low, "massive")
                volume = _first_number(session.get("volume"), day.get("v"), day.get("volume"), minute.get("v"))
                if volume is not None:
                    quote["volume"] = volume
                return quote, None, None, False

            if last_error:
                raise last_error
            return None, "missing", "no massive snapshot price", False

        if provider == "finnhub":
            if not FINNHUB_KEY:
                return None, "disabled", "missing FINNHUB_KEY", True
            url = f"{FINNHUB_BASE}/quote?symbol={ticker}&token={FINNHUB_KEY}"
            with urllib.request.urlopen(url, timeout=8) as resp:
                data = json.loads(resp.read())
            if data.get("error"):
                failure = "rate_limit" if "limit" in str(data.get("error")).lower() else "bad_response"
                return None, failure, data.get("error"), failure != "bad_response"
            price = data.get("c", 0)
            if not price:
                return None, "missing", "no current price", False
            return _normalize_quote(
                price,
                previous_close=data.get("pc", price),
                open_price=data.get("o", price),
                high=data.get("h", price),
                low=data.get("l", price),
                source="finnhub",
            ), None, None, False

        if provider == "alpha_vantage":
            if not ALPHA_VANTAGE_KEY:
                return None, "disabled", "missing ALPHA_VANTAGE_KEY", True
            params = urllib.parse.urlencode({
                "function": "GLOBAL_QUOTE",
                "symbol": ticker,
                "apikey": ALPHA_VANTAGE_KEY,
            })
            with urllib.request.urlopen(f"https://www.alphavantage.co/query?{params}", timeout=12) as resp:
                data = json.loads(resp.read())
            note = data.get("Note") or data.get("Information")
            if note:
                failure = "rate_limit" if "rate" in str(note).lower() or "standard api call" in str(note).lower() else "bad_response"
                return None, failure, note, True
            quote = data.get("Global Quote") or {}
            price = quote.get("05. price")
            if not price:
                return None, "missing", "no global quote", False
            prev = quote.get("08. previous close") or price
            open_value = quote.get("02. open") or price
            high = quote.get("03. high") or price
            low = quote.get("04. low") or price
            return _normalize_quote(price, prev, open_value, high, low, "alpha_vantage"), None, None, False

        if provider == "twelve_data":
            if not TWELVE_DATA_KEY:
                return None, "disabled", "missing TWELVE_DATA_KEY", True
            params = urllib.parse.urlencode({"symbol": ticker, "apikey": TWELVE_DATA_KEY})
            with urllib.request.urlopen(f"{TWELVE_DATA_BASE}/quote?{params}", timeout=12) as resp:
                data = json.loads(resp.read())
            if data.get("status") == "error":
                msg = data.get("message", "twelve data error")
                failure = "rate_limit" if "limit" in msg.lower() else "bad_response"
                return None, failure, msg, failure != "bad_response"
            price = data.get("close") or data.get("price")
            if not price:
                return None, "missing", "no quote price", False
            return _normalize_quote(
                price,
                previous_close=data.get("previous_close") or data.get("close"),
                open_price=data.get("open") or price,
                high=data.get("high") or price,
                low=data.get("low") or price,
                source="twelve_data",
            ), None, None, False
    except TimeoutError as exc:
        return None, "timeout", str(exc), True
    except Exception as exc:
        error_text = str(exc)
        failure = "timeout" if "timed out" in error_text.lower() else "network"
        return None, failure, error_text, failure == "timeout"
    return None, "disabled", f"unknown provider {provider}", True

def fetch_quote_with_fallback(ticker, cycle=None, use_cache=True):
    """
    Frugal quote router: cache first, then ranked providers with per-cycle
    provider health memory. Fallback is ticker-level unless the provider has
    a global failure such as auth/rate-limit/timeout.
    """
    if use_cache:
        cached = _read_quote_cache(ticker)
        if cached:
            return cached

    cycle = cycle or ProviderCycle("quote")
    health = get_provider_health_map()
    layers_used = 0
    for provider in PROVIDER_CHAIN:
        if layers_used >= cycle.max_layers:
            break
        if provider in cycle.unhealthy or not provider_is_available(provider, health):
            continue
        layers_used += 1
        quote, failure_type, error, global_failure = _provider_quote(provider, ticker)
        if quote:
            cycle.record(provider, True)
            _write_quote_cache(ticker, quote)
            return quote
        cycle.record(provider, False, failure_type=failure_type, error=error, global_failure=global_failure)
    return None

def fetch_finnhub_quote(ticker):
    """
    Fetch a single quote from Finnhub.
    Returns {"price", "open", "previous_close", "high", "low", "day_change_percent"} or None.
    """
    if not FINNHUB_KEY:
        return None
    try:
        import urllib.request
        url = f"{FINNHUB_BASE}/quote?symbol={ticker}&token={FINNHUB_KEY}"
        with urllib.request.urlopen(url, timeout=8) as resp:
            d = json.loads(resp.read())
        price = d.get("c", 0)
        prev = d.get("pc", price)
        if not price or price == 0:
            return None
        return {
            "price": float(price),
            "open": float(d.get("o", price)),
            "previous_close": float(prev),
            "high": float(d.get("h", price)),
            "low": float(d.get("l", price)),
            "volume": 0,
            "average_volume": 1,
            "volume_ratio": 1.0,
            "gap_percent": (float(d.get("o", price)) - float(prev)) / max(float(prev), 0.01) * 100,
            "day_change_percent": (float(price) - float(prev)) / max(float(prev), 0.01) * 100,
            "source": "finnhub",
            "52w_high": None,
            "broke_52w_high_days_ago": None,
            "daily_history": [],
        }
    except Exception as e:
        log.debug(f"Finnhub quote error {ticker}: {e}")
        return None


def fetch_finnhub_candles(ticker, days=60):
    """
    Fetch daily OHLCV candles from Finnhub for history/RSI/confluence.
    Uses /stock/candle endpoint with resolution=D.
    Returns list of {high, low, close, open, volume} dicts oldest-first.
    """
    if not FINNHUB_KEY:
        return []
    try:
        import urllib.request, time as _time
        now_ts = int(__import__("datetime").datetime.now().timestamp())
        from_ts = now_ts - (days * 86400)
        url = (f"{FINNHUB_BASE}/stock/candle"
               f"?symbol={ticker}&resolution=D&from={from_ts}&to={now_ts}&token={FINNHUB_KEY}")
        with urllib.request.urlopen(url, timeout=8) as resp:
            d = json.loads(resp.read())
        if d.get("s") != "ok":
            return []
        closes = d.get("c", [])
        opens = d.get("o", [])
        highs = d.get("h", [])
        lows = d.get("l", [])
        volumes = d.get("v", [])
        timestamps = d.get("t", [])
        history = []
        for i in range(len(closes)):
            ts = int(timestamps[i]) if i < len(timestamps) else None
            history.append({
                "close": float(closes[i]),
                "open": float(opens[i]) if i < len(opens) else float(closes[i]),
                "high": float(highs[i]) if i < len(highs) else float(closes[i]),
                "low": float(lows[i]) if i < len(lows) else float(closes[i]),
                "volume": float(volumes[i]) if i < len(volumes) else 0,
                "timestamp": ts,
                "date": datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else None,
            })
        return history
    except Exception as e:
        log.debug(f"Finnhub candles error {ticker}: {e}")
        return []

def fetch_massive_price_at_cst(ticker, target_dt_cst, multiplier=5, timespan="minute"):
    """
    Fetch the aggregate-bar open nearest to a Central-time execution slot.

    Massive is the preferred historical entry source when configured because
    wrong simulated entry prices poison P&L, win rate, and learning data.
    """
    if not MASSIVE_API_KEY:
        return None
    try:
        import urllib.parse
        import urllib.request

        central_aware = target_dt_cst.replace(tzinfo=ZoneInfo("America/Chicago"))
        target_utc = central_aware.astimezone(ZoneInfo("UTC"))
        target_ms = int(target_utc.timestamp() * 1000)
        from_ms = int((target_utc - timedelta(minutes=45)).timestamp() * 1000)
        to_ms = int((target_utc + timedelta(minutes=45)).timestamp() * 1000)
        encoded_ticker = urllib.parse.quote(ticker.upper())
        params = urllib.parse.urlencode({
            "adjusted": "false",
            "sort": "asc",
            "limit": 5000,
            "apiKey": MASSIVE_API_KEY,
        })
        url = (
            f"{MASSIVE_BASE}/v2/aggs/ticker/{encoded_ticker}/range/"
            f"{multiplier}/{timespan}/{from_ms}/{to_ms}?{params}"
        )
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())

        status_text = str(data.get("status") or data.get("error") or "").lower()
        if data.get("error") or status_text in ("error", "auth_failed"):
            log.debug(f"Massive aggregate error {ticker}: {data.get('error') or data.get('message') or data.get('status')}")
            return None

        bars = data.get("results") or []
        if not bars:
            return None

        def bar_time_ms(row):
            return int(row.get("t") or row.get("timestamp") or 0)

        best = min(bars, key=lambda row: abs(bar_time_ms(row) - target_ms))
        best_ms = bar_time_ms(best)
        if not best_ms or abs(best_ms - target_ms) > 45 * 60 * 1000:
            return None

        price = _first_number(best.get("o"), best.get("open"), best.get("c"), best.get("close"))
        if price is None:
            return None
        return {
            "price": float(price),
            "timestamp": int(best_ms / 1000),
            "source": f"massive_{multiplier}m_candle",
        }
    except Exception as e:
        log.debug(f"Massive intraday price error {ticker}: {e}")
        return None

def fetch_finnhub_price_at_cst(ticker, target_dt_cst, resolution="5"):
    """
    Fetch the intraday candle open nearest to a target CST/CDT time.
    Used for virtual entry prices, especially the 8:45 AM execution price.
    """
    if not FINNHUB_KEY:
        return None
    try:
        import urllib.request
        # Localize naive Central time to proper timezone, then convert to UTC
        central_aware = target_dt_cst.replace(tzinfo=ZoneInfo("America/Chicago"))
        target_utc = central_aware.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        from_ts = int((target_utc - timedelta(minutes=15)).timestamp())
        to_ts = int((target_utc + timedelta(minutes=20)).timestamp())
        target_ts = int(target_utc.timestamp())
        url = (f"{FINNHUB_BASE}/stock/candle"
               f"?symbol={ticker}&resolution={resolution}&from={from_ts}&to={to_ts}&token={FINNHUB_KEY}")
        with urllib.request.urlopen(url, timeout=8) as resp:
            d = json.loads(resp.read())
        if d.get("s") != "ok":
            return None

        times = d.get("t", [])
        opens = d.get("o", [])
        closes = d.get("c", [])
        if not times:
            return None

        best_idx = min(range(len(times)), key=lambda i: abs(int(times[i]) - target_ts))
        price = opens[best_idx] if best_idx < len(opens) and opens[best_idx] else closes[best_idx]
        return {
            "price": float(price),
            "timestamp": int(times[best_idx]),
            "source": f"finnhub_{resolution}m_candle",
        }
    except Exception as e:
        log.debug(f"Finnhub intraday price error {ticker}: {e}")
        return None

def fetch_alpha_vantage_price_at_cst(ticker, target_dt_cst, interval="5min"):
    """
    Fetch the intraday candle open nearest to a target CST/CDT time using Alpha Vantage.
    Alpha Vantage intraday timestamps are US/Eastern for US equities.
    """
    if not ALPHA_VANTAGE_KEY:
        return None
    try:
        import urllib.parse
        import urllib.request
        target_et = target_dt_cst + timedelta(hours=1)
        target_ts = target_et.timestamp()
        params = urllib.parse.urlencode({
            "function": "TIME_SERIES_INTRADAY",
            "symbol": ticker,
            "interval": interval,
            "outputsize": "compact",
            "apikey": ALPHA_VANTAGE_KEY,
        })
        url = f"https://www.alphavantage.co/query?{params}"
        with urllib.request.urlopen(url, timeout=12) as resp:
            d = json.loads(resp.read())

        series = d.get(f"Time Series ({interval})") or {}
        if not series:
            return None

        best_time = None
        best_row = None
        best_delta = None
        for ts_str, row in series.items():
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            delta = abs(ts.timestamp() - target_ts)
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_time = ts
                best_row = row

        if not best_row or best_delta is None or best_delta > 30 * 60:
            return None

        price = best_row.get("1. open") or best_row.get("4. close")
        if price is None:
            return None
        return {
            "price": float(price),
            "timestamp": best_time.isoformat(),
            "source": f"alpha_vantage_{interval}_candle",
        }
    except Exception as e:
        log.debug(f"Alpha Vantage intraday price error {ticker}: {e}")
        return None

def fetch_yfinance_price_at_cst(ticker, target_dt_cst, interval="5m"):
    """
    Fetch the recent intraday candle open nearest to a Central-time target.

    yfinance is a repair fallback, not the primary live quote source. It is
    useful here because it can return recent pre/post-market 5-minute candles
    when the direct provider candle endpoints miss an entry timestamp.
    """
    try:
        import yfinance as yf
        central_aware = target_dt_cst.replace(tzinfo=ZoneInfo("America/Chicago"))
        target_utc = central_aware.astimezone(ZoneInfo("UTC"))
        start = (target_utc - timedelta(hours=1)).date().isoformat()
        end = (target_utc + timedelta(days=1)).date().isoformat()
        frame = yf.download(
            ticker,
            start=start,
            end=end,
            interval=interval,
            prepost=True,
            auto_adjust=True,
            progress=False,
        )
        if frame is None or frame.empty:
            return None

        def row_value(row, field):
            value = row.get(field)
            if hasattr(value, "iloc"):
                value = value.iloc[0]
            return value

        best_index = min(frame.index, key=lambda ts: abs(ts.to_pydatetime() - target_utc))
        row = frame.loc[best_index]
        price = row_value(row, "Open") or row_value(row, "Close")
        if price is None:
            return None
        return {
            "price": float(price),
            "timestamp": int(best_index.timestamp()),
            "source": f"yfinance_{interval}_candle",
        }
    except Exception as e:
        log.debug(f"yfinance intraday price error {ticker}: {e}")
        return None


def fetch_entry_price_at_cst(ticker, target_dt_cst, cycle=None):
    """
    Resolve a simulated trade entry from the candle nearest its intended
    Central-time execution slot.

    Entry price is ledger-critical: if this is wrong, open P&L, account value,
    win rate, and learning data all become untrustworthy. Prefer historical
    intraday candles, then fall back to an uncached live quote only when the
    trade is being opened at that moment and no candle provider has coverage.
    """
    pinned = (
        fetch_massive_price_at_cst(ticker, target_dt_cst)
        or fetch_finnhub_price_at_cst(ticker, target_dt_cst)
        or fetch_alpha_vantage_price_at_cst(ticker, target_dt_cst)
        or fetch_yfinance_price_at_cst(ticker, target_dt_cst)
    )
    if pinned:
        return {
            "price": pinned["price"],
            "day_change_pct": 0,
            "day_change_percent": 0,
            "source": pinned.get("source", "historical_entry_candle"),
            "timestamp": pinned.get("timestamp"),
        }

    quote = fetch_quote_with_fallback(ticker, cycle=cycle, use_cache=False)
    if not quote:
        return None

    fallback_price = quote.get("price") or quote.get("open")
    if not fallback_price:
        return None

    return {
        **quote,
        "price": float(fallback_price),
        "source": f"{quote.get('source', 'provider')}_live_entry_fallback",
    }


def fetch_entry_prices_at_cst(tickers, target_dt_cst):
    """
    Batch wrapper for simulated entry prices. Intentionally rate-limited because
    it may touch several providers while protecting ledger correctness.
    """
    if not tickers:
        return {}

    cycle = ProviderCycle("entry_price")
    results = {}
    for ticker in tickers:
        entry_quote = fetch_entry_price_at_cst(ticker, target_dt_cst, cycle=cycle)
        if entry_quote:
            results[ticker] = entry_quote
        time.sleep(1.1)
    set_app_state("last_price_provider_summary", json.dumps(cycle.summary()))
    return results

def fetch_twelve_data_batch(tickers, interval="1day", outputsize=60):
    """
    Fetch OHLCV + history for multiple tickers.
    Uses Finnhub candles endpoint — one call per ticker with rate limiting.
    Returns {ticker: {price, open, previous_close, high, low, volume, 
                       average_volume, volume_ratio, gap_percent, 
                       day_change_percent, daily_history}}
    """
    results = {}
    cycle = ProviderCycle("daily_quote_batch")
    RATE_LIMIT_DELAY = 1.1  # 60 calls/min = 1 call/sec + small buffer

    for ticker in tickers:
        # First get current quote
        quote = fetch_quote_with_fallback(ticker, cycle=cycle, use_cache=True)
        if quote is None:
            time.sleep(RATE_LIMIT_DELAY)
            continue

        # Then get candle history for RSI + confluence
        time.sleep(RATE_LIMIT_DELAY)
        history = fetch_finnhub_candles(ticker, days=outputsize)
        quote["daily_history"] = history

        # Compute average volume from history
        if history:
            vols = [h["volume"] for h in history if h["volume"] > 0]
            avg_vol = sum(vols) / max(len(vols), 1)
            quote["average_volume"] = avg_vol
            quote["volume"] = history[-1]["volume"] if history else 0
            quote["volume_ratio"] = quote["volume"] / max(avg_vol, 1)

        results[ticker] = quote
        time.sleep(RATE_LIMIT_DELAY)

    log.info(f"Price providers returned {len(results)}/{len(tickers)} tickers")
    return results


def fetch_twelve_data_live(tickers):
    """
    Fetch real-time quotes for monitoring — Finnhub /quote endpoint.
    One call per ticker with rate limiting (60/min free tier).
    Returns {ticker: {"price", "day_change_pct", "open", "previous_close",
                       "gap_percent", "high", "low"}}
    Volume is not available from Finnhub /quote — enriched separately from candle cache.
    """
    results = {}
    RATE_LIMIT_DELAY = 1.1

    for ticker in tickers:
        quote = fetch_quote_with_fallback(ticker, use_cache=True)
        if quote:
            results[ticker] = {
                "price": quote["price"],
                "day_change_pct": quote["day_change_percent"],
                "day_change_percent": quote["day_change_percent"],
                "open": quote.get("open", quote["price"]),
                "previous_close": quote.get("previous_close", quote["price"]),
                "gap_percent": quote.get("gap_percent", 0),
                "high": quote.get("high", quote["price"]),
                "low": quote.get("low", quote["price"]),
            }
        time.sleep(RATE_LIMIT_DELAY)

    # Enrich with volume from candle cache where available
    try:
        cached_raw = None
        db = get_database()
        row = db.execute("SELECT value FROM app_state WHERE key='price_cache'").fetchone()
        if row:
            cached_raw = json.loads(row["value"])
        db.close()
        if cached_raw:
            for ticker in results:
                cached = cached_raw.get(ticker, {})
                hist = cached.get("daily_history", [])
                if hist:
                    latest = hist[-1]
                    vol = latest.get("volume", 0)
                    avg_vol = sum(h.get("volume", 0) for h in hist[-20:]) / max(len(hist[-20:]), 1)
                    results[ticker]["volume"] = vol
                    results[ticker]["average_volume"] = max(avg_vol, 1)
                    results[ticker]["volume_ratio"] = vol / max(avg_vol, 1) if avg_vol > 0 else 1.0
    except Exception as e:
        log.debug(f"Volume enrichment skipped: {e}")

    log.info(f"Live price providers: {len(results)}/{len(tickers)} tickers")
    return results


def fetch_price_data(tickers, scan_event_id=None, scan_type=None):
    """
    Fetch daily OHLCV price data for scanning and scoring.
    
    Cache-first strategy:
    - Loads fresh tickers from app_state cache first
    - Fetches fresh quotes for tickers missing a fresh cache row
    - Full candle history fetched only for top candidates (those with gap/volume signal)
    - Cache is refreshed incrementally — 60 tickers per scan cycle max
    
    This keeps Finnhub calls well within 60/min free tier across scan cycles.
    """
    if not tickers:
        return {}

    log.info(f"Fetching price data for {len(tickers)} tickers...")

    # Load fresh cached prices first. Rows without fetched_at are stale because
    # stale previous_close values corrupt %CHG and gap math.
    results = {}
    max_cache_age_seconds = int(os.getenv("SCAN_PRICE_CACHE_SECONDS", "900"))

    try:
        database = get_database()
        for ticker in tickers:
            cached = database.execute(
                "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
            ).fetchone()
            if cached:
                try:
                    payload = json.loads(cached["value"])
                    if isinstance(payload, dict) and "data" in payload:
                        fetched_at = datetime.fromisoformat(payload.get("fetched_at"))
                        if (current_time_cst() - fetched_at).total_seconds() > max_cache_age_seconds:
                            continue
                        data = payload.get("data") or {}
                        data["cached_at"] = payload.get("fetched_at")
                    else:
                        continue
                    results[ticker] = data
                except:
                    pass
        database.close()
    except Exception as e:
        log.debug(f"Cache load error: {e}")

    log.info(f"Cache hit: {len(results)}/{len(tickers)} tickers")

    # Fetch fresh quotes for missing or stale tickers — max 60 per cycle
    missing = [t for t in tickers if t not in results]
    refresh_limit = int(os.getenv("SCAN_PRICE_REFRESH_LIMIT", str(len(missing))))
    to_refresh = missing[:refresh_limit]

    if to_refresh:
        log.info(f"Refreshing {len(to_refresh)} tickers from Finnhub...")
        RATE_DELAY = 2.2
        cycle = ProviderCycle("comprehensive_quote")
        refreshed_tickers = []
        for idx, ticker in enumerate(to_refresh, start=1):
            if scan_event_id and (idx == 1 or idx % 5 == 0 or idx == len(to_refresh)):
                record_nn_scan_status(
                    status="running",
                    scan_type=scan_type,
                    phase="fetching_prices",
                    scan_event_id=scan_event_id,
                    total_scanned=len(results),
                    total_expected=len(tickers),
                    current_ticker=ticker,
                    scanned_tickers=refreshed_tickers[-12:],
                )
            quote = fetch_quote_with_fallback(ticker, cycle=cycle, use_cache=False)
            if quote:
                results[ticker] = quote
                refreshed_tickers.append(ticker)
                # Fetch candle history for fresh tickers
                history = fetch_finnhub_candles(ticker, days=60)
                if history:
                    results[ticker]["daily_history"] = history
                    repair_quote_baselines_from_history(results[ticker], history)
                    vols = [h["volume"] for h in history if h["volume"] > 0]
                    if vols:
                        avg_vol = sum(vols) / len(vols)
                        results[ticker]["average_volume"] = avg_vol
                        results[ticker]["volume_ratio"] = quote.get("volume", 0) / max(avg_vol, 1)
                # Cache it
                try:
                    database = get_database()
                    cache_data = dict(results[ticker])
                    database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                                     [f"cache_{ticker}", json.dumps({
                                         "fetched_at": current_time_cst().isoformat(),
                                         "data": cache_data,
                                     })])
                    database.commit()
                    database.close()
                except:
                    pass
            if scan_event_id and (idx == 1 or idx % 5 == 0 or idx == len(to_refresh)):
                record_nn_scan_status(
                    status="running",
                    scan_type=scan_type,
                    phase="fetching_prices",
                    scan_event_id=scan_event_id,
                    total_scanned=len(results),
                    total_expected=len(tickers),
                    current_ticker=ticker,
                    scanned_tickers=refreshed_tickers[-12:],
                )
            time.sleep(RATE_DELAY)
        set_app_state("last_price_provider_summary", json.dumps(cycle.summary()))

    log.info(f"fetch_price_data complete: {len(results)}/{len(tickers)} tickers")
    return results

def fetch_current_prices(tickers, pin_to_845=False):
    """
    Fetch current prices for monitoring, or true 8:45 AM candle entries.
    Returns {ticker: {"price": float, "day_change_pct": float}}.
    """
    if not tickers:
        return {}

    cycle = ProviderCycle("entry_pin" if pin_to_845 else "current_prices")

    if pin_to_845:
        results = {}
        target = current_time_cst().replace(hour=8, minute=45, second=0, microsecond=0)
        for ticker in tickers:
            pinned = fetch_entry_price_at_cst(ticker, target, cycle=cycle)
            if pinned:
                results[ticker] = pinned
            else:
                quote = fetch_quote_with_fallback(ticker, cycle=cycle, use_cache=False)
                if quote:
                    results[ticker] = {
                        "price": quote.get("open", quote["price"]),
                        "day_change_pct": 0,
                        "source": f"{quote.get('source', 'provider')}_day_open_fallback",
                    }
            time.sleep(1.1)
        set_app_state("last_price_provider_summary", json.dumps(cycle.summary()))
        return results

    results = {}
    for ticker in tickers:
        quote = fetch_quote_with_fallback(ticker, cycle=cycle, use_cache=True)
        if quote:
            results[ticker] = quote
        time.sleep(0.15 if "cache" in str((quote or {}).get("source", "")) else 1.05)
    set_app_state("last_price_provider_summary", json.dumps(cycle.summary()))
    log.info(f"Price fallback router: {len(results)}/{len(tickers)} tickers | {cycle.summary()}")
    return results

def calculate_rsi_batch(tickers, period=14, price_data=None):
    """
    Calculate RSI for multiple tickers using Wilder's smoothed moving average.
    Uses daily_history already in price_data when available.
    Missing history defaults to neutral RSI instead of doing hundreds of
    per-ticker provider calls inside the scan hot path.

    Wilder's method: first avg is simple, subsequent values use exponential
    smoothing: avg = (prev_avg * (period-1) + current) / period
    This matches TradingView, Finviz, and all standard RSI implementations.
    """
    rsi_values = {}

    for ticker in tickers:
        try:
            # Use pre-fetched daily history if available
            history = None
            if price_data and ticker in price_data:
                history = price_data[ticker].get("daily_history")

            if not history or len(history) < period + 1:
                rsi_values[ticker] = 50.0
                continue

            closes = [h["close"] for h in history]
            changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [max(c, 0) for c in changes]
            losses = [max(-c, 0) for c in changes]

            # Wilder's smoothed RSI: seed with simple average, then smooth
            avg_gain = sum(gains[:period]) / period
            avg_loss = sum(losses[:period]) / period
            for i in range(period, len(gains)):
                avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i]) / period

            if avg_loss == 0:
                rsi_values[ticker] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_values[ticker] = round(100 - (100 / (1 + rs)), 2)
        except:
            rsi_values[ticker] = 50.0

    for ticker in tickers:
        if ticker not in rsi_values:
            rsi_values[ticker] = 50.0

    return rsi_values

def check_upcoming_earnings(tickers):
    """
    Identify tickers with earnings in the next 7 days.
    Uses Twelve Data earnings calendar endpoint.
    Returns a dict of {ticker: days_until_earnings} for graduated scoring.
    """
    earnings_soon = {}
    if not TWELVE_DATA_KEY:
        return earnings_soon
    try:
        import urllib.request
        today_str = current_time_cst().strftime("%Y-%m-%d")
        ahead = (current_time_cst() + timedelta(days=7)).strftime("%Y-%m-%d")
        url = (f"{TWELVE_DATA_BASE}/earnings_calendar"
               f"?start_date={today_str}&end_date={ahead}&apikey={TWELVE_DATA_KEY}")
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        for event in data.get("earnings", []):
            ticker = event.get("symbol", "")
            date_str = event.get("date", "")
            if ticker in tickers and date_str:
                try:
                    days_away = (datetime.strptime(date_str, "%Y-%m-%d") - datetime.now()).days
                    if 0 <= days_away <= 7:
                        earnings_soon[ticker] = days_away
                except:
                    pass
    except Exception as e:
        log.debug(f"Earnings calendar error: {e}")
    return earnings_soon

# ── 52-WEEK BREAKOUT DETECTION ────────────────────────────────────────────────
def check_52w_breakouts(tickers, price_data):
    """
    Detect tickers that have broken above their 52-week high within the last 7 days.
    Uses daily_history already fetched by Twelve Data — no extra API calls.
    """
    breakouts = {}
    for ticker in tickers:
        if ticker not in price_data:
            continue
        try:
            history = price_data[ticker].get("daily_history", [])
            if len(history) < 30:
                continue
            yearly_highs = [h["high"] for h in history]
            yearly_high = max(yearly_highs)
            current_price = price_data[ticker]["price"]
            # Check last 7 trading days for 52W breakout
            recent = history[-7:]
            for days_back, row in enumerate(reversed(recent)):
                if float(row["high"]) >= yearly_high * 0.995:
                    breakouts[ticker] = days_back + 1
                    price_data[ticker]["52w_high"] = round(yearly_high, 2)
                    price_data[ticker]["broke_52w_high_days_ago"] = days_back + 1
                    break
        except:
            pass
    return breakouts

def calculate_atr(daily_history, period=14):
    """
    Calculate Average True Range (ATR-14) from daily OHLCV history.
    ATR is the volatility ruler — it normalizes all price-based thresholds
    to the stock's actual daily movement, making S&R detection scale-invariant.

    True Range = max(High-Low, |High-PrevClose|, |Low-PrevClose|)
    ATR = EMA of True Range over `period` days
    """
    if not daily_history or len(daily_history) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(daily_history)):
        h = daily_history[i]["high"]
        l = daily_history[i]["low"]
        pc = daily_history[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        true_ranges.append(tr)
    if len(true_ranges) < period:
        return None
    # Seed with simple mean of first `period` values, then EMA forward
    atr = sum(true_ranges[:period]) / period
    multiplier = 2 / (period + 1)
    for tr in true_ranges[period:]:
        atr = tr * multiplier + atr * (1 - multiplier)
    return atr


def calculate_support_resistance(ticker, price_data):
    """
    Detect support and resistance zones using ATR-adaptive swing pivot clustering.

    Algorithm:
    1. Pull 60-day daily_history (already populated by enrich_price_data_with_history)
    2. Calculate ATR-14 as the volatility ruler
    3. Identify swing highs (high[i] > neighbors 2 each side) → resistance pivots
       Identify swing lows  (low[i]  < neighbors 2 each side) → support pivots
    4. Cluster pivots within 0.5×ATR of each other → zones with touch counts
    5. Score relative to current price and expected move:
       - Resistance zone within expected move above price  → mild negative (ceiling)
       - Clean breakout above all resistance (open air)    → mild positive
       - Support zone close below current price            → mild positive (floor)
       - Price sitting directly at resistance              → moderate negative
       - Price bouncing off support (near support now)     → mild positive
    6. Store result in price_data for use in scoring and method_signals logging

    Returns: {"score": float 0-1, "signal": str, "nearest_resistance": float|None,
              "nearest_support": float|None, "zone_count": int, "rationale": str}
    """
    DEFAULT = {"score": 0.5, "signal": "neutral", "nearest_resistance": None,
               "nearest_support": None, "zone_count": 0, "rationale": "insufficient data"}

    if ticker not in price_data:
        return DEFAULT

    data = price_data[ticker]
    history = data.get("daily_history", [])
    current_price = data.get("price", 0)
    expected_move_pct = data.get("expected_move_pct", 5.0)  # fallback 5%

    if len(history) < 15 or current_price <= 0:
        return DEFAULT

    atr = calculate_atr(history)
    if not atr or atr <= 0:
        return DEFAULT

    cluster_radius = atr * 0.5  # Two pivots within half an ATR → same zone

    # ── Swing pivot detection (2-neighbor rule each side) ──
    resistance_pivots = []
    support_pivots = []
    for i in range(2, len(history) - 2):
        h = history[i]["high"]
        l = history[i]["low"]
        # Swing high: higher than both neighbors on each side
        if (h > history[i-1]["high"] and h > history[i-2]["high"] and
                h > history[i+1]["high"] and h > history[i+2]["high"]):
            resistance_pivots.append(h)
        # Swing low: lower than both neighbors on each side
        if (l < history[i-1]["low"] and l < history[i-2]["low"] and
                l < history[i+1]["low"] and l < history[i+2]["low"]):
            support_pivots.append(l)

    def cluster_levels(pivots):
        """Group pivots within cluster_radius into zones. Returns list of (price, touch_count)."""
        if not pivots:
            return []
        sorted_pivots = sorted(pivots)
        zones = []
        current_group = [sorted_pivots[0]]
        for p in sorted_pivots[1:]:
            if p - current_group[0] <= cluster_radius:
                current_group.append(p)
            else:
                zone_price = sum(current_group) / len(current_group)
                zones.append((round(zone_price, 4), len(current_group)))
                current_group = [p]
        zone_price = sum(current_group) / len(current_group)
        zones.append((round(zone_price, 4), len(current_group)))
        return zones

    resistance_zones = cluster_levels(resistance_pivots)
    support_zones = cluster_levels(support_pivots)
    total_zones = len(resistance_zones) + len(support_zones)

    # Zones above and below current price
    zones_above = [(z, n) for z, n in resistance_zones if z > current_price]
    zones_below = [(z, n) for z, n in support_zones if z < current_price]

    nearest_resistance = min(zones_above, key=lambda x: x[0])[0] if zones_above else None
    nearest_support = max(zones_below, key=lambda x: x[0])[0] if zones_below else None

    # Expected move ceiling
    move_ceiling = current_price * (1 + expected_move_pct / 100)

    # ── Scoring logic ──
    score = 0.5
    signal = "neutral"
    rationale = "no clear S&R signal"

    if nearest_resistance is not None:
        dist_to_resistance = (nearest_resistance - current_price) / current_price * 100
        resistance_in_move_range = current_price < nearest_resistance <= move_ceiling
        sitting_at_resistance = dist_to_resistance < (atr / current_price * 100 * 0.3)

        if sitting_at_resistance:
            score = 0.2
            signal = "at_resistance"
            rationale = f"price at resistance ${nearest_resistance:.2f} — likely ceiling"
        elif resistance_in_move_range:
            score = 0.35
            signal = "resistance_in_range"
            rationale = f"resistance ${nearest_resistance:.2f} within expected move — may cap gains"
        elif dist_to_resistance > expected_move_pct * 1.5:
            # Resistance well beyond expected move — open air
            score = 0.75
            signal = "open_air"
            rationale = f"open air to ${nearest_resistance:.2f} — no overhead supply in range"
    else:
        # No resistance detected above — truly open air
        score = 0.80
        signal = "open_air"
        rationale = "no resistance detected above current price"

    # Support floor bonus (additive, capped at 1.0)
    if nearest_support is not None:
        dist_to_support = (current_price - nearest_support) / current_price * 100
        near_support = dist_to_support < (atr / current_price * 100 * 0.5)
        if near_support:
            score = min(score + 0.15, 0.90)
            signal = signal + "+support_floor"
            rationale += f" · near support ${nearest_support:.2f}"

    result = {
        "score": round(score, 4),
        "signal": signal,
        "nearest_resistance": nearest_resistance,
        "nearest_support": nearest_support,
        "zone_count": total_zones,
        "rationale": rationale,
    }
    # Store on price_data so calculate_confidence_score can read it without recomputing
    price_data[ticker]["sr_analysis"] = result
    return result


def calculate_method_confluence(ticker, price_data, scored_stocks=None):
    """
    Score a ticker against confluence methods and return agreement count.

    Confluence methods are descriptive tags: they show that a stock resembles
    a known setup. They are not automatically standalone strategies with their
    own independent entry/exit lifecycle. If a method later becomes a strategy,
    it must get a separate strategy audit and execution contract.

    Confluence methods:
    1.  Darvas Box          — near 52W high + volume + positive gap
    2.  Gap and Go          — gap up >2% + volume surge
    3.  Donchian Channel    — price above 20-day high
    4.  Inside Day          — today's range inside yesterday's + breaking up
    5.  Bull Flag           — strong prior move + tight consolidation
    6.  Pocket Pivot        — up day with volume > any down-day vol of last 10 days
    7.  Support & Resistance — ATR-adaptive zone analysis (open air or near support)
    8.  VWAP Reclaim        — closing above VWAP, institutional buy-side conviction
    9.  Volatility Squeeze  — HV compression ratio, coiled spring setup

    Returns: {"count": int, "methods": [list of method names that agree]}
    """
    if ticker not in price_data:
        return {"count": 0, "methods": []}

    data = price_data[ticker]
    price = data.get("price", 0)
    volume_ratio = data.get("volume_ratio", 1)
    gap_pct = data.get("gap_percent", 0)
    day_change = data.get("day_change_percent", 0)
    high = data.get("high", price)
    low = data.get("low", price)
    prev_close = data.get("previous_close", price)
    week_high = data.get("52w_high")
    daily_history = data.get("daily_history", [])  # List of {high, low, close, volume} dicts

    methods_agree = []

    # 1. Darvas Box
    if week_high and price >= week_high * 0.95 and volume_ratio >= 1.5 and gap_pct > 0:
        methods_agree.append("Darvas")

    # 2. Gap and Go
    if gap_pct >= 2.0 and volume_ratio >= 1.5 and day_change >= 0:
        methods_agree.append("Gap & Go")

    # 3. Donchian Channel — price above 20-day high
    if daily_history and len(daily_history) >= 20:
        twenty_day_high = max(d["high"] for d in daily_history[-20:])
        if price >= twenty_day_high * 0.99:
            methods_agree.append("Donchian")
    elif week_high and price >= week_high * 0.97:
        # Fallback if no history: near 52W high is a strong proxy
        methods_agree.append("Donchian")

    # 4. Inside Day breakout — today's range inside yesterday's, now breaking up
    if daily_history and len(daily_history) >= 2:
        prev_high = daily_history[-2]["high"] if len(daily_history) >= 2 else high
        prev_low = daily_history[-2]["low"] if len(daily_history) >= 2 else low
        prev_day_high = daily_history[-1]["high"] if len(daily_history) >= 1 else high
        prev_day_low = daily_history[-1]["low"] if len(daily_history) >= 1 else low
        inside_day = prev_day_high <= prev_high and prev_day_low >= prev_low
        if inside_day and gap_pct > 0:
            methods_agree.append("Inside Day")

    # 5. Bull Flag — strong move in last 3-5 days + today consolidating/breaking up
    if daily_history and len(daily_history) >= 5:
        five_day_move = (price - daily_history[-5]["close"]) / max(daily_history[-5]["close"], 0.01) * 100
        recent_consolidation = abs(day_change) < 3  # Tight day = flag
        if five_day_move >= 8 and recent_consolidation and gap_pct >= 0:
            methods_agree.append("Bull Flag")

    # 6. Pocket Pivot — up day with volume exceeding any down-day volume of last 10 days
    if daily_history and len(daily_history) >= 10 and day_change > 0:
        down_day_volumes = [d["volume"] for d in daily_history[-10:] if d.get("close", 0) < d.get("open", 0)]
        current_volume = data.get("volume", 0)
        if down_day_volumes and current_volume > max(down_day_volumes):
            methods_agree.append("Pocket Pivot")
        elif not down_day_volumes and volume_ratio >= 1.5 and day_change > 0:
            # No down days in 10 days — strong uptrend, volume surge qualifies
            methods_agree.append("Pocket Pivot")

    # 7. Support & Resistance — ATR-adaptive zone analysis
    sr = data.get("sr_analysis") or calculate_support_resistance(ticker, price_data)
    if sr["signal"] in ("open_air", "open_air+support_floor") or        ("support_floor" in sr["signal"] and sr["score"] >= 0.65):
        methods_agree.append("S&R")

    # 8. VWAP Reclaim — price closing above VWAP shows institutional buy-side
    vwap_score = calculate_vwap_signal(ticker, price_data)
    if vwap_score >= 0.75:
        methods_agree.append("VWAP Reclaim")

    # 9. Volatility Squeeze — compression precedes explosive directional move
    squeeze_score = calculate_volatility_squeeze(ticker, price_data)
    if squeeze_score >= 0.75:
        methods_agree.append("Vol Squeeze")

    return {"count": len(methods_agree), "methods": methods_agree}


def enrich_price_data_with_history(tickers, price_data):
    """
    Ensure daily_history is populated in price_data for confluence scoring.
    Fetches only a bounded candidate subset so comprehensive scans cannot stall
    on hundreds of one-by-one candle calls.
    """
    missing = [t for t in tickers if t in price_data and not price_data[t].get("daily_history")]
    if not missing:
        return  # All tickers already have history from Twelve Data

    def history_priority(ticker):
        data = price_data.get(ticker, {}) or {}
        return max(abs(float(data.get("gap_percent") or 0)), abs(float(data.get("day_change_percent") or 0)))

    max_history_fetch = int(os.getenv("SCAN_HISTORY_REFRESH_LIMIT", "40"))
    selected = sorted(missing, key=history_priority, reverse=True)[:max_history_fetch]
    log.info(f"Fetching history for {len(selected)}/{len(missing)} tickers missing daily_history...")
    supplemental = fetch_twelve_data_batch(selected, interval="1day", outputsize=60)
    for ticker in missing:
        if ticker in supplemental and "daily_history" in supplemental[ticker]:
            price_data[ticker]["daily_history"] = supplemental[ticker]["daily_history"]
            repair_quote_baselines_from_history(price_data[ticker], price_data[ticker]["daily_history"])

def run_darvas_silent_collection(price_data, scored_stocks):
    """
    Silently record Darvas Box picks for future performance comparison.

    Darvas Box rules (simplified for overnight swing):
    1. Stock is within 5% of its 52-week high (near the top of its box)
    2. Volume is at least 1.5x average (confirms breakout conviction)
    3. Price gapped up or is showing positive momentum

    No virtual trades, no position monitoring, no UI impact.
    Just logging which stocks Darvas would have picked and tracking outcomes.
    Must run within 60 days of 2026-05-23 to enable retroactive backfill.
    """
    try:
        database = get_database()
        today = current_time_cst().strftime("%Y-%m-%d")
        darvas_picks = []

        for stock in scored_stocks:
            ticker = stock["ticker"]
            if ticker not in price_data:
                continue
            data = price_data[ticker]
            week_high = data.get("52w_high")
            if not week_high:
                continue
            current_price = data.get("price", 0)
            volume_ratio = data.get("volume_ratio", 0)

            # Darvas rule: within 5% of 52W high + volume confirmation
            near_high = current_price >= week_high * 0.95
            volume_confirmed = volume_ratio >= 1.5
            positive_gap = data.get("gap_percent", 0) > 0

            if near_high and volume_confirmed and positive_gap:
                pick_id = f"{ticker}_{today}_darvas"
                existing = database.execute(
                    "SELECT id FROM darvas_picks WHERE id=?", [pick_id]
                ).fetchone()
                if not existing:
                    database.execute("""
                        INSERT INTO darvas_picks
                        (id, ticker, date, entry_price, week_high, volume_ratio, would_have_bought, outcome, logged_at)
                        VALUES (?,?,?,?,?,?,1,'open',?)
                    """, [pick_id, ticker, today, current_price, week_high,
                          round(volume_ratio, 2), current_time_cst().isoformat()])
                    darvas_picks.append(ticker)

        # Resolve open Darvas picks older than 2 days
        open_picks = database.execute(
            "SELECT * FROM darvas_picks WHERE outcome='open' AND date < ?",
            [(current_time_cst() - timedelta(days=2)).strftime("%Y-%m-%d")]
        ).fetchall()

        for pick in open_picks:
            if pick["ticker"] in price_data:
                entry = pick["entry_price"] or 1
                current = price_data[pick["ticker"]]["price"]
                actual_move = (current - entry) / entry * 100
                outcome = "hit" if actual_move >= 5 else "miss"
                database.execute(
                    "UPDATE darvas_picks SET outcome=?, actual_move=? WHERE id=?",
                    [outcome, round(actual_move, 2), pick["id"]]
                )

        database.commit()
        database.close()
        if darvas_picks:
            log.info(f"Darvas silent: {len(darvas_picks)} picks logged — {darvas_picks}")
    except Exception as err:
        log.warning(f"Darvas silent collection error: {err}")

def get_pdt_count():
    """Return number of day trades used in the rolling 5-day window."""
    try:
        database = get_database()
        five_days_ago = (current_time_cst() - timedelta(days=5)).strftime("%Y-%m-%d")
        count = database.execute(
            "SELECT COUNT(*) as n FROM day_trades WHERE date >= ?", [five_days_ago]
        ).fetchone()["n"]
        database.close()
        return count
    except:
        return 0

def record_day_trade(ticker, buy_time=None, sell_time=None):
    """Record a day trade (same-day open and close)."""
    try:
        today = current_time_cst().strftime("%Y-%m-%d")
        trade_id = f"{ticker}_{today}_dt"
        database = get_database()
        database.execute("""
            INSERT OR REPLACE INTO day_trades (id, ticker, date, buy_time, sell_time, logged_at)
            VALUES (?,?,?,?,?,?)
        """, [trade_id, ticker, today, buy_time, sell_time, current_time_cst().isoformat()])
        database.commit()
        database.close()
    except Exception as e:
        log.warning(f"PDT record error: {e}")

def can_day_trade():
    """Return True if we have day trades remaining (< 3 in rolling 5-day window)."""
    return get_pdt_count() < 3


def run_method_signal_logging(price_data, scored_stocks):
    """
    Log signals for all 7 trading methods silently during each scan.
    Uses the same method_signals table for all non-Darvas methods.
    Resolves open signals older than 2 days.
    """
    try:
        database = get_database()
        today = current_time_cst().strftime("%Y-%m-%d")

        for stock in scored_stocks:
            ticker = stock["ticker"]
            if ticker not in price_data:
                continue
            confluence = calculate_method_confluence(ticker, price_data)
            for method in confluence["methods"]:
                if method == "Darvas":
                    continue  # Already tracked separately
                signal_id = f"{ticker}_{today}_{method.replace(' ', '_').replace('&', 'and')}"
                existing = database.execute(
                    "SELECT id FROM method_signals WHERE id=?", [signal_id]
                ).fetchone()
                if not existing:
                    database.execute("""
                        INSERT INTO method_signals (id, method, ticker, date, entry_price, outcome, logged_at)
                        VALUES (?,?,?,?,?,?,?)
                    """, [signal_id, method, ticker, today,
                          price_data[ticker].get("price", 0),
                          "open", current_time_cst().isoformat()])

        # Resolve open signals older than 2 days
        open_signals = database.execute(
            "SELECT * FROM method_signals WHERE outcome='open' AND date < ?",
            [(current_time_cst() - timedelta(days=2)).strftime("%Y-%m-%d")]
        ).fetchall()

        for signal in open_signals:
            if signal["ticker"] in price_data:
                entry = signal["entry_price"] or 1
                current = price_data[signal["ticker"]]["price"]
                actual_move = (current - entry) / max(entry, 0.01) * 100
                outcome = "hit" if actual_move >= 5 else "miss"
                database.execute(
                    "UPDATE method_signals SET outcome=?, actual_move=? WHERE id=?",
                    [outcome, round(actual_move, 2), signal["id"]]
                )

        database.commit()
        database.close()
    except Exception as err:
        log.warning(f"Method signal logging error: {err}")


def _normalize_news_article(title, summary, url, pub_ts, source):
    """
    Normalize a news article into the standard internal schema.
    All news sources must produce this shape so the provider can be
    swapped without touching any other code.

    Fields:
      title        — headline text
      summary      — article summary or excerpt (may be empty string)
      url          — full article URL
      pub_ts       — unix timestamp of publication (0 if unknown)
      source       — provider name string e.g. "alpha_vantage", "yahoo_rss"
    """
    try:
        pub_dt = datetime.utcfromtimestamp(pub_ts) if pub_ts else datetime.utcnow()
        date_str = pub_dt.strftime("%b %d")
    except:
        date_str = ""
        pub_ts = 0
    return {
        "title": title or "",
        "summary": summary or "",
        "url": url or "",
        "date": date_str,
        "ts": pub_ts,
        "source": source,
    }


def _fetch_news_alpha_vantage(ticker):
    """
    Fetch news for a single ticker via Alpha Vantage NEWS_SENTIMENT endpoint.
    Returns (articles, sentiment_score, article_count).
    Extracts ticker_sentiment_score and overall_sentiment_score for NN training.
    """
    if not ALPHA_VANTAGE_KEY:
        return [], 0.0, 0
    try:
        import urllib.request
        url = (f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
               f"&tickers={ticker}&limit=5&apikey={ALPHA_VANTAGE_KEY}")
        req = urllib.request.Request(url, headers={"User-Agent": "SwingDesk/1.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8", errors="ignore"))
        feed = data.get("feed", [])
        articles = []
        sentiment_scores = []
        for item in feed[:5]:
            title = item.get("title", "").strip()
            summary = item.get("summary", "").strip()
            url_str = item.get("url", "").strip()
            time_str = item.get("time_published", "")
            pub_ts = 0
            if time_str:
                try:
                    dt = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                    pub_ts = dt.timestamp()
                except:
                    pass
            # Extract per-ticker sentiment score from ticker_sentiment_label list
            for ts in item.get("ticker_sentiment", []):
                if ts.get("ticker", "").upper() == ticker.upper():
                    try:
                        sentiment_scores.append(float(ts.get("ticker_sentiment_score", 0)))
                    except:
                        pass
            if title and url_str:
                articles.append(_normalize_news_article(title, summary, url_str, pub_ts, "alpha_vantage"))
        articles.sort(key=lambda x: x["ts"], reverse=True)
        avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.0
        return articles[:3], round(avg_sentiment, 4), len(feed)
    except Exception as err:
        log.debug(f"Alpha Vantage news failed for {ticker}: {err}")
        return [], 0.0, 0


def _fetch_news_yahoo_rss(ticker):
    """
    Fetch news for a single ticker via Yahoo Finance RSS.
    Fallback when Alpha Vantage is unavailable or rate-limited.
    Returns headlines only (no summaries) — normalized to standard schema.
    """
    try:
        import urllib.request
        import xml.etree.ElementTree as ET
        from email.utils import parsedate_to_datetime
        url = f"https://finance.yahoo.com/rss/headline?s={ticker}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; SwingDesk/1.0)"})
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_content = response.read().decode("utf-8", errors="ignore")
        root = ET.fromstring(xml_content)
        articles = []
        for item in root.findall(".//item")[:5]:
            title_el = item.find("title")
            link_el = item.find("link")
            pubdate_el = item.find("pubDate")
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            pub_ts = 0
            if pubdate_el is not None and pubdate_el.text:
                try:
                    dt = parsedate_to_datetime(pubdate_el.text.strip())
                    pub_ts = dt.timestamp()
                except:
                    pub_ts = datetime.utcnow().timestamp()
            if title and link:
                articles.append(_normalize_news_article(title, "", link, pub_ts, "yahoo_rss"))
        articles.sort(key=lambda x: x["ts"], reverse=True)
        return articles[:3]
    except Exception as err:
        log.debug(f"Yahoo RSS news failed for {ticker}: {err}")
        return []


def fetch_ticker_news(tickers, price_data):
    """
    Fetch news articles for each ticker.
    Primary: Alpha Vantage NEWS_SENTIMENT — extracts sentiment score for NN.
    Fallback: Yahoo Finance RSS (headlines only, no sentiment score).
    Stores news, sentiment_score, and article_count on price_data per ticker.
    """
    for ticker in tickers:
        if ticker not in price_data:
            continue
        articles, sentiment_score, article_count = _fetch_news_alpha_vantage(ticker)
        if not articles:
            articles = _fetch_news_yahoo_rss(ticker)
            sentiment_score = 0.0
            article_count = len(articles)
        price_data[ticker]["news"] = articles[:1]
        price_data[ticker]["news_sentiment_score"] = sentiment_score
        price_data[ticker]["news_article_count"] = article_count


def calculate_relative_strength(ticker, price_data):
    """
    Relative Strength vs Market: compare ticker's 5-day return to SPY's 5-day return.
    A stock outperforming SPY is showing genuine institutional accumulation —
    money is flowing into this name specifically, not just riding the market.

    Score:
      Outperforming SPY by >3%  → 1.0 (strong RS)
      Outperforming SPY by >1%  → 0.75
      In line with SPY (±1%)    → 0.5 (neutral)
      Underperforming by >1%    → 0.3
      Underperforming by >3%    → 0.1 (weak RS)
    """
    if ticker not in price_data or "SPY" not in price_data:
        return 0.5
    try:
        ticker_history = price_data[ticker].get("daily_history", [])
        spy_history = price_data.get("SPY", {}).get("daily_history", [])
        if len(ticker_history) < 5 or len(spy_history) < 5:
            return 0.5
        ticker_5d = (ticker_history[-1]["close"] - ticker_history[-5]["close"]) / max(ticker_history[-5]["close"], 0.01) * 100
        spy_5d = (spy_history[-1]["close"] - spy_history[-5]["close"]) / max(spy_history[-5]["close"], 0.01) * 100
        rs_diff = ticker_5d - spy_5d
        if rs_diff > 3:   return 1.0
        if rs_diff > 1:   return 0.75
        if rs_diff > -1:  return 0.5
        if rs_diff > -3:  return 0.3
        return 0.1
    except:
        return 0.5


def calculate_sector_relative_strength(ticker, price_data):
    """
    Sector Relative Strength: compare ticker's sector ETF 5-day return to SPY.
    Institutional money rotates by sector. A stock in a sector with tailwind
    has a higher base rate of continuation than one swimming against sector flow.

    Uses SECTOR_MAP to find the right ETF. ETFs already in the universe so
    their price data is fetched for free during every scan.
    """
    SECTOR_ETF_MAP = {
        "Tech": "XLK", "Finance": "XLF", "Energy": "XLE",
        "Healthcare": "XLV", "Industrial": "XLI", "Consumer": "XLY",
        "Defense": "XLI", "Auto": "XLY", "Crypto": "XLK",
        "ETF": None, "Other": None,
    }
    sector = get_sector(ticker)
    etf = SECTOR_ETF_MAP.get(sector)
    if not etf or etf not in price_data or "SPY" not in price_data:
        return 0.5
    try:
        etf_history = price_data[etf].get("daily_history", [])
        spy_history = price_data.get("SPY", {}).get("daily_history", [])
        if len(etf_history) < 5 or len(spy_history) < 5:
            return 0.5
        etf_5d = (etf_history[-1]["close"] - etf_history[-5]["close"]) / max(etf_history[-5]["close"], 0.01) * 100
        spy_5d = (spy_history[-1]["close"] - spy_history[-5]["close"]) / max(spy_history[-5]["close"], 0.01) * 100
        diff = etf_5d - spy_5d
        if diff > 2:   return 0.85
        if diff > 0.5: return 0.7
        if diff > -0.5: return 0.5
        if diff > -2:  return 0.35
        return 0.2
    except:
        return 0.5


def calculate_vwap_signal(ticker, price_data):
    """
    VWAP Distance / VWAP Reclaim signal.
    VWAP (Volume Weighted Average Price) is the institutional benchmark.
    Stocks closing above VWAP show institutions are net buyers on the day.
    The reclaim setup — stock dips below VWAP intraday then closes above —
    is one of the most reliable institutional accumulation signals.

    Uses intraday_history if available (populated separately for candidates),
    falls back to close vs open as a VWAP proxy for universe-wide scanning.

    Score:
      Price well above VWAP (>1%)    → 0.85 (strong institutional buy)
      Price just above VWAP (0-1%)   → 0.65
      Price at VWAP (±0.3%)          → 0.5
      Price below VWAP               → 0.25
    """
    if ticker not in price_data:
        return 0.5
    try:
        data = price_data[ticker]
        # Use pre-computed VWAP if available from intraday fetch
        vwap = data.get("vwap")
        price = data.get("price", 0)
        if vwap and price and vwap > 0:
            dist_pct = (price - vwap) / vwap * 100
            if dist_pct > 1.0:  return 0.85
            if dist_pct > 0.0:  return 0.65
            if dist_pct > -0.3: return 0.5
            return 0.25
        # Proxy: closing above open with volume surge suggests above-VWAP close
        close = data.get("price", 0)
        open_p = data.get("open", close)
        volume_ratio = data.get("volume_ratio", 1.0)
        if open_p <= 0:
            return 0.5
        day_move = (close - open_p) / open_p * 100
        if day_move > 1.5 and volume_ratio > 1.3:  return 0.80
        if day_move > 0.5:                          return 0.65
        if day_move > -0.5:                         return 0.5
        return 0.3
    except:
        return 0.5


def calculate_volatility_squeeze(ticker, price_data):
    """
    Historical Volatility Ratio (Volatility Squeeze signal).
    Compares recent 5-day HV to 20-day HV. A low ratio means volatility
    is compressing — the stock is coiling. Compression historically precedes
    expansion: the tighter the squeeze, the more explosive the breakout.

    HV = annualized standard deviation of daily log returns.
    Ratio = HV_5 / HV_20

    Score:
      Ratio < 0.5  → 1.0 (extreme compression — coiled spring)
      Ratio < 0.7  → 0.85
      Ratio < 0.9  → 0.65
      Ratio < 1.1  → 0.5 (neutral)
      Ratio >= 1.1 → 0.3 (already expanding — may be late)
    """
    if ticker not in price_data:
        return 0.5
    try:
        import math
        history = price_data[ticker].get("daily_history", [])
        if len(history) < 21:
            return 0.5
        closes = [d["close"] for d in history]
        log_returns = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes)) if closes[i-1] > 0]
        if len(log_returns) < 20:
            return 0.5
        def hv(returns):
            n = len(returns)
            mean = sum(returns) / n
            variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
            return math.sqrt(variance * 252)  # Annualized
        hv5  = hv(log_returns[-5:])
        hv20 = hv(log_returns[-20:])
        if hv20 <= 0:
            return 0.5
        ratio = hv5 / hv20
        if ratio < 0.5:  return 1.0
        if ratio < 0.7:  return 0.85
        if ratio < 0.9:  return 0.65
        if ratio < 1.1:  return 0.5
        return 0.3
    except:
        return 0.5


def compute_signal_scores(ticker, price_data, rsi, earnings_soon, weights, direction="long"):
    """
    Compute individual scores for all 9 indicators.
    Returns:
      scores:  dict of {indicator_name: float 0-1}
      fired:   list of indicator names that scored >= 0.65
      values:  dict of raw measurements per indicator for human-readable display

    The values dict is what powers the sub-tray on position cards — showing
    the actual RSI number, volume ratio, gap %, etc. rather than abstract scores.
    """
    universe_data, ticker_data = split_price_context(ticker, price_data)
    rsi = rsi if rsi == rsi else 50.0

    # RSI
    if direction == "long":
        rsi_score = 1.0 if 40 <= rsi <= 65 else (0.9 if rsi < 40 else 0.5)
    else:
        rsi_score = 1.0 if rsi > 65 else (0.7 if rsi > 55 else 0.4)

    # Volume
    volume_ratio = ticker_data.get("volume_ratio", 1.0)
    volume_ratio = volume_ratio if volume_ratio == volume_ratio else 1.0
    volume_score = min(volume_ratio / 3.5, 1.0)

    # Gap
    gap_percent = ticker_data.get("gap_percent", 0)
    gap_percent = gap_percent if gap_percent == gap_percent else 0.0
    gap_score = min(abs(gap_percent) / 10.0, 1.0)
    if direction == "short":
        gap_score = gap_score if gap_percent < 0 else gap_score * 0.5

    # Earnings
    days_to_earnings = None
    if ticker in earnings_soon:
        days_to_earnings = earnings_soon.get(ticker, 7) if isinstance(earnings_soon, dict) else 3
        if days_to_earnings <= 1:   earnings_score = 0.0
        elif days_to_earnings <= 3: earnings_score = 0.75
        elif days_to_earnings <= 7: earnings_score = 0.65
        else:                       earnings_score = 0.5
    else:
        earnings_score = 0.5

    # S&R
    sr_analysis = ticker_data.get("sr_analysis")
    sr_score = sr_analysis["score"] if sr_analysis else 0.5
    sr_signal = sr_analysis["signal"] if sr_analysis else "unknown"
    sr_nearest_resistance = sr_analysis.get("nearest_resistance") if sr_analysis else None
    sr_nearest_support = sr_analysis.get("nearest_support") if sr_analysis else None
    if direction == "short": sr_score = 1.0 - sr_score

    # RS vs Market — compute diff for display
    rs_score = calculate_relative_strength(ticker, universe_data)
    rs_stock_5d, rs_spy_5d = None, None
    try:
        ticker_history = universe_data[ticker].get("daily_history", [])
        spy_history = universe_data.get("SPY", {}).get("daily_history", [])
        if len(ticker_history) >= 5 and len(spy_history) >= 5:
            rs_stock_5d = round((ticker_history[-1]["close"] - ticker_history[-5]["close"]) / max(ticker_history[-5]["close"], 0.01) * 100, 2)
            rs_spy_5d = round((spy_history[-1]["close"] - spy_history[-5]["close"]) / max(spy_history[-5]["close"], 0.01) * 100, 2)
    except: pass
    if direction == "short": rs_score = 1.0 - rs_score

    # Sector RS — compute diff + ETF name for display
    sector_rs_score = calculate_sector_relative_strength(ticker, universe_data)
    sector_etf_name, sector_etf_5d, sector_spy_5d = None, None, None
    try:
        SECTOR_ETF_MAP = {
            "Tech": "XLK", "Finance": "XLF", "Energy": "XLE",
            "Healthcare": "XLV", "Industrial": "XLI", "Consumer": "XLY",
            "Defense": "XLI", "Auto": "XLY", "Crypto": "XLK",
        }
        sector_etf_name = SECTOR_ETF_MAP.get(get_sector(ticker))
        if sector_etf_name and sector_etf_name in universe_data and "SPY" in universe_data:
            etf_hist = universe_data[sector_etf_name].get("daily_history", [])
            spy_hist = universe_data.get("SPY", {}).get("daily_history", [])
            if len(etf_hist) >= 5 and len(spy_hist) >= 5:
                sector_etf_5d = round((etf_hist[-1]["close"] - etf_hist[-5]["close"]) / max(etf_hist[-5]["close"], 0.01) * 100, 2)
                sector_spy_5d = round((spy_hist[-1]["close"] - spy_hist[-5]["close"]) / max(spy_hist[-5]["close"], 0.01) * 100, 2)
    except: pass
    if direction == "short": sector_rs_score = 1.0 - sector_rs_score

    # VWAP — capture mode + distance
    vwap_score = calculate_vwap_signal(ticker, universe_data)
    vwap_mode, vwap_dist = "unknown", None
    try:
        vwap = universe_data.get(ticker, {}).get("vwap")
        price = universe_data.get(ticker, {}).get("price", 0)
        if vwap and price and vwap > 0:
            vwap_mode = "real"
            vwap_dist = round((price - vwap) / vwap * 100, 2)
        else:
            vwap_mode = "proxy"
            close = universe_data.get(ticker, {}).get("price", 0)
            open_p = universe_data.get(ticker, {}).get("open", close)
            if open_p > 0:
                vwap_dist = round((close - open_p) / open_p * 100, 2)
    except: pass
    if direction == "short": vwap_score = 1.0 - vwap_score

    # Volatility Squeeze — compute HV ratio for display
    squeeze_score = calculate_volatility_squeeze(ticker, universe_data)
    hv_ratio = None
    try:
        import math
        history = universe_data.get(ticker, {}).get("daily_history", [])
        if len(history) >= 21:
            closes = [d["close"] for d in history]
            log_returns = [math.log(closes[i] / closes[i-1]) for i in range(1, len(closes)) if closes[i-1] > 0]
            if len(log_returns) >= 20:
                def hv(r): 
                    n = len(r); mean = sum(r)/n
                    return math.sqrt(sum((x-mean)**2 for x in r)/(n-1) * 252)
                hv5 = hv(log_returns[-5:])
                hv20 = hv(log_returns[-20:])
                if hv20 > 0: hv_ratio = round(hv5 / hv20, 3)
    except: pass

    scores = {
        "rsi_momentum":       round(rsi_score, 3),
        "volume_surge":       round(volume_score, 3),
        "overnight_gap_probability": round(gap_score, 3),
        "earnings_catalyst":  round(earnings_score, 3),
        "support_resistance": round(sr_score, 3),
        "relative_strength":  round(rs_score, 3),
        "sector_relative_strength": round(sector_rs_score, 3),
        "vwap_reclaim":       round(vwap_score, 3),
        "volatility_squeeze": round(squeeze_score, 3),
    }

    values = {
        "rsi_momentum":       round(rsi, 1),
        "volume_surge":       round(volume_ratio, 2),
        "overnight_gap_probability": round(gap_percent, 2),
        "earnings_catalyst":  days_to_earnings,
        "support_resistance": {"signal": sr_signal, "resistance": sr_nearest_resistance, "support": sr_nearest_support},
        "relative_strength":  {"stock_5d": rs_stock_5d, "spy_5d": rs_spy_5d},
        "sector_relative_strength": {"etf": sector_etf_name, "etf_5d": sector_etf_5d, "spy_5d": sector_spy_5d},
        "vwap_reclaim":       {"mode": vwap_mode, "dist": vwap_dist},
        "volatility_squeeze": hv_ratio,
    }

    FIRED_THRESHOLD = 0.65
    fired = [k for k, v in scores.items() if v >= FIRED_THRESHOLD]

    return scores, fired, values



def send_telegram_notification(message):
    """
    Send a Telegram bot message.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway env vars.
    Set NOTIFY_PROVIDER=telegram in Railway to use Telegram instead of Twilio.
    """
    try:
        import urllib.request
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            log.warning("Telegram env vars not set — TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat_id, "text": message}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
        if result.get("ok"):
            log.info(f"Telegram sent: {message}")
            return True
        log.warning(f"Telegram failed: {result}")
        return False
    except Exception as e:
        log.error(f"Telegram error: {e}")
        return False


def send_swingdesk_notification(message):
    """Send a configured SwingDesk notification through Telegram or Twilio."""
    if not notification_enabled():
        return False

    provider = os.environ.get("NOTIFY_PROVIDER", "twilio").lower()
    if provider == "telegram":
        return send_telegram_notification(message)

    try:
        from twilio.rest import Client
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        to_number   = os.environ.get("TWILIO_TO_NUMBER")
        if not all([account_sid, auth_token, from_number, to_number]):
            log.warning("Twilio env vars not set - SMS skipped")
            return False
        client = Client(account_sid, auth_token)
        client.messages.create(body=message, from_=from_number, to=to_number)
        log.info(f"Notification sent: {message}")
        return True
    except Exception as e:
        log.error(f"Twilio SMS error: {e}")
        return False

def _parse_iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts))
    except Exception:
        return None

def _alert_state():
    return get_app_state_json("notification_alert_state", {}) or {}

def _save_alert_state(state):
    set_app_state("notification_alert_state", json.dumps(state))

def can_send_alert(alert_key, cooldown_minutes=None, once_per_day=False):
    state = _alert_state()
    now = current_time_cst()
    record = state.get(alert_key) or {}
    last_sent = _parse_iso(record.get("last_sent_at"))
    if once_per_day and last_sent and last_sent.strftime("%Y-%m-%d") == now.strftime("%Y-%m-%d"):
        return False
    if cooldown_minutes and last_sent and (now - last_sent).total_seconds() < cooldown_minutes * 60:
        return False
    return True

def mark_alert_sent(alert_key, extra=None):
    state = _alert_state()
    record = state.get(alert_key) or {}
    record.update(extra or {})
    record["last_sent_at"] = current_time_cst().isoformat()
    state[alert_key] = record
    _save_alert_state(state)

def send_deduped_alert(alert_key, message, cooldown_minutes=None, once_per_day=False, extra=None):
    if not can_send_alert(alert_key, cooldown_minutes=cooldown_minutes, once_per_day=once_per_day):
        return False
    sent = send_swingdesk_notification(message)
    if sent:
        mark_alert_sent(alert_key, extra)
    return sent


def send_close_notification(ticker, pnl_dollar, pnl_pct, close_reason, close_time=None):
    """
    Send notification when a position closes.
    Provider: NOTIFY_PROVIDER env var — 'telegram' or 'twilio' (default twilio).
    Only fires if notifications are enabled in app_state.
    """
    try:
        db = get_database()
        setting = db.execute("SELECT value FROM app_state WHERE key='notify_on_close'").fetchone()
        db.close()
        if setting and setting["value"] == "false":
            return
    except:
        pass

    sign = "+" if pnl_dollar >= 0 else ""
    time_str = close_time or current_time_cst().strftime("%I:%M %p")
    message = f"SwingDesk: {ticker} closed {sign}${pnl_dollar:.2f} ({sign}{pnl_pct:.1f}%) — {close_reason} {time_str}"

    provider = os.environ.get("NOTIFY_PROVIDER", "twilio").lower()

    if provider == "telegram":
        send_telegram_notification(message)
        return

    try:
        from twilio.rest import Client
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        to_number   = os.environ.get("TWILIO_TO_NUMBER")
        if not all([account_sid, auth_token, from_number, to_number]):
            log.warning("Twilio env vars not set — SMS skipped")
            return
        client = Client(account_sid, auth_token)
        client.messages.create(body=message, from_=from_number, to=to_number)
        log.info(f"SMS sent: {message}")
    except Exception as e:
        log.error(f"Twilio SMS error: {e}")


def is_visible_weak_state(position, pnl_percent):
    """Backend mirror of the open-card Weak state: negative open P&L is Weak."""
    target = float(position.get("expected_move") or 10)
    if pnl_percent >= target:
        return False
    return pnl_percent < 0

def update_weak_alert_state(position, pnl_percent, should_sell=False):
    """Send low-noise Weak alerts based on the same binary state the UI shows."""
    ticker = position.get("ticker")
    trade_id = position.get("id") or f"{ticker}_{position.get('buy_date')}"
    if not ticker or should_sell:
        return

    state = _alert_state()
    weak_key = f"weak_state:{trade_id}"
    record = state.get(weak_key) or {"weak_checks": 0, "clear_checks": 0, "eligible": True}
    is_weak = is_visible_weak_state(position, pnl_percent)

    if is_weak:
        record["weak_checks"] = int(record.get("weak_checks") or 0) + 1
        record["clear_checks"] = 0
    else:
        record["clear_checks"] = int(record.get("clear_checks") or 0) + 1
        if record["clear_checks"] >= 2:
            record["weak_checks"] = 0
            record["eligible"] = True

    state[weak_key] = record
    _save_alert_state(state)

    if not is_weak or record["weak_checks"] < 2 or record.get("eligible") is False:
        return

    today = current_time_cst().strftime("%Y-%m-%d")
    alert_key = f"weak:{trade_id}:{today}"
    message = f"SwingDesk: {ticker} is Weak on 2 checks ({pnl_percent:+.1f}% open P&L). Watching, not a sell rule."
    sent = send_deduped_alert(
        alert_key,
        message,
        once_per_day=True,
        extra={"ticker": ticker, "trade_id": trade_id, "alert_type": "weak"},
    )
    if sent:
        state = _alert_state()
        record = state.get(weak_key) or record
        record["eligible"] = False
        state[weak_key] = record
        _save_alert_state(state)

def send_sell_rule_alert(position, pnl_percent, reason):
    """Send immediate sell-rule alert and suppress future weak alerts for this trade."""
    ticker = position.get("ticker")
    trade_id = position.get("id") or f"{ticker}_{position.get('buy_date')}"
    if not ticker:
        return
    alert_key = f"sell_rule:{trade_id}:{current_time_cst().strftime('%Y-%m-%d')}:{reason}"
    message = f"SwingDesk SELL: {ticker} triggered {str(reason).replace('_', ' ')} at {pnl_percent:+.1f}%."
    sent = send_deduped_alert(
        alert_key,
        message,
        extra={"ticker": ticker, "trade_id": trade_id, "alert_type": "sell_rule", "reason": reason},
    )
    if sent:
        state = _alert_state()
        weak_key = f"weak_state:{trade_id}"
        record = state.get(weak_key) or {}
        record["eligible"] = False
        record["sell_rule_fired"] = True
        state[weak_key] = record
        _save_alert_state(state)

def evaluate_monitor_health_alert(status=None):
    """Alert when open-position monitoring is stale during market hours."""
    status = status or get_monitor_status()
    if not is_market_open():
        return

    open_count = int(status.get("total_open_positions") or status.get("open_positions") or 0)
    if open_count <= 0:
        return

    last_success = _parse_iso(status.get("last_success_at") or status.get("finished_at"))
    if not last_success:
        return

    age_minutes = int((current_time_cst() - last_success).total_seconds() / 60)
    if age_minutes < 10:
        return

    near_force_close = 0 <= minutes_until_forced_close() <= 30
    prefix = "Monitor stale near force-close" if near_force_close else "Monitor stale"
    message = f"SwingDesk: {prefix} - open positions have not updated in {age_minutes}m."
    sent = send_deduped_alert(
        "monitor_failure",
        message,
        cooldown_minutes=60,
        extra={"alert_type": "monitor_failure", "age_minutes": age_minutes},
    )
    if sent:
        set_app_state("monitor_failure_alert_active", "true")

def maybe_send_monitor_recovery_alert(status):
    """Send one recovery alert after a stale/failure monitor alert was sent."""
    if get_app_state_value("monitor_failure_alert_active", "false") != "true":
        return
    updated_count = int(status.get("updated_count") or 0)
    total = int(status.get("total_open_positions") or 0)
    message = f"SwingDesk: Monitor recovered - {updated_count}/{total} open positions updated."
    sent = send_deduped_alert(
        "monitor_recovery",
        message,
        cooldown_minutes=60,
        extra={"alert_type": "monitor_recovery", "updated_count": updated_count, "total": total},
    )
    if sent:
        set_app_state("monitor_failure_alert_active", "false")


def is_extended_hours():
    """
    Returns True if current CST time is in pre-market (4:00-8:30 AM) or
    post-market (3:00-7:00 PM) session. Used to decide whether to fetch
    live extended-hours prices via fast_info instead of daily OHLCV close.
    """
    now = current_time_cst()
    minute_of_day = now.hour * 60 + now.minute
    is_premarket  = (4 * 60) <= minute_of_day < (8 * 60 + 30)
    is_postmarket = (15 * 60) <= minute_of_day < (19 * 60)
    return is_premarket or is_postmarket, is_premarket


def enrich_with_live_prices(tickers, price_data):
    """
    Override stale daily-close prices with live extended-hours prices.
    Uses Twelve Data /quote endpoint — same source as monitor.
    Called after fetch_price_data during pre-market and post-market windows.
    """
    in_extended, in_premarket = is_extended_hours()
    if not in_extended:
        return

    log.info(f"Extended hours active — enriching {len(tickers)} tickers with live prices ({'pre' if in_premarket else 'post'}-market)")

    max_external = int(os.getenv("SCAN_LIVE_REFRESH_LIMIT", "80"))
    external_used = 0
    enriched = 0
    cycle = ProviderCycle("extended_hours_enrich")
    for ticker in tickers:
        if ticker not in price_data:
            continue
        cached_quote = _read_quote_cache(ticker)
        if not cached_quote and external_used >= max_external:
            continue
        try:
            quote = cached_quote or fetch_quote_with_fallback(ticker, cycle=cycle, use_cache=False)
            if not cached_quote:
                external_used += 1
            if not quote or quote["price"] <= 0:
                if not cached_quote:
                    time.sleep(1.1)
                continue
            live_price = quote["price"]
            data = price_data[ticker]
            prev_close = data.get("previous_close", live_price)
            today_close = data.get("price", live_price)
            data["price"] = live_price
            if in_premarket:
                new_gap = (live_price - prev_close) / max(prev_close, 0.01) * 100
                data["gap_percent"] = round(new_gap, 4)
                data["premarket_change_percent"] = round(new_gap, 4)
            else:
                new_change = (live_price - today_close) / max(today_close, 0.01) * 100
                data["day_change_percent"] = round(new_change, 4)
            data["live_price_source"] = quote.get("source", "provider")
            enriched += 1
            if not cached_quote:
                time.sleep(1.1)
        except:
            pass
    set_app_state("last_price_provider_summary", json.dumps(cycle.summary()))

    log.info(f"Live price enrichment complete — {enriched}/{len(tickers)} tickers enriched")

# ── SCORING ENGINE ────────────────────────────────────────────────────────────
def calculate_confidence_score(ticker, price_data, rsi, earnings_soon, weights, direction="long"):
    """
    Calculate a confidence score (0-99) for a potential trade.
    9-signal scoring engine weighted by the brain's current learned weights.

    Signals:
      1. RSI Momentum              — price momentum quality
      2. Volume Surge              — participation/institutional conviction
      3. Overnight Gap             — directional bias at open
      4. Earnings Catalyst         — event-driven run-up signal
      5. Support & Resistance      — ATR-adaptive structural levels
      6. Relative Strength         — stock vs SPY 5-day return
      7. Sector Relative Strength  — sector ETF vs SPY 5-day return
      8. VWAP Distance/Reclaim     — institutional buy-side footprint
      9. Volatility Squeeze        — compression precedes expansion

    All signals return 0.0-1.0. Weighted sum × multiplier → integer score.
    Hard disqualifier: earnings tonight/tomorrow returns 0 immediately.
    Multiplier calibrated so average qualified setup scores ~70.
    """
    universe_data, ticker_data = split_price_context(ticker, price_data)
    rsi = rsi if rsi == rsi else 50.0

    # 1. RSI Momentum
    if direction == "long":
        rsi_score = 1.0 if 40 <= rsi <= 65 else (0.9 if rsi < 40 else 0.5)
    else:
        rsi_score = 1.0 if rsi > 65 else (0.7 if rsi > 55 else 0.4)

    # 2. Volume Surge
    volume_ratio = ticker_data.get("volume_ratio", 1.0)
    volume_ratio = volume_ratio if volume_ratio == volume_ratio else 1.0
    volume_score = min(volume_ratio / 3.5, 1.0)

    # 3. Overnight Gap
    gap_percent = ticker_data.get("gap_percent", 0)
    gap_percent = gap_percent if gap_percent == gap_percent else 0.0
    gap_score = min(abs(gap_percent) / 10.0, 1.0)
    if direction == "short":
        gap_score = gap_score if gap_percent < 0 else gap_score * 0.5

    # 4. Earnings Catalyst — hard disqualify if earnings tonight or tomorrow
    if ticker in earnings_soon:
        days_to_earnings = earnings_soon.get(ticker, 7) if isinstance(earnings_soon, dict) else 3
        if days_to_earnings <= 1:
            return 0
        elif days_to_earnings <= 3:
            earnings_score = 0.75
        elif days_to_earnings <= 7:
            earnings_score = 0.65
        else:
            earnings_score = 0.5
    else:
        earnings_score = 0.5

    # 5. Support & Resistance
    sr_analysis = ticker_data.get("sr_analysis")
    sr_score = sr_analysis["score"] if sr_analysis else 0.5
    if direction == "short":
        sr_score = 1.0 - sr_score

    # 6. Relative Strength vs Market
    rs_score = calculate_relative_strength(ticker, universe_data)
    if direction == "short":
        rs_score = 1.0 - rs_score

    # 7. Sector Relative Strength
    sector_rs_score = calculate_sector_relative_strength(ticker, universe_data)
    if direction == "short":
        sector_rs_score = 1.0 - sector_rs_score

    # 8. VWAP Distance/Reclaim
    vwap_score = calculate_vwap_signal(ticker, universe_data)
    if direction == "short":
        vwap_score = 1.0 - vwap_score

    # 9. Volatility Squeeze
    squeeze_score = calculate_volatility_squeeze(ticker, universe_data)

    # Weighted combination — all 9 signals
    raw_score = (
        rsi_score        * weights.get("rsi_momentum", 0.15) +
        volume_score     * weights.get("volume_surge", 0.15) +
        gap_score        * weights.get("overnight_gap_probability", 0.18) +
        earnings_score   * weights.get("earnings_catalyst", 0.14) +
        sr_score         * weights.get("support_resistance", 0.13) +
        rs_score         * weights.get("relative_strength", 0.12) +
        sector_rs_score  * weights.get("sector_relative_strength", 0.10) +
        vwap_score       * weights.get("vwap_reclaim", 0.08) +
        squeeze_score    * weights.get("volatility_squeeze", 0.05)
    )
    # Multiplier: 9 signals averaging 0.65 × weights summing to 1.0 × 108 ≈ 70
    return min(int(raw_score * 108), 99)

def estimate_overnight_move(price_data, confidence, has_earnings):
    """Estimate the expected overnight price movement percentage."""
    volume_ratio = price_data.get("volume_ratio", 1)
    volume_ratio = volume_ratio if volume_ratio == volume_ratio else 1.0
    gap_percent = price_data.get("gap_percent", 0)
    gap_percent = gap_percent if gap_percent == gap_percent else 0.0
    base_move = 4 + (confidence - 60) * 0.25
    volume_bonus = (volume_ratio - 1) * 1.5
    earnings_bonus = 3 if has_earnings else 0
    gap_boost = min(abs(gap_percent) * 0.3, 3)
    return round(min(base_move + volume_bonus + earnings_bonus + gap_boost, 25), 1)

def predict_sell_time_window(confidence):
    """Predict the optimal sell window based on confidence level."""
    if confidence >= 85: return "8:45-9:30 AM"
    if confidence >= 75: return "9:30-10:30 AM"
    if confidence >= 65: return "10:30-12 PM"
    return "12-1:30 PM"

def build_reasoning_text(ticker, price_data, rsi, has_earnings, direction):
    """Build a human-readable reasoning string for a recommendation."""
    parts = []
    if direction == "long":
        if rsi < 45: parts.append(f"RSI {rsi:.0f} oversold")
        elif rsi > 60: parts.append(f"RSI {rsi:.0f} momentum")
        else: parts.append(f"RSI {rsi:.0f} neutral")
    else:
        parts.append(f"RSI {rsi:.0f} overbought" if rsi > 65 else f"RSI {rsi:.0f} weakening")
    volume_ratio = price_data.get("volume_ratio", 1)
    if volume_ratio > 1.8:
        parts.append(f"{volume_ratio:.1f}x volume")
    gap = price_data.get("gap_percent", 0)
    if abs(gap) > 2:
        parts.append(f"{gap:+.1f}% gap")
    if has_earnings:
        parts.append("earnings catalyst")
    return " · ".join(parts[:3])

# ── DYNAMIC SELL ENGINE ───────────────────────────────────────────────────────
def evaluate_sell_decision(trade, current_price, rsi=None, volume_ratio=None):
    """
    Evaluate whether to sell an open position based on current market data.
    
    Returns: (should_sell: bool, reason: str, sentiment: str)
    
    The sell engine balances two competing goals:
    1. Let winners ride (don't sell too early if momentum is strong)
    2. Cut losers (don't hold a losing position hoping for reversal)
    
    The 2:45 PM CST deadline is absolute — everything closes by then.
    """
    buy_price = trade["buy_price"]
    pnl_percent = (current_price - buy_price) / buy_price * 100

    # For short positions, invert the P&L logic
    if trade["direction"] == "short":
        pnl_percent = -pnl_percent

    remaining_minutes = minutes_until_forced_close()

    # ── FORCED CLOSE — Non-negotiable deadline ──
    if remaining_minutes <= 0:
        return True, "forced_close", f"Force-closed at 2:45 PM — {pnl_percent:+.1f}%"

    # ── TARGET HIT — informational only; let winners ride until thesis weakens ──
    if pnl_percent >= 8:
        return False, "target_hit", f"Holding winner — target hit at {pnl_percent:+.1f}%"

    # ── STOP LOSS — Cut losses on strong reversals ──
    if pnl_percent <= -5:
        return True, MODEL_STOP_LOSS_REASON, f"Exiting — model stop at {pnl_percent:+.1f}%"

    # ── MOMENTUM FADE — Small gain but volume dying ──
    if pnl_percent >= 2 and pnl_percent < 5 and volume_ratio and volume_ratio < 0.6:
        return True, "momentum_fade", f"Exiting — volume fading at {pnl_percent:+.1f}%"

    # ── RSI EXHAUSTION — Momentum peaked for longs ──
    if trade["direction"] == "long" and rsi and rsi > 80 and pnl_percent > 3:
        return True, "rsi_exhaustion", f"Exiting — RSI {rsi:.0f} exhausted at {pnl_percent:+.1f}%"

    # ── HOLD — Various sentiments based on current P&L ──
    if pnl_percent >= 5:
        sentiment = f"Holding — on track at {pnl_percent:+.1f}%"
    elif pnl_percent >= 2:
        sentiment = f"Holding — momentum intact at {pnl_percent:+.1f}%"
    elif pnl_percent >= 0:
        sentiment = f"Holding — watching at {pnl_percent:+.1f}%"
    else:
        sentiment = f"Holding — down {pnl_percent:+.1f}%, watching for reversal"

    return False, "hold", sentiment

# ── COMPREHENSIVE SCAN — Generate Picks ───────────────────────────────────────
def _run_comprehensive_scan_impl(weights=None, scan_type="scheduled"):
    """
    Run a full scan of the entire ticker universe.
    Scores every stock, filters by confidence floor, caches results.
    Only stocks at or above CONFIDENCE_FLOOR (65%) are recommended.
    Open position tickers are excluded — they are owned by the monitor.
    """
    if weights is None:
        weights = get_signal_weights()
    universe = build_ticker_universe()

    # Exclude tickers with open positions — monitor handles those exclusively
    # This prevents DB lock conflicts between scan writes and monitor writes
    try:
        _db = get_database()
        open_tickers = set()
        for table in ("virtual_trades", "nn_virtual_trades", "personal_trades"):
            try:
                open_tickers.update(r["ticker"] for r in _db.execute(
                    f"SELECT ticker FROM {table} WHERE outcome='open'"
                ).fetchall())
            except Exception:
                pass
        _db.close()
        universe = [t for t in universe if t not in open_tickers]
    except Exception as e:
        log.warning(f"Could not exclude open tickers from scan: {e}")

    log.info(f"Comprehensive scan: {len(universe)} tickers ({scan_type}, {len(open_tickers) if 'open_tickers' in dir() else 0} open positions excluded)...")
    scan_event_id = begin_scan_event(scan_type, job_type="comprehensive", tickers_attempted=len(universe))
    record_nn_scan_status(
        status="running",
        scan_type=scan_type,
        source="shared_comprehensive_scan",
        started=True,
        already_running=False,
        started_at=current_time_cst().isoformat(),
        finished_at=None,
        total_scanned=0,
        qualified=0,
        picks=0,
        phase="fetching_prices",
        scan_event_id=scan_event_id,
        error=None,
    )

    # Ensure SPY is always fetched — needed for relative strength calculations
    universe_with_spy = list(dict.fromkeys(universe + ["SPY"]))
    price_data = fetch_price_data(universe_with_spy, scan_event_id=scan_event_id, scan_type=scan_type)
    record_nn_scan_status(
        status="running",
        scan_type=scan_type,
        source="shared_comprehensive_scan",
        started=True,
        already_running=False,
        started_at=current_time_cst().isoformat(),
        finished_at=None,
        total_scanned=0,
        total_expected=len(universe),
        scanned_tickers=[],
        current_ticker=None,
        phase="scoring",
        scan_event_id=scan_event_id,
        error=None,
    )

    # During pre/post market hours, override stale daily closes with live prices
    enrich_with_live_prices(universe_with_spy, price_data)

    # Filter out tickers where yfinance returned weekend/holiday stale data.
    # If the latest price date is more than 3 days old, the data is stale.
    from datetime import date as date_type
    today_date = current_time_cst().date()
    fresh_tickers = []
    for ticker, data in price_data.items():
        fresh_tickers.append(ticker)  # Keep all for now; stale detection in monitoring
    price_data = {t: price_data[t] for t in fresh_tickers}

    rsi_values = calculate_rsi_batch(list(price_data.keys()), price_data=price_data)
    earnings_soon = check_upcoming_earnings(list(price_data.keys()))

    # Check for 52-week breakouts (informational only, does not affect scoring)
    check_52w_breakouts(list(price_data.keys()), price_data)

    # Enrich price data with daily history for confluence method scoring
    enrich_price_data_with_history(list(price_data.keys()), price_data)

    # Pre-compute S&R analysis for all tickers — stored on price_data["sr_analysis"]
    # so calculate_confidence_score can read it without recomputing per-ticker
    for ticker in list(price_data.keys()):
        try:
            expected_move_pct = 5.0  # Rough default; refined per-pick after scoring
            price_data[ticker]["expected_move_pct"] = expected_move_pct
            calculate_support_resistance(ticker, price_data)
        except Exception as sr_err:
            log.debug(f"S&R pre-compute skipped for {ticker}: {sr_err}")

    # Prevent simultaneous long and short on the same ticker
    database = get_database()
    open_trades = []
    for table in ("virtual_trades", "nn_virtual_trades", "personal_trades"):
        try:
            open_trades.extend(database.execute(
                f"SELECT ticker, direction FROM {table} WHERE outcome='open'"
            ).fetchall())
        except Exception:
            pass
    database.close()
    open_long_tickers = set(t["ticker"] for t in open_trades if t["direction"] == "long")
    open_short_tickers = set(t["ticker"] for t in open_trades if t["direction"] == "short")
    all_open_tickers = open_long_tickers | open_short_tickers

    scored_stocks = []
    scanned_tickers = []
    for idx, ticker in enumerate(universe, start=1):
        scanned_tickers.append(ticker)
        if idx == 1 or idx % 2 == 0 or idx == len(universe):
            record_nn_scan_status(
                status="running",
                phase="scoring",
                scan_event_id=scan_event_id,
                total_scanned=idx,
                total_expected=len(universe),
                current_ticker=ticker,
                scanned_tickers=scanned_tickers[-12:],
            )
        if ticker not in price_data:
            continue
        # Skip tickers with open positions — they're already committed
        # and don't need new recommendations while the trade is active
        if ticker in all_open_tickers:
            continue
        stock_data = price_data[ticker]
        rsi = rsi_values.get(ticker, 50.0)
        has_earnings = ticker in earnings_soon

        # Hard disqualify if earnings tonight or tomorrow — never hold through earnings
        days_to_earnings = earnings_soon.get(ticker, 99) if isinstance(earnings_soon, dict) else 99
        if has_earnings and days_to_earnings <= 1:
            continue

        long_confidence = calculate_confidence_score(ticker, price_data, rsi, earnings_soon, weights, "long")
        short_confidence = calculate_confidence_score(ticker, price_data, rsi, earnings_soon, weights, "short")
        long_move = estimate_overnight_move(stock_data, long_confidence, has_earnings)
        short_move = estimate_overnight_move(stock_data, short_confidence, has_earnings)

        # Calculate method confluence
        confluence = calculate_method_confluence(ticker, price_data)
        long_signal_scores, long_fired_signals, long_signal_values = compute_signal_scores(
            ticker, price_data, rsi, earnings_soon, weights, "long"
        )

        scored_stocks.append({
            "ticker": ticker,
            "name": ticker,
            "sector": get_sector(ticker),
            "price": stock_data["price"],
            "open_price": stock_data.get("open", stock_data["price"]),
            "prev_close": stock_data.get("previous_close", stock_data["price"]),
            "rsi": round(rsi, 1),
            "vol_ratio": round(stock_data.get("volume_ratio", 1), 2),
            "overnight_gap_pct": round(stock_data.get("gap_percent", 0), 2),
            "day_change_pct": round(stock_data.get("day_change_percent", 0), 2),
            "pct_change_prev_close": round(pct_from_baseline(stock_data["price"], stock_data.get("previous_close")) or 0, 2),
            "pct_change_premarket": None,
            "pct_change_regular_open": round(pct_from_baseline(stock_data["price"], stock_data.get("open")) or 0, 2),
            "earnings_soon": has_earnings,
            "long_conf": long_confidence,
            "long_move": long_move,
            "long_reasoning": build_reasoning_text(ticker, stock_data, rsi, has_earnings, "long"),
            "short_conf": short_confidence,
            "short_move": short_move,
            "short_reasoning": build_reasoning_text(ticker, stock_data, rsi, has_earnings, "short"),
            "sell_time": predict_sell_time_window(long_confidence),
            "data_source": stock_data.get("source", "unknown"),
            "52w_high": stock_data.get("52w_high"),
            "broke_52w_high_days_ago": stock_data.get("broke_52w_high_days_ago"),
            "news": stock_data.get("news", []),
            "confluence_count": confluence["count"],
            "confluence_methods": confluence["methods"],
            "signal_scores_for_observation": long_signal_scores,
            "signal_values_for_observation": long_signal_values,
            "fired_signals_for_observation": long_fired_signals,
            "signal_scores": {
                "scores": long_signal_scores,
                "values": long_signal_values,
                "fired": long_fired_signals,
            },
        })

    # Check if queue is locked (post 8:25 AM CST)
    # If locked, scan still runs for monitoring purposes but no new picks enter the queue
    queue_is_locked = is_pick_queue_locked()

    if queue_is_locked and scan_type not in ("manual", "manual_fresh", "manual_shared", "manual_shared_nova"):
        log.info(f"Queue locked — scan completed but no new picks added ({scan_type})")
        pass

    # Filter by confidence floor — longs only.
    # Shorts are disabled: current signals (RSI momentum, volume surge, gap probability)
    # are optimized for long setups. Short-specific signals (RSI overbought, failed
    # breakout, sector weakness) will be added in a future session before re-enabling.
    recommended_longs = sorted(
        [s for s in scored_stocks if is_long_pick_eligible(s, open_short_tickers)],
        key=lambda x: x["long_conf"], reverse=True
    )
    recommended_shorts = []  # Disabled until short-specific signals are implemented

    # Run Darvas silent collection on all scored stocks
    run_darvas_silent_collection(price_data, scored_stocks)
    run_method_signal_logging(price_data, scored_stocks)

    # Fetch news for top recommended longs only (not full universe)
    top_tickers = [s["ticker"] for s in recommended_longs[:MAX_LONG_PICKS]]
    fetch_ticker_news(top_tickers, price_data)
    # Re-attach news to recommended picks after fetch
    price_data_news = {t: price_data[t].get("news", []) for t in top_tickers}
    for pick in recommended_longs[:MAX_LONG_PICKS]:
        pick["news"] = price_data_news.get(pick["ticker"], [])

    vector_observations = log_vector_signal_observations(
        scan_event_id,
        scan_type,
        price_data,
        scored_stocks,
        rsi_values,
        earnings_soon,
        weights,
        selected_tickers=[s["ticker"] for s in recommended_longs[:MAX_LONG_PICKS]],
        executable_tickers=[s["ticker"] for s in recommended_longs],
        queue_locked=queue_is_locked,
    )

    evidence_cache = build_confidence_evidence_cache()
    attach_confidence_evidence(recommended_longs, "long_conf", evidence_cache)
    attach_confidence_evidence(recommended_shorts, "short_conf", evidence_cache)

    scan_result = {
        "longs": recommended_longs[:MAX_LONG_PICKS],
        "shorts": recommended_shorts[:MAX_SHORT_PICKS],
        "all_longs": len(recommended_longs),
        "all_shorts": len(recommended_shorts),
        "total_scanned": len(scored_stocks),
        "ticker_universe_count": len(universe),
        "price_rows_loaded": len(price_data),
        "price_rows_expected": len(universe_with_spy),
        "partial_price_universe": len(price_data) < max(1, int(len(universe_with_spy) * 0.95)),
        "generated_at": current_time_cst().isoformat(),
        "scan_type": scan_type,
        "queue_locked": bool(queue_is_locked),
        "execution_locked": bool(queue_is_locked),
    }
    nn_scan_result = build_nn_picks_from_scan(price_data, scored_stocks, rsi_values, earnings_soon, scan_type, scan_event_id, queue_is_locked)
    scan_result["nn_picks"] = {
        "picks": nn_scan_result.get("picks", len(nn_scan_result.get("recommended_longs", []) or [])),
        "qualified_count": nn_scan_result.get("qualified_count", 0),
        "source": nn_scan_result.get("source", "shared_comprehensive_scan"),
        "error": nn_scan_result.get("error"),
    }
    scan_result["observations"] = {
        "vector": vector_observations,
        "nova": nn_scan_result.get("observations_logged", 0),
    }

    # Cache picks and log scan
    database = get_database()
    database.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_picks',?)", [json.dumps(scan_result)])
    database.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_picks_time',?)", [current_time_cst().isoformat()])
    database.execute(
        "INSERT INTO scan_cache (scan_time, scan_type, ticker_count, picks_json) VALUES (?,?,?,?)",
        [current_time_cst().isoformat(), scan_type, len(scored_stocks), json.dumps(scan_result)]
    )

    # Update candidates table (for 5-min monitoring)
    database.execute("UPDATE candidates SET monitoring = 0 WHERE monitoring = 1")
    all_recommended = recommended_longs[:MAX_LONG_PICKS] + recommended_shorts[:MAX_SHORT_PICKS]
    for pick in all_recommended:
        direction = "long" if pick in recommended_longs[:MAX_LONG_PICKS] else "short"
        conf = pick["long_conf"] if direction == "long" else pick["short_conf"]
        move = pick["long_move"] if direction == "long" else pick["short_move"]
        now_iso = current_time_cst().isoformat()
        # Check if candidate already exists to preserve first_seen timestamp
        existing = database.execute("SELECT first_seen FROM candidates WHERE ticker=?", [pick["ticker"]]).fetchone()
        first_seen = existing["first_seen"] if existing else now_iso
        database.execute(
            "INSERT OR REPLACE INTO candidates (ticker, direction, first_seen, last_seen, confidence, expected_move, monitoring) VALUES (?,?,?,?,?,?,?)",
            [pick["ticker"], direction, first_seen, now_iso, conf, move, 1]
        )

    # Log predictions (only for 65%+ confidence)
    today = current_time_cst().strftime("%Y-%m-%d")
    for pick in all_recommended:
        direction = "long" if pick in recommended_longs[:MAX_LONG_PICKS] else "short"
        confidence = pick["long_conf"] if direction == "long" else pick["short_conf"]
        expected_move = pick["long_move"] if direction == "long" else pick["short_move"]
        reasoning = pick["long_reasoning"] if direction == "long" else pick["short_reasoning"]
        prediction_id = f"{pick['ticker']}_{today}_{direction}"

        if not database.execute("SELECT id FROM predictions WHERE id=?", [prediction_id]).fetchone():
            database.execute("""
                INSERT INTO predictions (id, ticker, name, date, direction, confidence,
                expected_move, entry_price, sell_time_window, reasoning, sector, rsi,
                volume_ratio, weights_snapshot, logged_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [prediction_id, pick["ticker"], pick["name"], today, direction,
                  confidence, expected_move, pick["price"], pick["sell_time"],
                  reasoning, pick["sector"], pick["rsi"], pick["vol_ratio"],
                  json.dumps(weights), current_time_cst().isoformat()])

    database.commit()
    database.close()
    finish_scan_event(
        scan_event_id,
        status="degraded" if scan_result["partial_price_universe"] else "success",
        tickers_updated=len(price_data),
        picks_count=len(scan_result["longs"]) + len(scan_result["shorts"]),
        provider_summary=get_app_state_json("last_price_provider_summary", {}) or {},
    )
    scan_result["variant_run"] = {
        "auto_open_disabled": True,
        "message": "Comprehensive scans update caches only; variant trades open via scheduled 8:45/manual runner.",
    }
    log.info(f"Scan complete: {len(recommended_longs)} longs, {len(recommended_shorts)} shorts from {len(scored_stocks)} scanned")
    return scan_result

def run_comprehensive_scan(weights=None, scan_type="scheduled"):
    """Single-flight wrapper around the full comprehensive scan hot path."""
    if not _comprehensive_scan_lock.acquire(blocking=False):
        log.warning(f"Comprehensive scan skipped because another scan is active ({scan_type})")
        return {
            "longs": [],
            "shorts": [],
            "total_scanned": 0,
            "scan_type": scan_type,
            "skipped": True,
            "reason": "comprehensive_scan_already_running",
            "nn_picks": {"picks": 0, "qualified_count": 0, "source": "shared_comprehensive_scan"},
        }
    started_after = current_time_cst().isoformat()
    try:
        return _run_comprehensive_scan_impl(weights=weights, scan_type=scan_type)
    except Exception as error:
        mark_running_events_error("comprehensive", started_after, error)
        raise
    finally:
        _comprehensive_scan_lock.release()

def get_cached_picks():
    """Return cached picks instantly without triggering a new scan."""
    database = get_database()
    cached = database.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
    cache_time = database.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    database.close()
    if cached:
        result = json.loads(cached["value"])
        result["cached"] = True
        result["cache_time"] = cache_time["value"] if cache_time else None
        return result
    return None

# ── NEURAL NETWORK SCAN ──────────────────────────────────────────────────────
def run_variant_universes_from_cache(trigger="manual", buy_time=None, require_fresh=True):
    """Open simulated trades for every active strategy universe from cached shared scan outputs."""
    status = {
        "success": True,
        "trigger": trigger,
        "ran_at": current_time_cst().isoformat(),
        "variants": 0,
        "opened_count": 0,
        "skipped_count": 0,
        "opened": [],
        "skipped": [],
        "variant_summaries": [],
        "errors": [],
    }
    today = current_time_cst().strftime("%Y-%m-%d")
    buy_time = buy_time or current_time_cst().strftime("%H:%M:%S")
    target_execution_time = buy_time[:5]
    buy_time_parts = [int(part) for part in buy_time.split(":")[:3]]
    while len(buy_time_parts) < 3:
        buy_time_parts.append(0)
    entry_target_dt = datetime.strptime(today, "%Y-%m-%d").replace(
        hour=buy_time_parts[0],
        minute=buy_time_parts[1],
        second=buy_time_parts[2],
        microsecond=0,
    )
    database = get_database()
    try:
        snapshot, refusal = variant_cache_snapshot(database, require_fresh=require_fresh)
        if refusal:
            status.update(refusal)
            database.execute("INSERT OR REPLACE INTO app_state VALUES ('last_variant_run', ?)", [json.dumps(status)])
            database.commit()
            return status

        vector_payload = snapshot["vector_payload"]
        nova_payload = snapshot["nova_payload"]
        vector_picks = vector_payload.get("longs") or vector_payload.get("recommended_longs") or []
        nova_picks = nova_payload.get("recommended_longs") or nova_payload.get("longs") or []
        status.update({
            "shared_snapshot": True,
            "vector_cache_time": snapshot["vector_cache_time"],
            "nova_cache_time": snapshot["nova_cache_time"],
            "vector_cache_age_minutes": snapshot["vector_cache_age_minutes"],
            "nova_cache_age_minutes": snapshot["nova_cache_age_minutes"],
            "cache_gap_minutes": snapshot["cache_gap_minutes"],
            "vector_pick_count": len(vector_picks),
            "nova_pick_count": len(nova_picks),
        })

        variants = [dict(r) for r in database.execute("""
            SELECT sv.*, vp.cash, vp.equity
            FROM strategy_variants sv
            JOIN variant_portfolios vp ON vp.variant_id = sv.id
            WHERE sv.status='active' AND vp.lifecycle_status!='archived'
            ORDER BY sv.strategy, sv.brain, sv.selection_mode
        """).fetchall()]
        status["variants"] = len(variants)

        for variant in variants:
            execution_time = (variant.get("execution_time") or "").strip()
            if execution_time and execution_time != "reg" and execution_time != target_execution_time:
                continue
            brain = variant.get("brain")
            source_picks = nova_picks if brain == "Nova" else vector_picks
            if brain == "Nova":
                source_picks = [p for p in source_picks if p.get("nn_executable", True)]
            variant_weights = get_variant_signal_weights(database, variant["id"])
            strategy_filtered = filter_variant_strategy_picks(source_picks, variant, variant_weights)
            if not strategy_filtered:
                status["skipped"].append({"variant_id": variant["id"], "reason": "no strategy-qualified picks"})
                status["skipped_count"] += 1
                status["variant_summaries"].append({
                    "variant_id": variant["id"],
                    "brain": brain,
                    "strategy": variant.get("strategy"),
                    "source_picks": len(source_picks),
                    "strategy_qualified": 0,
                    "selected": 0,
                    "opened": 0,
                })
                update_variant_portfolio(database, variant["id"], note="no_strategy_picks")
                continue
            selected = select_variant_picks(strategy_filtered, variant.get("selection_mode"))
            if not selected:
                status["skipped"].append({"variant_id": variant["id"], "reason": "no picks"})
                status["skipped_count"] += 1
                update_variant_portfolio(database, variant["id"], note="no_picks")
                continue
            entry_quotes = fetch_entry_prices_at_cst(
                sorted({pick.get("ticker") for pick in selected if pick.get("ticker")}),
                entry_target_dt,
            )
            variant_opened = 0
            variant_skipped = 0
            open_cap = variant_open_position_cap(variant)
            existing_open_count = int(database.execute(
                "SELECT COUNT(*) AS n FROM variant_virtual_trades WHERE variant_id=? AND outcome='open'",
                [variant["id"]]
            ).fetchone()["n"] or 0)
            if existing_open_count >= open_cap:
                status["skipped"].append({"variant_id": variant["id"], "reason": "variant open-position cap reached", "open_count": existing_open_count, "cap": open_cap})
                status["skipped_count"] += 1
                update_variant_portfolio(database, variant["id"], note="open_cap_reached")
                continue
            scan_time = snapshot["nova_cache_time"] if brain == "Nova" else snapshot["vector_cache_time"]

            for rank, pick in enumerate(selected, start=1):
                if existing_open_count + variant_opened >= open_cap:
                    break
                ticker = pick.get("ticker")
                if not ticker:
                    continue
                trade_id = f"{variant['id']}_{ticker}_{today}_long"
                if database.execute("SELECT id FROM variant_virtual_trades WHERE id=?", [trade_id]).fetchone():
                    status["skipped_count"] += 1
                    variant_skipped += 1
                    status["skipped"].append({"variant_id": variant["id"], "ticker": ticker, "reason": "already open/executed today"})
                    continue
                if database.execute(
                    "SELECT id FROM variant_virtual_trades WHERE variant_id=? AND ticker=? AND outcome='open'",
                    [variant["id"], ticker]
                ).fetchone():
                    status["skipped_count"] += 1
                    variant_skipped += 1
                    status["skipped"].append({"variant_id": variant["id"], "ticker": ticker, "reason": "already open in variant"})
                    continue

                portfolio = dict(database.execute("SELECT * FROM variant_portfolios WHERE variant_id=?", [variant["id"]]).fetchone())
                invested = variant_investment_amount(portfolio)
                if invested <= 0:
                    status["skipped_count"] += 1
                    variant_skipped += 1
                    status["skipped"].append({"variant_id": variant["id"], "ticker": ticker, "reason": "no cash"})
                    continue

                entry_quote = normalize_monitor_quote(entry_quotes.get(ticker), pick.get("price")) if entry_quotes.get(ticker) else None
                buy_price = (entry_quote or {}).get("price") or pick.get("open_price") or pick.get("price") or pick.get("buy_price") or 0
                day_change_percent = float(
                    (entry_quote or {}).get("day_change_percent")
                    if (entry_quote or {}).get("day_change_percent") is not None
                    else pick.get("pct_change_prev_close", pick.get("day_change_pct", pick.get("day_change_percent", 0)))
                    or 0
                )
                if not buy_price:
                    status["skipped_count"] += 1
                    variant_skipped += 1
                    status["skipped"].append({"variant_id": variant["id"], "ticker": ticker, "reason": "missing price"})
                    continue

                confidence, expected_move = pick_confidence_and_move(pick, brain)
                signal_scores = build_signal_payload_json_from_pick(
                    pick, ticker, buy_price, variant_weights, "long"
                )
                confluence_methods = pick.get("confluence_methods") or pick.get("confluence_methods_for_observation") or []
                if not isinstance(confluence_methods, str):
                    confluence_methods = json.dumps(confluence_methods)
                confluence_count = int(pick.get("confluence_count") or 0)
                reasoning = pick.get("long_reasoning") or f"{brain} variant simulation"
                fee_quote = calculate_stock_fee_model(invested, buy_price, buy_price, "long")
                database.execute(f"""
                    INSERT INTO variant_virtual_trades
                    (id, variant_id, strategy, brain, ticker, direction, buy_date, buy_time,
                     buy_price, current_price, day_change_percent, invested_amount, current_value, confidence, expected_move,
                     {FEE_MODEL_INSERT_COLUMNS},
                     outcome, sector, reasoning, signal_scores, confluence_count, confluence_methods, source_scan_time, source_rank,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'long', ?, ?, ?, ?, ?, ?, ?, ?, ?, {FEE_MODEL_INSERT_PLACEHOLDERS}, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    trade_id, variant["id"], variant["strategy"], brain, ticker, today, buy_time,
                    float(buy_price), float(buy_price), round(day_change_percent, 4), round(invested, 4), fee_quote["net_current_value"], confidence, expected_move,
                    *fee_model_values(fee_quote),
                    pick.get("sector") or get_sector(ticker), reasoning, signal_scores, confluence_count, confluence_methods, scan_time, rank,
                    status["ran_at"], status["ran_at"],
                ])
                database.execute("""
                    UPDATE variant_portfolios
                    SET cash=ROUND(cash - ?, 4), updated_at=?
                    WHERE variant_id=?
                """, [round(invested, 4), status["ran_at"], variant["id"]])
                status["opened_count"] += 1
                variant_opened += 1
                status["opened"].append({
                    "variant_id": variant["id"],
                    "ticker": ticker,
                    "buy_price": float(buy_price),
                    "invested_amount": round(invested, 4),
                    "rank": rank,
                })

            update_variant_portfolio(database, variant["id"], note=f"run_{trigger}")
            status["variant_summaries"].append({
                "variant_id": variant["id"],
                "brain": brain,
                "strategy": variant.get("strategy"),
                "source_picks": len(source_picks),
                "strategy_qualified": len(strategy_filtered),
                "selected": len(selected),
                "opened": variant_opened,
                "skipped": variant_skipped,
            })

        database.execute("INSERT OR REPLACE INTO app_state VALUES ('last_variant_run', ?)", [json.dumps(status)])
        database.commit()
        return status
    except Exception as error:
        database.rollback()
        status["success"] = False
        status["errors"].append(str(error))
        log.error(f"variant universe run failed: {error}")
        return status
    finally:
        database.close()

def monitor_variant_universes(trigger="manual"):
    """Refresh and conservatively settle open trades in every variant universe."""
    status = {
        "success": True,
        "trigger": trigger,
        "ran_at": current_time_cst().isoformat(),
        "open_count": 0,
        "updated_count": 0,
        "closed_count": 0,
        "errors": [],
    }
    now = current_time_cst()
    today = now.strftime("%Y-%m-%d")
    database = get_database()
    try:
        open_rows = [dict(r) for r in database.execute(
            "SELECT * FROM variant_virtual_trades WHERE outcome='open'"
        ).fetchall()]
        status["open_count"] = len(open_rows)
        if not open_rows:
            database.execute("INSERT OR REPLACE INTO app_state VALUES ('last_variant_monitor', ?)", [json.dumps(status)])
            database.commit()
            return status

        tickers = sorted({r["ticker"] for r in open_rows})
        current_prices = fetch_current_prices(tickers)
        touched_variants = set()

        for row in open_rows:
            ticker = row["ticker"]
            raw = current_prices.get(ticker)
            if not raw:
                continue
            price_data = normalize_monitor_quote(raw, row.get("buy_price"))
            price = float(price_data["price"])
            day_change_percent = float(price_data.get("day_change_percent") or price_data.get("day_change_pct") or 0)
            buy_price = float(row.get("buy_price") or price)
            invested = float(row.get("invested_amount") or 0)
            pnl_pct = (price - buy_price) / max(buy_price, 0.01) * 100
            if row.get("direction") == "short":
                pnl_pct = -pnl_pct
            fee_quote = calculate_stock_fee_model(invested, buy_price, price, row.get("direction") or "long")
            current_value = fee_quote["net_current_value"]
            should_close = False
            sell_reason = None

            # Winner target hits are intentionally informational only.
            if row.get("buy_date") < today and minutes_until_forced_close() <= 0:
                should_close = True
                sell_reason = "forced_close"
            elif pnl_pct <= -5:
                should_close = True
                sell_reason = MODEL_STOP_LOSS_REASON

            if should_close:
                outcome = "hit" if pnl_pct > 0 else "miss"
                database.execute(f"""
                    UPDATE variant_virtual_trades
                    SET current_value=?, current_price=?, day_change_percent=?, sell_date=?, sell_time=?, sell_price=?,
                        actual_move=?, gross_pnl=?, net_pnl=?, {FEE_MODEL_UPDATE_SET},
                        outcome=?, sell_reason=?, updated_at=?
                    WHERE id=?
                """, [
                    round(current_value, 4), price, round(day_change_percent, 4), today, now.strftime("%H:%M:%S"), price,
                    round(pnl_pct, 2), fee_quote["gross_pnl"], fee_quote["net_pnl"],
                    *fee_model_values(fee_quote),
                    outcome, sell_reason, status["ran_at"], row["id"],
                ])
                database.execute("""
                    UPDATE variant_portfolios
                    SET cash=ROUND(cash + ?, 4), updated_at=?
                    WHERE variant_id=?
                """, [round(current_value, 4), status["ran_at"], row["variant_id"]])
                status["closed_count"] += 1
            else:
                database.execute(f"""
                    UPDATE variant_virtual_trades
                    SET current_value=?, current_price=?, day_change_percent=?, actual_move=?, {FEE_MODEL_UPDATE_SET}, updated_at=?
                    WHERE id=?
                """, [
                    round(current_value, 4), price, round(day_change_percent, 4), round(pnl_pct, 2), *fee_model_values(fee_quote),
                    status["ran_at"], row["id"],
                ])

            status["updated_count"] += 1
            touched_variants.add(row["variant_id"])

        for variant_id in touched_variants:
            update_variant_portfolio(database, variant_id, note=f"monitor_{trigger}")

        database.execute("INSERT OR REPLACE INTO app_state VALUES ('last_variant_monitor', ?)", [json.dumps(status)])
        database.commit()
        return status
    except Exception as error:
        database.rollback()
        status["success"] = False
        status["errors"].append(str(error))
        log.error(f"variant monitor failed: {error}")
        return status
    finally:
        database.close()

def refresh_variant_open_quotes(database, variant_id):
    """Refresh open quotes for one variant before returning detail to the UI."""
    open_rows = [dict(r) for r in database.execute(
        "SELECT * FROM variant_virtual_trades WHERE variant_id=? AND outcome='open'",
        [variant_id],
    ).fetchall()]
    if not open_rows:
        return 0
    current_prices = fetch_current_prices(sorted({r["ticker"] for r in open_rows}))
    updated = 0
    now_iso = current_time_cst().isoformat()
    for row in open_rows:
        raw = current_prices.get(row["ticker"])
        if not raw:
            continue
        quote = normalize_monitor_quote(raw, row.get("buy_price"))
        price = float(quote["price"])
        day_change_percent = float(quote.get("day_change_percent") or quote.get("day_change_pct") or 0)
        buy_price = float(row.get("buy_price") or price)
        invested = float(row.get("invested_amount") or 0)
        pnl_pct = (price - buy_price) / max(buy_price, 0.01) * 100
        if row.get("direction") == "short":
            pnl_pct = -pnl_pct
        fee_quote = calculate_stock_fee_model(invested, buy_price, price, row.get("direction") or "long")
        database.execute(f"""
            UPDATE variant_virtual_trades
            SET current_value=?, current_price=?, day_change_percent=?, actual_move=?, gross_pnl=?, net_pnl=?,
                {FEE_MODEL_UPDATE_SET}, updated_at=?
            WHERE id=?
        """, [
            round(fee_quote["net_current_value"], 4),
            price,
            round(day_change_percent, 4),
            round(pnl_pct, 2),
            fee_quote["gross_pnl"],
            fee_quote["net_pnl"],
            *fee_model_values(fee_quote),
            now_iso,
            row["id"],
        ])
        updated += 1
    if updated:
        update_variant_portfolio(database, variant_id, note="detail_refresh")
    return updated

def repair_variant_open_caps(apply_changes=False):
    """Archive excess open variant trades created before open-position caps existed."""
    db = get_database()
    repaired = []
    now = current_time_cst().isoformat()
    try:
        variants = [dict(r) for r in db.execute("""
            SELECT sv.id, sv.strategy, sv.brain, sv.selection_mode
            FROM strategy_variants sv
            JOIN variant_portfolios vp ON vp.variant_id=sv.id
            WHERE sv.status='active' AND vp.lifecycle_status!='archived'
        """).fetchall()]
        for variant in variants:
            cap = variant_open_position_cap(variant)
            rows = [dict(r) for r in db.execute("""
                SELECT *, (COALESCE(current_value, invested_amount, 0) / MAX(COALESCE(invested_amount, 0.01), 0.01)) AS value_ratio
                FROM variant_virtual_trades
                WHERE variant_id=? AND outcome='open'
                ORDER BY value_ratio DESC, created_at DESC
            """, [variant["id"]]).fetchall()]
            excess = rows[cap:]
            restore_cash = round(sum(float(r.get("invested_amount") or 0) for r in excess), 4)
            repaired.append({
                "variant_id": variant["id"],
                "brain": variant["brain"],
                "strategy": variant["strategy"],
                "cap": cap,
                "before_open": len(rows),
                "archived": len(excess),
                "restore_cash": restore_cash,
            })
            if apply_changes and excess:
                ids = [r["id"] for r in excess]
                placeholders = ",".join(["?"] * len(ids))
                db.execute(f"""
                    UPDATE variant_virtual_trades
                    SET outcome='archived_excess_open',
                        sell_reason='system_repaired_open_cap',
                        updated_at=?
                    WHERE id IN ({placeholders})
                """, [now, *ids])
                db.execute("""
                    UPDATE variant_portfolios
                    SET cash=ROUND(cash + ?, 4), updated_at=?
                    WHERE variant_id=?
                """, [restore_cash, now, variant["id"]])
                update_variant_portfolio(db, variant["id"], note="repair_open_cap")
        if apply_changes:
            db.commit()
        return {"success": True, "applied": bool(apply_changes), "repaired": repaired}
    except Exception as exc:
        db.rollback()
        return {"success": False, "error": str(exc), "applied": False, "repaired": repaired}
    finally:
        db.close()

def build_nn_picks_from_scan(price_data, scored_stocks, rsi_values, earnings_soon, scan_type="shared", scan_event_id=None, queue_locked=False):
    """
    Score NN picks from the already-built comprehensive scan snapshot.
    This avoids a second universe fetch and keeps crude + NN on the same data.
    """
    try:
        _nn_model.eval()
        db = get_database()
        open_tickers = set()
        for table in ("virtual_trades", "nn_virtual_trades"):
            try:
                rows = db.execute(f"SELECT ticker FROM {table} WHERE outcome='open'").fetchall()
                open_tickers.update(r["ticker"] for r in rows)
            except Exception:
                pass
        db.close()

        weights = get_signal_weights()
        scored = []
        for base in scored_stocks:
            ticker = base.get("ticker")
            if not ticker or ticker in open_tickers or ticker not in price_data:
                continue

            stock_data = price_data[ticker]
            rsi = rsi_values.get(ticker, base.get("rsi", 50.0))
            earnings = earnings_soon.get(ticker, 99) if isinstance(earnings_soon, dict) else 99
            if earnings <= 1:
                continue

            sig_scores, fired, sig_values = compute_signal_scores(
                ticker, price_data, rsi, earnings_soon, weights, "long"
            )
            synthetic = {
                "ticker": ticker,
                "direction": "long",
                "sector": base.get("sector") or get_sector(ticker),
                "signal_scores": json.dumps({"scores": sig_scores, "fired": fired, "values": sig_values}),
                "lock_in_confidence": base.get("long_conf") or 0,
                "expected_move": base.get("long_move") or 0,
                "day_change_percent": base.get("day_change_pct", stock_data.get("day_change_percent", 0)),
                "broke_52w_high_days_ago": stock_data.get("broke_52w_high_days_ago"),
                "weekend_hold": 0,
                "news_sentiment_score": stock_data.get("news_sentiment_score", 0),
                "news_article_count": stock_data.get("news_article_count", 0),
            }

            nn_conf = nn_score_ticker(synthetic, "long")
            nova_pick = {
                **base,
                "long_conf": nn_conf,
                "long_reasoning": f"NN confidence {nn_conf}% from shared scan",
                "crude_conf": base.get("long_conf"),
                "nn_score": nn_conf,
                "signal_scores_for_observation": sig_scores,
                "signal_values_for_observation": sig_values,
                "fired_signals_for_observation": fired,
                "signal_scores": {
                    "scores": sig_scores,
                    "values": sig_values,
                    "fired": fired,
                },
            }
            nova_pick["nn_executable"] = is_long_pick_eligible(
                nova_pick,
                confidence_floor=NN_CONFIDENCE_FLOOR,
            )
            scored.append({
                **nova_pick,
            })

        scored.sort(key=lambda x: x["long_conf"], reverse=True)
        qualified = [s for s in scored if s.get("nn_executable")]
        top_picks = qualified[:MAX_LONG_PICKS]
        attach_confidence_evidence(top_picks, "long_conf")
        observations_logged = log_nova_signal_observations(scan_event_id, scan_type, scored, price_data, queue_locked)
        result = {
            "scan_type": f"nn_shared_{scan_type}",
            "scan_time": current_time_cst().isoformat(),
            "recommended_longs": top_picks,
            "recommended_shorts": [],
            "total_scanned": len(scored_stocks),
            "qualified_count": len(qualified),
            "ranked_count": len(scored),
            "picks": len(top_picks),
            "source": "shared_comprehensive_scan",
            "observations_logged": observations_logged,
            "message": "No Nova picks qualified above the shared executable gate" if not top_picks else None,
        }

        db = get_database()
        db.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_nn_picks',?)", [json.dumps(result)])
        db.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_nn_picks_time',?)", [current_time_cst().isoformat()])
        db.commit()
        db.close()
        record_nn_scan_status(
            status="complete",
            scan_type=f"shared_{scan_type}",
            finished_at=current_time_cst().isoformat(),
            total_scanned=len(scored_stocks),
            qualified=len(qualified),
            picks=len(top_picks),
            error=None,
        )
        log.info(f"Shared NN scoring: {len(top_picks)} picks, {len(qualified)} qualified, {len(scored)} ranked from {len(scored_stocks)} scanned")
        return result
    except Exception as e:
        log.error(f"Shared NN scoring failed: {e}")
        record_nn_scan_status(
            status="error",
            scan_type=f"shared_{scan_type}",
            finished_at=current_time_cst().isoformat(),
            error=str(e),
        )
        return {
            "recommended_longs": [],
            "recommended_shorts": [],
            "total_scanned": len(scored_stocks or []),
            "qualified_count": 0,
            "picks": 0,
            "source": "shared_comprehensive_scan",
            "error": str(e),
        }

def run_nn_scan(scan_type="scheduled"):
    """
    Run a full scan of the ticker universe using SwingDeskNet instead of
    the weighted crude algo. Uses the same price data pipeline — zero extra
    API calls. Writes picks to cached_nn_picks in app_state.
    Requires signal_scores already computed via compute_signal_scores.
    """
    try:
        _nn_model.eval()
        weights = get_signal_weights()
        universe = build_ticker_universe()

        # Exclude open NN positions
        try:
            _db = get_database()
            open_tickers = set(r["ticker"] for r in _db.execute(
                "SELECT ticker FROM nn_virtual_trades WHERE outcome='open'"
            ).fetchall())
            _db.close()
            universe = [t for t in universe if t not in open_tickers]
        except:
            pass

        universe_with_spy = list(dict.fromkeys(universe + ["SPY"]))
        price_data = fetch_price_data(universe_with_spy)
        enrich_with_live_prices(universe_with_spy, price_data)

        rsi_values = calculate_rsi_batch(list(price_data.keys()), price_data=price_data)
        earnings_soon = check_upcoming_earnings(list(price_data.keys()))
        check_52w_breakouts(list(price_data.keys()), price_data)
        enrich_price_data_with_history(list(price_data.keys()), price_data)

        for ticker in list(price_data.keys()):
            try:
                calculate_support_resistance(ticker, price_data)
            except:
                pass

        scored = []
        scanned_count = 0
        for ticker in universe:
            if ticker not in price_data:
                continue
            scanned_count += 1
            stock_data = price_data[ticker]
            rsi = rsi_values.get(ticker, 50.0)
            earnings = earnings_soon.get(ticker, 99) if isinstance(earnings_soon, dict) else 99
            if earnings <= 1:
                continue

            # Compute signal scores — needed for feature extraction
            sig_scores, fired, sig_values = compute_signal_scores(
                ticker, price_data, rsi, earnings_soon, weights, "long"
            )

            # Build a synthetic trade row for feature extraction
            synthetic = {
                "ticker": ticker,
                "direction": "long",
                "sector": get_sector(ticker),
                "signal_scores": json.dumps({"scores": sig_scores, "fired": fired, "values": sig_values}),
                "lock_in_confidence": 0,
                "expected_move": estimate_overnight_move(stock_data, 70, ticker in earnings_soon),
                "day_change_percent": stock_data.get("day_change_percent", 0),
                "broke_52w_high_days_ago": stock_data.get("broke_52w_high_days_ago"),
                "weekend_hold": 0,
                "news_sentiment_score": stock_data.get("news_sentiment_score", 0),
                "news_article_count": stock_data.get("news_article_count", 0),
            }
            synthetic["lock_in_confidence"] = calculate_confidence_score(
                ticker, stock_data, rsi, earnings_soon, weights, "long"
            )
            synthetic["expected_move"] = estimate_overnight_move(
                stock_data, synthetic["lock_in_confidence"], ticker in earnings_soon
            )

            nn_conf = nn_score_ticker(synthetic, "long")
            if nn_conf < NN_CONFIDENCE_FLOOR:
                continue

            confluence = calculate_method_confluence(ticker, price_data)
            scored.append({
                "ticker": ticker,
                "name": ticker,
                "sector": get_sector(ticker),
                "price": stock_data["price"],
                "rsi": round(rsi, 1),
                "vol_ratio": round(stock_data.get("volume_ratio", 1), 2),
                "overnight_gap_pct": round(stock_data.get("gap_percent", 0), 2),
                "day_change_pct": round(stock_data.get("day_change_percent", 0), 2),
                "long_conf": nn_conf,
                "long_move": synthetic["expected_move"],
                "long_reasoning": f"NN confidence {nn_conf}%",
                "crude_conf": synthetic["lock_in_confidence"],
                "52w_high": stock_data.get("52w_high"),
                "broke_52w_high_days_ago": stock_data.get("broke_52w_high_days_ago"),
                "news": stock_data.get("news", []),
                "confluence_count": confluence["count"],
                "confluence_methods": confluence["methods"],
                "nn_score": nn_conf,
            })

        scored.sort(key=lambda x: x["long_conf"], reverse=True)
        top_picks = scored[:MAX_LONG_PICKS]

        result = {
            "scan_type": f"nn_{scan_type}",
            "scan_time": current_time_cst().isoformat(),
            "recommended_longs": top_picks,
            "recommended_shorts": [],
            "total_scanned": len(scored),
            "qualified_count": len(scored),
            "total_universe_scanned": scanned_count,
        }

        db = get_database()
        db.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_nn_picks',?)",
            [json.dumps(result)])
        db.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_nn_picks_time',?)",
            [current_time_cst().isoformat()])
        db.close()
        log.info(f"NN scan complete: {len(top_picks)} picks from {len(scored)} qualified")
        return result

    except Exception as e:
        log.error(f"NN scan error: {e}")
        return {"recommended_longs": [], "recommended_shorts": [], "total_scanned": 0}

# ── POSITION LIFECYCLE ────────────────────────────────────────────────────────
def lock_pick_queue():
    """
    8:25 AM CST queue lock-in. Freezes the pick queue so no new entries are
    added after this point. The 8:15 AM scan has had 10 minutes to complete.
    Positions still execute at 8:45 AM as usual — this just closes the window
    for new candidates, reflecting the pre-market conviction thesis.
    """
    try:
        database = get_database()
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('queue_locked', 'true')")
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('queue_locked_at', ?)",
                        [current_time_cst().isoformat()])
        database.commit()
        database.close()
        log.info("Pick queue locked at 8:25 AM CST — no new picks until next session")
    except Exception as e:
        log.error(f"Queue lock error: {e}")


def unlock_pick_queue():
    """Unlock the queue at start of next pre-market session (4:00 AM CST)."""
    try:
        database = get_database()
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('queue_locked', 'false')")
        database.commit()
        database.close()
        log.info("Pick queue unlocked — pre-market scanning resumed")
    except Exception as e:
        log.error(f"Queue unlock error: {e}")

def is_pick_queue_locked():
    """Return queue lock state, auto-healing stale locks before the 8:25 AM cutoff."""
    now = current_time_cst()
    cutoff = now.replace(hour=8, minute=25, second=0, microsecond=0)
    if now < cutoff:
        try:
            database = get_database()
            database.execute("INSERT OR REPLACE INTO app_state VALUES ('queue_locked', 'false')")
            database.commit()
            database.close()
        except Exception:
            pass
        return False
    try:
        database = get_database()
        row = database.execute("SELECT value FROM app_state WHERE key='queue_locked'").fetchone()
        database.close()
        return bool(row and row["value"] == "true")
    except Exception:
        return False


def _execute_opening_positions_legacy():
    """
    Execute at 8:45 AM CST: Convert committed picks into open positions.
    
    Each position's invested amount is drawn from the trade queue (FIFO).
    If the queue is empty, falls back to DEFAULT_INVESTMENT ($10.00).
    
    Queue amounts are assigned to picks in randomized order to avoid
    systematic bias when multiple positions open simultaneously.
    """
    today = current_time_cst().strftime("%Y-%m-%d")
    database = get_database()
    cached = database.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
    database.close()

    if not cached:
        log.info("No cached picks to execute")
        return

    picks = json.loads(cached["value"])
    is_friday = current_time_cst().weekday() == 4

    # Shorts are disabled — only execute long picks.
    # Virtual short execution requires short-specific signals to be meaningful.
    all_picks = picks.get("longs", [])[:MAX_LONG_PICKS]

    # Fetch current prices at execution time (8:45 AM) — pin to 8:45 candle for accuracy
    tickers = [pick["ticker"] for pick in all_picks]
    current_prices = fetch_current_prices(tickers, pin_to_845=True)

    # Randomize order to avoid systematic bias in queue assignment
    indexed_picks = list(enumerate(all_picks))
    random.shuffle(indexed_picks)

    opened_count = 0
    for original_index, pick in indexed_picks:
        direction = "long" if original_index < MAX_LONG_PICKS else "short"
        ticker = pick["ticker"]
        raw_price = current_prices.get(ticker)
        buy_price = (raw_price["price"] if isinstance(raw_price, dict) else raw_price) or pick.get("open_price", pick["price"])
        confidence = pick["long_conf"] if direction == "long" else pick["short_conf"]
        expected_move = pick["long_move"] if direction == "long" else pick["short_move"]
        reasoning = pick.get("long_reasoning", "") if direction == "long" else pick.get("short_reasoning", "")

        # Draw investment amount from queue
        queue_id, invested_amount = get_next_queue_amount()

        trade_id = f"{ticker}_{today}_{direction}_vt"
        existing = database if False else get_database()  # Fresh connection
        if existing.execute("SELECT id FROM virtual_trades WHERE id=?", [trade_id]).fetchone():
            existing.close()
            continue

        # Calculate closed_days: how many non-trading days between buy and next sell day
        # Friday = 3 (Sat+Sun+Mon if holiday, or just Sat+Sun normally)
        # All other days = 1 (just overnight)
        day_of_week = current_time_cst().weekday()
        if day_of_week == 4:  # Friday
            # Check if Monday is a holiday (like Memorial Day) — default to 3, holidays add more
            closed_days = 3  # Sat + Sun + overnight
        else:
            closed_days = 1  # Just overnight

        # Compute signal scores at open time for display on position cards
        try:
            _weights = get_signal_weights()
            _earnings = check_upcoming_earnings([ticker])
            # Pull real cached price data (with daily_history) from scan cache
            _cached_row = existing.execute(
                "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
            ).fetchone()
            if _cached_row:
                try:
                    _cached_payload = json.loads(_cached_row["value"])
                    _cached_data = _cached_payload.get("data") or {}
                    _cached_data["price"] = buy_price  # pin to execution price
                    _open_price_data = {ticker: _cached_data}
                except Exception:
                    _open_price_data = {ticker: {
                        "price": buy_price,
                        "volume_ratio": pick.get("vol_ratio", 1.0),
                        "gap_percent": pick.get("overnight_gap_pct", 0),
                        "day_change_percent": pick.get("day_change_pct", 0),
                        "daily_history": [],
                    }}
            else:
                _open_price_data = {ticker: {
                    "price": buy_price,
                    "volume_ratio": pick.get("vol_ratio", 1.0),
                    "gap_percent": pick.get("overnight_gap_pct", 0),
                    "day_change_percent": pick.get("day_change_pct", 0),
                    "daily_history": [],
                }}
            _sig_scores, _fired, _values = compute_signal_scores(ticker, _open_price_data, pick.get("rsi", 50.0), _earnings, _weights, direction)
            _signal_scores_json = json.dumps({"scores": _sig_scores, "fired": _fired, "values": _values})
        except:
            _signal_scores_json = json.dumps({"scores": {}, "fired": []})

        # Get news sentiment and 52w data from picks cache
        _news_sentiment = 0.0
        _news_count = 0
        _52w_days_ago = None
        try:
            _cached = json.loads(existing.execute(
                "SELECT value FROM app_state WHERE key='cached_picks'"
            ).fetchone()["value"] or "{}")
            for _p in _cached.get("recommended_longs", []):
                if _p.get("ticker") == ticker:
                    _news_sentiment = float(_p.get("news_sentiment_score") or 0)
                    _news_count = int(_p.get("news_article_count") or 0)
                    _52w_days_ago = _p.get("broke_52w_high_days_ago")
                    break
        except:
            pass

        fee_quote = calculate_stock_fee_model(invested_amount, buy_price, buy_price, direction)
        existing.execute(f"""
            INSERT INTO virtual_trades
            (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
             confidence, lock_in_confidence, expected_move, outcome, sector, reasoning, closed_days,
             status, current_value, intraday_high_pct, intraday_low_pct, queue_position,
             signal_scores, news_sentiment_score, news_article_count, broke_52w_high_days_ago,
             {FEE_MODEL_INSERT_COLUMNS})
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,{FEE_MODEL_INSERT_PLACEHOLDERS})
        """, [trade_id, ticker, direction, today, "08:45:00", buy_price,
              round(invested_amount, 4), confidence, confidence, expected_move, "open",
              get_sector(ticker), reasoning, closed_days,
              "open", fee_quote["net_current_value"], 0.0, 0.0, queue_id,
              _signal_scores_json, _news_sentiment, _news_count, _52w_days_ago,
              *fee_model_values(fee_quote)])
        existing.commit()
        existing.close()

        # Mark queue amount as consumed
        consume_queue_amount(queue_id, trade_id)
        opened_count += 1

    log.info(f"Opened {opened_count} positions at 8:45 AM CST")

def execute_opening_positions(trigger="scheduled", buy_time="08:45:00"):
    """
    Convert cached picks into open positions and persist a diagnostic payload.

    Safe to run more than once: existing trade ids for today's ticker/direction
    are skipped before any queue amount is consumed.
    """
    attempted_at = current_time_cst().isoformat()
    status = {
        "trigger": trigger,
        "attempted_at": attempted_at,
        "success_at": None,
        "cached_pick_count": 0,
        "opened_count": 0,
        "skipped_count": 0,
        "queue_consumed_count": 0,
        "fallback_count": 0,
        "opened": [],
        "skipped": [],
        "last_error": None,
    }
    record_open_execution_status(status)

    try:
        today = current_time_cst().strftime("%Y-%m-%d")
        database = get_database()
        cached = database.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
        database.close()

        if not cached:
            status["last_error"] = "No cached picks to execute"
            log.warning(status["last_error"])
            return record_open_execution_status(status)

        picks = json.loads(cached["value"])
        cached_longs = picks.get("longs") or picks.get("recommended_longs") or []
        all_picks = cached_longs[:MAX_LONG_PICKS]
        status["cached_pick_count"] = len(all_picks)

        if not all_picks:
            status["last_error"] = "Cached picks contained zero long picks"
            log.warning(status["last_error"])
            return record_open_execution_status(status)

        tickers = [pick["ticker"] for pick in all_picks if pick.get("ticker")]
        try:
            current_prices = fetch_current_prices(tickers, pin_to_845=True) if tickers else {}
        except Exception as price_error:
            current_prices = {}
            status["last_error"] = f"Price fetch failed; using cached pick prices: {price_error}"
            log.warning(status["last_error"])

        indexed_picks = list(enumerate(all_picks))
        random.shuffle(indexed_picks)

        for original_index, pick in indexed_picks:
            direction = "long" if original_index < MAX_LONG_PICKS else "short"
            ticker = pick.get("ticker")
            if not ticker:
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": None, "reason": "missing ticker"})
                continue

            trade_id = f"{ticker}_{today}_{direction}_vt"
            existing = get_database()
            if existing.execute("SELECT id FROM virtual_trades WHERE id=?", [trade_id]).fetchone():
                existing.close()
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": ticker, "reason": "already executed today"})
                continue

            raw_price = current_prices.get(ticker)
            buy_price = (raw_price["price"] if isinstance(raw_price, dict) else raw_price) or pick.get("open_price") or pick.get("price") or 0
            if not buy_price or buy_price <= 0:
                log.warning(f"Skipping {ticker} — no valid buy price at execution (price fetch failed)")
                existing.close()
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": ticker, "reason": "no_valid_buy_price"})
                continue
            confidence = pick.get("long_conf") if direction == "long" else pick.get("short_conf")
            expected_move = pick.get("long_move") if direction == "long" else pick.get("short_move")
            reasoning = pick.get("long_reasoning", "") if direction == "long" else pick.get("short_reasoning", "")

            queue_id, invested_amount = get_next_queue_amount()

            closed_days = 3 if current_time_cst().weekday() == 4 else 1

            try:
                _weights = get_signal_weights()
                _earnings = check_upcoming_earnings([ticker])
                # Pull real cached price data (with daily_history) from scan cache
                _cached_row = existing.execute(
                    "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
                ).fetchone()
                if _cached_row:
                    try:
                        _cached_payload = json.loads(_cached_row["value"])
                        _cached_data = _cached_payload.get("data") or {}
                        _cached_data["price"] = buy_price  # pin to execution price
                        _open_price_data = {ticker: _cached_data}
                    except Exception:
                        _open_price_data = {ticker: {
                            "price": buy_price,
                            "volume_ratio": pick.get("vol_ratio", 1.0),
                            "gap_percent": pick.get("overnight_gap_pct", 0),
                            "day_change_percent": pick.get("day_change_pct", 0),
                            "daily_history": [],
                        }}
                else:
                    _open_price_data = {ticker: {
                        "price": buy_price,
                        "volume_ratio": pick.get("vol_ratio", 1.0),
                        "gap_percent": pick.get("overnight_gap_pct", 0),
                        "day_change_percent": pick.get("day_change_pct", 0),
                        "daily_history": [],
                    }}
                _sig_scores, _fired, _values = compute_signal_scores(
                    ticker, _open_price_data, pick.get("rsi", 50.0),
                    _earnings, _weights, direction
                )
                _signal_scores_json = json.dumps({"scores": _sig_scores, "fired": _fired, "values": _values})
            except Exception as signal_error:
                log.warning(f"Signal snapshot failed for {ticker}: {signal_error}")
                _signal_scores_json = json.dumps({"scores": {}, "fired": []})

            _news_sentiment = 0.0
            _news_count = 0
            _52w_days_ago = pick.get("broke_52w_high_days_ago")
            try:
                _news_sentiment = float(pick.get("news_sentiment_score") or 0)
                _news_count = int(pick.get("news_article_count") or len(pick.get("news", []) or []))
            except Exception:
                pass

            try:
                fee_quote = calculate_stock_fee_model(invested_amount, buy_price, buy_price, direction)
                existing.execute(f"""
                    INSERT INTO virtual_trades
                    (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
                     confidence, lock_in_confidence, expected_move, outcome, sector, reasoning, closed_days,
                     status, current_value, intraday_high_pct, intraday_low_pct, queue_position,
                     signal_scores, news_sentiment_score, news_article_count, broke_52w_high_days_ago,
                     {FEE_MODEL_INSERT_COLUMNS})
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,{FEE_MODEL_INSERT_PLACEHOLDERS})
                """, [trade_id, ticker, direction, today, buy_time, buy_price,
                      round(invested_amount, 4), confidence, confidence, expected_move, "open",
                      get_sector(ticker), reasoning, closed_days,
                      "open", fee_quote["net_current_value"], 0.0, 0.0, queue_id,
                      _signal_scores_json, _news_sentiment, _news_count, _52w_days_ago,
                      *fee_model_values(fee_quote)])
                existing.commit()
                existing.close()
                consume_queue_amount(queue_id, trade_id)
                if queue_id is None:
                    status["fallback_count"] += 1
                else:
                    status["queue_consumed_count"] += 1
                status["opened_count"] += 1
                status["opened"].append({
                    "ticker": ticker,
                    "trade_id": trade_id,
                    "buy_price": buy_price,
                    "invested_amount": round(invested_amount, 4),
                    "queue_id": queue_id,
                })
            except Exception as insert_error:
                existing.close()
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": ticker, "reason": str(insert_error)})
                log.error(f"Open execution failed for {ticker}: {insert_error}")

        status["success_at"] = current_time_cst().isoformat()
        if status["opened_count"] > 0:
            status["last_error"] = None
        log.info(
            f"Open execution {trigger}: opened {status['opened_count']}, "
            f"skipped {status['skipped_count']}, cached {status['cached_pick_count']}"
        )
        return record_open_execution_status(status)
    except Exception as error:
        status["last_error"] = str(error)
        log.error(f"Open execution {trigger} failed: {error}")
        return record_open_execution_status(status)

def execute_nn_opening_positions(trigger="scheduled", buy_time="08:45:00"):
    """
    Convert cached NN picks into open NN portfolio positions.
    The NN portfolio has independent capital and does not consume the main queue.
    """
    status = {
        "trigger": trigger,
        "attempted_at": current_time_cst().isoformat(),
        "success_at": None,
        "cached_pick_count": 0,
        "opened_count": 0,
        "skipped_count": 0,
        "opened": [],
        "skipped": [],
        "last_error": None,
    }
    record_nn_open_execution_status(status)

    try:
        today = current_time_cst().strftime("%Y-%m-%d")
        database = get_database()
        cached = database.execute("SELECT value FROM app_state WHERE key='cached_nn_picks'").fetchone()
        database.close()

        if not cached:
            status["last_error"] = "No cached NN picks to execute"
            log.warning(status["last_error"])
            return record_nn_open_execution_status(status)

        picks = json.loads(cached["value"])
        cached_longs = (picks.get("recommended_longs") or picks.get("longs") or [])
        all_picks = [p for p in cached_longs if p.get("nn_executable", True)][:MAX_LONG_PICKS]
        status["cached_pick_count"] = len(all_picks)

        if not all_picks:
            status["last_error"] = "Cached NN picks contained zero long picks"
            log.warning(status["last_error"])
            return record_nn_open_execution_status(status)

        tickers = [pick["ticker"] for pick in all_picks if pick.get("ticker")]
        try:
            current_prices = fetch_current_prices(tickers, pin_to_845=True) if tickers else {}
        except Exception as price_error:
            current_prices = {}
            status["last_error"] = f"NN price fetch failed; using cached pick prices: {price_error}"
            log.warning(status["last_error"])

        indexed_picks = list(enumerate(all_picks))
        random.shuffle(indexed_picks)

        for original_index, pick in indexed_picks:
            ticker = pick.get("ticker")
            if not ticker:
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": None, "reason": "missing ticker"})
                continue

            direction = "long"
            trade_id = f"nn_{ticker}_{today}_{direction}_vt"
            existing = get_database()
            if existing.execute("SELECT id FROM nn_virtual_trades WHERE id=?", [trade_id]).fetchone():
                existing.close()
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": ticker, "reason": "already executed today"})
                continue

            raw_price = current_prices.get(ticker)
            buy_price = (raw_price["price"] if isinstance(raw_price, dict) else raw_price) or pick.get("open_price") or pick.get("price") or 0
            if not buy_price:
                existing.close()
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": ticker, "reason": "missing buy price"})
                continue

            nn_confidence = int(round(float(pick.get("nn_score") or pick.get("long_conf") or 0)))
            crude_confidence = int(round(float(pick.get("crude_conf") or pick.get("confidence") or nn_confidence)))
            expected_move = float(pick.get("long_move") or pick.get("expected_move") or 0)
            invested_amount = get_nn_investment_amount()
            reasoning = pick.get("long_reasoning") or f"NN confidence {nn_confidence}%"

            try:
                weights = get_signal_weights()
                earnings = check_upcoming_earnings([ticker])
                # Pull real cached price data (with daily_history) from scan cache
                _cached_row = existing.execute(
                    "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
                ).fetchone()
                if _cached_row:
                    try:
                        _cached_payload = json.loads(_cached_row["value"])
                        _cached_data = _cached_payload.get("data") or {}
                        _cached_data["price"] = buy_price  # pin to execution price
                        open_price_data = {ticker: _cached_data}
                    except Exception:
                        open_price_data = {ticker: {
                            "price": buy_price,
                            "volume_ratio": pick.get("vol_ratio", 1.0),
                            "gap_percent": pick.get("overnight_gap_pct", 0),
                            "day_change_percent": pick.get("day_change_pct", 0),
                            "daily_history": [],
                        }}
                else:
                    open_price_data = {ticker: {
                        "price": buy_price,
                        "volume_ratio": pick.get("vol_ratio", 1.0),
                        "gap_percent": pick.get("overnight_gap_pct", 0),
                        "day_change_percent": pick.get("day_change_pct", 0),
                        "daily_history": [],
                    }}
                sig_scores, fired, sig_values = compute_signal_scores(
                    ticker, open_price_data, pick.get("rsi", 50.0), earnings, weights, direction
                )
                signal_scores_json = json.dumps({"scores": sig_scores, "fired": fired, "values": sig_values})
            except Exception as signal_error:
                log.warning(f"NN signal snapshot failed for {ticker}: {signal_error}")
                signal_scores_json = json.dumps({"scores": {}, "fired": [], "values": {}})

            try:
                confluence_methods = json.dumps(pick.get("confluence_methods") or [])
            except Exception:
                confluence_methods = "[]"

            try:
                fee_quote = calculate_stock_fee_model(invested_amount, buy_price, buy_price, direction)
                existing.execute(f"""
                    INSERT INTO nn_virtual_trades
                    (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
                     current_value, confidence, nn_confidence, lock_in_confidence, expected_move,
                     outcome, sector, reasoning, intraday_high_pct, intraday_low_pct,
                     dynamic_confidence, dynamic_estimate, confluence_count, confluence_methods,
                     signal_scores, day_change_percent, news_sentiment_score, news_article_count,
                     {FEE_MODEL_INSERT_COLUMNS}, last_price_updated)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,{FEE_MODEL_INSERT_PLACEHOLDERS},?)
                """, [
                    trade_id, ticker, direction, today, buy_time, buy_price,
                    round(invested_amount, 4), fee_quote["net_current_value"],
                    crude_confidence, nn_confidence, nn_confidence, expected_move,
                    "open", get_sector(ticker), reasoning, 0.0, 0.0,
                    nn_confidence, expected_move, int(pick.get("confluence_count") or 0),
                    confluence_methods, signal_scores_json, pick.get("day_change_pct", 0),
                    float(pick.get("news_sentiment_score") or 0),
                    int(pick.get("news_article_count") or len(pick.get("news", []) or [])),
                    *fee_model_values(fee_quote),
                    current_time_cst().isoformat()
                ])
                existing.commit()
                existing.close()
                status["opened_count"] += 1
                status["opened"].append({
                    "ticker": ticker,
                    "trade_id": trade_id,
                    "buy_price": buy_price,
                    "invested_amount": round(invested_amount, 4),
                    "nn_confidence": nn_confidence,
                })
            except Exception as insert_error:
                existing.close()
                status["skipped_count"] += 1
                status["skipped"].append({"ticker": ticker, "reason": str(insert_error)})
                log.error(f"NN open execution failed for {ticker}: {insert_error}")

        status["success_at"] = current_time_cst().isoformat()
        if status["opened_count"] > 0:
            status["last_error"] = None
        log.info(
            f"NN open execution {trigger}: opened {status['opened_count']}, "
            f"skipped {status['skipped_count']}, cached {status['cached_pick_count']}"
        )
        return record_nn_open_execution_status(status)
    except Exception as error:
        status["last_error"] = str(error)
        log.error(f"NN open execution {trigger} failed: {error}")
        return record_nn_open_execution_status(status)

def monitor_nn_open_positions():
    """Update and settle open NN positions using the NN portfolio ledger."""
    database = get_database()
    open_positions = [dict(t) for t in database.execute(
        "SELECT * FROM nn_virtual_trades WHERE outcome='open'"
    ).fetchall()]
    database.close()

    if not open_positions:
        return

    tickers = list(set(position["ticker"] for position in open_positions))
    current_prices = fetch_current_prices(tickers)
    now = current_time_cst()
    today = now.strftime("%Y-%m-%d")
    database = get_database()
    updated_count = 0
    closed_count = 0

    for position in open_positions:
        ticker = position["ticker"]
        raw = current_prices.get(ticker)
        if not raw:
            continue
        buy_price = float(position["buy_price"] or 0)
        price_data = normalize_monitor_quote(raw, buy_price)
        price = price_data["price"]
        day_change_pct = price_data.get("day_change_pct", 0)
        buy_price = float(position["buy_price"] or price)
        invested = float(position["invested_amount"] or DEFAULT_INVESTMENT)
        pnl_percent = (price - buy_price) / buy_price * 100
        if position["direction"] == "short":
            pnl_percent = -pnl_percent
        pnl_dollars = invested * (pnl_percent / 100)
        fee_quote = calculate_stock_fee_model(invested, buy_price, price, position["direction"])
        current_value = fee_quote["net_current_value"]
        high_pct = max(position.get("intraday_high_pct") or 0, pnl_percent)
        low_pct = min(position.get("intraday_low_pct") or 0, pnl_percent)

        dyn_conf = position.get("dynamic_confidence") or position.get("nn_confidence") or position.get("confidence") or 0
        dyn_est = position.get("dynamic_estimate") or position.get("expected_move") or 0
        signal_scores_json = position.get("signal_scores") or json.dumps({"scores": {}, "fired": [], "values": {}})
        conf_count = position.get("confluence_count") or 0
        conf_methods = position.get("confluence_methods") or "[]"

        try:
            price_data_for_dynamic = {ticker: {
                "price": price,
                "previous_close": price_data.get("previous_close", buy_price),
                "open": price_data.get("open", price),
                "high": price_data.get("high", price),
                "low": price_data.get("low", price),
                "volume": price_data.get("volume", 0),
                "average_volume": price_data.get("average_volume", 1),
                "volume_ratio": price_data.get("volume_ratio", 1.0),
                "gap_percent": price_data.get("gap_percent", 0),
                "day_change_percent": day_change_pct,
            }}
            # Pull daily_history from scan cache so RSI/S&R/RS/Squeeze compute from real data
            try:
                _cache_row = database.execute(
                    "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
                ).fetchone()
                if _cache_row:
                    _cached = json.loads(_cache_row["value"]).get("data") or {}
                    if _cached.get("daily_history"):
                        price_data_for_dynamic[ticker]["daily_history"] = _cached["daily_history"]
            except Exception:
                pass
            weights = get_signal_weights()
            earnings = check_upcoming_earnings([ticker])
            rsi_val = calculate_rsi_batch([ticker], price_data=price_data_for_dynamic).get(ticker, 50.0)
            sig_scores, fired, sig_values = compute_signal_scores(
                ticker, price_data_for_dynamic[ticker], rsi_val, earnings, weights, position["direction"]
            )
            signal_scores_json = json.dumps({"scores": sig_scores, "fired": fired, "values": sig_values})
            synthetic = {
                **position,
                "signal_scores": signal_scores_json,
                "lock_in_confidence": position.get("lock_in_confidence") or position.get("nn_confidence") or 0,
                "expected_move": position.get("expected_move") or 0,
                "day_change_percent": day_change_pct,
            }
            dyn_conf = nn_score_ticker(synthetic, position["direction"])
            dyn_est = estimate_overnight_move(price_data_for_dynamic[ticker], dyn_conf, ticker in earnings)
            confluence = calculate_method_confluence(ticker, price_data_for_dynamic)
            conf_count = confluence["count"]
            conf_methods = json.dumps(confluence["methods"])
        except Exception as dynamic_error:
            log.debug(f"NN dynamic update skipped for {ticker}: {dynamic_error}")

        database.execute(f"""
            UPDATE nn_virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?,
            dynamic_confidence=?, dynamic_estimate=?, confluence_count=?, confluence_methods=?,
            signal_scores=?, last_price_updated=?, day_change_percent=?,
            {FEE_MODEL_UPDATE_SET}
            WHERE id=?
        """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2),
              dyn_conf, round(float(dyn_est or 0), 1), conf_count, conf_methods,
              signal_scores_json, now.isoformat(), day_change_pct,
              *fee_model_values(fee_quote), position["id"]])
        updated_count += 1

        if not is_market_open():
            continue

        is_sell_day = position["buy_date"] < today
        if is_sell_day and now.hour >= 8 and now.hour < 15:
            should_sell, reason, sentiment = evaluate_sell_decision(position, price)
            if should_sell:
                outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")
                database.execute(f"""
                    UPDATE nn_virtual_trades SET
                        sell_date=?, sell_time=?, sell_price=?, current_value=?,
                        actual_move=?, gross_pnl=?, net_pnl=?, {FEE_MODEL_UPDATE_SET},
                        outcome=?, sell_reason=?
                    WHERE id=?
                """, [today, now.strftime("%H:%M:%S"), price,
                      round(current_value, 4), round(pnl_percent, 2),
                      fee_quote["gross_pnl"], fee_quote["net_pnl"], *fee_model_values(fee_quote),
                      outcome, reason, position["id"]])
                closed_count += 1
                log.info(f"NN CLOSED {ticker} | {reason} | {pnl_percent:+.1f}% | ${pnl_dollars:+.2f}")

    database.commit()
    database.close()
    log.info(f"Monitored {updated_count} NN positions, closed {closed_count}")

def _monitor_open_positions_impl():
    """
    5-minute monitoring cycle for candidates and open positions.
    
    For open positions on their sell day (bought previous session):
    - Evaluates sell decision using the dynamic sell engine
    - Logs position check for intraday chart data
    - Executes sell if engine decides to exit
    
    For open positions on their buy day (bought today):
    - Only logs price data for chart tracking (no sell decisions)
    
    For candidates (not yet traded):
    - Tracks price movement for brain learning
    """
    database = get_database()
    open_positions = [dict(t) for t in database.execute(
        "SELECT * FROM virtual_trades WHERE outcome='open'"
    ).fetchall()]
    monitored_candidates = [dict(c) for c in database.execute(
        "SELECT * FROM candidates WHERE monitoring = 1"
    ).fetchall()]
    database.close()

    if not open_positions and not monitored_candidates:
        status = record_monitor_status(
            status="complete",
            started=False,
            total_open_positions=0,
            updated_count=0,
            current_ticker=None,
            last_success_at=current_time_cst().isoformat(),
            finished_at=current_time_cst().isoformat(),
            error=None,
        )
        maybe_send_monitor_recovery_alert(status)
        return

    # Combine all tickers that need price checks
    all_tickers = list(set(
        [position["ticker"] for position in open_positions] +
        [candidate["ticker"] for candidate in monitored_candidates]
    ))

    if not all_tickers:
        status = record_monitor_status(
            status="complete",
            started=False,
            total_open_positions=len(open_positions),
            updated_count=0,
            current_ticker=None,
            last_success_at=current_time_cst().isoformat(),
            finished_at=current_time_cst().isoformat(),
            error=None,
        )
        maybe_send_monitor_recovery_alert(status)
        return

    monitor_event_id = begin_scan_event("open_position_monitor", job_type="monitor", tickers_attempted=len(all_tickers))
    record_monitor_status(
        status="running",
        started=True,
        started_at=current_time_cst().isoformat(),
        finished_at=None,
        total_open_positions=len(open_positions),
        total_tickers=len(all_tickers),
        updated_count=0,
        current_ticker=None,
        error=None,
    )
    current_prices = fetch_current_prices(all_tickers)
    now = current_time_cst()
    today = now.strftime("%Y-%m-%d")
    database = get_database()
    updated_open_count = 0

    # Load last known prices for stale detection
    last_price_cache = {}
    for ticker in all_tickers:
        cached = database.execute(
            "SELECT value FROM app_state WHERE key=?", [f"last_monitor_price_{ticker}"]
        ).fetchone()
        if cached:
            try:
                last_price_cache[ticker] = json.loads(cached["value"])
            except:
                pass

    for position in open_positions:
        ticker = position["ticker"]
        database.commit()
        record_monitor_status(
            status="running",
            current_ticker=ticker,
            total_open_positions=len(open_positions),
            updated_count=updated_open_count,
        )
        if ticker not in current_prices:
            database.execute("""
                INSERT INTO position_checks (position_id, check_time, price, pnl_percent, sentiment, ticker)
                VALUES (?,?,?,?,?,?)
            """, [position["id"], now.isoformat(), None, None, "stale: no fresh provider price", ticker])
            database.commit()
            continue

        price_data = normalize_monitor_quote(current_prices[ticker], position.get("buy_price"))
        price = price_data["price"]
        day_change_pct = price_data.get("day_change_pct", 0)

        # Stale price detection — if price is identical to last 3 consecutive checks
        # during market hours, skip sell decisions (possible halt or bad data)
        last_known = last_price_cache.get(ticker, {})
        last_price = last_known.get("price")
        stale_count = last_known.get("stale_count", 0)

        if last_price is not None and abs(price - last_price) < 0.001:
            stale_count += 1
        else:
            stale_count = 0

        database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
            [f"last_monitor_price_{ticker}", json.dumps({"price": price, "stale_count": stale_count})])
        database.commit()

        # Stale price guard — if price unchanged 3+ checks during market hours, skip
        if stale_count >= 3 and is_market_open():
            log.warning(f"{ticker} price unchanged for {stale_count} checks — possible halt, freezing P&L")
            continue

        # Determine session context
        in_extended, in_premarket = is_extended_hours()
        after_hours = not is_market_open() and not in_extended
        extended_hours = in_extended and not is_market_open()

        # Always write price updates — during regular hours AND pre/post market
        # Skip only on weekends when markets are fully closed
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            continue

        buy_price = position["buy_price"]
        invested = position["invested_amount"] or DEFAULT_INVESTMENT
        pnl_percent = (price - buy_price) / buy_price * 100
        if position["direction"] == "short":
            pnl_percent = -pnl_percent
        pnl_dollars = invested * (pnl_percent / 100)
        fee_quote = calculate_stock_fee_model(invested, buy_price, price, position["direction"])
        baseline_data = monitor_baselines(position, price_data, pnl_percent)
        pct_prev_close = baseline_data["pct_prev_close"]
        pct_regular_open = baseline_data["pct_regular_open"]
        pct_entry = baseline_data["pct_entry"]
        entry_integrity_status, entry_integrity_note = baseline_data["entry_integrity"]

        # Update current value, intraday extremes, and dynamic scores
        current_value = fee_quote["net_current_value"]
        high_pct = max(position.get("intraday_high_pct") or 0, pnl_percent)
        low_pct = min(position.get("intraday_low_pct") or 0, pnl_percent)

        # Calculate and persist dynamic confidence and estimate
        # Use all available fields from the enriched live quote — not skeleton defaults
        price_data_for_dynamic = {
            ticker: {
                "price": price,
                "previous_close": price_data.get("previous_close", position.get("buy_price", price)),
                "open": price_data.get("open", price),
                "high": price_data.get("high", price),
                "low": price_data.get("low", price),
                "volume": price_data.get("volume", 0),
                "average_volume": price_data.get("average_volume", 1),
                "volume_ratio": price_data.get("volume_ratio", 1.0),
                "gap_percent": price_data.get("gap_percent", 0),
                "day_change_percent": day_change_pct,
            }
        }
        # Pull daily_history from scan cache so RSI/S&R/RS/Squeeze compute from real data
        # during monitoring instead of always returning neutral 0.5 defaults
        try:
            _cache_row = database.execute(
                "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
            ).fetchone()
            if _cache_row:
                _cached = json.loads(_cache_row["value"]).get("data") or {}
                if _cached.get("daily_history"):
                    price_data_for_dynamic[ticker]["daily_history"] = _cached["daily_history"]
        except Exception:
            pass
        try:
            weights = get_signal_weights()
            earnings_soon = check_upcoming_earnings([ticker])
            rsi_val = calculate_rsi_batch([ticker], price_data=price_data_for_dynamic).get(ticker, 50.0)
            dyn_conf = calculate_confidence_score(ticker, price_data_for_dynamic[ticker], rsi_val, earnings_soon, weights, position["direction"])
            dyn_est = estimate_overnight_move(price_data_for_dynamic[ticker], dyn_conf, ticker in earnings_soon)

            # Day 2 time-decay — tighten confidence as 2:45 PM deadline approaches
            is_sell_day_check = position["buy_date"] < today
            if is_sell_day_check and is_market_open():
                minutes_left = minutes_until_forced_close()
                total_day_minutes = 375
                time_elapsed_pct = max(0, (total_day_minutes - minutes_left) / total_day_minutes)
                decay = 1.0 - (time_elapsed_pct * 0.4)
                dyn_conf = max(1, round(dyn_conf * decay))
                log.debug(f"{ticker} Day 2 confidence decay: {decay:.2f}x → {dyn_conf}% ({minutes_left:.0f}min left)")
        except:
            dyn_conf = position.get("dynamic_confidence") or position.get("confidence", 0)
            dyn_est = position.get("dynamic_estimate") or position.get("expected_move", 0)

        try:
            conf_data = calculate_method_confluence(ticker, {ticker: {"price": price, "volume_ratio": 1.0, "gap_percent": 0, "day_change_percent": pnl_percent}})
            conf_count = conf_data["count"]
            conf_methods = json.dumps(conf_data["methods"])
        except:
            conf_count = position.get("confluence_count") or 0
            conf_methods = position.get("confluence_methods") or "[]"

        # Refresh signal_scores during monitoring
        try:
            _weights = get_signal_weights()
            _earnings_m = check_upcoming_earnings([ticker])
            _sig_scores, _fired, _values = compute_signal_scores(
                ticker, price_data_for_dynamic[ticker],
                rsi_val if "rsi_val" in dir() else 50.0,
                _earnings_m, _weights, position["direction"]
            )
            _signal_scores_json = json.dumps({"scores": _sig_scores, "fired": _fired, "values": _values})
        except:
            _signal_scores_json = position.get("signal_scores") or json.dumps({"scores": {}, "fired": []})

        try:
            database.execute(f"""
                UPDATE virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?,
                dynamic_confidence=?, dynamic_estimate=?, confluence_count=?, confluence_methods=?,
                signal_scores=?, last_price_updated=?, day_change_percent=?,
                pct_change_prev_close=?, pct_change_regular_open=?, pct_change_entry=?,
                entry_price_source=COALESCE(entry_price_source, ?),
                entry_integrity_status=?, entry_integrity_note=?,
                {FEE_MODEL_UPDATE_SET}
                WHERE id=?
            """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2),
                  dyn_conf, round(dyn_est, 1), conf_count, conf_methods,
                  _signal_scores_json, now.isoformat(), day_change_pct,
                  round(pct_prev_close, 4) if pct_prev_close is not None else None,
                  round(pct_regular_open, 4) if pct_regular_open is not None else None,
                  round(pct_entry, 4),
                  price_data.get("source", "unknown"),
                  entry_integrity_status, entry_integrity_note,
                  *fee_model_values(fee_quote), position["id"]])
        except:
            database.execute(f"""
                UPDATE virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?,
                last_price_updated=?, day_change_percent=?,
                pct_change_prev_close=?, pct_change_regular_open=?, pct_change_entry=?,
                entry_price_source=COALESCE(entry_price_source, ?),
                entry_integrity_status=?, entry_integrity_note=?,
                {FEE_MODEL_UPDATE_SET}
                WHERE id=?
            """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2),
                  now.isoformat(), day_change_pct,
                  round(pct_prev_close, 4) if pct_prev_close is not None else None,
                  round(pct_regular_open, 4) if pct_regular_open is not None else None,
                  round(pct_entry, 4),
                  price_data.get("source", "unknown"),
                  entry_integrity_status, entry_integrity_note,
                  *fee_model_values(fee_quote), position["id"]])

        # Refresh news for open positions — once per monitor cycle, rate-limited
        # Only refresh if news is stale (>30 min old) to stay within Alpha Vantage limits
        updated_open_count += 1
        database.commit()
        record_monitor_status(
            status="running",
            current_ticker=ticker,
            total_open_positions=len(open_positions),
            updated_count=updated_open_count,
        )

        try:
            news_key = f"last_news_fetch_{ticker}"
            last_news_row = database.execute("SELECT value FROM app_state WHERE key=?", [news_key]).fetchone()
            last_news_ts = float(last_news_row["value"]) if last_news_row else 0
            if time.time() - last_news_ts > 1800:  # 30 min stale threshold
                av_articles, av_sentiment, av_count = _fetch_news_alpha_vantage(ticker)
                fresh_news = av_articles or _fetch_news_yahoo_rss(ticker)
                if fresh_news:
                    database.execute(
                        "UPDATE virtual_trades SET news=?, news_sentiment_score=?, news_article_count=? WHERE id=?",
                        [json.dumps(fresh_news), av_sentiment, av_count, position["id"]]
                    )
                database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                    [news_key, str(time.time())])
        except Exception as e:
            log.debug(f"News refresh skipped for {ticker}: {e}")

        database.commit()
        # Skip sell decisions outside regular market hours
        if not is_market_open():
            continue

        # Determine if this is the sell day (position was opened before today)
        is_sell_day = position["buy_date"] < today

        if is_sell_day and now.hour >= 8 and now.hour < 15:
            # Evaluate sell decision
            should_sell, reason, sentiment = evaluate_sell_decision(position, price)
            if should_sell:
                send_sell_rule_alert(position, pnl_percent, reason)
            else:
                update_weak_alert_state(position, pnl_percent, should_sell=False)

            # PDT check: if this would be a same-day close (day trade), verify we have capacity
            is_day_trade = position["buy_date"] == today
            if should_sell and is_day_trade and reason in ("cut_loss", *LEGACY_STOP_LOSS_REASONS):
                if not can_day_trade():
                    log.warning(f"PDT limit reached — cannot CUT {ticker} today (day trade #{get_pdt_count()+1}). Downgrading to WEAK.")
                    should_sell = False
                    sentiment = f"PDT limit — holding {ticker} despite loss. Max 3 day trades/week."

            database.execute("""
                INSERT INTO position_checks (position_id, check_time, price, pnl_percent, sentiment, ticker)
                VALUES (?,?,?,?,?,?)
            """, [position["id"], now.isoformat(), price, round(pnl_percent, 2), sentiment, ticker])

            if should_sell:
                outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")

                database.execute(f"""
                    UPDATE virtual_trades SET
                        sell_date=?, sell_time=?, sell_price=?, current_value=?,
                        actual_move=?, gross_pnl=?, net_pnl=?, {FEE_MODEL_UPDATE_SET},
                        outcome=?, sell_reason=?
                    WHERE id=?
                """, [today, now.strftime("%H:%M:%S"), price,
                      round(current_value, 4), round(pnl_percent, 2),
                      fee_quote["gross_pnl"], fee_quote["net_pnl"], *fee_model_values(fee_quote),
                      outcome, reason, position["id"]])

                # Record as day trade if opened and closed same day
                if is_day_trade:
                    record_day_trade(ticker, position.get("buy_time"), now.strftime("%H:%M:%S"))

                # Update corresponding prediction
                database.execute("""
                    UPDATE predictions SET outcome=?, actual_move=?, resolved_at=?
                    WHERE id=?
                """, [outcome, round(pnl_percent, 2), now.isoformat(),
                      f"{ticker}_{position['buy_date']}_{position['direction']}"])

                # Add ending value to trade queue for compounding
                add_to_queue_on_connection(database, current_value, position["id"])

                # Send SMS notification
                if reason == "cut_loss" and is_day_trade:
                    sms_reason = "cut at a loss — day trade used"
                elif reason == "cut_loss":
                    sms_reason = "closed on reversal — confidence dropped"
                else:
                    sms_reason = reason.replace("_", " ")
                send_close_notification(ticker, round(pnl_dollars, 2), round(pnl_percent, 1), sms_reason)

                log.info(f"CLOSED {ticker} {position['direction']} | {reason} | {pnl_percent:+.1f}% | ${pnl_dollars:+.2f} | {'DAY TRADE' if is_day_trade else 'OVERNIGHT'}")
        else:
            # Not sell day — just log for chart data
            database.execute("""
                INSERT INTO position_checks (position_id, check_time, price, pnl_percent, sentiment, ticker)
                VALUES (?,?,?,?,?,?)
            """, [position["id"], now.isoformat(), price, round(pnl_percent, 2), "monitoring", ticker])

    database.commit()
    database.close()
    finish_scan_event(
        monitor_event_id,
        status="success" if current_prices else "degraded",
        tickers_updated=len(current_prices),
        provider_summary=get_app_state_json("last_price_provider_summary", {}) or {},
        error=None if current_prices else "no current prices returned",
    )
    set_app_state("last_open_position_monitor", json.dumps({
        "checked_at": now.isoformat(),
        "tickers_attempted": len(all_tickers),
        "tickers_updated": len(current_prices),
        "open_positions": len(open_positions),
        "candidates": len(monitored_candidates),
        "provider_summary": get_app_state_json("last_price_provider_summary", {}) or {},
    }))
    status = record_monitor_status(
        status="complete" if current_prices else "failed",
        started=False,
        total_open_positions=len(open_positions),
        total_tickers=len(all_tickers),
        updated_count=updated_open_count,
        current_ticker=None,
        last_success_at=now.isoformat() if updated_open_count > 0 or not open_positions else get_monitor_status().get("last_success_at"),
        finished_at=current_time_cst().isoformat(),
        error=None if current_prices else "no current prices returned",
    )
    if current_prices:
        maybe_send_monitor_recovery_alert(status)
    evaluate_monitor_health_alert(status)
    log.info(f"Monitored {len(open_positions)} positions + {len(monitored_candidates)} candidates")

def monitor_open_positions():
    """Run the open-position monitor with watchdog cleanup around the hot path."""
    started_at = current_time_cst().isoformat()
    if not _monitor_singleflight_lock.acquire(blocking=False):
        event_id = begin_scan_event("open_position_monitor", job_type="monitor", tickers_attempted=0)
        finish_scan_event(event_id, status="skipped", error="monitor already running")
        status = record_monitor_status(status="running", started=True, already_running=True, error=None)
        log.info("monitor_open_positions skipped - previous monitor pass still running")
        return {"success": False, "skipped": True, "reason": "monitor already running", "status": status}
    try:
        mark_stalled_scan_events(max_age_minutes=10)
        return _monitor_open_positions_impl()
    except Exception as exc:
        mark_running_events_error("monitor", started_at, exc)
        status = record_monitor_status(
            status="failed",
            started=False,
            finished_at=current_time_cst().isoformat(),
            error=str(exc),
        )
        evaluate_monitor_health_alert(status)
        log.error(f"monitor_open_positions failed: {exc}")
        raise
    finally:
        mark_stalled_scan_events(max_age_minutes=10)
        _monitor_singleflight_lock.release()

def force_close_previous_session():
    """
    Force-close all positions from the previous trading session.
    Called at 2:45 PM CST — this is a non-negotiable deadline.
    
    All remaining open positions are sold at current market price.
    Their ending values are added to the trade queue for compounding.
    Order is randomized to avoid alphabetical bias.
    """
    now = current_time_cst()
    # Skip weekends — markets are closed, Finnhub returns stale/zero prices
    if now.weekday() >= 5:
        log.info("force_close_previous_session: skipping — weekend")
        return
    today = now.strftime("%Y-%m-%d")
    database = get_database()
    previous_session_positions = [dict(t) for t in database.execute(
        "SELECT * FROM virtual_trades WHERE outcome='open' AND buy_date < ?", [today]
    ).fetchall()]
    database.close()

    if not previous_session_positions:
        log.info("No positions to force-close")
        return

    tickers = list(set(position["ticker"] for position in previous_session_positions))
    current_prices = fetch_current_prices(tickers)

    # Randomize close order to avoid systematic bias in queue ordering
    random.shuffle(previous_session_positions)

    database = get_database()
    closed_count = 0

    for position in previous_session_positions:
        ticker = position["ticker"]
        buy_price = float(position.get("buy_price") or 0)
        invested = float(position.get("invested_amount") or DEFAULT_INVESTMENT)

        # Price resolution: live fetch → quote cache → last stored current_value → flag
        raw = current_prices.get(ticker)
        if raw and (raw.get("price") if isinstance(raw, dict) else raw):
            price = float(raw["price"] if isinstance(raw, dict) else raw)
            price_source = "live"
        else:
            cached = _read_quote_cache(ticker, max_age_seconds=600)
            if cached and cached.get("price"):
                price = float(cached["price"])
                price_source = "quote_cache"
            elif position.get("current_value") and buy_price > 0:
                price = float(position["current_value"]) / max(invested, 0.01) * buy_price
                price_source = "stored_value"
            else:
                log.warning(f"Force-close {ticker}: no price available — flagging for manual review")
                database.execute(
                    "UPDATE virtual_trades SET sell_reason=? WHERE id=?",
                    ["forced_close_no_price", position["id"]]
                )
                send_close_notification(ticker, 0.0, 0.0, "force close 2:45 PM — price unavailable, verify manually")
                continue

        if buy_price <= 0:
            log.warning(f"Force-close {ticker}: buy_price is zero — skipping")
            continue

        pnl_percent = (price - buy_price) / buy_price * 100
        if position["direction"] == "short":
            pnl_percent = -pnl_percent
        fee_quote = calculate_stock_fee_model(invested, buy_price, price, position["direction"])
        ending_value = fee_quote["net_current_value"]
        outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")

        database.execute(f"""
            UPDATE virtual_trades SET
                sell_date=?, sell_time=?, sell_price=?, current_value=?,
                actual_move=?, gross_pnl=?, net_pnl=?, {FEE_MODEL_UPDATE_SET},
                outcome=?, sell_reason=?
            WHERE id=?
        """, [today, "14:45:00", price, round(ending_value, 4),
              round(pnl_percent, 2), fee_quote["gross_pnl"], fee_quote["net_pnl"],
              *fee_model_values(fee_quote),
              outcome, "forced_close", position["id"]])

        database.execute("""
            UPDATE predictions SET outcome=?, actual_move=?, resolved_at=?
            WHERE id=?
        """, [outcome, round(pnl_percent, 2), now.isoformat(),
              f"{ticker}_{position['buy_date']}_{position['direction']}"])

        # Add ending value to queue — this is where compounding happens
        add_to_queue_on_connection(database, ending_value, position["id"])
        closed_count += 1
        log.info(f"Force-closed {ticker} | {price_source} | {pnl_percent:+.1f}% | ${fee_quote['net_pnl']:+.2f}")

        # Send SMS notification
        send_close_notification(
            ticker, round(float(fee_quote["net_pnl"]), 2), round(pnl_percent, 1),
            "force closed 2:45 PM"
        )

    database.commit()
    database.close()
    log.info(f"Force-closed {closed_count} positions at 2:45 PM CST")

# ── SELF-AUDIT ENGINE ─────────────────────────────────────────────────────────
def force_close_nn_previous_session():
    """Force-close previous-session NN positions without touching the main queue."""
    now = current_time_cst()
    if now.weekday() >= 5:
        log.info("force_close_nn_previous_session: skipping weekend")
        return

    today = now.strftime("%Y-%m-%d")
    database = get_database()
    previous_session_positions = [dict(t) for t in database.execute(
        "SELECT * FROM nn_virtual_trades WHERE outcome='open' AND buy_date < ?", [today]
    ).fetchall()]
    database.close()

    if not previous_session_positions:
        log.info("No NN positions to force-close")
        return

    tickers = list(set(position["ticker"] for position in previous_session_positions))
    current_prices = fetch_current_prices(tickers)
    random.shuffle(previous_session_positions)

    database = get_database()
    closed_count = 0

    for position in previous_session_positions:
        ticker = position["ticker"]
        raw = current_prices.get(ticker)
        price = raw["price"] if isinstance(raw, dict) else (raw or position.get("buy_price", 0))
        buy_price = float(position["buy_price"] or price)
        invested = float(position["invested_amount"] or DEFAULT_INVESTMENT)
        pnl_percent = (price - buy_price) / buy_price * 100
        if position["direction"] == "short":
            pnl_percent = -pnl_percent
        pnl_dollars = invested * (pnl_percent / 100)
        fee_quote = calculate_stock_fee_model(invested, buy_price, price, position["direction"])
        ending_value = fee_quote["net_current_value"]
        outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")

        database.execute(f"""
            UPDATE nn_virtual_trades SET
                sell_date=?, sell_time=?, sell_price=?, current_value=?,
                actual_move=?, gross_pnl=?, net_pnl=?, {FEE_MODEL_UPDATE_SET},
                outcome=?, sell_reason=?
            WHERE id=?
        """, [today, "14:45:00", price, round(ending_value, 4),
              round(pnl_percent, 2), fee_quote["gross_pnl"], fee_quote["net_pnl"],
              *fee_model_values(fee_quote),
              outcome, "forced_close", position["id"]])
        closed_count += 1

    database.commit()
    database.close()
    log.info(f"Force-closed {closed_count} NN positions at 2:45 PM CST")

def extract_json_payload(text):
    """Extract the first JSON object from an LLM response."""
    cleaned = (text or "").replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise

def build_audit_prompt(current_weights, total_predictions, resolved_predictions,
                       hit_predictions, miss_predictions, win_rate, closed_days_summary):
    return (
        "Self-audit for overnight swing trading brain. Analyze and return updated weights.\n"
        f"CURRENT WEIGHTS: {json.dumps(current_weights)}\n"
        f"PERFORMANCE: {json.dumps({'total': total_predictions, 'resolved': len(resolved_predictions), 'hits': len(hit_predictions), 'misses': len(miss_predictions), 'win_rate': win_rate})}\n"
        f"HOLD DURATION BREAKDOWN: {json.dumps(closed_days_summary)}\n"
        "Indicators: rsi_momentum, volume_surge, overnight_gap_probability, earnings_catalyst, "
        "support_resistance, relative_strength, sector_relative_strength, vwap_reclaim, volatility_squeeze.\n"
        "support_resistance: open-air setups score high, resistance-capped setups score low.\n"
        "relative_strength: stock outperforming SPY 5-day scores high.\n"
        "sector_relative_strength: sector ETF outperforming SPY 5-day scores high.\n"
        "vwap_reclaim: closing above VWAP shows institutional buy-side conviction.\n"
        "volatility_squeeze: low HV ratio (compression) scores high -- coiled spring setup.\n"
        "Rules: weights must sum to 1.0, each between 0.03-0.35.\n"
        "Respond ONLY with valid JSON: {\"weights\":{...},\"reasoning\":[\"...\"],\"summary\":\"...\",\"confidence\":\"low|medium|high\"}"
    )

def call_anthropic_audit(prompt):
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=os.getenv("ANTHROPIC_AUDIT_MODEL", "claude-sonnet-4-20250514"),
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text

def call_openai_compatible_audit(provider):
    def _call(prompt):
        if not provider["api_key"]:
            raise RuntimeError(f"{provider['key_name']} not configured")
        import requests
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        if provider["name"] == "openrouter":
            headers["HTTP-Referer"] = os.getenv("APP_PUBLIC_URL", "https://swingdeskapp.netlify.app")
            headers["X-Title"] = "SwingDesk"
        response = requests.post(
            provider["url"],
            headers=headers,
            json={
                "model": os.getenv(provider["model_env"], provider["model"]),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 900,
                "response_format": {"type": "json_object"},
            },
            timeout=45,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    return _call

def audit_llm_chain(prompt):
    providers = [
        ("anthropic", call_anthropic_audit),
        ("openai", call_openai_compatible_audit({
            "name": "openai", "api_key": OPENAI_API_KEY, "key_name": "OPENAI_API_KEY",
            "url": "https://api.openai.com/v1/chat/completions",
            "model_env": "OPENAI_AUDIT_MODEL", "model": "gpt-4o-mini",
        })),
        ("groq", call_openai_compatible_audit({
            "name": "groq", "api_key": GROQ_API_KEY, "key_name": "GROQ_API_KEY",
            "url": "https://api.groq.com/openai/v1/chat/completions",
            "model_env": "GROQ_AUDIT_MODEL", "model": "llama-3.3-70b-versatile",
        })),
        ("mistral", call_openai_compatible_audit({
            "name": "mistral", "api_key": MISTRAL_API_KEY, "key_name": "MISTRAL_API_KEY",
            "url": "https://api.mistral.ai/v1/chat/completions",
            "model_env": "MISTRAL_AUDIT_MODEL", "model": "mistral-large-latest",
        })),
        ("together", call_openai_compatible_audit({
            "name": "together", "api_key": TOGETHER_API_KEY, "key_name": "TOGETHER_API_KEY",
            "url": "https://api.together.xyz/v1/chat/completions",
            "model_env": "TOGETHER_AUDIT_MODEL", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        })),
        ("openrouter", call_openai_compatible_audit({
            "name": "openrouter", "api_key": OPENROUTER_API_KEY, "key_name": "OPENROUTER_API_KEY",
            "url": "https://openrouter.ai/api/v1/chat/completions",
            "model_env": "OPENROUTER_AUDIT_MODEL", "model": "anthropic/claude-3.5-sonnet",
        })),
        ("xai", call_openai_compatible_audit({
            "name": "xai", "api_key": XAI_API_KEY, "key_name": "XAI_API_KEY",
            "url": "https://api.x.ai/v1/chat/completions",
            "model_env": "XAI_AUDIT_MODEL", "model": "grok-3-mini",
        })),
        ("perplexity", call_openai_compatible_audit({
            "name": "perplexity", "api_key": PERPLEXITY_API_KEY, "key_name": "PERPLEXITY_API_KEY",
            "url": "https://api.perplexity.ai/chat/completions",
            "model_env": "PERPLEXITY_AUDIT_MODEL", "model": "sonar-pro",
        })),
    ]
    attempts = []
    for name, caller in providers:
        try:
            result = extract_json_payload(caller(prompt))
            return name, result, attempts
        except Exception as error:
            attempts.append({"provider": name, "error": str(error)[:220]})
            log.warning(f"Audit provider {name} failed: {error}")
    raise RuntimeError(json.dumps(attempts))

def build_variant_summary_prompt(variant_summaries):
    """Build a prompt asking the LLM to explain what the ML already did — read only."""
    lines = []
    for v in variant_summaries:
        if not v.get("recent_events"):
            continue
        lines.append(f"\nVariant: {v['label']}")
        lines.append(f"  Current weights: {json.dumps({k: f'{round(val*100)}%' for k,val in v['weights'].items()})}")
        lines.append(f"  Recent ML adjustments ({len(v['recent_events'])} events):")
        for ev in v["recent_events"][:5]:
            diffs = []
            for k in v["weights"]:
                b = round((ev["weights_before"].get(k,0))*100)
                a = round((ev["weights_after"].get(k,0))*100)
                if abs(a-b) > 0:
                    diffs.append(f"{k}: {b}%→{a}%")
            lines.append(f"    [{ev['outcome'].upper()} {ev['actual_move']:+.1f}%] {', '.join(diffs) or 'no change'}")
            for r in (ev.get("reasoning") or [])[:2]:
                lines.append(f"      reasoning: {r}")

    data_block = "\n".join(lines) if lines else "No recent ML activity."

    return (
        "The following shows recent machine learning weight adjustments made automatically by the "
        "SwingDesk trading algorithm. These adjustments are applied in the daily 7 PM Central "
        "batch from closed trades; winning trades reward signals that fired, losing trades penalize them.\n\n"
        f"{data_block}\n\n"
        "In 3-5 sentences, explain in plain English what patterns the ML is learning. "
        "Which signals are being consistently rewarded or penalized? What does this suggest "
        "about current market conditions? Be specific and reference the actual variants and signals. "
        "Do NOT suggest changes — just explain what already happened.\n\n"
        'Respond with JSON: {"summary": "your explanation here", "confidence": "low|medium|high"}'
    )


def run_self_audit():
    """Read-only audit: summarize what the ML already did. Never writes weights."""
    log.info("Running read-only self-audit — summarizing ML learning events...")
    db = get_database()

    # Get all active variants
    variant_rows = [dict(r) for r in db.execute(
        "SELECT id, strategy, brain, label FROM strategy_variants WHERE status='active' ORDER BY id"
    ).fetchall()]

    global_resolved = [dict(p) for p in db.execute(
        "SELECT * FROM predictions WHERE outcome != 'pending' ORDER BY date DESC LIMIT 200"
    ).fetchall()]
    global_total = db.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    global_hits = [p for p in global_resolved if p["outcome"] == "hit"]
    global_misses = [p for p in global_resolved if p["outcome"] == "miss"]
    global_win_rate = len(global_hits)/len(global_resolved) if global_resolved else None
    db.close()

    # Build per-variant summaries from recent learning events
    variant_summaries = []
    for variant in variant_rows:
        vid = variant["id"]
        db2 = get_database()
        events = [dict(r) for r in db2.execute(
            "SELECT * FROM variant_learning_events WHERE variant_id=? ORDER BY timestamp DESC LIMIT 10",
            [vid]
        ).fetchall()]
        current_weights = get_variant_signal_weights(db2, vid)
        db2.close()

        parsed_events = []
        for ev in events:
            try:
                wb = json.loads(ev.get("weights_before") or "{}")
                wa = json.loads(ev.get("weights_after") or "{}")
                reasoning = json.loads(ev.get("reasoning") or "[]")
                parsed_events.append({**ev, "weights_before": wb, "weights_after": wa, "reasoning": reasoning})
            except Exception:
                pass

        if parsed_events:
            variant_summaries.append({
                "id": vid,
                "label": variant.get("label") or vid,
                "weights": current_weights,
                "recent_events": parsed_events,
            })

    ts = current_time_cst().isoformat()

    if not variant_summaries:
        summary_text = "No ML learning events recorded yet. Weights update once daily at 7 PM Central from closed trades."
        provider = None
        result_summary = summary_text
        confidence = "low"
    else:
        prompt = build_variant_summary_prompt(variant_summaries)
        try:
            provider, result, _ = audit_llm_chain(prompt)
            result_summary = result.get("summary", "ML audit complete.")
            confidence = result.get("confidence", "medium")
        except Exception as e:
            log.warning(f"LLM summary failed: {e}")
            provider = None
            result_summary = f"ML is actively learning. {sum(len(v['recent_events']) for v in variant_summaries)} weight adjustments recorded across {len(variant_summaries)} variants in recent history."
            confidence = "low"

    # Snapshot current weights for the audit log (read-only — never writes to variant_signal_weights)
    weights_snapshot = {v["id"]: v["weights"] for v in variant_summaries}

    db3 = get_database()
    db3.execute("""INSERT INTO audit_log
        (timestamp, audit_success, audit_provider, provider_attempts,
         weights_before, weights_after, reasoning, summary,
         total_predictions, resolved_count, hit_count, miss_count, win_rate)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [ts, 1, provider, json.dumps([]),
         json.dumps(weights_snapshot), json.dumps(weights_snapshot),  # same — no change
         json.dumps([f"{v['label']}: {len(v['recent_events'])} recent ML events" for v in variant_summaries]),
         result_summary,
         global_total, len(global_resolved), len(global_hits), len(global_misses), global_win_rate])
    db3.execute("INSERT OR REPLACE INTO app_state VALUES ('last_audit',?)", [ts])
    db3.commit()
    db3.close()

    return {
        "success": True,
        "summary": result_summary,
        "provider": provider,
        "confidence": confidence,
        "variants_summarized": len(variant_summaries),
        "note": "Read-only. ML weight updates happen in the daily 7 PM Central batch from closed variant trades.",
    }

def run_scheduler():
    """
    Background scheduler for all automated tasks.

    Scheduled jobs are keyed by America/Chicago wall-clock time. This avoids
    the old hardcoded UTC offset problem where November-March jobs fired an
    hour early during Central Standard Time.
    """
    def add_job(table, slot, name, callback):
        table.setdefault(slot, []).append((name, callback))

    def add_scan(table, slot, scan_type):
        add_job(table, slot, f"scan:{scan_type}", lambda st=scan_type: run_comprehensive_scan(scan_type=st))

    def eod_variant_equity_snapshot():
        """Store one ledger point for every active variant at the end of each market day."""
        if current_time_cst().weekday() >= 5:
            return
        db = None
        try:
            db = get_database()
            variants = [dict(row) for row in db.execute("""
                SELECT sv.id FROM strategy_variants sv
                JOIN variant_portfolios vp ON vp.variant_id = sv.id
                WHERE sv.status='active' AND vp.lifecycle_status!='archived'
            """).fetchall()]
            for variant in variants:
                update_variant_portfolio(db, variant["id"], note="eod_snapshot")
            db.commit()
            log.info(f"EOD equity snapshot: {len(variants)} variants updated")
        except Exception as error:
            log.error(f"EOD equity snapshot failed: {error}")
        finally:
            if db:
                db.close()

    def run_daily_learning_audit_and_training():
        """Run the 7 PM Central closed-trade learning batch, read-only audit recap, and NN training."""
        if current_time_cst().weekday() >= 5:
            return
        learning_result = run_daily_variant_learning()
        log.info(f"Daily variant learning result: {learning_result}")
        run_self_audit()
        try:
            train_neural_network()
        except Exception as error:
            log.error(f"NN training failed: {error}")

    def run_scan_history_retention():
        """Apply the 30-day raw scan telemetry retention policy."""
        try:
            prune_scan_history(SCAN_EVENT_RETENTION_DAYS)
        except Exception as error:
            log.error(f"Scan history retention failed: {error}")

    def run_scheduled_job(name, callback):
        try:
            log.info(f"Scheduled job started: {name}")
            callback()
            log.info(f"Scheduled job finished: {name}")
        except Exception as error:
            log.error(f"Scheduled job failed ({name}): {error}")

    dispatch = {}

    for slot, label in [
        ("04:00", "4:00am"), ("04:30", "4:30am"),
        ("05:00", "5:00am"), ("05:30", "5:30am"),
        ("06:00", "6:00am"), ("06:30", "6:30am"),
        ("07:00", "7:00am"), ("07:30", "7:30am"),
        ("08:00", "8:00am"),
    ]:
        add_scan(dispatch, slot, f"pre_market_{label}")

    add_job(dispatch, "04:00", "unlock_pick_queue", unlock_pick_queue)
    add_job(dispatch, "05:00", "variant_0500", lambda: run_variant_universes_from_cache(trigger="scheduled_0500", buy_time="05:00:00"))
    add_job(dispatch, "06:00", "variant_0600", lambda: run_variant_universes_from_cache(trigger="scheduled_0600", buy_time="06:00:00"))
    add_job(dispatch, "07:00", "variant_0700", lambda: run_variant_universes_from_cache(trigger="scheduled_0700", buy_time="07:00:00"))
    add_scan(dispatch, "08:15", "final_scan")
    add_job(dispatch, "08:25", "lock_pick_queue", lock_pick_queue)
    add_scan(dispatch, "08:30", "market_open")
    add_job(dispatch, "08:45", "execute_opening_positions", execute_opening_positions)
    add_job(dispatch, "08:45", "execute_nn_opening_positions", execute_nn_opening_positions)
    add_job(dispatch, "08:45", "variant_0845", lambda: run_variant_universes_from_cache(trigger="scheduled_0845", buy_time="08:45:00"))

    for slot, label in [
        ("09:00", "9:00am"), ("09:30", "9:30am"),
        ("10:00", "10:00am"), ("10:30", "10:30am"),
        ("11:00", "11:00am"), ("11:30", "11:30am"),
        ("12:00", "12:00pm"), ("12:30", "12:30pm"),
        ("13:00", "1:00pm"), ("13:30", "1:30pm"),
        ("14:00", "2:00pm"), ("14:30", "2:30pm"),
    ]:
        add_scan(dispatch, slot, f"regular_{label}")

    add_job(dispatch, "14:45", "force_close_previous_session", force_close_previous_session)
    add_job(dispatch, "14:45", "force_close_nn_previous_session", force_close_nn_previous_session)
    add_job(dispatch, "14:50", "eod_variant_equity_snapshot", eod_variant_equity_snapshot)
    add_scan(dispatch, "15:00", "market_close")

    for slot, label in [
        ("15:30", "3:30pm"), ("16:00", "4:00pm"),
        ("16:30", "4:30pm"), ("17:00", "5:00pm"),
        ("17:30", "5:30pm"), ("18:00", "6:00pm"),
    ]:
        add_scan(dispatch, slot, f"post_market_{label}")

    add_job(dispatch, "19:00", "daily_learning_audit_nn_training", run_daily_learning_audit_and_training)
    add_job(dispatch, "19:10", "scan_history_retention", run_scan_history_retention)

    log.info("Scheduler started: Chicago-time dispatcher, 30min shared scans, 2.5min regular/5min extended monitoring")

    fired_today = set()
    fired_date = current_time_cst().date()
    last_monitor_time = 0

    while True:
        current_time = time.time()
        now = current_time_cst()

        if now.date() != fired_date:
            fired_today.clear()
            fired_date = now.date()

        slot = now.strftime("%H:%M")
        for name, callback in dispatch.get(slot, []):
            fired_key = f"{fired_date}:{slot}:{name}"
            if fired_key in fired_today:
                continue
            fired_today.add(fired_key)
            threading.Thread(
                target=run_scheduled_job,
                args=(name, callback),
                daemon=True,
            ).start()

        is_regular = is_market_open()
        in_extended, _ = is_extended_hours()
        is_active = now.weekday() < 5 and (is_regular or in_extended or 4 <= now.hour < 20)
        dynamic_interval = 150 if is_regular else 300

        if is_active and current_time - last_monitor_time >= dynamic_interval:
            last_monitor_time = current_time
            threading.Thread(
                target=run_scheduled_job,
                args=("dynamic_monitoring_cycle", lambda: (
                    monitor_open_positions(),
                    monitor_nn_open_positions(),
                    monitor_variant_universes(trigger="scheduled"),
                )),
                daemon=True,
            ).start()

        time.sleep(15)
# ── API ROUTES ────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "time_cst": current_time_cst().isoformat(),
        "time_utc": datetime.utcnow().isoformat(),
    })

@app.route("/api/extended-runners")
def api_extended_runners():
    """
    Return extended runner positions using stored values only.
    Live price updates happen via the monitor — never on demand here.
    """
    database = get_database()
    runners = database.execute(
        "SELECT * FROM extended_runners WHERE status='running' ORDER BY buy_date DESC"
    ).fetchall()
    database.close()

    if not runners:
        return jsonify([])

    result = []
    for runner in runners:
        buy_price = runner["buy_price"] or 1
        current_price = runner["current_price"] or buy_price
        current_pnl = (current_price - buy_price) / buy_price * 100
        invested = runner["invested_amount"] or 10
        current_value = invested * (1 + current_pnl / 100)
        result.append({
            **dict(runner),
            "current_price": round(current_price, 4),
            "current_pnl_percent": round(current_pnl, 2),
            "current_value": round(current_value, 4),
        })

    return jsonify(result)

@app.route("/api/extended-runners/add", methods=["POST"])
def api_add_extended_runner():
    """
    Mark a closed brain trade as an extended runner — user is still holding.
    Called manually or when user taps "extend" on a closed position.
    """
    data = request.get_json()
    trade_id = data.get("trade_id")
    if not trade_id:
        return jsonify({"error": "trade_id required"}), 400

    database = get_database()
    trade = database.execute(
        "SELECT * FROM virtual_trades WHERE id=?", [trade_id]
    ).fetchone()

    if not trade:
        database.close()
        return jsonify({"error": "Trade not found"}), 404

    runner_id = f"{trade['ticker']}_{trade['buy_date']}_runner"
    database.execute("""
        INSERT OR REPLACE INTO extended_runners
        (id, ticker, buy_date, buy_price, brain_sell_date, brain_sell_price,
         brain_pnl_percent, current_price, invested_amount, status, last_updated)
        VALUES (?,?,?,?,?,?,?,?,?,'running',?)
    """, [runner_id, trade["ticker"], trade["buy_date"], trade["buy_price"],
          trade["sell_date"], trade["sell_price"], trade["actual_move"],
          trade["sell_price"], trade["invested_amount"],
          current_time_cst().isoformat()])
    database.commit()
    database.close()
    return jsonify({"success": True, "runner_id": runner_id})

@app.route("/api/last-known")
def api_last_known():
    """
    Returns the last successfully cached picks and portfolio snapshot.
    Used by the frontend to show stale-but-useful data when the brain
    is temporarily unreachable, instead of showing a blank screen.
    """
    database = get_database()
    cached = database.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
    cache_time = database.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    portfolio_snapshot = database.execute(
        "SELECT SUM(current_value) as total FROM virtual_trades WHERE outcome='open'"
    ).fetchone()
    database.close()
    return jsonify({
        "picks": json.loads(cached["value"]) if cached else {},
        "cache_time": cache_time["value"] if cache_time else None,
        "open_position_value": round(float(portfolio_snapshot["total"] or 0), 2),
        "stale": True,
    })

@app.route("/api/clear-universe-cache", methods=["POST"])
def api_clear_universe_cache():
    """
    Force a fresh ticker universe rebuild on next scan.
    Clears the cached universe and date so build_ticker_universe()
    fetches fresh S&P 500 data from GitHub instead of waiting until tomorrow.
    """
    try:
        database = get_database()
        database.execute("DELETE FROM app_state WHERE key IN ('universe', 'universe_date')")
        database.commit()
        database.close()
        fresh_universe = build_ticker_universe()
        return jsonify({"success": True, "ticker_count": len(fresh_universe)})
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500

@app.route("/api/picks")
def api_picks():
    """Serve cached picks instantly. Use ?fresh=true to force a new scan."""
    force_fresh = request.args.get("fresh", "false").lower() == "true"
    if not force_fresh:
        cached = get_cached_picks()
        if cached:
            return jsonify(cached)
    try:
        return jsonify(run_comprehensive_scan(scan_type="manual"))
    except Exception as error:
        return jsonify({"error": str(error)}), 500

@app.route("/api/picks/fresh")
def api_picks_fresh():
    """Force a fresh comprehensive scan."""
    try:
        return jsonify(run_comprehensive_scan(scan_type="manual_fresh"))
    except Exception as error:
        return jsonify({"error": str(error)}), 500

@app.route("/api/monitor-open-now", methods=["POST"])
def api_monitor_open_now():
    """Force one open-position monitor pass for freshness diagnostics."""
    try:
        current = get_monitor_status()
        if current.get("status") == "running":
            return jsonify({
                "success": True,
                "started": False,
                "already_running": True,
                "background": True,
                "status": current,
                "status_endpoint": "/api/monitor-open-status",
            })

        record_monitor_status(
            status="queued",
            started=True,
            started_at=current_time_cst().isoformat(),
            finished_at=None,
            updated_count=0,
            current_ticker=None,
            error=None,
        )
        thread = threading.Thread(target=monitor_open_positions, daemon=True)
        thread.start()
        return jsonify({
            "success": True,
            "started": True,
            "background": True,
            "status": get_monitor_status(),
            "status_endpoint": "/api/monitor-open-status",
        })
    except Exception as error:
        log.error(f"Manual monitor-open-now failed: {error}")
        record_monitor_status(status="failed", started=False, finished_at=current_time_cst().isoformat(), error=str(error))
        return jsonify({"success": False, "error": str(error)}), 500

@app.route("/api/monitor-open-status")
def api_monitor_open_status():
    """Return latest open-position monitor progress and freshness state."""
    try:
        status = get_monitor_status()
        evaluate_monitor_health_alert(status)
        return jsonify(status)
    except Exception as error:
        return jsonify({"status": "unknown", "error": str(error)}), 500

@app.route("/api/day-trade-status")
def api_day_trade_status():
    """Verify PDT/day-trade count against the durable ledger and closed trades."""
    try:
        now = current_time_cst()
        five_days_ago = (now - timedelta(days=5)).strftime("%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")
        database = get_database()
        ledger_rows = [dict(r) for r in database.execute("""
            SELECT * FROM day_trades
            WHERE date >= ?
            ORDER BY date DESC, logged_at DESC
        """, [five_days_ago]).fetchall()]
        same_day_rows = [dict(r) for r in database.execute("""
            SELECT id, ticker, buy_date, sell_date, buy_time, sell_time, sell_reason, outcome
            FROM virtual_trades
            WHERE buy_date = sell_date
              AND sell_date >= ?
            ORDER BY sell_date DESC, sell_time DESC
        """, [five_days_ago]).fetchall()]
        database.close()

        pdt_relevant_reasons = {"cut_loss", *LEGACY_STOP_LOSS_REASONS, "momentum_fade", "rsi_exhaustion", "target_hit"}
        pdt_relevant_same_day = []
        excluded_same_day = []
        for row in same_day_rows:
            reason = row.get("sell_reason")
            buy_time = str(row.get("buy_time") or "")
            sell_time = str(row.get("sell_time") or "")
            is_today = row.get("sell_date") == today
            reason_relevant = reason in pdt_relevant_reasons
            looks_intraday = buy_time and sell_time and buy_time != sell_time
            if is_today and reason_relevant and looks_intraday:
                pdt_relevant_same_day.append(row)
            else:
                excluded_same_day.append({
                    **row,
                    "excluded_reason": "historical_or_forced_close_not_counted_for_live_pdt",
                })

        ledger_keys = {
            (row.get("ticker"), row.get("date"), str(row.get("buy_time") or ""), str(row.get("sell_time") or ""))
            for row in ledger_rows
        }
        relevant_keys = {
            (row.get("ticker"), row.get("sell_date"), str(row.get("buy_time") or ""), str(row.get("sell_time") or ""))
            for row in pdt_relevant_same_day
        }
        missing_from_ledger = [
            row for row in pdt_relevant_same_day
            if (row.get("ticker"), row.get("sell_date"), str(row.get("buy_time") or ""), str(row.get("sell_time") or "")) not in ledger_keys
        ]
        extra_ledger_rows = [
            row for row in ledger_rows
            if (row.get("ticker"), row.get("date"), str(row.get("buy_time") or ""), str(row.get("sell_time") or "")) not in relevant_keys
        ]

        return jsonify({
            "success": True,
            "window_start": five_days_ago,
            "today": today,
            "pdt_used": len(ledger_rows),
            "pdt_remaining": max(0, 3 - len(ledger_rows)),
            "ledger_count": len(ledger_rows),
            "same_day_closed_count": len(same_day_rows),
            "pdt_relevant_same_day_count": len(pdt_relevant_same_day),
            "excluded_same_day_count": len(excluded_same_day),
            "counter_consistent": len(missing_from_ledger) == 0,
            "matches_closed_rows": len(ledger_rows) == len(pdt_relevant_same_day),
            "note": "PDT ledger is compared to today's PDT-relevant same-day exits only; historical or forced-close rows are listed as excluded context.",
            "ledger": ledger_rows,
            "same_day_closed": same_day_rows,
            "pdt_relevant_same_day": pdt_relevant_same_day,
            "excluded_same_day": excluded_same_day,
            "missing_from_ledger": missing_from_ledger,
            "extra_ledger_rows": extra_ledger_rows,
        })
    except Exception as error:
        return jsonify({"success": False, "error": str(error)}), 500

@app.route("/api/freshness-repair-now", methods=["POST"])
def api_freshness_repair_now():
    """Self-heal stale freshness state: stall old events, refresh open positions, optionally scan."""
    try:
        body = request.get_json(silent=True) or {}
        run_scan = bool(body.get("run_scan", False))
        repaired = {
            "stalled_events_marked": mark_stalled_scan_events(max_age_minutes=10),
            "monitor_ran": False,
            "scan_ran": False,
            "errors": [],
        }

        database = get_database()
        stale_open_count = database.execute("""
            SELECT COUNT(*) as n
            FROM virtual_trades
            WHERE outcome='open'
              AND (last_price_updated IS NULL OR last_price_updated < ?)
        """, [(current_time_cst() - timedelta(minutes=7)).isoformat()]).fetchone()["n"]
        database.close()

        if stale_open_count:
            try:
                monitor_open_positions()
                repaired["monitor_ran"] = True
            except Exception as exc:
                repaired["errors"].append(f"monitor: {exc}")

        if run_scan:
            try:
                run_comprehensive_scan(scan_type="freshness_repair")
                repaired["scan_ran"] = True
            except Exception as exc:
                repaired["errors"].append(f"scan: {exc}")

        status_code = 200 if not repaired["errors"] else 500
        return jsonify({"success": not repaired["errors"], **repaired}), status_code
    except Exception as error:
        log.error(f"freshness repair failed: {error}")
        return jsonify({"success": False, "error": str(error)}), 500

@app.route("/api/ui-preferences", methods=["GET", "POST"])
def api_ui_preferences():
    """Persist UI display preferences server-side instead of browser localStorage."""
    defaults = {
        "pick_percent_mode": "PM",
        "open_percent_mode": "RO",
        "show_ticker_banner": True,
    }
    allowed = {
        "pick_percent_mode": {"PC", "PM", "RO"},
        "open_percent_mode": {"PC", "PM", "RO", "EN"},
    }
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        current = get_app_state_json("ui_preferences", defaults) or defaults
        updated = {**defaults, **current}
        for key, valid_values in allowed.items():
            value = str(body.get(key, updated.get(key, defaults[key]))).upper()
            if value in valid_values:
                updated[key] = value
        if "show_ticker_banner" in body:
            updated["show_ticker_banner"] = bool(body.get("show_ticker_banner"))
        set_app_state("ui_preferences", json.dumps(updated))
        return jsonify(updated)
    return jsonify({**defaults, **(get_app_state_json("ui_preferences", {}) or {})})

@app.route("/api/weights")
def api_weights():
    return jsonify(get_signal_weights())

@app.route("/api/predictions")
def api_predictions():
    database = get_database()
    rows = [dict(r) for r in database.execute(
        "SELECT * FROM predictions ORDER BY logged_at DESC LIMIT 200"
    ).fetchall()]
    database.close()
    return jsonify(rows)

@app.route("/api/predictions/<prediction_id>/outcome", methods=["POST"])
def api_update_outcome(prediction_id):
    outcome = request.json.get("outcome")
    if outcome not in ["hit", "miss", "partial"]:
        return jsonify({"error": "invalid outcome"}), 400
    database = get_database()
    database.execute("UPDATE predictions SET outcome=?, resolved_at=? WHERE id=?",
                     [outcome, current_time_cst().isoformat(), prediction_id])
    database.commit()
    database.close()
    return jsonify({"success": True})

@app.route("/api/virtual-trades")
def api_virtual_trades():
    direction_filter = request.args.get("direction")
    database = get_database()
    if direction_filter:
        rows = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades WHERE direction=? ORDER BY buy_date DESC LIMIT 500",
            [direction_filter]
        ).fetchall()]
    else:
        rows = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades ORDER BY buy_date DESC LIMIT 500"
        ).fetchall()]
    database.close()
    return jsonify(rows)

@app.route("/api/open-positions")
def api_open_positions():
    database = get_database()
    rows = [dict(r) for r in database.execute(
        "SELECT * FROM virtual_trades WHERE outcome='open' ORDER BY buy_date DESC"
    ).fetchall()]
    database.close()
    return jsonify(rows)

@app.route("/api/queue")
def api_queue():
    """Return current trade queue status and recent entries."""
    return jsonify(get_queue_status())

@app.route("/api/audit", methods=["POST"])
def api_audit():
    return jsonify(run_self_audit())

@app.route("/api/audit/log")
def api_audit_log():
    limit = min(max(int(request.args.get("limit", 10)), 1), 100)
    offset = max(int(request.args.get("offset", 0)), 0)
    paged = str(request.args.get("paged", "")).lower() in ("1", "true", "yes")
    database = get_database()
    total = database.execute("SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
    rows = [dict(r) for r in database.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        [limit if paged else 30, offset if paged else 0],
    ).fetchall()]
    for row in rows:
        summary = (row.get("summary") or "").lower()
        if summary.startswith("audit failed:") or summary.startswith("local audit recorded") or "no configured llm provider" in summary:
            row["audit_success"] = 0
        try:
            before = normalize_signal_weights(json.loads(row.get("weights_before") or "{}"))
            after = normalize_signal_weights(json.loads(row.get("weights_after") or "{}"))
            row["weights_changed"] = any(abs(before.get(k, 0) - after.get(k, 0)) > 0.000001 for k in canonical_signal_weights())
        except Exception:
            row["weights_changed"] = None
        try:
            row["provider_attempts"] = json.loads(row.get("provider_attempts") or "[]")
        except Exception:
            row["provider_attempts"] = []
        prior = database.execute(
            "SELECT timestamp FROM audit_log WHERE timestamp < ? ORDER BY timestamp DESC LIMIT 1",
            [row.get("timestamp")]
        ).fetchone()
        prior_ts = prior["timestamp"] if prior else None
        if prior_ts:
            learning_rows = [dict(r) for r in database.execute("""
                SELECT weights_before, weights_after
                FROM variant_learning_events
                WHERE timestamp > ? AND timestamp <= ?
            """, [prior_ts, row.get("timestamp")]).fetchall()]
        else:
            learning_rows = [dict(r) for r in database.execute("""
                SELECT weights_before, weights_after
                FROM variant_learning_events
                WHERE timestamp <= ?
            """, [row.get("timestamp")]).fetchall()]
        changed_count = 0
        for event in learning_rows:
            try:
                before = json.loads(event.get("weights_before") or "{}")
                after = json.loads(event.get("weights_after") or "{}")
                if any(abs(float(before.get(k, 0) or 0) - float(after.get(k, 0) or 0)) > 0.000001 for k in canonical_signal_weights()):
                    changed_count += 1
            except Exception:
                pass
        row["prior_audit_timestamp"] = prior_ts
        row["learning_events_since_prior"] = len(learning_rows)
        row["learning_changed_events_since_prior"] = changed_count
        row["learning_noop_events_since_prior"] = max(len(learning_rows) - changed_count, 0)
    database.close()
    if paged:
        return jsonify({"rows": rows, "total": total, "limit": limit, "offset": offset})
    return jsonify(rows)

@app.route("/api/perf-history")
def api_performance_history():
    """
    Build performance history from resolved trades and position check snapshots.

    Strategy:
    - Closed trades contribute settled dollar P&L to the running balance.
    - Position checks contribute intraday/multi-day snapshots so the chart
      shows portfolio value fluctuating with open positions — even before any
      trade closes. Each check_time snapshot aggregates dollar P&L across all
      open positions at that moment using invested_amount as the base.
    - Always emits a $1,000 seed point so the chart has something to draw from
      day one.
    """
    fees_on = request.args.get("fees", "on").lower() != "off"
    pnl_expr = "COALESCE(net_pnl, gross_pnl, 0)" if fees_on else "COALESCE(gross_pnl, net_pnl, 0)"
    database = get_database()

    # ── Settled (closed) daily P&L ────────────────────────────────────────────
    daily_results = database.execute(f"""
        SELECT sell_date AS date,
               SUM({pnl_expr}) AS daily_pnl,
               COUNT(*) AS trade_count
        FROM virtual_trades
        WHERE outcome != 'open' AND sell_date IS NOT NULL
        GROUP BY sell_date
        ORDER BY sell_date ASC
    """).fetchall()

    # ── Position check snapshots (all dates, not just today) ──────────────────
    # Join with virtual_trades to get invested_amount so we can calculate
    # real dollar P&L: invested_amount * pnl_percent / 100
    check_snapshots = database.execute("""
        SELECT pc.check_time,
               SUM(pc.pnl_percent * COALESCE(vt.invested_amount, 10.0) / 100.0) AS snapshot_pnl_dollars
        FROM position_checks pc
        LEFT JOIN virtual_trades vt ON pc.position_id = vt.id
        GROUP BY pc.check_time
        ORDER BY pc.check_time ASC
    """).fetchall()

    first_trade_row = database.execute("""
        SELECT MIN(first_date) AS first_date FROM (
            SELECT MIN(buy_date) AS first_date FROM virtual_trades WHERE buy_date IS NOT NULL
            UNION ALL
            SELECT MIN(sell_date) AS first_date FROM virtual_trades WHERE sell_date IS NOT NULL
            UNION ALL
            SELECT MIN(substr(check_time, 1, 10)) AS first_date FROM position_checks WHERE check_time IS NOT NULL
        )
    """).fetchone()

    database.close()

    # ── Build settled balance timeline ────────────────────────────────────────
    running_balance = 1000.0
    history = []

    # Seed point: anchor the account at the first real day this ledger has data.
    # A moving "yesterday" seed makes W/M charts understate young portfolios.
    def last_trading_weekday():
        d = datetime.utcnow() - timedelta(days=1)
        # Walk back until we hit a weekday (Mon=0 ... Fri=4)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d
    first_trade_date = first_trade_row["first_date"] if first_trade_row else None
    seed_day = datetime.fromisoformat(first_trade_date) if first_trade_date else last_trading_weekday()
    seed_ts = int(seed_day.replace(hour=9, minute=0, second=0).timestamp() * 1000)
    history.append({
        "date": seed_day.strftime("%Y-%m-%d"),
        "virtual": 1000.0,
        "daily_pnl": 0,
        "trades": 0,
        "ts": seed_ts,
        "seed": True,
    })

    closed_dates = set()
    for row in daily_results:
        running_balance += float(row["daily_pnl"] or 0)
        closed_dates.add(row["date"])
        history.append({
            "date": row["date"],
            "virtual": round(running_balance, 2),
            "daily_pnl": round(float(row["daily_pnl"] or 0), 4),
            "trades": row["trade_count"],
            "ts": int(datetime.fromisoformat(row["date"]).replace(hour=16, minute=0, second=0).timestamp() * 1000),
        })

    # ── Overlay position check snapshots as intraday points ───────────────────
    # Include all position checks — natural data accumulation will smooth
    # out any early dips over time as real trading days accumulate.
    for snapshot in check_snapshots:
        if not snapshot["check_time"]:
            continue
        snapshot_dollars = float(snapshot["snapshot_pnl_dollars"] or 0)
        check_dt = datetime.fromisoformat(snapshot["check_time"])
        history.append({
            "date": check_dt.strftime("%Y-%m-%d"),
            "virtual": round(running_balance + snapshot_dollars, 2),
            "daily_pnl": round(snapshot_dollars, 4),
            "trades": 0,
            "ts": int(check_dt.timestamp() * 1000),
            "intraday": True,
        })

    history.sort(key=lambda point: point["ts"])

    # ── Always append a live "now" point from current open positions ──────────
    # This ensures the chart reflects reality even when no position_checks have
    # run today (e.g. no positions were open during market hours).
    try:
        open_trades = database.execute(
            "SELECT invested_amount, current_value, gross_current_value FROM virtual_trades WHERE outcome='open'"
        ).fetchall() if not database else None
        # Re-open db since we closed it above
        _db2 = get_database()
        open_trades = _db2.execute(
            "SELECT invested_amount, current_value, gross_current_value FROM virtual_trades WHERE outcome='open'"
        ).fetchall()
        _db2.close()
        live_pnl = sum(
            float((t["current_value"] if fees_on else t["gross_current_value"]) or t["current_value"] or t["invested_amount"] or 10) - float(t["invested_amount"] or 10)
            for t in open_trades
        )
        if live_pnl != 0:
            now_cst = current_time_cst()
            history.append({
                "date": now_cst.strftime("%Y-%m-%d"),
                "virtual": round(running_balance + live_pnl, 2),
                "daily_pnl": round(live_pnl, 4),
                "trades": 0,
                "ts": int(now_cst.timestamp() * 1000),
                "intraday": True,
                "live": True,
            })
            history.sort(key=lambda point: point["ts"])
    except Exception as e:
        log.debug(f"perf-history live point skipped: {e}")

    return jsonify(history)

@app.route("/api/day-pnl")
def api_day_pnl():
    """Display-safe Day's P&L with live-open and frozen-closed session semantics."""
    try:
        fees_on = request.args.get("fees", "on").lower() != "off"
        pnl_expr = "COALESCE(net_pnl, gross_pnl, 0)" if fees_on else "COALESCE(gross_pnl, net_pnl, 0)"
        now = current_time_cst()
        today = now.strftime("%Y-%m-%d")
        market_state = market_session_state(now)
        db = get_database()
        settled_rows = [dict(r) for r in db.execute(f"""
            SELECT sell_date AS date,
                   SUM({pnl_expr}) AS daily_pnl
            FROM virtual_trades
            WHERE outcome != 'open' AND sell_date IS NOT NULL
            GROUP BY sell_date
            ORDER BY sell_date ASC
        """).fetchall()]
        open_rows = [dict(r) for r in db.execute("""
            SELECT buy_date, invested_amount, current_value, gross_current_value
            FROM virtual_trades
            WHERE outcome='open'
        """).fetchall()]
        db.close()

        running = 1000.0
        previous_close = 1000.0
        previous_close_date = None
        settled_by_date = {}
        for row in settled_rows:
            if not row.get("date"):
                continue
            settled_by_date[row["date"]] = float(row.get("daily_pnl") or 0)

        completed_session_dates = sorted(d for d in settled_by_date if d <= today)
        latest_completed_session = completed_session_dates[-1] if completed_session_dates else None

        if market_state == "open":
            session_date = today
        else:
            session_date = latest_completed_session or today

        today_settled = settled_by_date.get(session_date, 0.0)
        for row in settled_rows:
            date = row.get("date")
            if not date or date >= session_date:
                continue
            daily = float(row.get("daily_pnl") or 0)
            running += daily
            previous_close = running
            previous_close_date = date

        open_pnl = sum(
            float((r.get("current_value") if fees_on else r.get("gross_current_value")) or r.get("current_value") or r.get("invested_amount") or 10) -
            float(r.get("invested_amount") or 10)
            for r in open_rows
        )
        live_day_pnl = today_settled + open_pnl
        frozen_day_pnl = today_settled
        display_day_pnl = live_day_pnl if market_state == "open" else frozen_day_pnl
        display_mode = "live_session" if market_state == "open" else "frozen_last_completed_session"
        current_value = previous_close + display_day_pnl
        return jsonify({
            "success": True,
            "label": "Day's P&L",
            "session_date": session_date,
            "current_value": round(current_value, 2),
            "previous_close_value": round(previous_close, 2),
            "previous_close_date": previous_close_date,
            "today_settled_pnl": round(today_settled, 4),
            "open_pnl": round(open_pnl, 4),
            "live_day_pnl": round(live_day_pnl, 4),
            "frozen_day_pnl": round(frozen_day_pnl, 4),
            "display_day_pnl": round(display_day_pnl, 4),
            "display_mode": display_mode,
            "market_state": market_state,
            "day_pnl": round(display_day_pnl, 4),
            "day_pnl_percent": round((display_day_pnl / previous_close * 100), 2) if previous_close else 0,
            "open_count": len(open_rows),
            "as_of": now.isoformat(),
            "basis": "live during market hours; frozen to the latest completed market session when closed or premarket",
            "fees_on": fees_on,
            "fee_model_version": STOCK_FEE_MODEL_VERSION if fees_on else "gross",
        })
    except Exception as e:
        log.error(f"day-pnl error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/fee-model")
def api_fee_model():
    """Expose the pinned fee/slippage assumptions used by SwingDesk simulations."""
    stock_qa = calculate_stock_fee_model(100.0, 100.0, 100.0, "long")
    crypto_qa = calculate_crypto_fee_model(100.0, 100.0, 100.0, "long")
    return jsonify({
        "success": True,
        "stocks": {
            "version": STOCK_FEE_MODEL_VERSION,
            "mode": "conservative_stress",
            "buy_friction_pct": STOCK_BUY_FRICTION_RATE * 100,
            "sell_friction_pct": STOCK_SELL_FRICTION_RATE * 100,
            "sec_section_31_rate_per_million": SEC_SECTION_31_RATE * 1_000_000,
            "finra_taf_per_share": FINRA_TAF_PER_SHARE,
            "finra_taf_cap": FINRA_TAF_CAP,
            "qa_no_move_round_trip_100": stock_qa,
        },
        "crypto": {
            "version": CRYPTO_FEE_MODEL_VERSION,
            "mode": "conservative_stress_pinned_for_sdcrypto",
            "buy_friction_pct": CRYPTO_BUY_FRICTION_RATE * 100,
            "sell_friction_pct": CRYPTO_SELL_FRICTION_RATE * 100,
            "qa_no_move_round_trip_100": crypto_qa,
        },
    })

@app.route("/api/ping")
def api_ping():
    """Lightweight wake-up endpoint. Frontend hits this first to warm Railway before real requests."""
    return jsonify({"ok": True, "ts": current_time_cst().isoformat()})

def get_open_execution_status(open_position_count=None):
    """Return latest open execution diagnostics plus a missed-open alert flag."""
    status = get_app_state_json("last_open_execution", {}) or {}
    try:
        database = get_database()
        cached = database.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
        if open_position_count is None:
            open_position_count = database.execute(
                "SELECT COUNT(*) as n FROM virtual_trades WHERE outcome='open'"
            ).fetchone()["n"]
        database.close()
        cached_pick_count = 0
        if cached:
            picks = json.loads(cached["value"])
            cached_pick_count = len((picks.get("longs") or picks.get("recommended_longs") or [])[:MAX_LONG_PICKS])
    except Exception:
        cached_pick_count = status.get("cached_pick_count", 0) or 0

    now = current_time_cst()
    after_open_execution = now.weekday() < 5 and (now.hour > 8 or (now.hour == 8 and now.minute >= 45))
    before_force_close = now.hour < 14 or (now.hour == 14 and now.minute < 45)
    missed_open_alert = bool(after_open_execution and before_force_close and cached_pick_count > 0 and int(open_position_count or 0) == 0)

    return {
        **status,
        "cached_pick_count_live": cached_pick_count,
        "open_position_count_live": int(open_position_count or 0),
        "missed_open_alert": missed_open_alert,
    }

@app.route("/api/stats")
def api_stats():
    database = get_database()

    # virtual_trades is the single source of truth for all performance stats
    virtual_trade_count = database.execute("SELECT COUNT(*) as n FROM virtual_trades").fetchone()["n"]
    open_position_count = database.execute("SELECT COUNT(*) as n FROM virtual_trades WHERE outcome='open'").fetchone()["n"]
    closed_rows = database.execute(
        "SELECT outcome, actual_move, gross_pnl, net_pnl FROM virtual_trades WHERE outcome != 'open'"
    ).fetchall()
    resolved_count = len(closed_rows)
    hit_count = sum(1 for t in closed_rows if t["outcome"] == "hit")
    partial_count = sum(1 for t in closed_rows if t["outcome"] == "partial")
    miss_count = sum(1 for t in closed_rows if t["outcome"] == "miss")
    total_gross_pnl = sum(float(t["gross_pnl"] or 0) for t in closed_rows)
    total_net_pnl = sum(float(t["net_pnl"] if t["net_pnl"] is not None else t["gross_pnl"] or 0) for t in closed_rows)
    win_rate = round(hit_count / resolved_count * 100, 1) if resolved_count else None

    # predictions table used only for audit/weight system — not for performance stats
    total_predictions = database.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]

    last_audit = database.execute("SELECT value FROM app_state WHERE key='last_audit'").fetchone()
    last_audit_row = database.execute(
        "SELECT audit_success, audit_provider FROM audit_log ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    last_scan = database.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    database.close()

    return jsonify({
        "total_predictions": total_predictions,
        "resolved": resolved_count,
        "hits": hit_count,
        "partials": partial_count,
        "misses": miss_count,
        "win_rate": win_rate,
        "total_gross_pnl": round(total_gross_pnl, 2),
        "total_net_pnl": round(total_net_pnl, 2),
        "fee_model_version": STOCK_FEE_MODEL_VERSION,
        "virtual_trades": virtual_trade_count,
        "virtual_open": open_position_count,
        "last_audit": last_audit["value"] if last_audit else None,
        "last_audit_success": bool(last_audit_row["audit_success"]) if last_audit_row else None,
        "last_audit_provider": last_audit_row["audit_provider"] if last_audit_row else None,
        "last_scan": last_scan["value"] if last_scan else None,
        "weights": get_signal_weights(),
        "queue": get_queue_status(),
        "open_execution": get_open_execution_status(open_position_count),
        "pdt_used": get_pdt_count(),
        "pdt_remaining": max(0, 3 - get_pdt_count()),
    })

@app.route("/api/method-stats")
def api_method_stats():
    """Return win rate and signal history for all 7 trading methods."""
    try:
        database = get_database()
        methods = ["Darvas", "Gap & Go", "Donchian", "Inside Day", "Bull Flag", "Pocket Pivot", "S&R", "VWAP Reclaim", "Vol Squeeze"]
        result = {}

        for method in methods:
            if method == "Darvas":
                rows = [dict(r) for r in database.execute(
                    "SELECT * FROM darvas_picks ORDER BY date DESC LIMIT 100"
                ).fetchall()]
            else:
                rows = [dict(r) for r in database.execute(
                    "SELECT * FROM method_signals WHERE method=? ORDER BY date DESC LIMIT 100",
                    [method]
                ).fetchall()]

            resolved = [r for r in rows if r.get("outcome") in ("hit", "miss")]
            hits = [r for r in resolved if r.get("outcome") == "hit"]
            moves = [r.get("actual_move", 0) for r in resolved if r.get("actual_move") is not None]
            win_rate = round(len(hits) / len(resolved) * 100, 1) if resolved else None
            avg_move = round(sum(moves) / len(moves), 2) if moves else None
            best_trade = max(moves) if moves else None

            result[method] = {
                "total_signals": len(rows),
                "resolved": len(resolved),
                "hits": len(hits),
                "misses": len(resolved) - len(hits),
                "win_rate": win_rate,
                "avg_move": avg_move,
                "best_trade": best_trade,
                "recent": rows[:5],
            }

        # Also get weights history for SwingDesk Algo section
        weights_history = [dict(r) for r in database.execute(
            "SELECT * FROM weights_history ORDER BY timestamp DESC LIMIT 50"
        ).fetchall()]

        database.close()
        return jsonify({"methods": result, "weights_history": weights_history})
    except Exception as e:
        log.error(f"method-stats error: {e}")
        return jsonify({"methods": {}, "weights_history": []}), 500

@app.route("/api/strategy-variants")
def api_strategy_variants():
    """Return registered simulation universes.

    Historical route/table naming uses "strategy variants", but each row is a
    universe combining strategy/method label, brain, entry time, selection mode,
    exit mode, and portfolio ledger.
    """
    try:
        db = get_database()
        rows = [dict(r) for r in db.execute("""
            SELECT sv.*,
                   COUNT(so.id) AS observations,
                   SUM(CASE WHEN so.selected=1 THEN 1 ELSE 0 END) AS selected_observations,
                   MAX(so.scan_time) AS last_observed_at
            FROM strategy_variants sv
            LEFT JOIN signal_observations so ON so.variant_id = sv.id
            WHERE sv.status='active'
            GROUP BY sv.id
            ORDER BY sv.strategy, sv.brain, sv.execution_time, sv.selection_mode
        """).fetchall()]
        db.close()
        return jsonify(rows)
    except Exception as e:
        log.error(f"strategy-variants error: {e}")
        return jsonify([]), 500

@app.route("/api/ticker-universe")
def api_ticker_universe():
    """Return current scan universe membership for a ticker."""
    try:
        ticker = (request.args.get("ticker") or "").strip().upper()
        universe = build_ticker_universe()
        payload = {
            "success": True,
            "count": len(universe),
            "ticker": ticker or None,
            "present": ticker in universe if ticker else None,
        }
        if ticker:
            payload["note"] = (
                f"{ticker} is in the active scan universe."
                if payload["present"]
                else f"{ticker} is not in the active scan universe; it will not receive scan observations or Why Not rows."
            )
        return jsonify(payload)
    except Exception as e:
        log.error(f"ticker-universe error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/variant-portfolios")
def api_variant_portfolios():
    """Return every live universe portfolio with current counts."""
    try:
        db = get_database()
        rows = [dict(r) for r in db.execute("""
            SELECT sv.id, sv.strategy, sv.brain, sv.execution_time, sv.selection_mode,
                   sv.exit_mode, sv.label, sv.status AS registry_status,
                   vp.*
            FROM strategy_variants sv
            JOIN variant_portfolios vp ON vp.variant_id = sv.id
            WHERE sv.status='active' AND vp.lifecycle_status!='archived'
            ORDER BY sv.strategy, sv.brain, sv.selection_mode
        """).fetchall()]
        db.close()
        for row in rows:
            try:
                row["lifecycle_reasons"] = json.loads(row.get("lifecycle_reasons") or "[]")
            except Exception:
                row["lifecycle_reasons"] = []
        return jsonify(rows)
    except Exception as e:
        log.error(f"variant-portfolios error: {e}")
        return jsonify([]), 500

@app.route("/api/variant-leaderboard")
def api_variant_leaderboard():
    """Rank universes by equity, win rate, drawdown, and sample size."""
    try:
        db = get_database()
        rows = [dict(r) for r in db.execute("""
            SELECT sv.id, sv.strategy, sv.brain, sv.execution_time, sv.selection_mode,
                   sv.exit_mode, sv.label,
                   vp.equity, vp.starting_cash, vp.cash, vp.open_value, vp.open_count,
                   vp.closed_count, vp.win_count, vp.loss_count, vp.max_drawdown_pct,
                   vp.lifecycle_status, vp.recommended_status, vp.lifecycle_reasons,
                   MAX(vt.updated_at) AS last_trade_at
            FROM strategy_variants sv
            JOIN variant_portfolios vp ON vp.variant_id = sv.id
            LEFT JOIN variant_virtual_trades vt ON vt.variant_id = sv.id
            WHERE sv.status='active' AND vp.lifecycle_status!='archived'
            GROUP BY sv.id
            ORDER BY vp.equity DESC, vp.win_count DESC, vp.max_drawdown_pct ASC
        """).fetchall()]
        db.close()
        for idx, row in enumerate(rows, start=1):
            closed = int(row.get("closed_count") or 0)
            wins = int(row.get("win_count") or 0)
            row["rank"] = idx
            row["return_pct"] = round((float(row.get("equity") or 1000) - float(row.get("starting_cash") or 1000)) / max(float(row.get("starting_cash") or 1000), 0.01) * 100, 2)
            row["win_rate"] = round(wins / closed * 100, 1) if closed else None
            try:
                row["lifecycle_reasons"] = json.loads(row.get("lifecycle_reasons") or "[]")
            except Exception:
                row["lifecycle_reasons"] = []
        return jsonify(rows)
    except Exception as e:
        log.error(f"variant-leaderboard error: {e}")
        return jsonify([]), 500

@app.route("/api/variant-status")
def api_variant_status():
    """Small operational summary for UI and quick Railway checks."""
    try:
        db = get_database()
        last_run = get_app_state_json("last_variant_run", {}) or {}
        last_monitor = get_app_state_json("last_variant_monitor", {}) or {}
        snapshot, refusal = variant_cache_snapshot(db, require_fresh=False)
        counts = db.execute("""
            SELECT
                COUNT(*) AS variants,
                SUM(CASE WHEN brain='Vector' THEN 1 ELSE 0 END) AS vector_variants,
                SUM(CASE WHEN brain='Nova' THEN 1 ELSE 0 END) AS nova_variants
            FROM strategy_variants
            WHERE status='active'
        """).fetchone()
        portfolio = db.execute("""
            SELECT
                SUM(open_count) AS open_positions,
                SUM(closed_count) AS closed_positions,
                MAX(equity) AS best_equity,
                MIN(equity) AS worst_equity
            FROM variant_portfolios
            WHERE lifecycle_status!='archived'
        """).fetchone()
        db.close()
        payload = {
            "success": True,
            "variants": counts["variants"] if counts else 0,
            "vector_variants": counts["vector_variants"] if counts else 0,
            "nova_variants": counts["nova_variants"] if counts else 0,
            "open_positions": portfolio["open_positions"] if portfolio else 0,
            "closed_positions": portfolio["closed_positions"] if portfolio else 0,
            "best_equity": portfolio["best_equity"] if portfolio else None,
            "worst_equity": portfolio["worst_equity"] if portfolio else None,
            "last_run": last_run,
            "last_monitor": last_monitor,
        }
        if snapshot:
            vector_pick_count = len(snapshot["vector_payload"].get("longs") or snapshot["vector_payload"].get("recommended_longs") or [])
            nova_pick_count = len(snapshot["nova_payload"].get("recommended_longs") or snapshot["nova_payload"].get("longs") or [])
            payload.update({
                "shared_snapshot": True,
                "vector_cache_time": snapshot["vector_cache_time"],
                "nova_cache_time": snapshot["nova_cache_time"],
                "vector_cache_age_minutes": snapshot["vector_cache_age_minutes"],
                "nova_cache_age_minutes": snapshot["nova_cache_age_minutes"],
                "cache_gap_minutes": snapshot["cache_gap_minutes"],
                "vector_pick_count": vector_pick_count,
                "nova_pick_count": nova_pick_count,
            })
        else:
            payload["shared_snapshot"] = False
            payload["cache_issue"] = refusal
        now = current_time_cst()
        last_run_date = str((last_run or {}).get("ran_at") or "")[:10]
        last_run_succeeded = bool((last_run or {}).get("success", True)) and not bool((last_run or {}).get("refused"))
        today = now.strftime("%Y-%m-%d")
        has_openable_snapshot = bool((payload.get("vector_pick_count") or 0) + (payload.get("nova_pick_count") or 0))
        after_primary_execution = now.hour > 8 or (now.hour == 8 and now.minute >= 50)
        payload["missed_variant_open_alert"] = bool(
            after_primary_execution and
            has_openable_snapshot and
            int(payload.get("open_positions") or 0) == 0 and
            (last_run_date != today or not last_run_succeeded)
        )
        payload["missed_variant_open_reason"] = (
            "Cached Vector/Nova picks exist after 8:50 AM Central, but no variant universe has open positions and last_variant_run did not successfully open today."
            if payload["missed_variant_open_alert"] else None
        )
        return jsonify(payload)
    except Exception as e:
        log.error(f"variant-status error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/variant-health")
def api_variant_health():
    """Operational proof that each active variant has current inputs, portfolio state, and preview results."""
    try:
        db = get_database()
        snapshot, refusal = variant_cache_snapshot(db, require_fresh=False)
        variants = [dict(r) for r in db.execute("""
            SELECT sv.id, sv.strategy, sv.brain, sv.execution_time, sv.selection_mode, sv.exit_mode, sv.label,
                   sv.status AS registry_status,
                   vp.lifecycle_status, vp.open_count, vp.closed_count, vp.equity, vp.updated_at AS portfolio_updated_at,
                   MAX(vt.updated_at) AS last_trade_at
            FROM strategy_variants sv
            LEFT JOIN variant_portfolios vp ON vp.variant_id=sv.id
            LEFT JOIN variant_virtual_trades vt ON vt.variant_id=sv.id
            WHERE sv.status='active'
            GROUP BY sv.id
            ORDER BY sv.brain, sv.strategy, sv.execution_time, sv.selection_mode
        """).fetchall()]
        latest_observation = db.execute("SELECT MAX(scan_time) AS ts FROM signal_observations").fetchone()["ts"]
        db.close()

        vector_picks = []
        nova_picks = []
        if snapshot:
            vector_picks = snapshot["vector_payload"].get("longs") or snapshot["vector_payload"].get("recommended_longs") or []
            nova_picks = snapshot["nova_payload"].get("recommended_longs") or snapshot["nova_payload"].get("longs") or []

        rows = []
        for variant in variants:
            source = nova_picks if variant.get("brain") == "Nova" else vector_picks
            if variant.get("brain") == "Nova":
                source = [p for p in source if p.get("nn_executable", True)]
            qualified = filter_variant_strategy_picks(source, variant) if snapshot else []
            selected = select_variant_picks(qualified, variant.get("selection_mode")) if snapshot else []
            issues = []
            evaluation_state = "not_evaluated"
            if not snapshot:
                issues.append(refusal.get("reason", "missing_shared_snapshot") if isinstance(refusal, dict) else "missing_shared_snapshot")
            if variant.get("lifecycle_status") == "archived":
                issues.append("portfolio_archived")
            if snapshot:
                if not source:
                    evaluation_state = "evaluated_no_source_candidates"
                elif selected:
                    evaluation_state = "selected_candidates"
                elif qualified:
                    evaluation_state = "qualified_but_not_selected"
                else:
                    evaluation_state = "evaluated_no_pick"
            health = "attention" if issues else "ok"
            rows.append({
                **variant,
                "source_count": len(source),
                "strategy_qualified": len(qualified),
                "selected_count": len(selected),
                "selected_tickers": [p.get("ticker") for p in selected[:20]],
                "last_shared_observation_at": latest_observation,
                "evaluation_state": evaluation_state,
                "health": health,
                "issues": issues,
            })

        ok_count = sum(1 for row in rows if row["health"] == "ok")
        selected_count = sum(1 for row in rows if row["evaluation_state"] == "selected_candidates")
        no_pick_count = sum(1 for row in rows if row["evaluation_state"] == "evaluated_no_pick")
        no_source_count = sum(1 for row in rows if row["evaluation_state"] == "evaluated_no_source_candidates")
        return jsonify({
            "success": True,
            "shared_snapshot": bool(snapshot),
            "cache_issue": refusal,
            "latest_observation_at": latest_observation,
            "variant_count": len(rows),
            "ok_count": ok_count,
            "attention_count": len(rows) - ok_count,
            "selected_count": selected_count,
            "no_pick_count": no_pick_count,
            "no_source_count": no_source_count,
            "rows": rows,
            "note": "OK means the variant registry, portfolio, and shared snapshot plumbing are usable. Evaluation state tells whether it selected candidates, found no qualifying pick, or had no source candidates from its brain.",
        })
    except Exception as e:
        log.error(f"variant-health error: {e}")
        return jsonify({"success": False, "error": str(e), "rows": []}), 500

@app.route("/api/variant-ledger-proof")
def api_variant_ledger_proof():
    """Glass-house proof for variant aliveness, closed-trade learning, and ledger reconciliation."""
    try:
        db = get_database()
        snapshot, refusal = variant_cache_snapshot(db, require_fresh=False)
        variants = [dict(r) for r in db.execute("""
            SELECT sv.id, sv.strategy, sv.brain, sv.execution_time, sv.selection_mode,
                   sv.exit_mode, sv.label, sv.status
            FROM strategy_variants sv
            WHERE sv.status='active'
            ORDER BY sv.brain, sv.strategy, sv.execution_time, sv.selection_mode
        """).fetchall()]
        rows = [
            build_variant_ledger_proof_core(
                db,
                variant,
                snapshot=snapshot,
                get_weights=get_variant_signal_weights,
                filter_picks=filter_variant_strategy_picks,
                select_picks=select_variant_picks,
                explain_strategy=explain_variant_strategy_match,
            )
            for variant in variants
        ]
        db.close()

        ok_rows = [row for row in rows if row["health"] == "ok"]
        ledger_mismatches = [row for row in rows if not row["ledger_ok"]]
        learned_open = [
            row for row in rows
            if row["learning"]["learned_open_trade_ids"]
        ]
        unlearned_closed = [
            row for row in rows
            if row["learning"]["unlearned_closed_trade_count"] > 0
        ]
        outcome_mismatches = [
            row for row in rows
            if row.get("outcome_integrity", {}).get("mismatch_count", 0) > 0
        ]
        no_pick_rows = [
            row for row in rows
            if row["evaluation_state"] == "evaluated_no_pick"
        ]

        return jsonify({
            "success": True,
            "shared_snapshot": bool(snapshot),
            "cache_issue": refusal,
            "variant_count": len(rows),
            "ok_count": len(ok_rows),
            "attention_count": len(rows) - len(ok_rows),
            "ledger_mismatch_count": len(ledger_mismatches),
            "learned_open_trade_count": len(learned_open),
            "unlearned_closed_variant_count": len(unlearned_closed),
            "outcome_mismatch_variant_count": len(outcome_mismatches),
            "evaluated_no_pick_count": len(no_pick_rows),
            "rows": rows,
            "contract": proof_contract(),
        })
    except Exception as e:
        log.error(f"variant-ledger-proof error: {e}")
        return jsonify({"success": False, "error": str(e), "rows": []}), 500

@app.route("/api/variant-strategy-preview")
def api_variant_strategy_preview():
    """Show how each active strategy would filter the current shared snapshot."""
    try:
        db = get_database()
        snapshot, refusal = variant_cache_snapshot(db, require_fresh=False)
        variants = [dict(r) for r in db.execute("""
            SELECT id, strategy, brain, execution_time, selection_mode, label
            FROM strategy_variants
            WHERE status='active'
            ORDER BY strategy, brain, selection_mode
        """).fetchall()]
        db.close()
        if not snapshot:
            return jsonify({"success": False, "cache_issue": refusal, "rows": []})

        vector_picks = snapshot["vector_payload"].get("longs") or snapshot["vector_payload"].get("recommended_longs") or []
        nova_picks = snapshot["nova_payload"].get("recommended_longs") or snapshot["nova_payload"].get("longs") or []
        rows = []
        for variant in variants:
            source = nova_picks if variant["brain"] == "Nova" else vector_picks
            if variant["brain"] == "Nova":
                source = [p for p in source if p.get("nn_executable", True)]
            qualified = filter_variant_strategy_picks(source, variant)
            selected = select_variant_picks(qualified, variant.get("selection_mode"))
            rows.append({
                "variant_id": variant["id"],
                "label": variant["label"],
                "strategy": variant["strategy"],
                "brain": variant["brain"],
                "execution_time": variant["execution_time"],
                "selection_mode": variant["selection_mode"],
                "source_count": len(source),
                "qualified_count": len(qualified),
                "selected_count": len(selected),
                "selected_tickers": [p.get("ticker") for p in selected[:20]],
                "qualified_preview": [
                    {
                        **p,
                        "ticker": p.get("ticker"),
                        "confidence": p.get("long_conf") or p.get("confidence") or p.get("nn_score"),
                        "move": p.get("long_move") or p.get("expected_move"),
                        "day_change_pct": (
                            p.get("pct_change_prev_close")
                            if p.get("pct_change_prev_close") is not None
                            else p.get("day_change_pct")
                        ),
                        "gap_pct": (
                            p.get("overnight_gap_pct")
                            if p.get("overnight_gap_pct") is not None
                            else p.get("gap_percent")
                        ),
                        "source_scan_time": p.get("source_scan_time") or snapshot.get("vector_cache_time" if variant["brain"] == "Vector" else "nova_cache_time"),
                        "source_variant_id": variant["id"],
                    }
                    for p in qualified[:10]
                ],
            })
        return jsonify({
            "success": True,
            "vector_cache_time": snapshot["vector_cache_time"],
            "nova_cache_time": snapshot["nova_cache_time"],
            "cache_gap_minutes": snapshot["cache_gap_minutes"],
            "rows": rows,
        })
    except Exception as e:
        log.error(f"variant-strategy-preview error: {e}")
        return jsonify({"success": False, "error": str(e), "rows": []}), 500

@app.route("/api/variant/<variant_id>")
def api_variant_detail(variant_id):
    """Return one universe with portfolio, trades, equity curve, and mutable weights."""
    try:
        db = get_database()
        variant = db.execute("SELECT * FROM strategy_variants WHERE id=?", [variant_id]).fetchone()
        if not variant:
            db.close()
            return jsonify({"error": "variant not found"}), 404
        portfolio = db.execute("SELECT * FROM variant_portfolios WHERE variant_id=?", [variant_id]).fetchone()
        weights = db.execute("SELECT * FROM variant_signal_weights WHERE variant_id=?", [variant_id]).fetchone()
        trades = [dict(r) for r in db.execute("""
            SELECT * FROM variant_virtual_trades
            WHERE variant_id=?
              AND outcome NOT IN ('archived_excess_open')
            ORDER BY buy_date DESC, created_at DESC
            LIMIT 200
        """, [variant_id]).fetchall()]
        equity = [dict(r) for r in db.execute("""
            SELECT * FROM variant_equity_points
            WHERE variant_id=?
            ORDER BY timestamp DESC
            LIMIT 500
        """, [variant_id]).fetchall()]
        equity = [decorate_variant_equity_point(point) for point in equity]
        db.close()
        payload = {
            "variant": dict(variant),
            "portfolio": dict(portfolio) if portfolio else None,
            "weights": dict(weights) if weights else None,
            "trades": trades,
            "equity_points": equity,
        }
        if payload["weights"]:
            for key in ("weights_json", "baseline_weights_json"):
                try:
                    payload["weights"][key] = json.loads(payload["weights"][key] or "{}")
                except Exception:
                    payload["weights"][key] = {}
            payload["weights"]["weight_count"] = len(payload["weights"].get("weights_json") or {})
            payload["weights"]["baseline_weight_count"] = len(payload["weights"].get("baseline_weights_json") or {})
        if payload["portfolio"]:
            try:
                payload["portfolio"]["lifecycle_reasons"] = json.loads(payload["portfolio"].get("lifecycle_reasons") or "[]")
            except Exception:
                payload["portfolio"]["lifecycle_reasons"] = []
        return jsonify(payload)
    except Exception as e:
        log.error(f"variant detail error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/variant-learning-events")
def api_variant_learning_events():
    """Recent per-universe weight updates for Vector/Nova QA."""
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 5000)
        offset = max(int(request.args.get("offset", 0)), 0)
        paged = str(request.args.get("paged", "")).lower() in ("1", "true", "yes")
        variant_id = request.args.get("variant_id")
        where = "WHERE e.variant_id=?" if variant_id else ""
        params = [variant_id] if variant_id else []
        db = get_database()
        total = db.execute(f"SELECT COUNT(*) AS n FROM variant_learning_events e {where}", params).fetchone()["n"]
        rows = [dict(r) for r in db.execute(f"""
            SELECT e.*,
                   t.ticker, t.buy_date, t.sell_date, t.sell_time,
                   t.sell_reason, t.outcome AS trade_outcome
            FROM variant_learning_events e
            LEFT JOIN variant_virtual_trades t ON t.id = e.trade_id
            {where}
            ORDER BY e.timestamp DESC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()]
        db.close()
        for row in rows:
            for key in ("weights_before", "weights_after", "reasoning"):
                try:
                    row[key] = json.loads(row[key] or "{}")
                except Exception:
                    row[key] = [] if key == "reasoning" else {}
        if paged:
            return jsonify({"rows": rows, "total": total, "limit": limit, "offset": offset})
        return jsonify(rows)
    except Exception as e:
        log.error(f"variant-learning-events error: {e}")
        return jsonify([]), 500

@app.route("/api/run-daily-variant-learning", methods=["POST"])
def api_run_daily_variant_learning():
    """Manually run the same closed-trade learning batch used by the 7 PM job."""
    return jsonify(run_daily_variant_learning())

@app.route("/api/variant-run-now", methods=["POST"])
def api_variant_run_now():
    """Manually run active universes from the latest cached shared scan."""
    body = request.get_json(silent=True) or {}
    buy_time = body.get("buy_time")
    trigger = body.get("trigger") or ("manual_recovery" if buy_time else "manual")
    return jsonify(run_variant_universes_from_cache(trigger=trigger, buy_time=buy_time))

@app.route("/api/recover-missed-variant-open", methods=["POST"])
def api_recover_missed_variant_open():
    """Replay the 8:45 universe run from the latest cached shared scan.

    Idempotent: run_variant_universes_from_cache skips any variant/ticker/date
    trade id that already exists before opening a new simulated position.
    """
    try:
        body = request.get_json(silent=True) or {}
        buy_time = body.get("buy_time") or "08:45:00"
        result = run_variant_universes_from_cache(
            trigger="manual_recovery_0845",
            buy_time=buy_time,
            require_fresh=False,
        )
        return jsonify(result), 200 if result.get("success", True) else 500
    except Exception as e:
        log.error(f"Manual missed variant-open recovery failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/recover-missed-variant-open-from-executions-preview", methods=["GET"])
def api_recover_missed_variant_open_from_executions_preview():
    """Preview execution-backed recovery without mutating variant ledgers."""
    database = None
    today = current_time_cst().strftime("%Y-%m-%d")
    try:
        database = get_database()
        variants = [dict(row) for row in database.execute("""
            SELECT sv.id, sv.strategy, sv.brain, sv.execution_time, sv.selection_mode,
                   sv.exit_mode, vp.cash, vp.open_count, vp.lifecycle_status
            FROM strategy_variants sv
            JOIN variant_portfolios vp ON vp.variant_id = sv.id
            WHERE sv.status='active'
              AND vp.lifecycle_status!='archived'
              AND sv.strategy='SwingDesk'
              AND sv.execution_time='08:45'
            ORDER BY sv.brain, sv.id
        """).fetchall()]
        source_tables = {
            "Vector": "virtual_trades",
            "Nova": "nn_virtual_trades",
        }
        source_counts = {}
        source_tickers = {}
        for brain_name, table_name in source_tables.items():
            rows = [dict(row) for row in database.execute(f"""
                SELECT ticker, buy_time, buy_price, invested_amount, outcome
                FROM {table_name}
                WHERE outcome='open'
                  AND buy_date=?
                  AND COALESCE(direction, 'long')='long'
                ORDER BY buy_time ASC, ticker ASC
            """, [today]).fetchall()]
            source_counts[brain_name] = len(rows)
            source_tickers[brain_name] = rows
        existing_variant_opens = [dict(row) for row in database.execute("""
            SELECT variant_id, ticker, buy_date, buy_time
            FROM variant_virtual_trades
            WHERE outcome='open'
              AND buy_date=?
            ORDER BY variant_id, ticker
        """, [today]).fetchall()]
        return jsonify({
            "success": True,
            "today": today,
            "target_strategy": "SwingDesk",
            "target_execution_time": "08:45",
            "variant_count": len(variants),
            "variants": variants,
            "source_counts": source_counts,
            "source_tickers": source_tickers,
            "existing_variant_open_count": len(existing_variant_opens),
            "existing_variant_opens": existing_variant_opens,
            "would_recover": any(source_counts.get(variant.get("brain"), 0) for variant in variants),
        })
    except Exception as error:
        log.error(f"recover missed variant open preview failed: {error}")
        return jsonify({"success": False, "today": today, "error": str(error)}), 500
    finally:
        if database:
            database.close()

@app.route("/api/recover-missed-variant-open-from-executions", methods=["POST"])
def api_recover_missed_variant_open_from_executions():
    """Recover primary SwingDesk 8:45 simulation universes from real open executions.

    Use this when the main Vector/Nova opening engines succeeded but the variant
    universe runner missed its 8:45 job. It only reconstructs the primary
    SwingDesk 8:45 universes, using the real open rows as the source of truth.
    """
    today = current_time_cst().strftime("%Y-%m-%d")
    status = {
        "success": True,
        "trigger": "manual_recovery_from_executions",
        "ran_at": current_time_cst().isoformat(),
        "variants": 0,
        "opened_count": 0,
        "skipped_count": 0,
        "opened": [],
        "skipped": [],
        "errors": [],
    }
    database = None
    try:
        database = get_database()
        source_tables = {
            "Vector": "virtual_trades",
            "Nova": "nn_virtual_trades",
        }
        variants = [dict(row) for row in database.execute("""
            SELECT sv.*, vp.cash, vp.equity
            FROM strategy_variants sv
            JOIN variant_portfolios vp ON vp.variant_id = sv.id
            WHERE sv.status='active'
              AND vp.lifecycle_status!='archived'
              AND sv.strategy='SwingDesk'
              AND sv.execution_time='08:45'
        """).fetchall()]
        status["variants"] = len(variants)
        for variant in variants:
            source_table = source_tables.get(variant.get("brain"))
            if not source_table:
                continue
            source_rows = [dict(row) for row in database.execute(f"""
                SELECT *
                FROM {source_table}
                WHERE outcome='open'
                  AND buy_date=?
                  AND COALESCE(direction, 'long')='long'
                ORDER BY buy_time ASC, ticker ASC
            """, [today]).fetchall()]
            if not source_rows:
                status["skipped_count"] += 1
                status["skipped"].append({"variant_id": variant["id"], "reason": f"no {variant.get('brain')} open executions today"})
                update_variant_portfolio(database, variant["id"], note="recovery_no_source_opens")
                continue
            existing_open_count = int(database.execute(
                "SELECT COUNT(*) AS n FROM variant_virtual_trades WHERE variant_id=? AND outcome='open'",
                [variant["id"]],
            ).fetchone()["n"] or 0)
            open_cap = variant_open_position_cap(variant)
            variant_opened = 0
            for rank, source in enumerate(source_rows, start=1):
                if existing_open_count + variant_opened >= open_cap:
                    break
                ticker = source.get("ticker")
                trade_id = f"{variant['id']}_{ticker}_{today}_long"
                if database.execute("SELECT id FROM variant_virtual_trades WHERE id=?", [trade_id]).fetchone():
                    status["skipped_count"] += 1
                    status["skipped"].append({"variant_id": variant["id"], "ticker": ticker, "reason": "already recovered/executed today"})
                    continue
                portfolio = dict(database.execute("SELECT * FROM variant_portfolios WHERE variant_id=?", [variant["id"]]).fetchone())
                invested = variant_investment_amount(portfolio)
                buy_price = float(source.get("buy_price") or source.get("current_price") or 0)
                if invested <= 0 or buy_price <= 0:
                    status["skipped_count"] += 1
                    status["skipped"].append({"variant_id": variant["id"], "ticker": ticker, "reason": "missing cash or buy price"})
                    continue
                day_change_percent = float(source.get("day_change_percent") or source.get("day_change_pct") or 0)
                confidence = int(source.get("lock_in_confidence") or source.get("nn_confidence") or source.get("confidence") or 0)
                expected_move = float(source.get("expected_move") or 0)
                signal_scores = source.get("signal_scores") or json.dumps({"scores": {}, "fired": [], "values": {}})
                confluence_methods = source.get("confluence_methods") or "[]"
                if not isinstance(confluence_methods, str):
                    confluence_methods = json.dumps(confluence_methods)
                confluence_count = int(source.get("confluence_count") or 0)
                fee_quote = calculate_stock_fee_model(invested, buy_price, buy_price, "long")
                database.execute(f"""
                    INSERT INTO variant_virtual_trades
                    (id, variant_id, strategy, brain, ticker, direction, buy_date, buy_time,
                     buy_price, current_price, day_change_percent, invested_amount, current_value, confidence, expected_move,
                     {FEE_MODEL_INSERT_COLUMNS},
                     outcome, sector, reasoning, signal_scores, confluence_count, confluence_methods, source_scan_time, source_rank,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'long', ?, ?, ?, ?, ?, ?, ?, ?, ?, {FEE_MODEL_INSERT_PLACEHOLDERS}, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    trade_id, variant["id"], variant["strategy"], variant["brain"], ticker, today, source.get("buy_time") or "08:45:00",
                    buy_price, buy_price, round(day_change_percent, 4), round(invested, 4), fee_quote["net_current_value"], confidence, expected_move,
                    *fee_model_values(fee_quote),
                    source.get("sector") or get_sector(ticker),
                    source.get("reasoning") or f"{variant['brain']} execution recovery",
                    signal_scores,
                    confluence_count,
                    confluence_methods,
                    source.get("source_scan_time") or source.get("created_at") or status["ran_at"],
                    rank,
                    status["ran_at"],
                    status["ran_at"],
                ])
                database.execute("""
                    UPDATE variant_portfolios
                    SET cash=ROUND(cash - ?, 4), updated_at=?
                    WHERE variant_id=?
                """, [round(invested, 4), status["ran_at"], variant["id"]])
                status["opened_count"] += 1
                variant_opened += 1
                status["opened"].append({
                    "variant_id": variant["id"],
                    "ticker": ticker,
                    "buy_price": buy_price,
                    "invested_amount": round(invested, 4),
                    "source_table": source_table,
                })
            update_variant_portfolio(database, variant["id"], note="recovery_from_executions")
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('last_variant_run', ?)", [json.dumps(status)])
        database.commit()
        return jsonify(json.loads(json.dumps(status, default=str)))
    except Exception as error:
        if database:
            database.rollback()
        status["success"] = False
        status["errors"].append(str(error))
        log.error(f"recover missed variant open from executions failed: {error}")
        return jsonify(json.loads(json.dumps(status, default=str))), 500
    finally:
        if database:
            database.close()

@app.route("/api/variant-monitor-now", methods=["POST"])
def api_variant_monitor_now():
    """Manually refresh all open universe simulations."""
    return jsonify(monitor_variant_universes(trigger="manual"))

@app.route("/api/repair-variant-open-caps", methods=["POST"])
def api_repair_variant_open_caps():
    """One-time maintenance: archive excess pre-cap variant opens."""
    apply_changes = str(request.args.get("apply", "")).lower() in ("1", "true", "yes")
    return jsonify(repair_variant_open_caps(apply_changes=apply_changes))

@app.route("/api/evidence-stats")
def api_evidence_stats():
    """
    Return evidence/calibration foundation stats.
    Confidence-bin outcome stats come from resolved predictions; observation
    coverage comes from the new all-scanned-ticker ledger.
    """
    try:
        evidence_bins = build_confidence_evidence_cache()
        db = get_database()
        observation_total = db.execute("SELECT COUNT(*) AS n FROM signal_observations").fetchone()["n"]
        observation_selected = db.execute("SELECT COUNT(*) AS n FROM signal_observations WHERE selected=1").fetchone()["n"]
        observation_executable = db.execute("SELECT COUNT(*) AS n FROM signal_observations WHERE executable=1").fetchone()["n"]
        last_observation = db.execute("SELECT MAX(scan_time) AS ts FROM signal_observations").fetchone()["ts"]
        by_variant = [dict(r) for r in db.execute("""
            SELECT variant_id, brain,
                   COUNT(*) AS observations,
                   SUM(CASE WHEN selected=1 THEN 1 ELSE 0 END) AS selected,
                   SUM(CASE WHEN executable=1 THEN 1 ELSE 0 END) AS executable,
                   MAX(scan_time) AS last_observed_at
            FROM signal_observations
            GROUP BY variant_id, brain
            ORDER BY observations DESC
        """).fetchall()]
        by_confidence = [dict(r) for r in db.execute("""
            SELECT confidence_bin,
                   COUNT(*) AS observations,
                   SUM(CASE WHEN selected=1 THEN 1 ELSE 0 END) AS selected,
                   SUM(CASE WHEN executable=1 THEN 1 ELSE 0 END) AS executable
            FROM signal_observations
            GROUP BY confidence_bin
            ORDER BY MIN(confidence)
        """).fetchall()]
        db.close()

        return jsonify({
            "confidence_bins": list(evidence_bins.values()),
            "observation_coverage": {
                "total": observation_total,
                "selected": observation_selected,
                "executable": observation_executable,
                "last_observed_at": last_observation,
                "by_variant": by_variant,
                "by_confidence": by_confidence,
            },
            "note": "Evidence stats are observational context only; they do not change Vector or Nova scoring.",
        })
    except Exception as e:
        log.error(f"evidence-stats error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/signal-observations")
def api_signal_observations():
    """Return recent raw scan observations for audit/debug/Aegis research."""
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 500)
        variant_id = request.args.get("variant_id")
        ticker = request.args.get("ticker")
        where = []
        params = []
        if variant_id:
            where.append("variant_id=?")
            params.append(variant_id)
        if ticker:
            where.append("ticker=?")
            params.append(ticker.upper())
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        db = get_database()
        rows = [dict(r) for r in db.execute(f"""
            SELECT *
            FROM signal_observations
            {where_sql}
            ORDER BY scan_time DESC, rank IS NULL, rank ASC, confidence DESC
            LIMIT ?
        """, params + [limit]).fetchall()]
        db.close()
        for row in rows:
            for key in ("signal_scores", "signal_values", "fired_signals", "confluence_methods", "regime_context", "context_json"):
                try:
                    row[key] = json.loads(row[key] or "{}")
                except Exception:
                    row[key] = [] if key in ("fired_signals", "confluence_methods") else {}
        return jsonify(rows)
    except Exception as e:
        log.error(f"signal-observations error: {e}")
        return jsonify([]), 500

@app.route("/api/why-not")
def api_why_not():
    """Explain why a ticker did or did not make the latest pick lists."""
    ticker = (request.args.get("ticker") or "").strip().upper()
    if not ticker:
        return jsonify({"success": False, "error": "ticker is required"}), 400
    try:
        db = get_database()
        open_rows = []
        for table in ("virtual_trades", "nn_virtual_trades", "personal_trades"):
            try:
                open_rows.extend([dict(r) for r in db.execute(
                    f"SELECT ticker, direction, 'open' AS status, '{table}' AS source FROM {table} WHERE outcome='open' AND ticker=?",
                    [ticker],
                ).fetchall()])
            except Exception:
                pass
        open_tickers = {r["ticker"] for r in open_rows}

        obs_rows = [dict(r) for r in db.execute("""
            SELECT *
            FROM signal_observations
            WHERE ticker=?
            ORDER BY scan_time DESC, brain DESC, confidence DESC
            LIMIT 20
        """, [ticker]).fetchall()]
        db.close()

        for row in obs_rows:
            for key in ("signal_scores", "signal_values", "fired_signals", "confluence_methods", "regime_context", "context_json"):
                try:
                    row[key] = json.loads(row[key] or "{}")
                except Exception:
                    row[key] = [] if key in ("fired_signals", "confluence_methods") else {}

        latest_by_brain = {}
        for row in obs_rows:
            brain = row.get("brain") or "Unknown"
            if brain not in latest_by_brain:
                gate = explain_long_pick_gate(row, open_tickers, NN_CONFIDENCE_FLOOR if brain == "Nova" else CONFIDENCE_FLOOR)
                selected = bool(row.get("selected"))
                executable = bool(row.get("executable"))
                if selected:
                    verdict = "selected"
                elif ticker in open_tickers:
                    verdict = "already_open"
                elif not executable:
                    verdict = "not_executable"
                elif not gate["eligible"]:
                    verdict = "failed_gate"
                else:
                    verdict = "ranked_below_selected"
                latest_by_brain[brain] = {
                    "brain": brain,
                    "verdict": verdict,
                    "selected": selected,
                    "executable": executable,
                    "scan_time": row.get("scan_time"),
                    "scan_type": row.get("scan_type"),
                    "rank": row.get("rank"),
                    "sector": row.get("sector"),
                    "confidence_bin": row.get("confidence_bin"),
                    "gate": gate,
                    "scores": row.get("signal_scores") or {},
                    "values": row.get("signal_values") or {},
                    "methods": row.get("confluence_methods") or [],
                    "context": row.get("context_json") or {},
                    "regime": row.get("regime_context") or {},
                }

        return jsonify({
            "success": True,
            "ticker": ticker,
            "open_positions": open_rows,
            "observed": bool(obs_rows),
            "latest": list(latest_by_brain.values()),
            "observation_count": len(obs_rows),
            "note": "This explains the latest stored scan observations. If the market move shown here disagrees with your broker/watchlist, the data feed or freshness layer needs investigation.",
        })
    except Exception as e:
        log.error(f"why-not error for {ticker}: {e}")
        return jsonify({"success": False, "ticker": ticker, "error": str(e)}), 500

@app.route("/api/position-checks/<position_id>")
def api_position_checks(position_id):
    database = get_database()
    rows = [dict(r) for r in database.execute(
        "SELECT * FROM position_checks WHERE position_id=? ORDER BY check_time ASC",
        [position_id]
    ).fetchall()]
    database.close()
    return jsonify(rows)

@app.route("/api/candidates")
def api_candidates():
    database = get_database()
    rows = [dict(r) for r in database.execute(
        "SELECT * FROM candidates WHERE monitoring = 1 ORDER BY confidence DESC"
    ).fetchall()]
    database.close()
    return jsonify(rows)

@app.route("/api/intraday-pnl")
def api_intraday_pnl():
    """Fetch retroactive 5-min intraday data for open positions."""
    database = get_database()
    open_positions = [dict(t) for t in database.execute(
        "SELECT * FROM virtual_trades WHERE outcome='open'"
    ).fetchall()]
    database.close()

    if not open_positions:
        return jsonify({"points": [], "positions": 0})

    try:
        import yfinance as yf
        tickers = list(set(position["ticker"] for position in open_positions))
        data = yf.download(tickers, period="2d", interval="5m",
                           group_by="ticker", auto_adjust=True, progress=False)
        points = []
        if data is not None and len(data) > 0:
            for index in range(len(data)):
                timestamp = data.index[index]
                total_pnl = 0
                for position in open_positions:
                    try:
                        price = (float(data["Close"].iloc[index]) if len(tickers) == 1
                                 else float(data[position["ticker"]]["Close"].iloc[index]))
                        if price != price:
                            continue
                        pnl_pct = (price - position["buy_price"]) / position["buy_price"] * 100
                        if position["direction"] == "short":
                            pnl_pct = -pnl_pct
                        total_pnl += (position["invested_amount"] or DEFAULT_INVESTMENT) * (pnl_pct / 100)
                    except:
                        pass
                points.append({
                    "ts": int(timestamp.timestamp() * 1000),
                    "time": timestamp.strftime("%H:%M"),
                    "date": timestamp.strftime("%Y-%m-%d"),
                    "virtual": round(1000 + total_pnl, 2),
                    "pnl": round(total_pnl, 4),
                })
        return jsonify({"points": points, "positions": len(open_positions)})
    except Exception as error:
        return jsonify({"points": [], "error": str(error)})

@app.route("/api/scan-history")
def api_scan_history():
    mark_stalled_scan_events(max_age_minutes=10)
    database = get_database()
    try:
        requested_limit = int(request.args.get("limit", 75))
    except Exception:
        requested_limit = 75
    try:
        requested_offset = int(request.args.get("offset", 0))
    except Exception:
        requested_offset = 0
    limit = max(1, min(requested_limit, 250))
    offset = max(0, requested_offset)
    paged = str(request.args.get("paged", "")).lower() in {"1", "true", "yes"}

    total_row = database.execute("SELECT COUNT(*) AS total FROM scan_events").fetchone()
    total = int(total_row["total"] or 0) if total_row else 0
    rows = [dict(r) for r in database.execute("""
        SELECT id,
               COALESCE(finished_at, started_at) AS scan_time,
               scan_type,
               job_type,
               status,
               tickers_attempted AS ticker_count,
               tickers_updated,
               picks_count,
               provider_summary,
               error
        FROM scan_events
        ORDER BY started_at DESC
        LIMIT ? OFFSET ?
    """, [limit, offset]).fetchall()]
    if not rows:
        legacy_total_row = database.execute("SELECT COUNT(*) AS total FROM scan_cache").fetchone()
        legacy_total = int(legacy_total_row["total"] or 0) if legacy_total_row else 0
        rows = [dict(r) for r in database.execute("""
            SELECT id,
                   scan_time,
                   scan_type,
                   'legacy' AS job_type,
                   'success' AS status,
                   ticker_count,
                   ticker_count AS tickers_updated,
                   0 AS picks_count,
                   '{}' AS provider_summary,
                   NULL AS error
            FROM scan_cache
            ORDER BY scan_time DESC
            LIMIT ? OFFSET ?
        """, [limit, offset]).fetchall()]
        if not total:
            total = legacy_total
    database.close()
    if paged:
        return jsonify({
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
            "page": offset // limit if limit else 0,
        })
    return jsonify(rows)

@app.route("/api/freshness-status")
def api_freshness_status():
    """Explain whether scans, monitor checks, and provider data are fresh enough to trust."""
    mark_stalled_scan_events(max_age_minutes=10)
    now = current_time_cst()

    def parse_dt(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return None

    def age_minutes(value):
        parsed = parse_dt(value)
        if not parsed:
            return None
        return round((now - parsed).total_seconds() / 60, 1)

    database = get_database()
    last_comprehensive = database.execute("""
        SELECT * FROM scan_events
        WHERE job_type='comprehensive' AND status IN ('success','degraded')
        ORDER BY started_at DESC LIMIT 1
    """).fetchone()
    last_monitor = database.execute("""
        SELECT * FROM scan_events
        WHERE job_type='monitor' AND status IN ('success','degraded','error')
        ORDER BY started_at DESC LIMIT 1
    """).fetchone()
    stale_positions = [dict(r) for r in database.execute("""
        SELECT id, ticker, last_price_updated
        FROM virtual_trades
        WHERE outcome='open'
          AND (last_price_updated IS NULL OR last_price_updated < ?)
        ORDER BY ticker
    """, [(now - timedelta(minutes=10)).isoformat()]).fetchall()]
    provider_rows = [dict(r) for r in database.execute("SELECT * FROM provider_health ORDER BY provider").fetchall()]
    legacy_scan = database.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    database.close()

    comprehensive = dict(last_comprehensive) if last_comprehensive else None
    monitor = dict(last_monitor) if last_monitor else None
    legacy_scan_time = legacy_scan["value"] if legacy_scan else None
    comprehensive_age = age_minutes(comprehensive.get("finished_at") or comprehensive.get("started_at")) if comprehensive else age_minutes(legacy_scan_time)
    monitor_age = age_minutes(monitor.get("finished_at") or monitor.get("started_at")) if monitor else None

    warnings = []
    if comprehensive_age is None:
        warnings.append("No comprehensive scan has been logged.")
    elif comprehensive_age > 45:
        warnings.append(f"Comprehensive scan is stale ({comprehensive_age} min old).")
    if monitor_age is None:
        warnings.append("No open-position monitor pass has been logged.")
    elif is_market_open() and monitor_age > 7:
        warnings.append(f"Open-position monitor is stale ({monitor_age} min old).")
    if stale_positions:
        warnings.append(f"{len(stale_positions)} open positions have stale price updates.")

    decision_status = "safe"
    if warnings:
        decision_status = "degraded"
    if is_market_open() and (monitor_age is None or monitor_age > 15):
        decision_status = "unsafe_stale"

    return jsonify({
        "now_cst": now.isoformat(),
        "decision_status": decision_status,
        "repair_recommended": bool(warnings),
        "repair_endpoint": "/api/freshness-repair-now",
        "warnings": warnings,
        "last_comprehensive_scan": comprehensive or ({"scan_time": legacy_scan_time, "status": "legacy"} if legacy_scan_time else None),
        "last_comprehensive_age_minutes": comprehensive_age,
        "last_open_position_monitor": monitor,
        "last_monitor_age_minutes": monitor_age,
        "stale_open_positions": stale_positions,
        "provider_health": provider_rows,
        "last_provider_summary": get_app_state_json("last_price_provider_summary", {}) or {},
    })

@app.route("/api/open-positions-dynamic")
def api_open_positions_dynamic():
    """
    Return open positions using only DB-stored values.
    All live enrichment (prices, RSI, confidence, news, confluence) is written
    by the 2.5-min monitor on its schedule — this endpoint never calls yfinance.
    """
    try:
        database = get_database()
        open_positions = [dict(t) for t in database.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]
        database.close()

        if not open_positions:
            return jsonify([])

        now_cst = current_time_cst()
        minute_of_day = now_cst.hour * 60 + now_cst.minute
        is_weekday = now_cst.weekday() < 5
        WINDOW1 = 9 * 60 + 30
        WINDOW2 = 11 * 60 + 20
        WINDOW3 = 13 * 60 + 10
        MARKET_OPEN = 8 * 60 + 30
        MARKET_CLOSE = 15 * 60
        evidence_cache = build_confidence_evidence_cache()

        enriched_positions = []
        for position in open_positions:
            ticker = position["ticker"]
            enriched = dict(position)

            # ── P&L from stored current_value (written by 2.5-min monitor) ──
            invested = position.get("invested_amount") or 10.0
            stored_value = position.get("current_value") or invested
            buy_price = position.get("buy_price") or 0
            if buy_price > 0:
                pnl_pct = (stored_value - invested) / max(invested, 0.01) * 100
            else:
                pnl_pct = 0.0
            if abs(pnl_pct) < 0.005:
                pnl_pct = 0.0
            enriched["current_pnl_percent"] = round(pnl_pct, 2)
            enriched["current_value"] = round(stored_value, 4)

            # ── Dynamic confidence/estimate from stored values ──
            enriched["dynamic_confidence"] = position.get("dynamic_confidence") or position.get("confidence", 0)
            enriched["dynamic_estimate"] = position.get("dynamic_estimate") or position.get("expected_move", 0)
            enriched["lock_in_confidence"] = position.get("lock_in_confidence") or position.get("confidence", 0)
            enriched["evidence"] = evidence_for_confidence(enriched["lock_in_confidence"], evidence_cache)
            enriched["last_price_updated"] = position.get("last_price_updated")
            enriched["day_change_percent"] = position.get("day_change_percent") or 0

            # ── Sentiment icon — use stored, fallback to warning ──
            enriched["sentiment_icon"] = position.get("sentiment_icon") or "warning"
            enriched["sentiment"] = position.get("sentiment") or "Monitoring."

            # ── Confluence — always parse from DB, never recalculate ──
            stored_count = position.get("confluence_count") or 0
            stored_methods_raw = position.get("confluence_methods")
            enriched["confluence_count"] = stored_count
            try:
                enriched["confluence_methods"] = json.loads(stored_methods_raw) if isinstance(stored_methods_raw, str) else (stored_methods_raw or [])
            except:
                enriched["confluence_methods"] = []

            # ── 52W — use stored value from DB ──
            enriched["broke_52w_high_days_ago"] = position.get("broke_52w_high_days_ago")

            # ── Signal scores — parse from stored JSON ──
            raw_scores = position.get("signal_scores")
            try:
                parsed = json.loads(raw_scores) if isinstance(raw_scores, str) else (raw_scores or {})
                enriched["signal_scores"] = parsed.get("scores", {})
                enriched["signal_fired"] = parsed.get("fired", [])
                enriched["signal_values"] = parsed.get("values", {})
            except:
                enriched["signal_scores"] = {}
                enriched["signal_fired"] = []
                enriched["signal_values"] = {}

            # ── News — use stored value ──
            enriched["news"] = position.get("news") or []

            enriched_positions.append(enriched)

        # Sort: target hit first, then HOLD, then WEAK, then worst P&L
        def sort_priority(pos):
            pnl = pos.get("current_pnl_percent") or 0
            target = pos.get("expected_move") or 10
            icon = pos.get("sentiment_icon", "")
            if pnl >= target: return (1, -pnl)
            if pnl >= 0: return (2, -pnl)
            if icon == "x": return (0, -pnl)
            return (3, -pnl)

        enriched_positions.sort(key=sort_priority)
        return jsonify(enriched_positions)

    except Exception as e:
        log.error(f"open-positions-dynamic error: {e}")
        try:
            database = get_database()
            positions = [dict(t) for t in database.execute(
                "SELECT * FROM virtual_trades WHERE outcome='open'"
            ).fetchall()]
            database.close()
            return jsonify(positions)
        except:
            return jsonify([]), 500

@app.route("/api/seed-friday", methods=["POST"])
def api_seed_friday():
    """Retroactively populate Friday May 22 2026 trades and position checks."""
    try:
        import yfinance as yf
        friday_date = "2026-05-22"
        
        universe = list(dict.fromkeys([
            "NVDA","META","AMD","TSLA","AMZN","MSFT","PLTR","SOFI","MSTR","JPM",
            "BAC","COIN","GOOGL","AAPL","NFLX","PYPL","HOOD","RBLX","SNAP","UBER",
            "LYFT","RIVN","LCID","GME","AMC","SMCI","IONQ","XOM","RGTI","INTC",
            "MU","QCOM","ARM","AVGO","TSM","ORCL","CRM","SNOW","DDOG","NET",
            "CRWD","ZS","PANW","SHOP","ROKU","SPOT","ABNB","DASH","BB","NOK",
            "TLRY","SNDL","MARA","RIOT","DKNG","PLUG","FCEL","UPST","AFRM",
            "SPCE","QS","CHPT","BLNK",
            "SPY","QQQ","IWM","DIA","ARKK","ARKG","XLF","XLK","XLE","XLV",
        ]))
        
        log.info(f"Seeding Friday trades for {len(universe)} tickers...")
        
        daily_data = yf.download(universe, start="2026-05-18", end="2026-05-23",
                                 interval="1d", group_by="ticker", auto_adjust=True, progress=False)
        intraday_data = yf.download(universe, start="2026-05-22", end="2026-05-23",
                                    interval="5m", group_by="ticker", auto_adjust=True, progress=False)
        
        weights = get_signal_weights()
        scored = []
        
        for ticker in universe:
            try:
                df = daily_data if len(universe)==1 else (daily_data[ticker] if ticker in daily_data.columns.get_level_values(0) else None)
                if df is None or len(df) < 2: continue
                
                friday_close = float(df["Close"].iloc[-1])
                friday_open = float(df["Open"].iloc[-1])
                thursday_close = float(df["Close"].iloc[-2])
                volume = float(df["Volume"].iloc[-1])
                avg_vol = float(df["Volume"].mean())
                
                if friday_close != friday_close or friday_open != friday_open: continue
                
                volume_ratio = volume / max(avg_vol, 1)
                gap_pct = (friday_open - thursday_close) / max(thursday_close, 0.01) * 100
                day_chg = (friday_close - thursday_close) / max(thursday_close, 0.01) * 100
                
                rsi_score = 1.0
                vol_score = min(volume_ratio / 3.5, 1.0)
                gap_score = min(abs(gap_pct) / 10.0, 1.0)
                raw = (rsi_score * weights.get("rsi_momentum", 0.15) +
                       vol_score * weights.get("volume_surge", 0.15) +
                       gap_score * weights.get("overnight_gap_probability", 0.18) +
                       0.6 * weights.get("earnings_catalyst", 0.14) +
                       0.6 * weights.get("support_resistance", 0.13) +
                       0.5 * weights.get("relative_strength", 0.12) +
                       0.5 * weights.get("sector_relative_strength", 0.10) +
                       0.5 * weights.get("vwap_reclaim", 0.08) +
                       0.5 * weights.get("volatility_squeeze", 0.05))
                confidence = min(int(raw * 108), 96)
                expected_move = round(min(4 + (confidence-60)*0.25 + (volume_ratio-1)*1.5 + min(abs(gap_pct)*0.3,3), 25), 1)
                
                if confidence >= CONFIDENCE_FLOOR and expected_move >= MIN_EXPECTED_MOVE:
                    scored.append({
                        "ticker": ticker, "confidence": confidence, "expected_move": expected_move,
                        "open_price": friday_open, "close_price": friday_close,
                        "volume_ratio": round(volume_ratio,2), "gap_percent": round(gap_pct,2),
                        "day_change": round(day_chg,2),
                        "reasoning": f"RSI 50 neutral" + (f" · {volume_ratio:.1f}x vol" if volume_ratio>1.8 else "") + (f" · {gap_pct:+.1f}% gap" if abs(gap_pct)>2 else ""),
                    })
            except: continue
        
        scored.sort(key=lambda x: x["confidence"], reverse=True)
        long_picks = scored[:MAX_LONG_PICKS]
        
        import random
        execution_order = list(long_picks)
        random.shuffle(execution_order)
        
        database = get_database()
        opened = 0
        
        for pick in execution_order:
            trade_id = f"{pick['ticker']}_{friday_date}_long_vt"
            pred_id = f"{pick['ticker']}_{friday_date}_long"
            
            if database.execute("SELECT id FROM virtual_trades WHERE id=?", [trade_id]).fetchone():
                continue
            
            database.execute("""
                INSERT OR IGNORE INTO predictions
                (id, ticker, name, date, direction, confidence, expected_move, entry_price,
                 sell_time_window, reasoning, sector, rsi, volume_ratio, weights_snapshot, logged_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [pred_id, pick["ticker"], pick["ticker"], friday_date, "long",
                  pick["confidence"], pick["expected_move"], pick["open_price"],
                  "9:30-10:30 AM" if pick["confidence"]>=75 else "10:30-12 PM",
                  pick["reasoning"], get_sector(pick["ticker"]), 50.0, pick["volume_ratio"],
                  json.dumps(weights), f"{friday_date}T08:15:00"])
            
            fee_quote = calculate_stock_fee_model(
                DEFAULT_INVESTMENT,
                pick["open_price"],
                pick["open_price"],
                "long",
            )
            database.execute("""
                INSERT INTO virtual_trades
                (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
                 confidence, expected_move, outcome, sector, reasoning, closed_days,
                 status, current_value, intraday_high_pct, intraday_low_pct,
                 fee_model_version, entry_fee, entry_slippage, exit_fee, exit_slippage,
                 total_fees, gross_current_value, share_quantity)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [trade_id, pick["ticker"], "long", friday_date, "08:45:00", pick["open_price"],
                  DEFAULT_INVESTMENT, pick["confidence"], pick["expected_move"],
                  "open", get_sector(pick["ticker"]), pick["reasoning"], 4,
                  "open", fee_quote["net_current_value"], 0.0, 0.0,
                  fee_quote["fee_model_version"], fee_quote["entry_fee"], fee_quote["entry_slippage"],
                  fee_quote["exit_fee"], fee_quote["exit_slippage"], fee_quote["total_fees"],
                  fee_quote["gross_current_value"], fee_quote["share_quantity"]])
            opened += 1
        
        # Backfill 5-minute position checks
        open_trades = [dict(t) for t in database.execute(
            "SELECT * FROM virtual_trades WHERE buy_date=? AND outcome='open'", [friday_date]
        ).fetchall()]
        
        checks_total = 0
        if intraday_data is not None and len(intraday_data) > 0:
            for trade in open_trades:
                ticker = trade["ticker"]
                buy_price = trade["buy_price"]
                try:
                    ticker_5m = intraday_data if len(universe)==1 else (intraday_data[ticker] if ticker in intraday_data.columns.get_level_values(0) else None)
                    if ticker_5m is None: continue
                    
                    all_pcts = []
                    for idx in range(len(ticker_5m)):
                        ts = ticker_5m.index[idx]
                        if ts.hour < 8 or (ts.hour == 8 and ts.minute < 45): continue
                        price = float(ticker_5m["Close"].iloc[idx])
                        if price != price: continue
                        pnl_pct = (price - buy_price) / buy_price * 100
                        all_pcts.append(pnl_pct)
                        database.execute("""
                            INSERT OR IGNORE INTO position_checks
                            (position_id, check_time, price, pnl_percent, sentiment, ticker)
                            VALUES (?,?,?,?,?,?)
                        """, [trade["id"], ts.isoformat(), price, round(pnl_pct,2), "monitoring", ticker])
                        checks_total += 1
                    
                    if all_pcts:
                        last_pct = all_pcts[-1]
                        final_price = buy_price * (1 + last_pct / 100)
                        fee_quote = calculate_stock_fee_model(DEFAULT_INVESTMENT, buy_price, final_price, "long")
                        database.execute("""
                            UPDATE virtual_trades
                            SET current_value=?, intraday_high_pct=?, intraday_low_pct=?,
                                fee_model_version=?, entry_fee=?, entry_slippage=?,
                                exit_fee=?, exit_slippage=?, total_fees=?,
                                gross_current_value=?, share_quantity=?
                            WHERE id=?
                        """, [
                            fee_quote["net_current_value"], round(max(all_pcts), 2), round(min(all_pcts), 2),
                            fee_quote["fee_model_version"], fee_quote["entry_fee"], fee_quote["entry_slippage"],
                            fee_quote["exit_fee"], fee_quote["exit_slippage"], fee_quote["total_fees"],
                            fee_quote["gross_current_value"], fee_quote["share_quantity"], trade["id"],
                        ])
                except: continue
        
        database.commit()
        database.close()
        
        return jsonify({
            "success": True,
            "trades_opened": opened,
            "total_candidates": len(long_picks),
            "position_checks": checks_total,
            "note": "Weekend holds — close Tuesday after Memorial Day"
        })
    except Exception as error:
        log.error(f"Seed error: {error}")
        return jsonify({"success": False, "error": str(error)}), 500

# ── BANNER PRICES ─────────────────────────────────────────────────────────────
@app.route("/api/banner-prices")
def api_banner_prices():
    """Return latest prices for VIX, SPY, QQQ + any open position tickers.
    Uses fast_info per ticker for reliability — avoids batch download 400s."""
    try:
        import yfinance as yf
        database = get_database()
        open_tickers = [r["ticker"] for r in database.execute(
            "SELECT ticker FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]
        database.close()

        # ^VIX is the correct yfinance symbol for VIX index
        base = ["^VIX", "SPY", "QQQ", "IWM", "NVDA", "TLT", "GLD", "BTC-USD"]
        all_tickers = list(dict.fromkeys(base + open_tickers))

        results = {}
        for ticker in all_tickers:
            try:
                fi = yf.Ticker(ticker).fast_info
                price = fi.last_price
                prev = fi.previous_close
                if price and prev and price == price and prev == prev:
                    change = price - prev
                    change_pct = (change / prev) * 100
                    # Store under display name (VIX not ^VIX)
                    display = ticker.lstrip("^")
                    results[display] = {
                        "price": round(float(price), 2),
                        "prev_close": round(float(prev), 2),
                        "change": round(float(change), 2),
                        "change_pct": round(float(change_pct), 2),
                    }
                time.sleep(0.1)
            except Exception as e:
                log.debug(f"Banner price skip {ticker}: {e}")

        return jsonify(results)
    except Exception as e:
        log.error(f"Banner prices error: {e}")
        return jsonify({}), 500

# ── BACKFILL CLOSE PRICES ─────────────────────────────────────────────────────
@app.route("/api/backfill-close-prices", methods=["POST"])
def api_backfill_close_prices():
    """
    One-time (or on-demand) fix: fetch the last trading day's closing price
    for every open position and write it into current_value in the DB.
    Call this on weekends when positions are showing 0.0% because the monitor
    never wrote a real price before market close.
    """
    try:
        import yfinance as yf
        database = get_database()
        open_positions = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]

        if not open_positions:
            database.close()
            return jsonify({"success": True, "updated": 0, "message": "No open positions"})

        tickers = list(set(p["ticker"] for p in open_positions))
        log.info(f"Backfilling close prices for {tickers}")

        raw = yf.download(tickers, period="5d", auto_adjust=True, progress=False)
        close_prices = {}

        if len(tickers) == 1:
            ticker = tickers[0]
            closes = raw["Close"] if "Close" in raw else raw
            if not closes.empty:
                close_prices[ticker] = float(closes.dropna().iloc[-1])
        else:
            if "Close" in raw:
                for ticker in tickers:
                    try:
                        col = raw["Close"][ticker].dropna()
                        if not col.empty:
                            close_prices[ticker] = float(col.iloc[-1])
                    except Exception as e:
                        log.warning(f"Could not get close for {ticker}: {e}")

        updated = 0
        results = []
        for position in open_positions:
            ticker = position["ticker"]
            if ticker not in close_prices:
                results.append({"ticker": ticker, "status": "no_price"})
                continue

            close = close_prices[ticker]
            buy_price = position["buy_price"] or 0
            invested = position["invested_amount"] or 10.0

            if buy_price <= 0:
                results.append({"ticker": ticker, "status": "no_buy_price"})
                continue

            pnl_pct = (close - buy_price) / buy_price * 100
            if position["direction"] == "short":
                pnl_pct = -pnl_pct
            fee_quote = calculate_stock_fee_model(invested, buy_price, close, position["direction"])
            current_value = fee_quote["net_current_value"]

            database.execute("""
                UPDATE virtual_trades
                SET current_value=?, fee_model_version=?, entry_fee=?, entry_slippage=?,
                    exit_fee=?, exit_slippage=?, total_fees=?, gross_current_value=?, share_quantity=?
                WHERE id=?
            """, [
                round(current_value, 4), fee_quote["fee_model_version"],
                fee_quote["entry_fee"], fee_quote["entry_slippage"],
                fee_quote["exit_fee"], fee_quote["exit_slippage"], fee_quote["total_fees"],
                fee_quote["gross_current_value"], fee_quote["share_quantity"], position["id"],
            ])
            updated += 1
            results.append({
                "ticker": ticker,
                "buy_price": buy_price,
                "close_price": round(close, 4),
                "pnl_pct": round(pnl_pct, 2),
                "current_value": round(current_value, 4),
                "status": "updated"
            })
            log.info(f"Backfilled {ticker}: buy={buy_price} close={close} pnl={pnl_pct:.2f}%")

        database.commit()
        database.close()
        return jsonify({"success": True, "updated": updated, "results": results})

    except Exception as e:
        log.error(f"Backfill error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── FIX BUY PRICES ───────────────────────────────────────────────────────────
@app.route("/api/fix-buy-prices", methods=["POST"])
def api_fix_buy_prices():
    """
    One-time correction: write the verified 8:45 AM CST open prices for the
    May 24 positions whose buy prices were recorded incorrectly.
    Also recalculates current_value using Friday's close via yfinance daily data.
    """
    CORRECT_PRICES = {
        "DELL": (282.05, 295.20),
        "WDAY": (133.24, 128.17),
        "ROST": (234.12, 234.81),
        "EL":   (87.97,  88.32),
        "TTWO": (231.87, 227.68),
        "GNRC": (257.72, 270.15),
    }

    try:
        database = get_database()
        results = []
        updated = 0

        for ticker, (correct_price, close_price) in CORRECT_PRICES.items():
            position = database.execute(
                "SELECT * FROM virtual_trades WHERE ticker=? AND outcome='open'", [ticker]
            ).fetchone()

            if not position:
                results.append({"ticker": ticker, "status": "not_found"})
                continue

            position = dict(position)
            invested = position["invested_amount"] or 10.0

            pnl_pct = (close_price - correct_price) / correct_price * 100
            if position["direction"] == "short":
                pnl_pct = -pnl_pct
            if abs(pnl_pct) < 0.005:
                pnl_pct = 0.0
            fee_quote = calculate_stock_fee_model(invested, correct_price, close_price, position["direction"])
            current_value = fee_quote["net_current_value"]

            database.execute("""
                UPDATE virtual_trades
                SET buy_price=?, current_value=?, fee_model_version=?, entry_fee=?, entry_slippage=?,
                    exit_fee=?, exit_slippage=?, total_fees=?, gross_current_value=?, share_quantity=?
                WHERE id=?
            """, [
                correct_price, round(current_value, 4), fee_quote["fee_model_version"],
                fee_quote["entry_fee"], fee_quote["entry_slippage"],
                fee_quote["exit_fee"], fee_quote["exit_slippage"], fee_quote["total_fees"],
                fee_quote["gross_current_value"], fee_quote["share_quantity"], position["id"],
            ])
            updated += 1
            results.append({
                "ticker": ticker,
                "old_buy_price": position["buy_price"],
                "correct_buy_price": correct_price,
                "close_price": round(close_price, 4),
                "pnl_pct": round(pnl_pct, 2),
                "current_value": round(current_value, 4),
                "status": "updated"
            })
            log.info(f"Fixed {ticker}: old={position['buy_price']} correct={correct_price} pnl={pnl_pct:.2f}%")

        database.commit()
        database.close()
        return jsonify({"success": True, "updated": updated, "results": results})

    except Exception as e:
        log.error(f"Fix buy prices error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── SECTOR BACKFILL ──────────────────────────────────────────────────────────
@app.route("/api/backfill-sectors", methods=["POST"])
def api_backfill_sectors():
    """
    One-time backfill: fetch and cache Finnhub sector for all universe tickers.
    Runs ~500 calls at 1.1s each — takes ~10 minutes. Call once, cached forever.
    """
    def _run():
        universe = build_ticker_universe()
        total = len(universe)
        done = 0
        updated = 0
        for ticker in universe:
            try:
                existing = get_sector(ticker)
                if existing != "Other":
                    done += 1
                    continue
                sector = fetch_and_cache_sector(ticker)
                if sector != "Other":
                    updated += 1
                time.sleep(1.1)
            except Exception as e:
                log.debug(f"Sector backfill skip {ticker}: {e}")
            done += 1
            if done % 50 == 0:
                log.info(f"Sector backfill progress: {done}/{total} ({updated} mapped)")
        log.info(f"Sector backfill complete: {updated}/{total} tickers mapped")
        set_app_state("sector_backfill_done", current_time_cst().isoformat())

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"success": True, "message": "Sector backfill running in background. Check logs."})

# ── BACKFILL TAGS ─────────────────────────────────────────────────────────────
@app.route("/api/reprice-open-entries", methods=["POST"])
def api_reprice_open_entries():
    """
    Recalculate open trade entry prices from their recorded buy_time candle.
    Use after a manual recovery if entries were approximated with live quotes.
    """
    try:
        database = get_database()
        open_positions = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]

        if not open_positions:
            database.close()
            return jsonify({"success": True, "updated": 0, "results": []})

        results = []
        updated = 0
        for position in open_positions:
            ticker = position["ticker"]
            try:
                buy_date = datetime.strptime(position["buy_date"], "%Y-%m-%d")
                buy_time_raw = position.get("buy_time") or "08:45:00"
                hour, minute, second = [int(part) for part in buy_time_raw.split(":")[:3]]
                target = buy_date.replace(hour=hour, minute=minute, second=second, microsecond=0)

                pinned = (
                    fetch_massive_price_at_cst(ticker, target)
                    or fetch_finnhub_price_at_cst(ticker, target)
                    or fetch_alpha_vantage_price_at_cst(ticker, target)
                    or fetch_yfinance_price_at_cst(ticker, target)
                )
                quote = fetch_quote_with_fallback(ticker, use_cache=False)
                if not quote:
                    results.append({"ticker": ticker, "status": "no_current_quote"})
                    time.sleep(1.1)
                    continue
                if not pinned:
                    fallback_price = quote.get("open") or quote.get("price")
                    if not fallback_price:
                        results.append({"ticker": ticker, "status": "no_entry_price"})
                        time.sleep(1.1)
                        continue
                    pinned = {
                        "price": float(fallback_price),
                        "timestamp": None,
                        "source": "finnhub_day_open_fallback",
                    }

                old_buy_price = float(position.get("buy_price") or 0)
                new_buy_price = float(pinned["price"])
                current_price = float(quote["price"])
                invested = float(position.get("invested_amount") or DEFAULT_INVESTMENT)
                pnl_pct = (current_price - new_buy_price) / max(new_buy_price, 0.01) * 100
                if position.get("direction") == "short":
                    pnl_pct = -pnl_pct
                current_value = invested * (1 + pnl_pct / 100)

                database.execute("""
                    UPDATE virtual_trades
                    SET buy_price=?, current_value=?, intraday_high_pct=MAX(COALESCE(intraday_high_pct, 0), ?),
                        intraday_low_pct=MIN(COALESCE(intraday_low_pct, 0), ?), last_price_updated=?
                    WHERE id=?
                """, [
                    round(new_buy_price, 4), round(current_value, 4),
                    round(max(pnl_pct, 0), 2), round(min(pnl_pct, 0), 2),
                    current_time_cst().isoformat(), position["id"]
                ])
                updated += 1
                results.append({
                    "ticker": ticker,
                    "old_buy_price": round(old_buy_price, 4),
                    "new_buy_price": round(new_buy_price, 4),
                    "current_price": round(current_price, 4),
                    "pnl_pct": round(pnl_pct, 2),
                    "current_value": round(current_value, 4),
                    "source": pinned.get("source"),
                    "status": "updated",
                })
                time.sleep(1.1)
            except Exception as item_error:
                results.append({"ticker": ticker, "status": "error", "error": str(item_error)})

        database.commit()
        database.close()
        log.info(f"Repriced open entries: updated {updated}/{len(open_positions)} positions")
        return jsonify({"success": True, "updated": updated, "results": results})
    except Exception as e:
        log.error(f"Reprice open entries error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/reprice-variant-open-entries", methods=["POST"])
def api_reprice_variant_open_entries():
    """
    Repair variant trades whose entry prices were captured from stale quotes.

    The repair is variant-aware: it replays each row's recorded buy_date +
    buy_time, fetches the nearest historical intraday candle, then recalculates
    P&L, fees, and the owning variant ledger. Closed rows are included only
    when explicitly requested because they affect realized P&L and win rate.
    """
    body = request.get_json(silent=True) or {}
    apply_changes = bool(body.get("apply", False))
    include_closed = bool(body.get("include_closed", False))
    target_tickers = {
        str(t).upper()
        for t in body.get("tickers", [])
        if str(t or "").strip()
    }

    database = None
    try:
        database = get_database()
        if include_closed:
            query = "SELECT * FROM variant_virtual_trades WHERE outcome!='archived_excess_open'"
        else:
            query = "SELECT * FROM variant_virtual_trades WHERE outcome='open'"
        params = []
        if target_tickers:
            query += f" AND ticker IN ({','.join(['?'] * len(target_tickers))})"
            params = sorted(target_tickers)
        open_positions = [dict(row) for row in database.execute(query, params).fetchall()]

        if not open_positions:
            return jsonify({
                "success": True,
                "applied": apply_changes,
                "updated": 0,
                "results": [],
            })

        now_iso = current_time_cst().isoformat()
        current_quotes = fetch_current_prices(sorted({
            row["ticker"]
            for row in open_positions
            if row.get("outcome") == "open"
        }))
        touched_variants = set()
        learning_rebuild_variants = set()
        results = []
        updated = 0

        for position in open_positions:
            ticker = position["ticker"]
            try:
                buy_date = datetime.strptime(position["buy_date"], "%Y-%m-%d")
                buy_time_raw = position.get("buy_time") or "08:45:00"
                parts = [int(part) for part in str(buy_time_raw).split(":")[:3]]
                while len(parts) < 3:
                    parts.append(0)
                target = buy_date.replace(hour=parts[0], minute=parts[1], second=parts[2], microsecond=0)

                pinned = (
                    fetch_massive_price_at_cst(ticker, target)
                    or fetch_finnhub_price_at_cst(ticker, target)
                    or fetch_alpha_vantage_price_at_cst(ticker, target)
                    or fetch_yfinance_price_at_cst(ticker, target)
                )
                if not pinned:
                    results.append({
                        "id": position["id"],
                        "variant_id": position["variant_id"],
                        "ticker": ticker,
                        "status": "no_historical_entry_price",
                    })
                    time.sleep(1.1)
                    continue

                raw_quote = current_quotes.get(ticker)
                is_open_row = position.get("outcome") == "open"
                if is_open_row and not raw_quote:
                    results.append({
                        "id": position["id"],
                        "variant_id": position["variant_id"],
                        "ticker": ticker,
                        "status": "no_current_quote",
                    })
                    time.sleep(1.1)
                    continue

                quote = normalize_monitor_quote(raw_quote, pinned["price"]) if raw_quote else {}
                current_price = float(quote.get("price") or position.get("sell_price") or position.get("current_price") or pinned["price"])
                new_buy_price = float(pinned["price"])
                old_buy_price = float(position.get("buy_price") or 0)
                invested = float(position.get("invested_amount") or DEFAULT_INVESTMENT)
                direction = position.get("direction") or "long"
                pnl_pct = (current_price - new_buy_price) / max(new_buy_price, 0.01) * 100
                if direction == "short":
                    pnl_pct = -pnl_pct
                day_change_percent = float(
                    quote.get("day_change_percent")
                    or quote.get("day_change_pct")
                    or position.get("day_change_percent")
                    or 0
                )
                fee_quote = calculate_stock_fee_model(invested, new_buy_price, current_price, direction)
                entry_integrity_status, entry_integrity_note = build_entry_integrity(
                    {**position, "buy_price": new_buy_price},
                    quote,
                )
                old_outcome = position.get("outcome")
                repaired_outcome = old_outcome if is_open_row else classify_variant_outcome_from_pnl(pnl_pct)
                outcome_changed = (not is_open_row) and repaired_outcome != old_outcome

                result = {
                    "id": position["id"],
                    "variant_id": position["variant_id"],
                    "ticker": ticker,
                    "buy_date": position.get("buy_date"),
                    "buy_time": buy_time_raw,
                    "old_buy_price": round(old_buy_price, 4),
                    "new_buy_price": round(new_buy_price, 4),
                    "current_price": round(current_price, 4),
                    "old_pnl_pct": round(float(position.get("actual_move") or 0), 2),
                    "new_pnl_pct": round(pnl_pct, 2),
                    "day_change_percent": round(day_change_percent, 4),
                    "outcome": old_outcome,
                    "repaired_outcome": repaired_outcome,
                    "outcome_changed": outcome_changed,
                    "entry_source": pinned.get("source"),
                    "entry_integrity_status": entry_integrity_status,
                    "applied": apply_changes,
                    "status": "would_update" if not apply_changes else "updated",
                }

                if apply_changes:
                    database.execute(f"""
                        UPDATE variant_virtual_trades
                        SET buy_price=?, current_price=?, current_value=?, day_change_percent=?,
                            actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, {FEE_MODEL_UPDATE_SET},
                            entry_price_source=?, entry_integrity_status=?, entry_integrity_note=?,
                            last_price_updated=?, updated_at=?
                        WHERE id=?
                    """, [
                        round(new_buy_price, 4), round(current_price, 4), round(fee_quote["net_current_value"], 4),
                        round(day_change_percent, 4), round(pnl_pct, 2),
                        fee_quote["gross_pnl"], fee_quote["net_pnl"], repaired_outcome, *fee_model_values(fee_quote),
                        pinned.get("source"), entry_integrity_status, entry_integrity_note,
                        now_iso, now_iso, position["id"],
                    ])
                    touched_variants.add(position["variant_id"])
                    if not is_open_row:
                        learning_rebuild_variants.add(position["variant_id"])
                    updated += 1

                results.append(result)
                time.sleep(1.1)
            except Exception as item_error:
                results.append({
                    "id": position.get("id"),
                    "variant_id": position.get("variant_id"),
                    "ticker": ticker,
                    "status": "error",
                    "error": str(item_error),
                })

        if apply_changes:
            for variant_id in touched_variants:
                update_variant_portfolio(database, variant_id, note="reprice_variant_open_entries")
            learning_rebuilt = rebuild_variant_learning_for_variants(database, learning_rebuild_variants)
        else:
            learning_rebuilt = []
            for result in results:
                if result.get("outcome_changed"):
                    learning_rebuild_variants.add(result.get("variant_id"))
        if apply_changes:
            database.commit()

        return jsonify({
            "success": True,
            "applied": apply_changes,
            "updated": updated,
            "touched_variants": sorted(touched_variants),
            "learning_rebuild_required": sorted(v for v in learning_rebuild_variants if v),
            "learning_rebuilt": learning_rebuilt,
            "results": results,
        })
    except Exception as e:
        if database:
            database.rollback()
        log.error(f"Variant reprice open entries error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        if database:
            database.close()

@app.route("/api/backfill-tags", methods=["POST"])
def api_backfill_tags():
    """
    Backfill confluence_count, confluence_methods, and broke_52w_high_days_ago
    for all open positions using fresh yfinance data.
    """
    try:
        import yfinance as yf
        database = get_database()
        open_positions = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]

        if not open_positions:
            database.close()
            return jsonify({"success": True, "updated": 0})

        tickers = list(set(p["ticker"] for p in open_positions))
        price_data = fetch_price_data(tickers)
        check_52w_breakouts(tickers, price_data)
        enrich_price_data_with_history(tickers, price_data)

        updated = 0
        results = []
        for position in open_positions:
            ticker = position["ticker"]
            confluence = calculate_method_confluence(ticker, price_data)
            conf_count = confluence["count"]
            conf_methods = json.dumps(confluence["methods"])
            broke_52w = price_data.get(ticker, {}).get("broke_52w_high_days_ago")

            try:
                database.execute("""
                    UPDATE virtual_trades SET confluence_count=?, confluence_methods=?
                    WHERE id=?
                """, [conf_count, conf_methods, position["id"]])
                updated += 1
                results.append({
                    "ticker": ticker,
                    "confluence_count": conf_count,
                    "confluence_methods": confluence["methods"],
                    "broke_52w_high_days_ago": broke_52w,
                })
            except Exception as e:
                results.append({"ticker": ticker, "error": str(e)})

        database.commit()
        database.close()
        return jsonify({"success": True, "updated": updated, "results": results})
    except Exception as e:
        log.error(f"Backfill tags error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── COMPREHENSIVE BACKFILL ───────────────────────────────────────────────────
@app.route("/api/backfill-all", methods=["POST"])
def api_backfill_all():
    """
    Comprehensive one-time backfill for all open positions.
    Applies all current scoring logic retroactively:
      - All 10 confluence methods (including VWAP Reclaim, Vol Squeeze)
      - All 9 scoring indicators (including RS, Sector RS, VWAP, HVR)
      - Updated confidence and dynamic_confidence
      - Updated confluence_count and confluence_methods
      - 52W breakout tags

    Safe to call multiple times. Never touches P&L, current_value,
    buy_price, outcome, or any trade outcome data.
    Supersedes /api/backfill-tags and /api/backfill-sr-confidence.
    """
    try:
        database = get_database()
        open_positions = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]

        if not open_positions:
            database.close()
            return jsonify({"success": True, "updated": 0, "message": "No open positions"})

        tickers = list(set(p["ticker"] for p in open_positions))
        weights = get_signal_weights()

        # Fetch all data needed — include SPY for relative strength
        tickers_with_spy = list(dict.fromkeys(tickers + ["SPY"]))
        price_data = fetch_price_data(tickers_with_spy)
        enrich_with_live_prices(tickers_with_spy, price_data)
        rsi_values = calculate_rsi_batch(tickers)
        earnings_soon = check_upcoming_earnings(tickers)
        enrich_price_data_with_history(tickers_with_spy, price_data)
        check_52w_breakouts(tickers, price_data)

        # Pre-compute S&R for all tickers
        for ticker in tickers:
            if ticker in price_data:
                try:
                    price_data[ticker]["expected_move_pct"] = 5.0
                    calculate_support_resistance(ticker, price_data)
                except:
                    pass

        updated = 0
        results = []
        for position in open_positions:
            ticker = position["ticker"]
            if ticker not in price_data:
                results.append({"ticker": ticker, "status": "no_price_data"})
                continue
            try:
                rsi = rsi_values.get(ticker, 50.0)

                # Recalculate all 10 confluence methods
                confluence = calculate_method_confluence(ticker, price_data)

                # Recalculate confidence with all 9 signals
                new_confidence = calculate_confidence_score(
                    ticker, price_data[ticker], rsi, earnings_soon, weights, "long"
                )
                new_estimate = estimate_overnight_move(
                    price_data[ticker], new_confidence, ticker in earnings_soon
                )

                broke_52w = price_data.get(ticker, {}).get("broke_52w_high_days_ago")

                # Compute signal scores for display
                try:
                    _sig_scores, _fired, _values = compute_signal_scores(
                        ticker, price_data[ticker], rsi, earnings_soon, weights, "long"
                    )
                    _signal_scores_json = json.dumps({"scores": _sig_scores, "fired": _fired, "values": _values})
                except:
                    _signal_scores_json = json.dumps({"scores": {}, "fired": []})

                database.execute("""
                    UPDATE virtual_trades SET
                        confidence=?, dynamic_confidence=?, dynamic_estimate=?,
                        confluence_count=?, confluence_methods=?, signal_scores=?
                    WHERE id=?
                """, [
                    new_confidence, new_confidence, new_estimate,
                    confluence["count"], json.dumps(confluence["methods"]),
                    _signal_scores_json, position["id"]
                ])
                updated += 1
                results.append({
                    "ticker": ticker,
                    "old_confidence": position.get("confidence", 0),
                    "new_confidence": new_confidence,
                    "confluence_count": confluence["count"],
                    "confluence_methods": confluence["methods"],
                    "broke_52w_high_days_ago": broke_52w,
                    "status": "updated",
                })
            except Exception as e:
                results.append({"ticker": ticker, "status": "error", "error": str(e)})

        database.commit()
        database.close()
        log.info(f"Backfill all: updated {updated} positions")
        return jsonify({"success": True, "updated": updated, "results": results})

    except Exception as e:
        log.error(f"Backfill all error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── BACKFILL S&R CONFIDENCE ──────────────────────────────────────────────────
@app.route("/api/backfill-sr-confidence", methods=["POST"])
def api_backfill_sr_confidence():
    """
    One-time endpoint: retroactively apply 5-signal confidence scores to all
    open positions using the full scoring engine including Support & Resistance.

    Positions opened before Push 32 were scored with the 4-signal engine
    (no S&R). This recalculates confidence and dynamic_confidence using the
    current 5-signal engine so cards show accurate scores going forward.

    Safe to call multiple times — only updates confidence fields, never touches
    P&L, current_value, buy_price, outcome, or any other trade data.
    """
    try:
        database = get_database()
        open_positions = [dict(r) for r in database.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]

        if not open_positions:
            database.close()
            return jsonify({"success": True, "updated": 0, "message": "No open positions"})

        tickers = list(set(p["ticker"] for p in open_positions))
        weights = get_signal_weights()

        # Fetch all data needed for 5-signal scoring
        price_data = fetch_price_data(tickers)
        rsi_values = calculate_rsi_batch(tickers)
        earnings_soon = check_upcoming_earnings(tickers)
        enrich_price_data_with_history(tickers, price_data)

        # Pre-compute S&R for all tickers
        for ticker in tickers:
            if ticker in price_data:
                try:
                    price_data[ticker]["expected_move_pct"] = 5.0
                    calculate_support_resistance(ticker, price_data)
                except:
                    pass

        updated = 0
        results = []
        for position in open_positions:
            ticker = position["ticker"]
            if ticker not in price_data:
                results.append({"ticker": ticker, "status": "no_price_data"})
                continue
            try:
                rsi = rsi_values.get(ticker, 50.0)
                new_confidence = calculate_confidence_score(
                    ticker, price_data[ticker], rsi, earnings_soon, weights, "long"
                )
                new_estimate = estimate_overnight_move(
                    price_data[ticker], new_confidence, ticker in earnings_soon
                )
                old_confidence = position.get("confidence", 0)

                database.execute("""
                    UPDATE virtual_trades
                    SET confidence=?, dynamic_confidence=?, dynamic_estimate=?
                    WHERE id=?
                """, [new_confidence, new_confidence, new_estimate, position["id"]])
                updated += 1
                results.append({
                    "ticker": ticker,
                    "old_confidence": old_confidence,
                    "new_confidence": new_confidence,
                    "new_estimate": new_estimate,
                    "status": "updated",
                })
            except Exception as e:
                results.append({"ticker": ticker, "status": "error", "error": str(e)})

        database.commit()
        database.close()
        log.info(f"Backfill S&R confidence: updated {updated} positions")
        return jsonify({"success": True, "updated": updated, "results": results})

    except Exception as e:
        log.error(f"Backfill SR confidence error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── BACKFILL WEIGHTS HISTORY ──────────────────────────────────────────────────
@app.route("/api/backfill-weights-history", methods=["POST"])
def api_backfill_weights_history():
    """Backfill weights_history from audit_log for past audits."""
    try:
        database = get_database()
        audit_rows = [dict(r) for r in database.execute(
            "SELECT * FROM audit_log ORDER BY timestamp ASC"
        ).fetchall()]
        inserted = 0
        for row in audit_rows:
            try:
                weights = json.loads(row.get("weights_after") or "{}")
                if not weights:
                    continue
                existing = database.execute(
                    "SELECT id FROM weights_history WHERE timestamp=?", [row["timestamp"]]
                ).fetchone()
                if not existing:
                    database.execute("""
                        INSERT INTO weights_history (timestamp, rsi_momentum, volume_surge,
                        overnight_gap_probability, earnings_catalyst, support_resistance,
                        relative_strength, sector_relative_strength, vwap_reclaim, volatility_squeeze,
                        win_rate, total_resolved)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, [row["timestamp"],
                          weights.get("rsi_momentum", 0),
                          weights.get("volume_surge", 0),
                          weights.get("overnight_gap_probability", 0),
                          weights.get("earnings_catalyst", 0),
                          weights.get("support_resistance", weights.get("sector_rotation", 0)),
                          weights.get("relative_strength", 0),
                          weights.get("sector_relative_strength", 0),
                          weights.get("vwap_reclaim", 0),
                          weights.get("volatility_squeeze", 0),
                          row.get("win_rate", 0),
                          row.get("resolved_count", 0)])
                    inserted += 1
            except Exception as e:
                log.warning(f"Backfill row error: {e}")
        database.commit()
        database.close()
        return jsonify({"success": True, "inserted": inserted})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# ── RESET WEIGHTS ────────────────────────────────────────────────────────────
@app.route("/api/backfill-lock-in-confidence", methods=["POST"])
def api_backfill_lock_in_confidence():
    """
    Backfill lock_in_confidence for all trades where it is NULL.
    Uses the trade's confidence column as the baseline.
    Safe to call multiple times — only touches NULL rows.
    """
    try:
        database = get_database()
        result = database.execute(
            "UPDATE virtual_trades SET lock_in_confidence = confidence WHERE lock_in_confidence IS NULL AND confidence IS NOT NULL"
        )
        database.commit()
        updated = result.rowcount
        database.close()
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/today-closed")
def api_today_closed():
    """
    Return trades closed today with outcome labels for the closed card UI.
    Called by the frontend to show DONE-able closed position cards.
    """
    try:
        today = current_time_cst().strftime("%Y-%m-%d")
        database = get_database()
        closed = [dict(t) for t in database.execute(
            "SELECT * FROM virtual_trades WHERE sell_date=? AND outcome != 'open' ORDER BY sell_time DESC",
            [today]
        ).fetchall()]
        database.close()

        enriched = []
        for trade in closed:
            sell_reason = trade.get("sell_reason") or ""
            pnl_pct = trade.get("actual_move") or 0
            gross = trade.get("gross_pnl") or 0

            # Build human-readable outcome label
            if sell_reason == "forced_close":
                label = "Force closed 2:45 PM"
                label_type = "force"
            elif sell_reason in ("cut_loss", *LEGACY_STOP_LOSS_REASONS):
                label = "Losses cut"
                label_type = "cut"
            elif pnl_pct >= 0:
                label = "Closed in profit"
                label_type = "profit"
            else:
                label = "Closed at a loss"
                label_type = "loss"

            enriched.append({
                **trade,
                "outcome_label": label,
                "outcome_type": label_type,
                "lock_in_confidence": trade.get("lock_in_confidence") or trade.get("confidence", 0),
            })
        return jsonify(enriched)
    except Exception as e:
        return jsonify([])


@app.route("/api/open-execution-status")
def api_open_execution_status():
    """Return latest open-position execution diagnostics."""
    try:
        return jsonify(get_open_execution_status())
    except Exception as e:
        return jsonify({"last_error": str(e), "missed_open_alert": False}), 500

@app.route("/api/recover-missed-open", methods=["POST"])
def api_recover_missed_open():
    """
    Manually recover a missed 8:45 AM open execution.

    Idempotent: existing ticker/date/direction trade ids are skipped before
    queue amounts are consumed.
    """
    try:
        result = execute_opening_positions(trigger="manual_recovery", buy_time="08:45:00")
        return jsonify({"success": result.get("last_error") is None, **result})
    except Exception as e:
        log.error(f"Manual missed-open recovery failed: {e}")
        return jsonify({"success": False, "last_error": str(e)}), 500


@app.route("/api/force-close-now", methods=["POST"])
def api_force_close_now():
    """
    Manually trigger force-close for all stuck open positions from previous sessions.
    Uses last known current_value — no live price fetch needed.
    Safe to call any time, including weekends.
    """
    try:
        now = current_time_cst()
        today = now.strftime("%Y-%m-%d")
        db = get_database()
        stuck = [dict(t) for t in db.execute(
            "SELECT * FROM virtual_trades WHERE outcome=\'open\' AND buy_date < ?", [today]
        ).fetchall()]
        db.close()
        if not stuck:
            return jsonify({"success": True, "closed": 0, "message": "No stuck positions found"})
        db = get_database()
        results = []
        for position in stuck:
            invested = position["invested_amount"] or DEFAULT_INVESTMENT
            ending_value = position["current_value"] or invested
            gross_value = position.get("gross_current_value") or ending_value
            gross_pnl = float(gross_value or invested) - float(invested or 0)
            net_pnl = float(ending_value or invested) - float(invested or 0)
            pnl_percent = (gross_pnl / invested) * 100 if invested else 0
            outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")
            db.execute("""
                UPDATE virtual_trades SET
                    sell_date=?, sell_time=?, sell_price=?, current_value=?,
                    actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
                WHERE id=?
            """, [position["buy_date"], "14:45:00", position["buy_price"],
                  round(ending_value, 4), round(pnl_percent, 2),
                  round(gross_pnl, 4), round(net_pnl, 4),
                  outcome, "forced_close", position["id"]])
            db.execute("""
                UPDATE predictions SET outcome=?, actual_move=?, resolved_at=?
                WHERE id=?
            """, [outcome, round(pnl_percent, 2), now.isoformat(),
                  "{}_{}_{}" .format(position["ticker"], position["buy_date"], position["direction"])])
            add_to_queue_on_connection(db, ending_value, position["id"])
            results.append({"ticker": position["ticker"], "outcome": outcome, "pnl_percent": round(pnl_percent, 2)})
        db.commit()
        db.close()
        log.info(f"Manual force-close: settled {len(results)} positions")
        return jsonify({"success": True, "closed": len(results), "trades": results})
    except Exception as e:
        log.error(f"Manual force-close failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/all-closed")
def api_all_closed():
    """
    Return all closed trades across all dates — single source of truth from virtual_trades.
    Used by the Analytics Closed Trades subpage.
    """
    try:
        database = get_database()
        closed = [dict(t) for t in database.execute("""
            SELECT ticker, ticker AS name, direction, buy_date, sell_date, buy_price, sell_price,
                   actual_move, gross_pnl, net_pnl, outcome, sell_reason,
                   lock_in_confidence, confidence, expected_move, sector
            FROM virtual_trades
            WHERE outcome != 'open'
            ORDER BY sell_date DESC, sell_time DESC
        """).fetchall()]
        database.close()

        enriched = []
        for t in closed:
            outcome = t.get("outcome") or ""
            sell_reason = t.get("sell_reason") or ""
            pnl_pct = t.get("actual_move") or 0
            gross = t.get("gross_pnl") or 0

            if sell_reason in ("force_close", "forced_close"):
                label = "Force closed"
                label_type = "force"
            elif sell_reason in ("cut_loss", *LEGACY_STOP_LOSS_REASONS):
                label = "Cut"
                label_type = "cut"
            elif outcome == "hit":
                label = "Win"
                label_type = "win"
            elif outcome == "partial":
                label = "Partial"
                label_type = "partial"
            else:
                label = "Loss"
                label_type = "loss"

            enriched.append({
                **t,
                "outcome_label": label,
                "outcome_type": label_type,
                "lock_in_confidence": t.get("lock_in_confidence") or t.get("confidence") or 0,
            })

        return jsonify(enriched)
    except Exception as e:
        log.error(f"all-closed error: {e}")
        return jsonify([])

@app.route("/api/nn-train-now", methods=["POST"])
def api_nn_train_now():
    """Manually trigger NN training. Returns training result."""
    try:
        train_neural_network()
        # Force save weights with a fresh connection after training
        try:
            weights = {k: v.tolist() for k, v in _nn_model.state_dict().items()}
            db = get_database()
            db.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                [NN_MODEL_KEY, json.dumps(weights)])
            db.commit()
            db.close()
            saved = True
        except Exception as se:
            saved = False
            log.error(f"Weight save failed: {se}")
        return jsonify({"success": True, "weights_saved": saved})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/nn-scan-now", methods=["POST"])
def api_nn_scan_now():
    """Compatibility endpoint: queue a shared comprehensive scan with Nova scoring."""
    try:
        status = start_nn_scan_background(scan_type="manual_shared_nova")
        response = {
            "success": True,
            "started": bool(status.get("started", status.get("status") == "running")) and not bool(status.get("already_running")),
            "already_running": bool(status.get("already_running")),
            "shared_scan": True,
            "background": True,
            "scan_type": status.get("scan_type", "manual_shared_nova"),
            "status_endpoint": "/api/nn-scan-status",
            "history_endpoint": "/api/scan-history",
            "message": "Shared comprehensive scan queued; Nova will update from the same snapshot.",
            "status": status,
        }
        http_status = 202 if status.get("status") == "running" else 200
        return jsonify(response), http_status
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/shared-scan-now", methods=["POST"])
def api_shared_scan_now():
    """Queue a manual shared comprehensive scan; Vector and Nova score the same snapshot."""
    try:
        status = start_shared_scan_background(scan_type="manual_shared")
        response = {
            "success": True,
            "started": bool(status.get("started", status.get("status") == "running")) and not bool(status.get("already_running")),
            "already_running": bool(status.get("already_running")),
            "shared_scan": True,
            "background": True,
            "scan_type": status.get("scan_type", "manual_shared"),
            "status_endpoint": "/api/nn-scan-status",
            "history_endpoint": "/api/scan-history",
            "message": "Shared comprehensive scan queued; Vector and Nova will update from the same snapshot.",
            "status": status,
        }
        http_status = 202 if status.get("status") == "running" else 200
        return jsonify(response), http_status
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/nn-scan-status")
def api_nn_scan_status():
    """Return latest background NN scan status."""
    try:
        return jsonify(get_nn_scan_status_payload())
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/nn-open-now", methods=["POST"])
def api_nn_open_now():
    """Manual recovery/testing endpoint for NN open execution."""
    try:
        result = execute_nn_opening_positions(trigger="manual_recovery", buy_time="08:45:00")
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/nn-open-execution-status")
def api_nn_open_execution_status():
    """Return the latest NN open execution diagnostic payload."""
    try:
        return jsonify(get_app_state_json("last_nn_open_execution", {}) or {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/nn-force-close-now", methods=["POST"])
def api_nn_force_close_now():
    """Manual endpoint to force-close previous-session NN positions."""
    try:
        force_close_nn_previous_session()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/repair-accidental-startup-close", methods=["POST"])
def api_repair_accidental_startup_close():
    """
    Reopen positions that startup backfill incorrectly settled before the
    valid 2:45 PM CST force-close window.

    Targets the bad signature from the bug only:
    - row still has status='open'
    - outcome was changed away from open
    - sell_reason is forced_close
    - sell_date was set to buy_date by startup backfill
    """
    try:
        body = request.get_json(silent=True) or {}
        repair_date = body.get("buy_date")
        if not repair_date:
            last_execution = get_app_state_json("last_open_execution", {}) or {}
            opened = last_execution.get("opened") or []
            if opened:
                first_trade_id = opened[0].get("trade_id", "")
                parts = first_trade_id.split("_")
                if len(parts) >= 3:
                    repair_date = parts[1]
        if not repair_date:
            return jsonify({"success": False, "error": "buy_date required"}), 400

        db = get_database()
        suspect_rows = [dict(row) for row in db.execute("""
            SELECT id, ticker, outcome, gross_pnl
            FROM virtual_trades
            WHERE buy_date=?
              AND status='open'
              AND outcome!='open'
              AND sell_reason='forced_close'
              AND sell_date=buy_date
        """, [repair_date]).fetchall()]

        if not suspect_rows:
            db.close()
            return jsonify({"success": True, "restored": 0, "buy_date": repair_date, "removed_queue_entries": 0, "trades": []})

        trade_ids = [row["id"] for row in suspect_rows]
        placeholders = ",".join("?" for _ in trade_ids)
        removed_queue_entries = db.execute(
            f"DELETE FROM trade_queue WHERE consumed=0 AND source_trade_id IN ({placeholders})",
            trade_ids
        ).rowcount

        db.execute(f"""
            UPDATE virtual_trades
            SET outcome='open',
                status='open',
                sell_date=NULL,
                sell_time=NULL,
                sell_price=NULL,
                actual_move=NULL,
                gross_pnl=NULL,
                net_pnl=NULL,
                sell_reason=NULL
            WHERE id IN ({placeholders})
        """, trade_ids)

        for trade in suspect_rows:
            parts = trade["id"].split("_")
            if len(parts) >= 4:
                prediction_id = f"{parts[0]}_{parts[1]}_{parts[2]}"
                db.execute(
                    "UPDATE predictions SET outcome='pending', actual_move=NULL, resolved_at=NULL WHERE id=?",
                    [prediction_id]
                )

        db.commit()
        db.close()
        return jsonify({
            "success": True,
            "buy_date": repair_date,
            "restored": len(suspect_rows),
            "removed_queue_entries": removed_queue_entries,
            "trades": suspect_rows,
        })
    except Exception as e:
        log.error(f"repair accidental startup close failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/suspect-startup-closed")
def api_suspect_startup_closed():
    """Return positions matching the accidental-startup-close signature."""
    try:
        db = get_database()
        rows = [dict(row) for row in db.execute("""
            SELECT id, ticker, buy_date, outcome, status, sell_date, sell_time,
                   sell_reason, current_value, invested_amount
            FROM virtual_trades
            WHERE status='open'
              AND outcome!='open'
              AND sell_reason='forced_close'
              AND sell_date=buy_date
            ORDER BY buy_date DESC, ticker ASC
        """).fetchall()]
        db.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/repair-consumed-accidental-queue", methods=["POST"])
def api_repair_consumed_accidental_queue():
    """
    Normalize trades that consumed queue entries created by the accidental
    startup close before those source positions were restored.
    """
    try:
        body = request.get_json(silent=True) or {}
        source_buy_date = body.get("source_buy_date")
        consumer_buy_date = body.get("consumer_buy_date") or current_time_cst().strftime("%Y-%m-%d")
        if not source_buy_date:
            return jsonify({"success": False, "error": "source_buy_date required"}), 400

        db = get_database()
        bad_rows = [dict(row) for row in db.execute("""
            SELECT tq.id AS queue_id,
                   tq.amount AS queue_amount,
                   tq.source_trade_id,
                   tq.consumed_by_trade_id,
                   vt.ticker,
                   vt.invested_amount,
                   vt.current_value
            FROM trade_queue tq
            JOIN virtual_trades vt ON vt.id = tq.consumed_by_trade_id
            WHERE tq.consumed=1
              AND tq.source_trade_id IN (
                  SELECT id FROM virtual_trades
                  WHERE buy_date=?
                    AND outcome='open'
                    AND sell_date IS NULL
                    AND sell_reason IS NULL
              )
              AND vt.buy_date=?
              AND vt.outcome='open'
        """, [source_buy_date, consumer_buy_date]).fetchall()]

        fallback_amount = round(get_dynamic_fallback_amount(), 4)
        repaired = []
        for row in bad_rows:
            old_invested = float(row["invested_amount"] or DEFAULT_INVESTMENT)
            old_current = float(row["current_value"] or old_invested)
            value_ratio = old_current / old_invested if old_invested else 1.0
            new_current = round(fallback_amount * value_ratio, 4)
            db.execute("""
                UPDATE virtual_trades
                SET invested_amount=?, current_value=?, queue_position=NULL
                WHERE id=?
            """, [fallback_amount, new_current, row["consumed_by_trade_id"]])
            repaired.append({
                **row,
                "new_invested_amount": fallback_amount,
                "new_current_value": new_current,
            })

        if bad_rows:
            placeholders = ",".join("?" for _ in bad_rows)
            db.execute(
                f"DELETE FROM trade_queue WHERE id IN ({placeholders})",
                [row["queue_id"] for row in bad_rows]
            )
        db.commit()
        db.close()
        return jsonify({
            "success": True,
            "source_buy_date": source_buy_date,
            "consumer_buy_date": consumer_buy_date,
            "repaired": len(repaired),
            "fallback_amount": fallback_amount,
            "trades": repaired,
        })
    except Exception as e:
        log.error(f"repair consumed accidental queue failed: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/nn-debug")
def api_nn_debug():
    """Diagnose NN state — torch install, weights, training readiness."""
    try:
        import torch as _torch
        torch_version = _torch.__version__
        torch_ok = True
    except ImportError as e:
        torch_version = None
        torch_ok = False
        torch_err = str(e)

    try:
        db = get_database()
        weights_row = db.execute("SELECT value FROM app_state WHERE key=?", [NN_MODEL_KEY]).fetchone()
        has_weights = weights_row is not None
        closed_count = db.execute("SELECT COUNT(*) as n FROM virtual_trades WHERE outcome != 'open'").fetchone()["n"]
        db.close()
    except Exception as e:
        has_weights = False
        closed_count = 0

    # Test a dummy inference
    inference_ok = False
    inference_score = None
    try:
        dummy = {
            "signal_scores": '{"scores":{"rsi_momentum":0.8,"volume_surge":0.6,"overnight_gap":0.5,"earnings_catalyst":0.5,"support_resistance":0.5,"relative_strength":0.5,"sector_rs":0.5,"vwap_reclaim":0.5,"volatility_squeeze":0.5},"fired":["rsi_momentum"],"values":{"rsi_momentum":55,"volume_surge":1.5,"overnight_gap":5,"earnings_catalyst":null,"support_resistance":{"signal":"open_air","resistance":null,"support":null},"relative_strength":{"stock_5d":2.0,"spy_5d":1.0},"sector_rs":{"etf":"XLK","etf_5d":1.5,"spy_5d":1.0},"vwap_reclaim":{"mode":"proxy","dist":1.0},"volatility_squeeze":0.8}}',
            "direction": "long", "sector": "Tech", "lock_in_confidence": 70,
            "expected_move": 8.0, "day_change_percent": 5.0,
            "broke_52w_high_days_ago": None, "weekend_hold": 0,
            "news_sentiment_score": 0.1, "news_article_count": 2,
        }
        score = nn_score_ticker(dummy, "long")
        inference_ok = score > 0
        inference_score = score
    except Exception as e:
        inference_ok = False

    return jsonify({
        "torch_installed": torch_ok,
        "torch_version": torch_version,
        "has_saved_weights": has_weights,
        "closed_trades_for_training": closed_count,
        "min_trades_needed": 10,
        "ready_to_train": closed_count >= 10,
        "inference_test_score": inference_score,
        "inference_working": inference_ok,
    })

@app.route("/api/nn-picks")
def api_nn_picks():
    """Return cached NN scan picks."""
    try:
        db = get_database()
        row = db.execute("SELECT value FROM app_state WHERE key='cached_nn_picks'").fetchone()
        cache_time = db.execute("SELECT value FROM app_state WHERE key='cached_nn_picks_time'").fetchone()
        db.close()
        if row:
            result = json.loads(row["value"])
            result["cache_time"] = cache_time["value"] if cache_time else result.get("scan_time")
            result["status"] = "ok"
            if not result.get("recommended_longs"):
                result["message"] = result.get("message") or "No NN picks qualified above threshold"
            return jsonify(result)
        return jsonify({
            "recommended_longs": [],
            "recommended_shorts": [],
            "total_scanned": 0,
            "qualified_count": 0,
            "status": "no_cache",
            "message": "No shared NN scan has been cached yet",
        })
    except Exception as e:
        return jsonify({
            "recommended_longs": [],
            "recommended_shorts": [],
            "total_scanned": 0,
            "qualified_count": 0,
            "status": "error",
            "message": str(e),
        })

@app.route("/api/nn-positions")
def api_nn_positions():
    """Return open positions in the NN portfolio."""
    try:
        db = get_database()
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM nn_virtual_trades WHERE outcome='open' ORDER BY buy_date DESC"
        ).fetchall()]
        db.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify([])

@app.route("/api/nn-stats")
def api_nn_stats():
    """Return NN portfolio performance stats — source of truth from nn_virtual_trades."""
    try:
        db = get_database()
        closed = [dict(r) for r in db.execute(
            "SELECT outcome, actual_move, gross_pnl, net_pnl FROM nn_virtual_trades WHERE outcome != 'open'"
        ).fetchall()]
        open_count = db.execute(
            "SELECT COUNT(*) as n FROM nn_virtual_trades WHERE outcome='open'"
        ).fetchone()["n"]
        db.close()
        resolved = len(closed)
        hits = sum(1 for t in closed if t["outcome"] == "hit")
        misses = sum(1 for t in closed if t["outcome"] == "miss")
        partials = sum(1 for t in closed if t["outcome"] == "partial")
        total_gross_pnl = sum(float(t["gross_pnl"] or 0) for t in closed)
        total_net_pnl = sum(float(t["net_pnl"] if t["net_pnl"] is not None else t["gross_pnl"] or 0) for t in closed)
        return jsonify({
            "resolved": resolved,
            "hits": hits,
            "misses": misses,
            "partials": partials,
            "win_rate": round(hits / resolved * 100, 1) if resolved else None,
            "total_gross_pnl": round(total_gross_pnl, 2),
            "total_net_pnl": round(total_net_pnl, 2),
            "fee_model_version": STOCK_FEE_MODEL_VERSION,
            "open_positions": open_count,
            "portfolio_value": round(get_nn_portfolio_value(), 2),
            "next_investment_amount": round(get_nn_investment_amount(), 2),
        })
    except Exception as e:
        return jsonify({"resolved": 0, "hits": 0, "misses": 0, "win_rate": None})

@app.route("/api/nn-perf-history")
def api_nn_performance_history():
    """Return Neural portfolio equity curve from its independent trade ledger."""
    try:
        database = get_database()
        daily_results = database.execute("""
            SELECT sell_date AS date,
                   SUM(COALESCE(net_pnl, gross_pnl, 0)) AS daily_pnl,
                   COUNT(*) AS trade_count
            FROM nn_virtual_trades
            WHERE outcome != 'open' AND sell_date IS NOT NULL
            GROUP BY sell_date
            ORDER BY sell_date ASC
        """).fetchall()
        first_trade_row = database.execute("""
            SELECT MIN(first_date) AS first_date FROM (
                SELECT MIN(buy_date) AS first_date FROM nn_virtual_trades WHERE buy_date IS NOT NULL
                UNION ALL
                SELECT MIN(sell_date) AS first_date FROM nn_virtual_trades WHERE sell_date IS NOT NULL
            )
        """).fetchone()
        open_rows = database.execute(
            "SELECT invested_amount, current_value FROM nn_virtual_trades WHERE outcome='open'"
        ).fetchall()
        database.close()

        first_trade_date = first_trade_row["first_date"] if first_trade_row else None
        if first_trade_date:
            seed_day = datetime.fromisoformat(first_trade_date)
        else:
            seed_day = current_time_cst()
        seed_ts = int(seed_day.replace(hour=9, minute=0, second=0).timestamp() * 1000)
        running_balance = STARTING_PORTFOLIO_VALUE
        history = [{
            "date": seed_day.strftime("%Y-%m-%d"),
            "virtual": round(STARTING_PORTFOLIO_VALUE, 2),
            "daily_pnl": 0,
            "trades": 0,
            "ts": seed_ts,
            "seed": True,
        }]

        for row in daily_results:
            running_balance += float(row["daily_pnl"] or 0)
            history.append({
                "date": row["date"],
                "virtual": round(running_balance, 2),
                "daily_pnl": round(float(row["daily_pnl"] or 0), 4),
                "trades": row["trade_count"],
                "ts": int(datetime.fromisoformat(row["date"]).replace(hour=16, minute=0, second=0).timestamp() * 1000),
            })

        live_pnl = sum(
            float(row["current_value"] or row["invested_amount"] or DEFAULT_INVESTMENT)
            - float(row["invested_amount"] or DEFAULT_INVESTMENT)
            for row in open_rows
        )
        if open_rows:
            now_cst = current_time_cst()
            history.append({
                "date": now_cst.strftime("%Y-%m-%d"),
                "virtual": round(running_balance + live_pnl, 2),
                "daily_pnl": round(live_pnl, 4),
                "trades": 0,
                "ts": int(now_cst.timestamp() * 1000),
                "intraday": True,
                "live": True,
            })
        history.sort(key=lambda point: point["ts"])
        return jsonify(history)
    except Exception as e:
        log.warning(f"nn perf history failed: {e}")
        return jsonify([])

@app.route("/api/nn-all-closed")
def api_nn_all_closed():
    """Return all closed NN trades for the Neural Analytics subpage."""
    try:
        db = get_database()
        closed = [dict(r) for r in db.execute(
            "SELECT * FROM nn_virtual_trades WHERE outcome != 'open' ORDER BY sell_date DESC, sell_time DESC"
        ).fetchall()]
        db.close()
        return jsonify(closed)
    except:
        return jsonify([])

@app.route("/api/personal-trades")
def api_personal_trades():
    """Return all personal portfolio positions."""
    try:
        db = get_database()
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM personal_trades ORDER BY added_at DESC"
        ).fetchall()]
        db.close()
        return jsonify(rows)
    except Exception as e:
        return jsonify([])

@app.route("/api/personal-trades/add", methods=["POST"])
def api_personal_trades_add():
    """
    Add a position to the personal portfolio.
    Called when user taps 'Add to personal' on a Brain or Neural card.
    Body: {ticker, direction, buy_price, invested_amount, sector, source_portfolio, notes}
    """
    try:
        body = request.get_json() or {}
        ticker = body.get("ticker", "").upper().strip()
        if not ticker:
            return jsonify({"error": "ticker required"}), 400
        now = current_time_cst()
        trade_id = f"personal_{ticker}_{now.strftime('%Y%m%d%H%M%S')}"
        buy_price = float(body.get("buy_price", 0))
        invested = float(body.get("invested_amount", 10))
        sector = body.get("sector") or get_sector(ticker)
        db = get_database()
        db.execute("""
            INSERT OR REPLACE INTO personal_trades
            (id, ticker, direction, buy_date, buy_price, invested_amount,
             current_value, sector, notes, source, source_portfolio, added_at, last_updated)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [
            trade_id, ticker,
            body.get("direction", "long"),
            now.strftime("%Y-%m-%d"),
            buy_price, invested, invested,
            sector,
            body.get("notes", ""),
            "manual",
            body.get("source_portfolio", "brain"),
            now.isoformat(), now.isoformat()
        ])
        db.commit()
        db.close()
        log.info(f"Personal trade added: {ticker} from {body.get('source_portfolio', 'brain')}")
        return jsonify({"success": True, "id": trade_id})
    except Exception as e:
        log.error(f"personal-trades/add error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/personal-trades/remove", methods=["POST"])
def api_personal_trades_remove():
    """Remove a position from the personal portfolio."""
    try:
        body = request.get_json() or {}
        trade_id = body.get("id")
        if not trade_id:
            return jsonify({"error": "id required"}), 400
        db = get_database()
        db.execute("DELETE FROM personal_trades WHERE id=?", [trade_id])
        db.commit()
        db.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/reset-weights", methods=["POST"])
def api_reset_weights():
    """
    Write the current 9-signal default weights to the DB.
    Use when new indicators have been added and the stored weights
    JSON is missing the new keys, causing them to show 0% in Analytics.
    Safe to call at any time — does not affect audit history.
    """
    try:
        default_weights = canonical_signal_weights()
        save_signal_weights(default_weights)
        log.info(f"Weights reset to 9-signal defaults: {default_weights}")
        return jsonify({"success": True, "weights": default_weights})
    except Exception as e:
        log.error(f"Reset weights error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── NOTIFICATION SETTINGS ────────────────────────────────────────────────────
@app.route("/api/notification-settings", methods=["GET"])
def api_get_notification_settings():
    try:
        database = get_database()
        setting = database.execute("SELECT value FROM app_state WHERE key='notify_on_close'").fetchone()
        database.close()
        enabled = setting["value"] != "false" if setting else True
        provider = os.environ.get("NOTIFY_PROVIDER", "twilio").lower()
        telegram_configured = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
        twilio_configured = bool(os.environ.get("TWILIO_ACCOUNT_SID") and os.environ.get("TWILIO_AUTH_TOKEN"))
        return jsonify({
            "notify_on_close": enabled,
            "provider": provider,
            "telegram_configured": telegram_configured,
            "twilio_configured": twilio_configured,
        })
    except Exception as e:
        return jsonify({"notify_on_close": True, "error": str(e)})

@app.route("/api/notification-settings", methods=["POST"])
def api_set_notification_settings():
    try:
        data = request.get_json()
        notify = data.get("notify_on_close", True)
        database = get_database()
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('notify_on_close',?)",
                        ["true" if notify else "false"])
        database.commit()
        database.close()
        return jsonify({"success": True, "notify_on_close": notify})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/test-notification", methods=["POST"])
def api_test_notification():
    try:
        provider = os.environ.get("NOTIFY_PROVIDER", "twilio").lower()
        test_msg = "SwingDesk: Test notification working. You'll be notified on cut, force close, and overnight reversal."

        if provider == "telegram":
            success = send_telegram_notification(test_msg)
            if success:
                return jsonify({"success": True, "provider": "telegram"})
            return jsonify({"success": False, "error": "Telegram send failed — check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Railway"}), 400

        from twilio.rest import Client
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        to_number   = os.environ.get("TWILIO_TO_NUMBER")
        if not all([account_sid, auth_token, from_number, to_number]):
            return jsonify({"success": False, "error": "Twilio env vars not configured in Railway"}), 400
        client = Client(account_sid, auth_token)
        message = client.messages.create(body=test_msg, from_=from_number, to=to_number)
        log.info(f"Test notification sent: {message.sid}")
        return jsonify({"success": True, "provider": "twilio", "sid": message.sid})
    except Exception as e:
        log.error(f"Test notification error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

# ── KEEP ALIVE ────────────────────────────────────────────────────────────────
def keep_server_alive():
    """Ping self every 10 minutes to prevent Railway from sleeping the container."""
    import urllib.request
    while True:
        try:
            port = os.environ.get("PORT", 5000)
            urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=5)
        except:
            pass
        time.sleep(600)

# ── INITIALIZATION ────────────────────────────────────────────────────────────
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
initialize_database()
load_nn_weights()  # Load persisted NN weights on startup

# ── STARTUP BACKFILL — close any positions stuck open from missed scheduler jobs ──
def backfill_missed_closes():
    """
    On every startup, check for positions that should have been force-closed
    but weren't (Railway restarts, missed scheduler windows, holidays).
    Uses last known current_value as the closing price — best available data.
    All writes use a single DB connection to avoid locking conflicts.
    """
    try:
        now = current_time_cst()
        if now.weekday() >= 5 or (now.hour < 14 or (now.hour == 14 and now.minute < 45)):
            log.info("Startup backfill: skipping before the 2:45 PM CST force-close window")
            return
        today = now.strftime("%Y-%m-%d")
        db = get_database()
        stuck = [dict(t) for t in db.execute(
            "SELECT * FROM virtual_trades WHERE outcome='open' AND buy_date < ?", [today]
        ).fetchall()]
        if not stuck:
            db.close()
            log.info("Startup backfill: no stuck positions found")
            return
        log.info(f"Startup backfill: closing {len(stuck)} stuck positions from previous sessions")
        closed_count = 0
        for position in stuck:
            invested = position["invested_amount"] or DEFAULT_INVESTMENT
            ending_value = position["current_value"] or invested
            gross_value = position.get("gross_current_value") or ending_value
            gross_pnl = float(gross_value or invested) - float(invested or 0)
            net_pnl = float(ending_value or invested) - float(invested or 0)
            pnl_percent = (gross_pnl / invested) * 100 if invested else 0
            outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")
            db.execute("""
                UPDATE virtual_trades SET
                    sell_date=?, sell_time=?, sell_price=?, current_value=?,
                    actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
                WHERE id=?
            """, [position["buy_date"], "14:45:00", position["buy_price"],
                  round(ending_value, 4), round(pnl_percent, 2),
                  round(gross_pnl, 4), round(net_pnl, 4),
                  outcome, "forced_close", position["id"]])
            db.execute("""
                UPDATE predictions SET outcome=?, actual_move=?, resolved_at=?
                WHERE id=?
            """, [outcome, round(pnl_percent, 2), now.isoformat(),
                  "{}_{}_{}" .format(position["ticker"], position["buy_date"], position["direction"])])
            # Inline queue insert — same connection, no locking conflict
            db.execute("""
                INSERT INTO trade_queue (amount, source_trade_id, created_at, consumed)
                VALUES (?, ?, ?, 0)
            """, [round(ending_value, 4), position["id"], now.isoformat()])
            closed_count += 1
        db.commit()
        db.close()
        log.info(f"Startup backfill: settled {closed_count} positions")
    except Exception as e:
        log.error(f"Startup backfill failed: {e}")

def backfill_nn_missed_closes():
    """Settle NN positions left open from previous sessions after restarts."""
    try:
        now = current_time_cst()
        if now.weekday() >= 5 or (now.hour < 14 or (now.hour == 14 and now.minute < 45)):
            log.info("NN startup backfill: skipping before the 2:45 PM CST force-close window")
            return
        today = now.strftime("%Y-%m-%d")
        db = get_database()
        stuck = [dict(t) for t in db.execute(
            "SELECT * FROM nn_virtual_trades WHERE outcome='open' AND buy_date < ?", [today]
        ).fetchall()]
        if not stuck:
            db.close()
            log.info("NN startup backfill: no stuck positions found")
            return
        log.info(f"NN startup backfill: closing {len(stuck)} stuck positions from previous sessions")
        closed_count = 0
        for position in stuck:
            invested = position["invested_amount"] or DEFAULT_INVESTMENT
            ending_value = position["current_value"] or invested
            gross_value = position.get("gross_current_value") or ending_value
            gross_pnl = float(gross_value or invested) - float(invested or 0)
            net_pnl = float(ending_value or invested) - float(invested or 0)
            pnl_percent = (gross_pnl / invested) * 100 if invested else 0
            outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")
            db.execute("""
                UPDATE nn_virtual_trades SET
                    sell_date=?, sell_time=?, sell_price=?, current_value=?,
                    actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
                WHERE id=?
            """, [position["buy_date"], "14:45:00", position["buy_price"],
                  round(ending_value, 4), round(pnl_percent, 2),
                  round(gross_pnl, 4), round(net_pnl, 4),
                  outcome, "forced_close", position["id"]])
            closed_count += 1
        db.commit()
        db.close()
        log.info(f"NN startup backfill: settled {closed_count} positions")
    except Exception as e:
        log.error(f"NN startup backfill failed: {e}")

if os.environ.get("SWINGDESK_DISABLE_STARTUP_TASKS") != "1":
    try:
        prune_scan_history(SCAN_EVENT_RETENTION_DAYS)
    except Exception as e:
        log.error(f"Startup scan history retention failed: {e}")
    backfill_missed_closes()
    backfill_nn_missed_closes()
    threading.Thread(target=run_scheduler, daemon=True).start()
    threading.Thread(target=keep_server_alive, daemon=True).start()

# ── GRACEFUL SHUTDOWN ─────────────────────────────────────────────────────────
# Railway sends SIGTERM on every deploy. Scheduler threads are daemon threads
# and die immediately. If a force-close is in progress or overdue, this handler
# ensures positions don't stay open overnight due to deploy timing.
import signal, atexit
_shutdown_requested = False
def _graceful_shutdown(signum=None, frame=None):
    global _shutdown_requested
    if _shutdown_requested:
        return
    _shutdown_requested = True
    now = current_time_cst()
    log.info(f"Shutdown signal received at {now.strftime('%H:%M:%S')} CST")
    # If it's past 2:45 PM on a weekday and positions might still be open, run force-close
    if now.weekday() < 5 and (now.hour > 14 or (now.hour == 14 and now.minute >= 45)):
        try:
            log.info("Emergency force-close check on shutdown...")
            force_close_previous_session()
            force_close_nn_previous_session()
        except Exception as e:
            log.error(f"Emergency force-close failed: {e}")
try:
    signal.signal(signal.SIGTERM, _graceful_shutdown)
    atexit.register(_graceful_shutdown)
except Exception:
    pass  # signal handling may not work in all environments
log.info("Brain v4 initialized — full trading engine with self-regulating queue system + SwingDeskNet NN")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
