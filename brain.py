"""
brain.py — Overnight Swing Desk Backend v19b (Push 47b)
════════════════════════════════════════════════════════
Trading Engine with Self-Regulating Queue System

Changes in Push 47b:
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
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import torch
import torch.nn as nn
import torch.optim as optim

load_dotenv()

# ── CONFIGURATION ─────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_KEY") or os.getenv("ANTHROPIC_API_KEY")
ALPHA_VANTAGE_KEY    = os.getenv("ALPHA_VANTAGE_KEY")
DATABASE_PATH        = Path(os.environ.get("DATABASE_PATH", "/app/data/portfolio_brain.db"))
FEE_PER_TRADE        = 0.02      # Cash App sell fee
DEFAULT_INVESTMENT   = 10.00     # Fallback when queue is empty
CONFIDENCE_FLOOR     = 65        # Minimum confidence to recommend/trade
MIN_EXPECTED_MOVE    = 5.0       # Minimum predicted overnight move (%)
MAX_LONG_PICKS       = 20        # Maximum long recommendations per scan
MAX_SHORT_PICKS      = 10        # Maximum short recommendations per scan
TIMEZONE_OFFSET      = -5        # CST = UTC-5 (CDT during summer)
MONITOR_INTERVAL     = 300       # 5 minutes in seconds
SCAN_BATCH_SIZE      = 100       # Tickers per yfinance batch call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

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

        # [0-8] Signal scores
        f = [
            float(scores.get("rsi_momentum", 0.5)),
            float(scores.get("volume_surge", 0.5)),
            float(scores.get("overnight_gap", 0.5)),
            float(scores.get("earnings_catalyst", 0.5)),
            float(scores.get("support_resistance", 0.5)),
            float(scores.get("relative_strength", 0.5)),
            float(scores.get("sector_rs", 0.5)),
            float(scores.get("vwap_reclaim", 0.5)),
            float(scores.get("volatility_squeeze", 0.5)),
        ]

        # [9] RSI raw
        f.append(min(float(values.get("rsi_momentum", 50)) / 100.0, 1.0))

        # [10] volume_ratio
        f.append(min(float(values.get("volume_surge", 1.0)) / 5.0, 1.0))

        # [11] gap_percent
        gap = float(values.get("overnight_gap", 0))
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
        sector_val = values.get("sector_rs", {})
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
    """Returns current time adjusted to Central Standard Time."""
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)

def is_weekday():
    """Returns True if today is a weekday (Mon-Fri)."""
    return current_time_cst().weekday() < 5

def is_market_open():
    """Returns True during regular market hours (8:30 AM - 3:00 PM CST)."""
    now = current_time_cst()
    return now.weekday() < 5 and 8 <= now.hour < 15

def minutes_until_forced_close():
    """Returns minutes remaining until the 2:45 PM CST forced close."""
    now = current_time_cst()
    close_time = now.replace(hour=14, minute=45, second=0)
    return int((close_time - now).total_seconds() / 60)

# ── TICKER UNIVERSE ───────────────────────────────────────────────────────────
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
    "LLY":"Healthcare","UNH":"Healthcare","JNJ":"Healthcare","PFE":"Healthcare",
    "ABBV":"Healthcare","MRK":"Healthcare","V":"Finance","MA":"Finance",
    "GS":"Finance","BLK":"Finance","WFC":"Finance","PG":"Consumer",
    "KO":"Consumer","PEP":"Consumer","WMT":"Consumer","COST":"Consumer",
    "HD":"Consumer","LOW":"Consumer","BA":"Industrial","CAT":"Industrial",
    "GE":"Industrial","HON":"Industrial","RTX":"Defense","NOC":"Defense",
}

def get_sector(ticker):
    """Return the sector classification for a ticker, defaulting to 'Other'."""
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
    today = current_time_cst().strftime("%Y-%m-%d")

    if cached_universe and cached_date and cached_date["value"] == today:
        database.close()
        tickers = json.loads(cached_universe["value"])
        log.info(f"Using cached universe: {len(tickers)} tickers")
        return tickers

    sp500 = fetch_sp500_tickers()
    nasdaq100 = fetch_nasdaq100_tickers()
    combined = list(dict.fromkeys(sp500 + nasdaq100 + HIGH_VOLATILITY_TICKERS))

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
            fee REAL DEFAULT 0.02,
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
            fee REAL DEFAULT 0.02,
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
    ]:
        try:
            column_name = column_definition.split()[0]
            database.execute(f"ALTER TABLE virtual_trades ADD COLUMN {column_definition}")
        except:
            pass  # Column already exists

    # Seed default signal weights if not already set
    existing_weights = database.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
    if not existing_weights:
        default_weights = {
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
    database.close()
    return {
        "available_count": available["count"],
        "available_total": round(available["total"], 2),
        "total_ever_queued": total_ever["count"],
        "default_fallback": get_dynamic_fallback_amount(),
        "recent_entries": recent,
    }

# ── PRICE DATA ────────────────────────────────────────────────────────────────
TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_KEY")
TWELVE_DATA_BASE = "https://api.twelvedata.com"
FINNHUB_KEY = os.getenv("FINNHUB_KEY")
FINNHUB_BASE = "https://finnhub.io/api/v1"

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
        history = []
        for i in range(len(closes)):
            history.append({
                "close": float(closes[i]),
                "open": float(opens[i]) if i < len(opens) else float(closes[i]),
                "high": float(highs[i]) if i < len(highs) else float(closes[i]),
                "low": float(lows[i]) if i < len(lows) else float(closes[i]),
                "volume": float(volumes[i]) if i < len(volumes) else 0,
            })
        return history
    except Exception as e:
        log.debug(f"Finnhub candles error {ticker}: {e}")
        return []

def fetch_twelve_data_batch(tickers, interval="1day", outputsize=60):
    """
    Fetch OHLCV + history for multiple tickers.
    Uses Finnhub candles endpoint — one call per ticker with rate limiting.
    Returns {ticker: {price, open, previous_close, high, low, volume, 
                       average_volume, volume_ratio, gap_percent, 
                       day_change_percent, daily_history}}
    """
    results = {}
    RATE_LIMIT_DELAY = 1.1  # 60 calls/min = 1 call/sec + small buffer

    for ticker in tickers:
        # First get current quote
        quote = fetch_finnhub_quote(ticker)
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

    log.info(f"Finnhub returned {len(results)}/{len(tickers)} tickers")
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
        quote = fetch_finnhub_quote(ticker)
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

    log.info(f"Finnhub live: {len(results)}/{len(tickers)} tickers")
    return results


def fetch_price_data(tickers):
    """
    Fetch daily OHLCV price data for scanning and scoring.
    
    Cache-first strategy:
    - Loads all tickers from app_state cache first
    - Fetches fresh Finnhub quotes only for tickers not in cache or cache >24h old
    - Full candle history fetched only for top candidates (those with gap/volume signal)
    - Cache is refreshed incrementally — 60 tickers per scan cycle max
    
    This keeps Finnhub calls well within 60/min free tier across scan cycles.
    """
    if not tickers:
        return {}

    log.info(f"Fetching price data for {len(tickers)} tickers...")

    # Load all cached prices first
    results = {}
    now_ts = int(__import__("time").time())
    stale_cutoff = now_ts - 86400  # 24 hours

    try:
        database = get_database()
        for ticker in tickers:
            cached = database.execute(
                "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
            ).fetchone()
            if cached:
                try:
                    data = json.loads(cached["value"])
                    results[ticker] = data
                except:
                    pass
        database.close()
    except Exception as e:
        log.debug(f"Cache load error: {e}")

    log.info(f"Cache hit: {len(results)}/{len(tickers)} tickers")

    # Fetch fresh quotes for missing or stale tickers — max 60 per cycle
    missing = [t for t in tickers if t not in results]
    to_refresh = missing[:60]  # Refresh up to 60 per scan cycle

    if to_refresh:
        log.info(f"Refreshing {len(to_refresh)} tickers from Finnhub...")
        RATE_DELAY = 1.1
        for ticker in to_refresh:
            quote = fetch_finnhub_quote(ticker)
            if quote:
                results[ticker] = quote
                # Fetch candle history for fresh tickers
                history = fetch_finnhub_candles(ticker, days=60)
                if history:
                    results[ticker]["daily_history"] = history
                    vols = [h["volume"] for h in history if h["volume"] > 0]
                    if vols:
                        avg_vol = sum(vols) / len(vols)
                        results[ticker]["average_volume"] = avg_vol
                        results[ticker]["volume_ratio"] = quote.get("volume", 0) / max(avg_vol, 1)
                # Cache it
                try:
                    database = get_database()
                    cache_data = {k: v for k, v in results[ticker].items() if k != "daily_history"}
                    database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                                     [f"cache_{ticker}", json.dumps(cache_data)])
                    database.commit()
                    database.close()
                except:
                    pass
                time.sleep(RATE_DELAY)

    log.info(f"fetch_price_data complete: {len(results)}/{len(tickers)} tickers")
    return results

def fetch_current_prices(tickers, pin_to_845=False):
    """
    Fetch current prices for monitoring.
    Uses Finnhub /quote endpoint per ticker.
    Returns {ticker: {"price": float, "day_change_pct": float}}
    """
    if not tickers:
        return {}

    if pin_to_845:
        # For 8:45 AM entry price — use last available quote as approximation
        results = {}
        for ticker in tickers:
            quote = fetch_finnhub_quote(ticker)
            if quote:
                results[ticker] = {"price": quote["price"], "day_change_pct": 0}
            time.sleep(1.1)
        return results

    return fetch_twelve_data_live(tickers)

def calculate_rsi_batch(tickers, period=14, price_data=None):
    """
    Calculate RSI for multiple tickers.
    Uses daily_history already in price_data when available (no extra API calls).
    Falls back to fetching from Twelve Data if history not available.
    """
    rsi_values = {}

    for ticker in tickers:
        try:
            # Use pre-fetched daily history if available
            history = None
            if price_data and ticker in price_data:
                history = price_data[ticker].get("daily_history")

            if not history or len(history) < period + 1:
                # Fetch history for this ticker
                td = fetch_twelve_data_batch([ticker], interval="1day", outputsize=60)
                if ticker in td:
                    history = td[ticker].get("daily_history", [])

            if not history or len(history) < period + 1:
                rsi_values[ticker] = 50.0
                continue

            closes = [h["close"] for h in history]
            changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            gains = [max(c, 0) for c in changes]
            losses = [max(-c, 0) for c in changes]

            avg_gain = sum(gains[-period:]) / period
            avg_loss = sum(losses[-period:]) / period

            if avg_loss == 0:
                rsi_values[ticker] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_values[ticker] = 100 - (100 / (1 + rs))
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
    Score a ticker against 8 trading methods and return confluence count.
    Each method returns True/False based on its rules applied to daily OHLCV data.

    Methods:
    1.  Darvas Box          — near 52W high + volume + positive gap
    2.  Gap and Go          — gap up >2% + volume surge
    3.  Donchian Channel    — price above 20-day high
    4.  Inside Day          — today's range inside yesterday's + breaking up
    5.  NR7                 — narrowest range of last 7 days
    6.  Bull Flag           — strong prior move + tight consolidation
    7.  Pocket Pivot        — up day with volume > any down-day vol of last 10 days
    8.  Support & Resistance — ATR-adaptive zone analysis (open air or near support)
    9.  VWAP Reclaim        — closing above VWAP, institutional buy-side conviction
    10. Volatility Squeeze  — HV compression ratio, coiled spring setup

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

    # 5. NR7 — today's range is narrowest of last 7 days (compression)
    if daily_history and len(daily_history) >= 7:
        ranges = [(d["high"] - d["low"]) for d in daily_history[-7:]]
        today_range = high - low
        if today_range <= min(ranges) * 1.05 and gap_pct > 0:
            methods_agree.append("NR7")

    # 6. Bull Flag — strong move in last 3-5 days + today consolidating/breaking up
    if daily_history and len(daily_history) >= 5:
        five_day_move = (price - daily_history[-5]["close"]) / max(daily_history[-5]["close"], 0.01) * 100
        recent_consolidation = abs(day_change) < 3  # Tight day = flag
        if five_day_move >= 8 and recent_consolidation and gap_pct >= 0:
            methods_agree.append("Bull Flag")

    # 7. Pocket Pivot — up day with volume exceeding any down-day volume of last 10 days
    if daily_history and len(daily_history) >= 10 and day_change > 0:
        down_day_volumes = [d["volume"] for d in daily_history[-10:] if d.get("close", 0) < d.get("open", 0)]
        current_volume = data.get("volume", 0)
        if down_day_volumes and current_volume > max(down_day_volumes):
            methods_agree.append("Pocket Pivot")
        elif not down_day_volumes and volume_ratio >= 1.5 and day_change > 0:
            # No down days in 10 days — strong uptrend, volume surge qualifies
            methods_agree.append("Pocket Pivot")

    # 8. Support & Resistance — ATR-adaptive zone analysis
    sr = data.get("sr_analysis") or calculate_support_resistance(ticker, price_data)
    if sr["signal"] in ("open_air", "open_air+support_floor") or        ("support_floor" in sr["signal"] and sr["score"] >= 0.65):
        methods_agree.append("S&R")

    # 9. VWAP Reclaim — price closing above VWAP shows institutional buy-side
    vwap_score = calculate_vwap_signal(ticker, price_data)
    if vwap_score >= 0.75:
        methods_agree.append("VWAP Reclaim")

    # 10. Volatility Squeeze — compression precedes explosive directional move
    squeeze_score = calculate_volatility_squeeze(ticker, price_data)
    if squeeze_score >= 0.75:
        methods_agree.append("Vol Squeeze")

    return {"count": len(methods_agree), "methods": methods_agree}


def enrich_price_data_with_history(tickers, price_data):
    """
    Ensure daily_history is populated in price_data for confluence scoring.
    Twelve Data already includes history in fetch_price_data results.
    Only fetches missing history for tickers that don't have it yet.
    """
    missing = [t for t in tickers if t in price_data and not price_data[t].get("daily_history")]
    if not missing:
        return  # All tickers already have history from Twelve Data

    log.info(f"Fetching history for {len(missing)} tickers missing daily_history...")
    supplemental = fetch_twelve_data_batch(missing, interval="1day", outputsize=60)
    for ticker in missing:
        if ticker in supplemental and "daily_history" in supplemental[ticker]:
            price_data[ticker]["daily_history"] = supplemental[ticker]["daily_history"]

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
    rsi = rsi if rsi == rsi else 50.0

    # RSI
    if direction == "long":
        rsi_score = 1.0 if 40 <= rsi <= 65 else (0.9 if rsi < 40 else 0.5)
    else:
        rsi_score = 1.0 if rsi > 65 else (0.7 if rsi > 55 else 0.4)

    # Volume
    volume_ratio = price_data.get("volume_ratio", 1.0)
    volume_ratio = volume_ratio if volume_ratio == volume_ratio else 1.0
    volume_score = min(volume_ratio / 3.5, 1.0)

    # Gap
    gap_percent = price_data.get("gap_percent", 0)
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
    sr_analysis = price_data.get("sr_analysis")
    sr_score = sr_analysis["score"] if sr_analysis else 0.5
    sr_signal = sr_analysis["signal"] if sr_analysis else "unknown"
    sr_nearest_resistance = sr_analysis.get("nearest_resistance") if sr_analysis else None
    sr_nearest_support = sr_analysis.get("nearest_support") if sr_analysis else None
    if direction == "short": sr_score = 1.0 - sr_score

    # RS vs Market — compute diff for display
    rs_score = calculate_relative_strength(ticker, price_data)
    rs_stock_5d, rs_spy_5d = None, None
    try:
        ticker_history = price_data[ticker].get("daily_history", [])
        spy_history = price_data.get("SPY", {}).get("daily_history", [])
        if len(ticker_history) >= 5 and len(spy_history) >= 5:
            rs_stock_5d = round((ticker_history[-1]["close"] - ticker_history[-5]["close"]) / max(ticker_history[-5]["close"], 0.01) * 100, 2)
            rs_spy_5d = round((spy_history[-1]["close"] - spy_history[-5]["close"]) / max(spy_history[-5]["close"], 0.01) * 100, 2)
    except: pass
    if direction == "short": rs_score = 1.0 - rs_score

    # Sector RS — compute diff + ETF name for display
    sector_rs_score = calculate_sector_relative_strength(ticker, price_data)
    sector_etf_name, sector_etf_5d, sector_spy_5d = None, None, None
    try:
        SECTOR_ETF_MAP = {
            "Tech": "XLK", "Finance": "XLF", "Energy": "XLE",
            "Healthcare": "XLV", "Industrial": "XLI", "Consumer": "XLY",
            "Defense": "XLI", "Auto": "XLY", "Crypto": "XLK",
        }
        sector_etf_name = SECTOR_ETF_MAP.get(get_sector(ticker))
        if sector_etf_name and sector_etf_name in price_data and "SPY" in price_data:
            etf_hist = price_data[sector_etf_name].get("daily_history", [])
            spy_hist = price_data.get("SPY", {}).get("daily_history", [])
            if len(etf_hist) >= 5 and len(spy_hist) >= 5:
                sector_etf_5d = round((etf_hist[-1]["close"] - etf_hist[-5]["close"]) / max(etf_hist[-5]["close"], 0.01) * 100, 2)
                sector_spy_5d = round((spy_hist[-1]["close"] - spy_hist[-5]["close"]) / max(spy_hist[-5]["close"], 0.01) * 100, 2)
    except: pass
    if direction == "short": sector_rs_score = 1.0 - sector_rs_score

    # VWAP — capture mode + distance
    vwap_score = calculate_vwap_signal(ticker, price_data)
    vwap_mode, vwap_dist = "unknown", None
    try:
        vwap = price_data.get(ticker, {}).get("vwap")
        price = price_data.get(ticker, {}).get("price", 0)
        if vwap and price and vwap > 0:
            vwap_mode = "real"
            vwap_dist = round((price - vwap) / vwap * 100, 2)
        else:
            vwap_mode = "proxy"
            close = price_data.get(ticker, {}).get("price", 0)
            open_p = price_data.get(ticker, {}).get("open", close)
            if open_p > 0:
                vwap_dist = round((close - open_p) / open_p * 100, 2)
    except: pass
    if direction == "short": vwap_score = 1.0 - vwap_score

    # Volatility Squeeze — compute HV ratio for display
    squeeze_score = calculate_volatility_squeeze(ticker, price_data)
    hv_ratio = None
    try:
        import math
        history = price_data.get(ticker, {}).get("daily_history", [])
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
        "overnight_gap":      round(gap_score, 3),
        "earnings_catalyst":  round(earnings_score, 3),
        "support_resistance": round(sr_score, 3),
        "relative_strength":  round(rs_score, 3),
        "sector_rs":          round(sector_rs_score, 3),
        "vwap_reclaim":       round(vwap_score, 3),
        "volatility_squeeze": round(squeeze_score, 3),
    }

    values = {
        "rsi_momentum":       round(rsi, 1),
        "volume_surge":       round(volume_ratio, 2),
        "overnight_gap":      round(gap_percent, 2),
        "earnings_catalyst":  days_to_earnings,
        "support_resistance": {"signal": sr_signal, "resistance": sr_nearest_resistance, "support": sr_nearest_support},
        "relative_strength":  {"stock_5d": rs_stock_5d, "spy_5d": rs_spy_5d},
        "sector_rs":          {"etf": sector_etf_name, "etf_5d": sector_etf_5d, "spy_5d": sector_spy_5d},
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


def is_extended_hours():
    """
    Returns True if current CST time is in pre-market (4:00-9:30 AM) or
    post-market (4:00-8:00 PM) session. Used to decide whether to fetch
    live extended-hours prices via fast_info instead of daily OHLCV close.
    """
    now = current_time_cst()
    hour = now.hour + now.minute / 60
    is_premarket  = 4.0 <= hour < 9.5
    is_postmarket = 16.0 <= hour < 20.0
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

    enriched = 0
    for ticker in tickers:
        if ticker not in price_data:
            continue
        try:
            quote = fetch_finnhub_quote(ticker)
            if not quote or quote["price"] <= 0:
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
                data["day_change_percent"] = round(new_gap, 4)
            else:
                new_change = (live_price - today_close) / max(today_close, 0.01) * 100
                data["day_change_percent"] = round(new_change, 4)
            data["live_price_source"] = "finnhub"
            enriched += 1
            time.sleep(1.1)
        except:
            pass

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
    rsi = rsi if rsi == rsi else 50.0

    # 1. RSI Momentum
    if direction == "long":
        rsi_score = 1.0 if 40 <= rsi <= 65 else (0.9 if rsi < 40 else 0.5)
    else:
        rsi_score = 1.0 if rsi > 65 else (0.7 if rsi > 55 else 0.4)

    # 2. Volume Surge
    volume_ratio = price_data.get("volume_ratio", 1.0)
    volume_ratio = volume_ratio if volume_ratio == volume_ratio else 1.0
    volume_score = min(volume_ratio / 3.5, 1.0)

    # 3. Overnight Gap
    gap_percent = price_data.get("gap_percent", 0)
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
    sr_analysis = price_data.get("sr_analysis")
    sr_score = sr_analysis["score"] if sr_analysis else 0.5
    if direction == "short":
        sr_score = 1.0 - sr_score

    # 6. Relative Strength vs Market
    rs_score = calculate_relative_strength(ticker, price_data)
    if direction == "short":
        rs_score = 1.0 - rs_score

    # 7. Sector Relative Strength
    sector_rs_score = calculate_sector_relative_strength(ticker, price_data)
    if direction == "short":
        sector_rs_score = 1.0 - sector_rs_score

    # 8. VWAP Distance/Reclaim
    vwap_score = calculate_vwap_signal(ticker, price_data)
    if direction == "short":
        vwap_score = 1.0 - vwap_score

    # 9. Volatility Squeeze
    squeeze_score = calculate_volatility_squeeze(ticker, price_data)

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

    # ── TARGET HIT — Take profits on strong moves ──
    if pnl_percent >= 8:
        return True, "target_hit", f"Sold — target hit at {pnl_percent:+.1f}%"

    # ── STOP LOSS — Cut losses on strong reversals ──
    if pnl_percent <= -5:
        return True, "stop_loss", f"Exiting — reversal at {pnl_percent:+.1f}%"

    # ── MOMENTUM FADE — Small gain but volume dying ──
    if pnl_percent >= 2 and pnl_percent < 5 and volume_ratio and volume_ratio < 0.6:
        return True, "momentum_fade", f"Exiting — volume fading at {pnl_percent:+.1f}%"

    # ── RSI EXHAUSTION — Momentum peaked for longs ──
    if trade["direction"] == "long" and rsi and rsi > 80 and pnl_percent > 3:
        return True, "rsi_exhaustion", f"Exiting — RSI {rsi:.0f} exhausted at {pnl_percent:+.1f}%"

    # ── TIME PRESSURE — Clock running out, take what you have ──
    if remaining_minutes < 30 and pnl_percent > 0.5:
        return True, "time_pressure", f"Closing — {remaining_minutes}min left at {pnl_percent:+.1f}%"

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
def run_comprehensive_scan(weights=None, scan_type="scheduled"):
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
        open_tickers = set(r["ticker"] for r in _db.execute(
            "SELECT ticker FROM virtual_trades WHERE outcome='open'"
        ).fetchall())
        _db.close()
        universe = [t for t in universe if t not in open_tickers]
    except Exception as e:
        log.warning(f"Could not exclude open tickers from scan: {e}")

    log.info(f"Comprehensive scan: {len(universe)} tickers ({scan_type}, {len(open_tickers) if 'open_tickers' in dir() else 0} open positions excluded)...")

    # Ensure SPY is always fetched — needed for relative strength calculations
    universe_with_spy = list(dict.fromkeys(universe + ["SPY"]))
    price_data = fetch_price_data(universe_with_spy)

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
    open_trades = database.execute(
        "SELECT ticker, direction FROM virtual_trades WHERE outcome='open'"
    ).fetchall()
    database.close()
    open_long_tickers = set(t["ticker"] for t in open_trades if t["direction"] == "long")
    open_short_tickers = set(t["ticker"] for t in open_trades if t["direction"] == "short")
    all_open_tickers = open_long_tickers | open_short_tickers

    scored_stocks = []
    for ticker in universe:
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

        long_confidence = calculate_confidence_score(ticker, stock_data, rsi, earnings_soon, weights, "long")
        short_confidence = calculate_confidence_score(ticker, stock_data, rsi, earnings_soon, weights, "short")
        long_move = estimate_overnight_move(stock_data, long_confidence, has_earnings)
        short_move = estimate_overnight_move(stock_data, short_confidence, has_earnings)

        # Calculate method confluence
        confluence = calculate_method_confluence(ticker, price_data)

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
        })

    # Check if queue is locked (post 8:25 AM CST)
    # If locked, scan still runs for monitoring purposes but no new picks enter the queue
    try:
        _db = get_database()
        _lock = _db.execute("SELECT value FROM app_state WHERE key='queue_locked'").fetchone()
        queue_is_locked = _lock and _lock["value"] == "true"
        _db.close()
    except:
        queue_is_locked = False

    if queue_is_locked and scan_type not in ("manual", "manual_fresh"):
        log.info(f"Queue locked — scan completed but no new picks added ({scan_type})")
        return {"longs": [], "shorts": [], "queue_locked": True,
                "total_scanned": len(scored_stocks), "scan_type": scan_type,
                "generated_at": current_time_cst().isoformat()}

    # Filter by confidence floor — longs only.
    # Shorts are disabled: current signals (RSI momentum, volume surge, gap probability)
    # are optimized for long setups. Short-specific signals (RSI overbought, failed
    # breakout, sector weakness) will be added in a future session before re-enabling.
    MIN_VOLUME_RATIO = 1.2  # Minimum volume activity to confirm a real setup
    recommended_longs = sorted(
        [s for s in scored_stocks
         if s["long_conf"] >= CONFIDENCE_FLOOR
         and s["long_move"] >= MIN_EXPECTED_MOVE
         and s["vol_ratio"] >= MIN_VOLUME_RATIO
         and s["ticker"] not in open_short_tickers],
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

    scan_result = {
        "longs": recommended_longs[:MAX_LONG_PICKS],
        "shorts": recommended_shorts[:MAX_SHORT_PICKS],
        "all_longs": len(recommended_longs),
        "all_shorts": len(recommended_shorts),
        "total_scanned": len(scored_stocks),
        "generated_at": current_time_cst().isoformat(),
        "scan_type": scan_type,
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
    log.info(f"Scan complete: {len(recommended_longs)} longs, {len(recommended_shorts)} shorts from {len(scored_stocks)} scanned")
    return scan_result

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
        for ticker in universe:
            if ticker not in price_data:
                continue
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


def execute_opening_positions():
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

        existing.execute("""
            INSERT INTO virtual_trades
            (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
             confidence, lock_in_confidence, expected_move, outcome, sector, reasoning, closed_days,
             status, current_value, intraday_high_pct, intraday_low_pct, queue_position,
             signal_scores, news_sentiment_score, news_article_count, broke_52w_high_days_ago)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [trade_id, ticker, direction, today, "08:45:00", buy_price,
              round(invested_amount, 4), confidence, confidence, expected_move, "open",
              get_sector(ticker), reasoning, closed_days,
              "open", round(invested_amount, 4), 0.0, 0.0, queue_id,
              _signal_scores_json, _news_sentiment, _news_count, _52w_days_ago])
        existing.commit()
        existing.close()

        # Mark queue amount as consumed
        consume_queue_amount(queue_id, trade_id)
        opened_count += 1

    log.info(f"Opened {opened_count} positions at 8:45 AM CST")

def monitor_open_positions():
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
        return

    # Combine all tickers that need price checks
    all_tickers = list(set(
        [position["ticker"] for position in open_positions] +
        [candidate["ticker"] for candidate in monitored_candidates]
    ))

    if not all_tickers:
        return

    current_prices = fetch_current_prices(all_tickers)
    now = current_time_cst()
    today = now.strftime("%Y-%m-%d")
    database = get_database()

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
        if ticker not in current_prices:
            continue

        price_data = current_prices[ticker]
        price = price_data["price"] if isinstance(price_data, dict) else float(price_data)
        day_change_pct = price_data.get("day_change_pct", 0) if isinstance(price_data, dict) else 0

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

        # Update current value, intraday extremes, and dynamic scores
        current_value = invested + pnl_dollars
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
            database.execute("""
                UPDATE virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?,
                dynamic_confidence=?, dynamic_estimate=?, confluence_count=?, confluence_methods=?,
                signal_scores=?, last_price_updated=?, day_change_percent=?
                WHERE id=?
            """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2),
                  dyn_conf, round(dyn_est, 1), conf_count, conf_methods,
                  _signal_scores_json, now.isoformat(), day_change_pct, position["id"]])
        except:
            database.execute("""
                UPDATE virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?,
                last_price_updated=?, day_change_percent=?
                WHERE id=?
            """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2),
                  now.isoformat(), day_change_pct, position["id"]])

        # Refresh news for open positions — once per monitor cycle, rate-limited
        # Only refresh if news is stale (>30 min old) to stay within Alpha Vantage limits
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

        # Skip sell decisions outside regular market hours
        if not is_market_open():
            continue

        # Determine if this is the sell day (position was opened before today)
        is_sell_day = position["buy_date"] < today

        if is_sell_day and now.hour >= 8 and now.hour < 15:
            # Evaluate sell decision
            should_sell, reason, sentiment = evaluate_sell_decision(position, price)

            # PDT check: if this would be a same-day close (day trade), verify we have capacity
            is_day_trade = position["buy_date"] == today
            if should_sell and is_day_trade and reason in ("cut_loss", "stop_loss"):
                if not can_day_trade():
                    log.warning(f"PDT limit reached — cannot CUT {ticker} today (day trade #{get_pdt_count()+1}). Downgrading to WEAK.")
                    should_sell = False
                    sentiment = f"PDT limit — holding {ticker} despite loss. Max 3 day trades/week."

            database.execute("""
                INSERT INTO position_checks (position_id, check_time, price, pnl_percent, sentiment, ticker)
                VALUES (?,?,?,?,?,?)
            """, [position["id"], now.isoformat(), price, round(pnl_percent, 2), sentiment, ticker])

            if should_sell:
                net_pnl = pnl_dollars - FEE_PER_TRADE
                outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")

                database.execute("""
                    UPDATE virtual_trades SET
                        sell_date=?, sell_time=?, sell_price=?, current_value=?,
                        actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
                    WHERE id=?
                """, [today, now.strftime("%H:%M:%S"), price,
                      round(current_value, 4), round(pnl_percent, 2),
                      round(pnl_dollars, 4), round(net_pnl, 4),
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
                add_to_queue(current_value, position["id"])

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
    log.info(f"Monitored {len(open_positions)} positions + {len(monitored_candidates)} candidates")

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
        raw = current_prices.get(ticker)
        price = raw["price"] if isinstance(raw, dict) else (raw or position.get("buy_price", 0))
        buy_price = position["buy_price"]
        invested = position["invested_amount"] or DEFAULT_INVESTMENT
        pnl_percent = (price - buy_price) / buy_price * 100
        if position["direction"] == "short":
            pnl_percent = -pnl_percent
        pnl_dollars = invested * (pnl_percent / 100)
        net_pnl = pnl_dollars - FEE_PER_TRADE
        ending_value = invested + pnl_dollars
        outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")

        database.execute("""
            UPDATE virtual_trades SET
                sell_date=?, sell_time=?, sell_price=?, current_value=?,
                actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
            WHERE id=?
        """, [today, "14:45:00", price, round(ending_value, 4),
              round(pnl_percent, 2), round(pnl_dollars, 4), round(net_pnl, 4),
              outcome, "forced_close", position["id"]])

        database.execute("""
            UPDATE predictions SET outcome=?, actual_move=?, resolved_at=?
            WHERE id=?
        """, [outcome, round(pnl_percent, 2), now.isoformat(),
              f"{ticker}_{position['buy_date']}_{position['direction']}"])

        # Add ending value to queue — this is where compounding happens
        add_to_queue(ending_value, position["id"])
        closed_count += 1

        # Send SMS notification
        send_close_notification(
            ticker, round(pnl_dollars, 2), round(pnl_percent, 1),
            "force closed in profit at 2:45 PM"
        )

    database.commit()
    database.close()
    log.info(f"Force-closed {closed_count} positions at 2:45 PM CST")

# ── SELF-AUDIT ENGINE ─────────────────────────────────────────────────────────
def run_self_audit():
    """Call Claude API to analyze prediction history and update signal weights."""
    log.info("Running self-audit...")
    database = get_database()
    resolved_predictions = [dict(p) for p in database.execute(
        "SELECT * FROM predictions WHERE outcome != 'pending' ORDER BY date DESC LIMIT 200"
    ).fetchall()]
    total_predictions = database.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    database.close()

    hit_predictions = [p for p in resolved_predictions if p["outcome"] == "hit"]
    miss_predictions = [p for p in resolved_predictions if p["outcome"] == "miss"]
    win_rate = len(hit_predictions) / len(resolved_predictions) if resolved_predictions else None
    current_weights = get_signal_weights()

    # Gather closed_days distribution to help brain learn from extended holds
    database = get_database()
    closed_days_rows = database.execute("""
        SELECT closed_days, COUNT(*) as count,
               AVG(COALESCE(actual_move, 0)) as avg_move,
               SUM(CASE WHEN outcome='hit' THEN 1 ELSE 0 END) as hits
        FROM virtual_trades
        WHERE outcome != 'open' AND closed_days IS NOT NULL
        GROUP BY closed_days ORDER BY closed_days
    """).fetchall()
    database.close()
    closed_days_summary = [dict(row) for row in closed_days_rows]

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=800,
            messages=[{"role": "user", "content":
                f"Self-audit for overnight swing trading brain. Analyze and return updated weights.\n"
                f"CURRENT WEIGHTS: {json.dumps(current_weights)}\n"
                f"PERFORMANCE: {json.dumps({'total': total_predictions, 'resolved': len(resolved_predictions), 'hits': len(hit_predictions), 'misses': len(miss_predictions), 'win_rate': win_rate})}\n"
                f"HOLD DURATION BREAKDOWN: {json.dumps(closed_days_summary)}\n"
                f"Indicators: rsi_momentum, volume_surge, overnight_gap_probability, earnings_catalyst, "
                f"support_resistance, relative_strength, sector_relative_strength, vwap_reclaim, volatility_squeeze.\n"
                f"support_resistance: open-air setups score high, resistance-capped setups score low.\n"
                f"relative_strength: stock outperforming SPY 5-day scores high.\n"
                f"sector_relative_strength: sector ETF outperforming SPY 5-day scores high.\n"
                f"vwap_reclaim: closing above VWAP shows institutional buy-side conviction.\n"
                f"volatility_squeeze: low HV ratio (compression) scores high — coiled spring setup.\n"
                f"Rules: weights must sum to 1.0, each between 0.03-0.35.\n"
                f"Respond ONLY with valid JSON: {{\"weights\":{{...}},\"reasoning\":[\"...\"],\"summary\":\"...\",\"confidence\":\"low|medium|high\"}}"
            }]
        )
        result = json.loads(response.content[0].text.replace("```json", "").replace("```", "").strip())
        new_weights = result["weights"]
        weight_sum = sum(new_weights.values())
        if 0.85 < weight_sum < 1.15:
            new_weights = {k: round(v / weight_sum, 4) for k, v in new_weights.items()}
            save_signal_weights(new_weights)
        else:
            new_weights = current_weights

        database = get_database()
        database.execute("""
            INSERT INTO audit_log (timestamp, weights_before, weights_after, reasoning, summary,
            total_predictions, resolved_count, hit_count, miss_count, win_rate)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, [current_time_cst().isoformat(), json.dumps(current_weights), json.dumps(new_weights),
              json.dumps(result.get("reasoning", [])), result.get("summary", ""),
              total_predictions, len(resolved_predictions), len(hit_predictions),
              len(miss_predictions), win_rate])
        # Also write to weights_history for chart visualization
        database.execute("""
            INSERT INTO weights_history (timestamp, rsi_momentum, volume_surge,
            overnight_gap_probability, earnings_catalyst, support_resistance,
            relative_strength, sector_relative_strength, vwap_reclaim, volatility_squeeze,
            win_rate, total_resolved)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, [current_time_cst().isoformat(),
              new_weights.get("rsi_momentum", 0),
              new_weights.get("volume_surge", 0),
              new_weights.get("overnight_gap_probability", 0),
              new_weights.get("earnings_catalyst", 0),
              new_weights.get("support_resistance", 0),
              new_weights.get("relative_strength", 0),
              new_weights.get("sector_relative_strength", 0),
              new_weights.get("vwap_reclaim", 0),
              new_weights.get("volatility_squeeze", 0),
              win_rate, len(resolved_predictions)])
        database.execute("INSERT OR REPLACE INTO app_state VALUES ('last_audit',?)",
                         [current_time_cst().isoformat()])
        database.commit()
        database.close()
        return {"success": True, "weights": new_weights,
                "reasoning": result.get("reasoning", []),
                "summary": result.get("summary", ""),
                "confidence": result.get("confidence", "medium")}
    except Exception as error:
        log.error(f"Audit error: {error}")
        return {"success": False, "error": str(error)}

# ── SCHEDULER ─────────────────────────────────────────────────────────────────
def run_scheduler():
    """
    Background scheduler for all automated tasks.
    
    All times are specified in UTC (CST + 5 hours).
    
    Comprehensive scans run every 30 minutes during pre-market and post-market.
    8:30 AM CST market open scan fires after queue lock-in for fresh open-market scores.
    5-minute monitoring runs continuously during active hours (4 AM - 7 PM CST).
    """
    import schedule

    # ── Pre-market comprehensive scans (every 30 min, 4:00-8:00 AM CST) ──
    # CST + 5 = UTC
    for hour_utc, label in [(9,"4:00am"),(9.5,"4:30am"),(10,"5:00am"),(10.5,"5:30am"),
                             (11,"6:00am"),(11.5,"6:30am"),(12,"7:00am"),(12.5,"7:30am"),
                             (13,"8:00am")]:
        hour = int(hour_utc)
        minute = int((hour_utc % 1) * 60)
        time_str = f"{hour:02d}:{minute:02d}"
        scan_label = f"pre_market_{label}"
        schedule.every().day.at(time_str).do(lambda st=scan_label: run_comprehensive_scan(scan_type=st))

    # 8:15 AM CST = 13:15 UTC — Final pre-market scan
    schedule.every().day.at("13:15").do(lambda: run_comprehensive_scan(scan_type="final_scan"))

    # 8:25 AM CST = 13:25 UTC — Queue lock-in: no new picks after this
    schedule.every().day.at("13:25").do(lock_pick_queue)

    # 8:30 AM CST = 13:30 UTC — Market open scan: fresh scores at open for recs + ML data
    schedule.every().day.at("13:30").do(lambda: run_comprehensive_scan(scan_type="market_open"))

    # 8:45 AM CST = 13:45 UTC — Execute positions at market open + 15 min
    schedule.every().day.at("13:45").do(execute_opening_positions)

    # 2:45 PM CST = 19:45 UTC — Force-close previous session positions
    schedule.every().day.at("19:45").do(force_close_previous_session)

    # 3:00 PM CST = 20:00 UTC — Market close scan
    schedule.every().day.at("20:00").do(lambda: run_comprehensive_scan(scan_type="market_close"))

    # ── Post-market comprehensive scans (every 30 min, 3:30-6:00 PM CST) ──
    for hour_utc, label in [(20.5,"3:30pm"),(21,"4:00pm"),(21.5,"4:30pm"),
                             (22,"5:00pm"),(22.5,"5:30pm"),(23,"6:00pm")]:
        hour = int(hour_utc)
        minute = int((hour_utc % 1) * 60)
        time_str = f"{hour:02d}:{minute:02d}"
        scan_label = f"post_market_{label}"
        schedule.every().day.at(time_str).do(lambda st=scan_label: run_comprehensive_scan(scan_type=st))

    # 4:00 AM CST = 09:00 UTC — Unlock queue for new pre-market session
    schedule.every().day.at("09:00").do(unlock_pick_queue)

    # Self-audit at 7:00 PM CST = 00:00 UTC (midnight) — end of trading day
    # Runs after post-market closes so brain has full day of data to learn from
    # Skip weekends — no trading data on Sat/Sun
    def run_audit_if_weekday():
        if current_time_cst().weekday() < 5:
            run_self_audit()
            # Train NN after audit — fresh data available
            try:
                train_neural_network()
            except Exception as nn_err:
                log.error(f"NN training failed: {nn_err}")
    schedule.every().day.at("23:55").do(run_audit_if_weekday)

    # NN scan runs every 30 min alongside crude algo scan
    for hour, minute, label in [
        (9,"00","4:00am"),(9,30,"4:30am"),(10,"00","5:00am"),(10,30,"5:30am"),
        (11,"00","6:00am"),(11,30,"6:30am"),(12,"00","7:00am"),(12,30,"7:30am"),
        (13,"00","8:00am"),(13,30,"8:30am"),(14,"00","9:00am"),(14,30,"9:30am"),
        (15,"00","10:00am"),(15,30,"10:30am"),(16,"00","11:00am"),(16,30,"11:30am"),
        (17,"00","12:00pm"),(17,30,"12:30pm"),(18,"00","1:00pm"),(18,30,"1:30pm"),
        (19,"00","2:00pm"),(19,30,"2:30pm"),(20,"00","3:00pm"),(20,30,"3:30pm"),
        (21,"00","4:00pm"),(21,30,"4:30pm"),(22,"00","5:00pm"),(22,30,"5:30pm"),
        (23,"00","6:00pm"),(23,30,"6:30pm"),(0,"00","7:00pm"),(0,30,"7:30pm"),
    ]:
        time_str = f"{hour:02d}:{minute:02d}" if isinstance(minute, int) else f"{hour:02d}:{minute}"
        schedule.every().day.at(time_str).do(lambda st=label: run_nn_scan(scan_type=st))

    log.info("Scheduler started — comprehensive scans every 30min, position monitoring 2.5min regular/5min extended, NN scan every 30min")

    # Dynamic monitoring loop — 2.5 min during regular hours, 5 min during pre/post market
    last_monitor_time = 0
    while True:
        schedule.run_pending()
        current_time = time.time()

        now = current_time_cst()
        is_regular = is_market_open()
        in_extended, _ = is_extended_hours()
        is_active = now.weekday() < 5 and (is_regular or in_extended or 4 <= now.hour < 20)

        # 2.5 min during regular market hours, 5 min during pre/post market
        dynamic_interval = 150 if is_regular else 300  # 150s = 2.5 min, 300s = 5 min

        if is_active and current_time - last_monitor_time >= dynamic_interval:
            try:
                monitor_open_positions()
                last_monitor_time = current_time
            except Exception as error:
                log.error(f"Monitor error: {error}")

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
    database = get_database()
    rows = [dict(r) for r in database.execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 30"
    ).fetchall()]
    database.close()
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
    database = get_database()

    # ── Settled (closed) daily P&L ────────────────────────────────────────────
    daily_results = database.execute("""
        SELECT sell_date AS date,
               SUM(COALESCE(gross_pnl, 0)) AS daily_pnl,
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

    database.close()

    # ── Build settled balance timeline ────────────────────────────────────────
    running_balance = 1000.0
    history = []

    # Seed point — always use last trading weekday date so the frontend
    # baseline lookup (which filters for weekdays only) can always find it.
    # Using utcnow()-1 breaks on weekends when "yesterday" is Saturday.
    def last_trading_weekday():
        d = datetime.utcnow() - timedelta(days=1)
        # Walk back until we hit a weekday (Mon=0 ... Fri=4)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d
    seed_day = last_trading_weekday()
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
            "ts": int(datetime.fromisoformat(row["date"]).timestamp() * 1000),
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
            "SELECT invested_amount, current_value FROM virtual_trades WHERE outcome='open'"
        ).fetchall() if not database else None
        # Re-open db since we closed it above
        _db2 = get_database()
        open_trades = _db2.execute(
            "SELECT invested_amount, current_value FROM virtual_trades WHERE outcome='open'"
        ).fetchall()
        _db2.close()
        live_pnl = sum(
            float(t["current_value"] or t["invested_amount"] or 10) - float(t["invested_amount"] or 10)
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

@app.route("/api/ping")
def api_ping():
    """Lightweight wake-up endpoint. Frontend hits this first to warm Railway before real requests."""
    return jsonify({"ok": True, "ts": current_time_cst().isoformat()})

@app.route("/api/stats")
def api_stats():
    database = get_database()

    # virtual_trades is the single source of truth for all performance stats
    virtual_trade_count = database.execute("SELECT COUNT(*) as n FROM virtual_trades").fetchone()["n"]
    open_position_count = database.execute("SELECT COUNT(*) as n FROM virtual_trades WHERE outcome='open'").fetchone()["n"]
    closed_rows = database.execute(
        "SELECT outcome, actual_move, gross_pnl FROM virtual_trades WHERE outcome != 'open'"
    ).fetchall()
    resolved_count = len(closed_rows)
    hit_count = sum(1 for t in closed_rows if t["outcome"] == "hit")
    partial_count = sum(1 for t in closed_rows if t["outcome"] == "partial")
    miss_count = sum(1 for t in closed_rows if t["outcome"] == "miss")
    total_gross_pnl = sum(float(t["gross_pnl"] or 0) for t in closed_rows)
    win_rate = round(hit_count / resolved_count * 100, 1) if resolved_count else None

    # predictions table used only for audit/weight system — not for performance stats
    total_predictions = database.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]

    last_audit = database.execute("SELECT value FROM app_state WHERE key='last_audit'").fetchone()
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
        "virtual_trades": virtual_trade_count,
        "virtual_open": open_position_count,
        "last_audit": last_audit["value"] if last_audit else None,
        "last_scan": last_scan["value"] if last_scan else None,
        "weights": get_signal_weights(),
        "queue": get_queue_status(),
        "pdt_used": get_pdt_count(),
        "pdt_remaining": max(0, 3 - get_pdt_count()),
    })

@app.route("/api/method-stats")
def api_method_stats():
    """Return win rate and signal history for all 7 trading methods."""
    try:
        database = get_database()
        methods = ["Darvas", "Gap & Go", "Donchian", "Inside Day", "NR7", "Bull Flag", "Pocket Pivot", "S&R", "VWAP Reclaim", "Vol Squeeze"]
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
    database = get_database()
    rows = [dict(r) for r in database.execute(
        "SELECT id, scan_time, scan_type, ticker_count FROM scan_cache ORDER BY scan_time DESC LIMIT 50"
    ).fetchall()]
    database.close()
    return jsonify(rows)

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
            
            database.execute("""
                INSERT INTO virtual_trades
                (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
                 confidence, expected_move, outcome, sector, reasoning, closed_days,
                 status, current_value, intraday_high_pct, intraday_low_pct)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [trade_id, pick["ticker"], "long", friday_date, "08:45:00", pick["open_price"],
                  DEFAULT_INVESTMENT, pick["confidence"], pick["expected_move"],
                  "open", get_sector(pick["ticker"]), pick["reasoning"], 4,
                  "open", DEFAULT_INVESTMENT, 0.0, 0.0])
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
                        final_value = DEFAULT_INVESTMENT + DEFAULT_INVESTMENT * (last_pct/100)
                        database.execute("""
                            UPDATE virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?
                            WHERE id=?
                        """, [round(final_value,4), round(max(all_pcts),2), round(min(all_pcts),2), trade["id"]])
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
        base = ["^VIX", "SPY", "QQQ", "IWM", "NVDA", "TLT", "BTC-USD", "GLD"]
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
            current_value = invested * (1 + pnl_pct / 100)

            database.execute(
                "UPDATE virtual_trades SET current_value=? WHERE id=?",
                [round(current_value, 4), position["id"]]
            )
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
            current_value = invested * (1 + pnl_pct / 100)

            database.execute(
                "UPDATE virtual_trades SET buy_price=?, current_value=? WHERE id=?",
                [correct_price, round(current_value, 4), position["id"]]
            )
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

# ── BACKFILL TAGS ─────────────────────────────────────────────────────────────
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
            elif sell_reason in ("cut_loss", "stop_loss"):
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
            pnl_dollars = ending_value - invested
            pnl_percent = (pnl_dollars / invested) * 100 if invested else 0
            net_pnl = pnl_dollars - FEE_PER_TRADE
            outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")
            db.execute("""
                UPDATE virtual_trades SET
                    sell_date=?, sell_time=?, sell_price=?, current_value=?,
                    actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
                WHERE id=?
            """, [position["buy_date"], "14:45:00", position["buy_price"],
                  round(ending_value, 4), round(pnl_percent, 2),
                  round(pnl_dollars, 4), round(net_pnl, 4),
                  outcome, "forced_close", position["id"]])
            db.execute("""
                UPDATE predictions SET outcome=?, actual_move=?, resolved_at=?
                WHERE id=?
            """, [outcome, round(pnl_percent, 2), now.isoformat(),
                  "{}_{}_{}" .format(position["ticker"], position["buy_date"], position["direction"])])
            add_to_queue(ending_value, position["id"])
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
            SELECT ticker, name, direction, buy_date, sell_date, buy_price, sell_price,
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
            elif sell_reason in ("cut_loss", "stop_loss"):
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
    """Manually trigger NN scan. Returns picks."""
    try:
        result = run_nn_scan(scan_type="manual")
        return jsonify({"success": True, "total_scanned": result.get("total_scanned", 0), "picks": len(result.get("recommended_longs", []))})
    except Exception as e:
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
        db.close()
        if row:
            return jsonify(json.loads(row["value"]))
        return jsonify({"recommended_longs": [], "recommended_shorts": [], "total_scanned": 0})
    except Exception as e:
        return jsonify({"recommended_longs": [], "recommended_shorts": [], "total_scanned": 0})

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
            "SELECT outcome, actual_move, gross_pnl FROM nn_virtual_trades WHERE outcome != 'open'"
        ).fetchall()]
        open_count = db.execute(
            "SELECT COUNT(*) as n FROM nn_virtual_trades WHERE outcome='open'"
        ).fetchone()["n"]
        db.close()
        resolved = len(closed)
        hits = sum(1 for t in closed if t["outcome"] == "hit")
        misses = sum(1 for t in closed if t["outcome"] == "miss")
        partials = sum(1 for t in closed if t["outcome"] == "partial")
        total_pnl = sum(float(t["gross_pnl"] or 0) for t in closed)
        return jsonify({
            "resolved": resolved,
            "hits": hits,
            "misses": misses,
            "partials": partials,
            "win_rate": round(hits / resolved * 100, 1) if resolved else None,
            "total_gross_pnl": round(total_pnl, 2),
            "open_positions": open_count,
        })
    except Exception as e:
        return jsonify({"resolved": 0, "hits": 0, "misses": 0, "win_rate": None})

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
            body.get("sector", get_sector(ticker)),
            body.get("notes", ""),
            "manual",
            body.get("source_portfolio", "brain"),
            now.isoformat(), now.isoformat()
        ])
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
        default_weights = {
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
            pnl_dollars = ending_value - invested
            pnl_percent = (pnl_dollars / invested) * 100 if invested else 0
            net_pnl = pnl_dollars - FEE_PER_TRADE
            outcome = "hit" if pnl_percent >= MIN_EXPECTED_MOVE else ("partial" if pnl_percent > 0 else "miss")
            db.execute("""
                UPDATE virtual_trades SET
                    sell_date=?, sell_time=?, sell_price=?, current_value=?,
                    actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_reason=?
                WHERE id=?
            """, [position["buy_date"], "14:45:00", position["buy_price"],
                  round(ending_value, 4), round(pnl_percent, 2),
                  round(pnl_dollars, 4), round(net_pnl, 4),
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

backfill_missed_closes()
threading.Thread(target=run_scheduler, daemon=True).start()
threading.Thread(target=keep_server_alive, daemon=True).start()
log.info("Brain v4 initialized — full trading engine with self-regulating queue system + SwingDeskNet NN")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
