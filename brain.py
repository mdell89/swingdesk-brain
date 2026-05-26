"""
brain.py — Overnight Swing Desk Backend v15 (Push 43)
══════════════════════════════════════════════════════
Trading Engine with Self-Regulating Queue System

Changes in Push 43:
  - open-positions-dynamic: DB-only, zero yfinance calls on demand
    all values served from what the 2.5-min monitor last wrote to virtual_trades
    eliminates 5-6 sequential yfinance calls per request, fixes scheduler violation
  - /api/ping: lightweight wake-up endpoint for Railway cold start mitigation

Previous (Push 42):
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

import os, json, sqlite3, time, logging, threading, random
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

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
    """Open a connection to the SQLite database with WAL mode enabled."""
    connection = sqlite3.connect(DATABASE_PATH, check_same_thread=False, timeout=10)
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
def fetch_price_data(tickers):
    """
    Fetch daily price data for a list of tickers using yfinance (primary)
    with Alpha Vantage as fallback and local cache as last resort.
    Processes tickers in batches to handle large universes.
    """
    results = {}
    try:
        import yfinance as yf
        log.info(f"Fetching price data for {len(tickers)} tickers...")
        for batch_start in range(0, len(tickers), SCAN_BATCH_SIZE):
            batch_tickers = tickers[batch_start:batch_start + SCAN_BATCH_SIZE]
            try:
                batch_data = yf.download(
                    batch_tickers, period="5d", interval="1d",
                    group_by="ticker", auto_adjust=True, progress=False, threads=True
                )
                for ticker in batch_tickers:
                    try:
                        ticker_data = (batch_data if len(batch_tickers) == 1
                                       else (batch_data[ticker] if ticker in batch_data.columns.get_level_values(0) else None))
                        if ticker_data is not None and len(ticker_data) >= 2:
                            close_price = float(ticker_data["Close"].iloc[-1])
                            if close_price != close_price:
                                continue  # Skip NaN
                            previous_close = float(ticker_data["Close"].iloc[-2])
                            open_price = float(ticker_data["Open"].iloc[-1])
                            volume = float(ticker_data["Volume"].iloc[-1])
                            average_volume = float(ticker_data["Volume"].mean())
                            results[ticker] = {
                                "price": close_price,
                                "open": open_price,
                                "previous_close": previous_close,
                                "high": float(ticker_data["High"].iloc[-1]),
                                "low": float(ticker_data["Low"].iloc[-1]),
                                "volume": volume,
                                "average_volume": average_volume,
                                "volume_ratio": volume / max(average_volume, 1),
                                "gap_percent": (open_price - previous_close) / max(previous_close, 0.01) * 100,
                                "day_change_percent": (close_price - previous_close) / max(previous_close, 0.01) * 100,
                                "source": "yfinance",
                                "52w_high": None,
                                "broke_52w_high_days_ago": None,
                            }
                    except:
                        pass
            except Exception as batch_error:
                log.warning(f"Batch error at index {batch_start}: {batch_error}")
            time.sleep(0.3)  # Brief pause between batches to be polite
        log.info(f"yfinance returned {len(results)}/{len(tickers)} tickers")
    except Exception as error:
        log.error(f"yfinance error: {error}")

    # Alpha Vantage fallback for missing tickers
    missing_tickers = [t for t in tickers if t not in results]
    if missing_tickers and ALPHA_VANTAGE_KEY:
        import urllib.request
        for ticker in missing_tickers[:10]:
            try:
                url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}"
                with urllib.request.urlopen(url, timeout=5) as response:
                    quote = json.loads(response.read()).get("Global Quote", {})
                if quote.get("05. price"):
                    price = float(quote["05. price"])
                    previous = float(quote["08. previous close"])
                    results[ticker] = {
                        "price": price, "open": price, "previous_close": previous,
                        "high": price, "low": price, "volume": 0, "average_volume": 1,
                        "volume_ratio": 1.0,
                        "gap_percent": (price - previous) / max(previous, 0.01) * 100,
                        "day_change_percent": (price - previous) / max(previous, 0.01) * 100,
                        "source": "alpha_vantage",
                    }
                time.sleep(0.5)
            except:
                pass

    # Cache all fetched prices
    database = get_database()
    for ticker, data in results.items():
        database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                         [f"cache_{ticker}", json.dumps(data)])
    database.commit()
    database.close()
    return results

def fetch_current_prices(tickers, pin_to_845=False):
    """Quick price fetch for 5-minute monitoring — returns {ticker: price}.
    
    If pin_to_845=True (used at trade open time), fetches 1-minute data and
    returns the 8:45 AM CST candle open price for accuracy. This ensures buy
    prices are always anchored to the correct entry time, not a random 5m close.
    """
    results = {}
    try:
        import yfinance as yf
        import pytz

        if pin_to_845:
            # Use 1-minute data and find the exact 8:45 AM CST candle
            cst = pytz.timezone("America/Chicago")
            today_str = current_time_cst().strftime("%Y-%m-%d")
            batch_data = yf.download(
                tickers, period="1d", interval="1m",
                auto_adjust=True, progress=False, threads=True
            )
            for ticker in tickers:
                try:
                    ticker_data = (batch_data if len(tickers) == 1
                                   else (batch_data[ticker] if ticker in batch_data.columns.get_level_values(0) else None))
                    if ticker_data is None or ticker_data.empty:
                        continue
                    # Convert to CST and find 8:45 candle
                    ticker_data.index = ticker_data.index.tz_convert(cst)
                    candle = ticker_data[ticker_data.index.strftime("%H:%M") == "08:45"]
                    if candle.empty:
                        candle = ticker_data[ticker_data.index.strftime("%H:%M") == "08:46"]
                    if not candle.empty:
                        price = float(candle["Open"].iloc[0])
                        if price == price:  # Not NaN
                            results[ticker] = price
                    else:
                        # Fallback to first candle of the day if 8:45 not found
                        price = float(ticker_data["Open"].iloc[0])
                        if price == price:
                            results[ticker] = price
                except:
                    pass
        else:
            batch_data = yf.download(
                tickers, period="1d", interval="5m",
                group_by="ticker", auto_adjust=True, progress=False, threads=True
            )
            for ticker in tickers:
                try:
                    ticker_data = (batch_data if len(tickers) == 1
                                   else (batch_data[ticker] if ticker in batch_data.columns.get_level_values(0) else None))
                    if ticker_data is not None and len(ticker_data) >= 1:
                        price = float(ticker_data["Close"].iloc[-1])
                        if price == price:  # Not NaN
                            results[ticker] = price
                except:
                    pass
    except:
        pass
    return results

def calculate_rsi_batch(tickers, period=14):
    """
    Calculate RSI for multiple tickers in batches.

    Handles the yfinance multi-ticker DataFrame structure carefully:
    - Single ticker: columns are flat (Close, Volume, etc.)
    - Multiple tickers: columns are MultiIndex (field, ticker)
    Both cases are handled explicitly to avoid silent fallback to 50.0.
    """
    rsi_values = {}
    try:
        import yfinance as yf
        for batch_start in range(0, len(tickers), 50):
            batch_tickers = tickers[batch_start:batch_start + 50]
            try:
                data = yf.download(
                    batch_tickers, period="60d", interval="1d",
                    auto_adjust=True, progress=False, threads=True
                )
                if data is None or data.empty:
                    continue

                for ticker in batch_tickers:
                    try:
                        # Extract per-ticker Close series based on DataFrame structure
                        if len(batch_tickers) == 1:
                            # Single ticker: flat columns
                            close_series = data["Close"]
                        elif hasattr(data.columns, "get_level_values") and ticker in data.columns.get_level_values(1):
                            # Multi-ticker: MultiIndex columns (field, ticker)
                            close_series = data["Close"][ticker]
                        else:
                            rsi_values[ticker] = 50.0
                            continue

                        close_series = close_series.dropna()
                        if len(close_series) < period + 1:
                            rsi_values[ticker] = 50.0
                            continue

                        price_changes = close_series.diff()
                        average_gain = price_changes.clip(lower=0).rolling(period).mean()
                        average_loss = (-price_changes.clip(upper=0)).rolling(period).mean()
                        last_loss = float(average_loss.iloc[-1])

                        if last_loss == 0:
                            rsi_values[ticker] = 100.0
                        else:
                            relative_strength = float(average_gain.iloc[-1]) / last_loss
                            rsi = 100 - 100 / (1 + relative_strength)
                            rsi_values[ticker] = rsi if rsi == rsi else 50.0
                    except:
                        rsi_values[ticker] = 50.0
            except Exception as batch_err:
                log.warning(f"RSI batch error at {batch_start}: {batch_err}")
            time.sleep(0.3)
    except Exception as err:
        log.error(f"RSI calculation error: {err}")

    # Fill missing with neutral RSI
    for ticker in tickers:
        if ticker not in rsi_values:
            rsi_values[ticker] = 50.0
    return rsi_values

def check_upcoming_earnings(tickers):
    """
    Identify tickers with earnings in the next 7 days.
    Returns a dict of {ticker: days_until_earnings} for graduated scoring.
    Closer earnings = stronger catalyst signal.
    """
    earnings_soon = {}
    try:
        import yfinance as yf
        for ticker in tickers[:30]:
            try:
                calendar = yf.Ticker(ticker).calendar
                if calendar is not None and not calendar.empty:
                    earnings_date = calendar.iloc[0].get("Earnings Date")
                    if earnings_date:
                        days_away = (earnings_date - datetime.now()).days
                        if 0 <= days_away <= 7:
                            earnings_soon[ticker] = days_away
            except:
                pass
    except:
        pass
    return earnings_soon

# ── 52-WEEK BREAKOUT DETECTION ────────────────────────────────────────────────
def check_52w_breakouts(tickers, price_data):
    """
    Detect tickers that have broken above their 52-week high within the last 7 days.
    This is purely informational metadata — it does NOT affect confidence scores
    or recommendations. The brain tracks outcomes separately so we can learn
    over time whether 52W breakouts correlate with better performance.

    Returns: dict of {ticker: days_ago} for recent breakouts, or {} if none.
    """
    breakouts = {}
    try:
        import yfinance as yf
        for ticker in tickers:
            if ticker not in price_data:
                continue
            try:
                # Fetch 1 year of daily data to find the 52-week high
                hist = yf.Ticker(ticker).history(period="1y", interval="1d", auto_adjust=True)
                if hist is None or len(hist) < 30:
                    continue

                current_price = price_data[ticker]["price"]
                yearly_high = float(hist["High"].max())

                # Find the most recent day the price crossed above the 52W high
                # We look at the last 7 trading days
                recent = hist.tail(7)
                for days_back, (date, row) in enumerate(reversed(list(recent.iterrows()))):
                    if float(row["High"]) >= yearly_high * 0.995:  # Within 0.5% of 52W high
                        breakouts[ticker] = days_back + 1
                        price_data[ticker]["52w_high"] = round(yearly_high, 2)
                        price_data[ticker]["broke_52w_high_days_ago"] = days_back + 1
                        break
            except:
                pass
    except Exception as error:
        log.warning(f"52W breakout check error: {error}")
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
    Fetch daily OHLCV history for confluence scoring methods that need it.
    Adds 'daily_history' list to each ticker's price_data entry.
    Uses 60 days so S&R pivot detection has enough swing history to cluster from.
    """
    try:
        import yfinance as yf
        batch_data = yf.download(
            tickers, period="60d", interval="1d",
            auto_adjust=True, progress=False, threads=True
        )
        for ticker in tickers:
            if ticker not in price_data:
                continue
            try:
                if len(tickers) == 1:
                    td = batch_data
                else:
                    td = batch_data[ticker] if ticker in batch_data.columns.get_level_values(0) else None
                if td is None or td.empty:
                    continue
                history = []
                for i in range(len(td)):
                    row = td.iloc[i]
                    history.append({
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "open": float(row["Open"]),
                        "volume": float(row["Volume"]),
                    })
                price_data[ticker]["daily_history"] = history
            except:
                pass
    except Exception as e:
        log.warning(f"History enrichment error: {e}")

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
    Returns a list of normalized articles (up to 3), or empty list on failure.
    Alpha Vantage returns real article summaries unlike Yahoo RSS headlines-only.
    No sentiment scoring is used — display only.
    """
    if not ALPHA_VANTAGE_KEY:
        return []
    try:
        import urllib.request
        url = (f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT"
               f"&tickers={ticker}&limit=5&apikey={ALPHA_VANTAGE_KEY}")
        req = urllib.request.Request(url, headers={"User-Agent": "SwingDesk/1.0"})
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8", errors="ignore"))
        feed = data.get("feed", [])
        articles = []
        for item in feed[:5]:
            title = item.get("title", "").strip()
            summary = item.get("summary", "").strip()
            url_str = item.get("url", "").strip()
            # Alpha Vantage time format: "20260525T085000"
            time_str = item.get("time_published", "")
            pub_ts = 0
            if time_str:
                try:
                    dt = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                    pub_ts = dt.timestamp()
                except:
                    pass
            if title and url_str:
                articles.append(_normalize_news_article(title, summary, url_str, pub_ts, "alpha_vantage"))
        articles.sort(key=lambda x: x["ts"], reverse=True)
        return articles[:3]
    except Exception as err:
        log.debug(f"Alpha Vantage news failed for {ticker}: {err}")
        return []


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
    Primary: Alpha Vantage NEWS_SENTIMENT (real summaries, not just headlines).
    Fallback: Yahoo Finance RSS (headlines only).
    All articles normalized to internal schema regardless of source.
    Display only — no sentiment scoring or ML integration.
    """
    for ticker in tickers:
        if ticker not in price_data:
            continue
        articles = _fetch_news_alpha_vantage(ticker)
        if not articles:
            articles = _fetch_news_yahoo_rss(ticker)
        price_data[ticker]["news"] = articles[:1]  # Show most recent article on card


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



def send_close_notification(ticker, pnl_dollar, pnl_pct, close_reason, close_time=None):
    """
    Send Twilio SMS when a position closes.
    Only fires if notifications are enabled in app_state.
    Reads credentials from Railway environment variables.
    """
    try:
        # Check notification toggle
        db = get_database()
        setting = db.execute("SELECT value FROM app_state WHERE key='notify_on_close'").fetchone()
        db.close()
        if setting and setting["value"] == "false":
            return
    except:
        pass

    try:
        import os
        from twilio.rest import Client
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        to_number   = os.environ.get("TWILIO_TO_NUMBER")
        if not all([account_sid, auth_token, from_number, to_number]):
            log.warning("Twilio env vars not set — SMS skipped")
            return
        client = Client(account_sid, auth_token)
        sign = "+" if pnl_dollar >= 0 else ""
        time_str = close_time or current_time_cst().strftime("%I:%M %p")
        body = f"SwingDesk: {ticker} closed {sign}${pnl_dollar:.2f} ({sign}{pnl_pct:.1f}%) — {close_reason} {time_str}"
        client.messages.create(body=body, from_=from_number, to=to_number)
        log.info(f"SMS sent: {body}")
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
    Called after fetch_price_data during pre-market and post-market windows.

    Pre-market  (4:00-9:30 AM CST):
      - price      → fast_info.last_price (current pre-market price)
      - gap_percent → recalculated as (premarket_price - prev_close) / prev_close
      - day_change_percent → same as gap_percent in pre-market

    Post-market (4:00-8:00 PM CST):
      - price      → fast_info.last_price (current post-market price)
      - day_change_percent → recalculated as (postmarket_price - today_close) / today_close
      - gap_percent unchanged (gap already happened at today's open)

    Batches 10 tickers at a time with a small sleep to avoid rate limiting.
    Silently skips any ticker where fast_info is unavailable.
    """
    try:
        import yfinance as yf
        in_extended, in_premarket = is_extended_hours()
        if not in_extended:
            return  # Nothing to do during regular market hours

        log.info(f"Extended hours active — enriching {len(tickers)} tickers with live prices ({'pre' if in_premarket else 'post'}-market)")

        for i in range(0, len(tickers), 10):
            batch = tickers[i:i+10]
            for ticker in batch:
                if ticker not in price_data:
                    continue
                try:
                    fi = yf.Ticker(ticker).fast_info
                    live_price = fi.last_price
                    if not live_price or live_price != live_price:
                        continue
                    data = price_data[ticker]
                    prev_close = data.get("previous_close", live_price)
                    today_close = data.get("price", live_price)  # daily close before override

                    data["price"] = float(live_price)

                    if in_premarket:
                        # Gap is current pre-market price vs yesterday's close
                        new_gap = (live_price - prev_close) / max(prev_close, 0.01) * 100
                        data["gap_percent"] = round(new_gap, 4)
                        data["day_change_percent"] = round(new_gap, 4)
                    else:
                        # Post-market: day change vs today's regular-session close
                        new_change = (live_price - today_close) / max(today_close, 0.01) * 100
                        data["day_change_percent"] = round(new_change, 4)
                        # gap_percent unchanged — gap already happened at open

                    data["live_price_source"] = "fast_info"
                except:
                    pass
            time.sleep(0.2)

        log.info("Live price enrichment complete")
    except Exception as e:
        log.warning(f"Live price enrichment error: {e}")

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
    """
    if weights is None:
        weights = get_signal_weights()
    universe = build_ticker_universe()
    log.info(f"Comprehensive scan: {len(universe)} tickers ({scan_type})...")

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

    rsi_values = calculate_rsi_batch(list(price_data.keys()))
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
        buy_price = current_prices.get(ticker, pick.get("open_price", pick["price"]))
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

        existing.execute("""
            INSERT INTO virtual_trades
            (id, ticker, direction, buy_date, buy_time, buy_price, invested_amount,
             confidence, lock_in_confidence, expected_move, outcome, sector, reasoning, closed_days,
             status, current_value, intraday_high_pct, intraday_low_pct, queue_position,
             signal_scores)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [trade_id, ticker, direction, today, "08:45:00", buy_price,
              round(invested_amount, 4), confidence, confidence, expected_move, "open",
              get_sector(ticker), reasoning, closed_days,
              "open", round(invested_amount, 4), 0.0, 0.0, queue_id,
              _signal_scores_json])
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

        price = current_prices[ticker]

        # Stale price detection — if price is identical to last 3 consecutive checks
        # during market hours, skip sell decisions (possible halt or bad data)
        stale_key = f"stale_count_{ticker}"
        last_known = last_price_cache.get(ticker, {})
        last_price = last_known.get("price")
        stale_count = last_known.get("stale_count", 0)

        if last_price is not None and abs(price - last_price) < 0.001:
            stale_count += 1
        else:
            stale_count = 0

        database.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
            [f"last_monitor_price_{ticker}", json.dumps({"price": price, "stale_count": stale_count})])

        # Stale price guard — if price unchanged 3+ checks OR outside market hours,
        # skip all DB writes to preserve last known good P&L values.
        if stale_count >= 3 and is_market_open():
            log.warning(f"{ticker} price unchanged for {stale_count} checks — possible halt, freezing P&L")
            continue

        # Outside market hours (weekends, after-hours) — freeze P&L, no writes
        if not is_market_open():
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
        try:
            weights = get_signal_weights()
            earnings_soon = check_upcoming_earnings([ticker])
            price_data_for_dynamic = fetch_price_data([ticker])
            if ticker in price_data_for_dynamic:
                rsi_val = calculate_rsi_batch([ticker]).get(ticker, 50.0)
                dyn_conf = calculate_confidence_score(ticker, price_data_for_dynamic[ticker], rsi_val, earnings_soon, weights, position["direction"])
                dyn_est = estimate_overnight_move(price_data_for_dynamic[ticker], dyn_conf, ticker in earnings_soon)
            else:
                dyn_conf = position.get("dynamic_confidence") or position.get("confidence", 0)
                dyn_est = position.get("dynamic_estimate") or position.get("expected_move", 0)
        except:
            dyn_conf = position.get("dynamic_confidence") or position.get("confidence", 0)
            dyn_est = position.get("dynamic_estimate") or position.get("expected_move", 0)

        try:
            conf_data = calculate_method_confluence(ticker, {ticker: {"price": current_price, "volume_ratio": position.get("current_volume_ratio", 1), "gap_percent": 0, "day_change_percent": pnl_percent}})
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
                ticker, price_data_for_dynamic.get(ticker, {"price": price, "volume_ratio": 1.0, "gap_percent": 0}),
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
                signal_scores=?
                WHERE id=?
            """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2),
                  dyn_conf, round(dyn_est, 1), conf_count, conf_methods,
                  _signal_scores_json, position["id"]])
        except:
            database.execute("""
                UPDATE virtual_trades SET current_value=?, intraday_high_pct=?, intraday_low_pct=?
                WHERE id=?
            """, [round(current_value, 4), round(high_pct, 2), round(low_pct, 2), position["id"]])

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
        price = current_prices.get(ticker, position.get("buy_price", 0))
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
    schedule.every().day.at("23:55").do(run_audit_if_weekday)

    log.info("Scheduler started — comprehensive scans every 30min, 5-min position monitoring")

    # 5-minute monitoring loop runs inline with the scheduler
    last_monitor_time = 0
    while True:
        schedule.run_pending()
        current_time = time.time()

        # Run 5-minute monitoring during active hours (4 AM - 7 PM CST)
        if current_time - last_monitor_time >= MONITOR_INTERVAL:
            try:
                now = current_time_cst()
                if now.weekday() < 5 and 4 <= now.hour < 19:
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
    Return extended runner positions — trades the user is holding after the brain sold.
    Fetches current price from yfinance to calculate live user P&L vs brain P&L.
    """
    database = get_database()
    runners = database.execute(
        "SELECT * FROM extended_runners WHERE status='running' ORDER BY buy_date DESC"
    ).fetchall()
    database.close()

    if not runners:
        return jsonify([])

    tickers = [r["ticker"] for r in runners]
    price_data = fetch_price_data(tickers)
    result = []

    for runner in runners:
        ticker = runner["ticker"]
        current_price = price_data.get(ticker, {}).get("price", runner["current_price"] or runner["buy_price"])
        buy_price = runner["buy_price"] or 1
        current_pnl = (current_price - buy_price) / buy_price * 100
        invested = runner["invested_amount"] or 10
        current_value = invested * (1 + current_pnl / 100)

        result.append({
            **dict(runner),
            "current_price": round(current_price, 4),
            "current_pnl_percent": round(current_pnl, 2),
            "current_value": round(current_value, 4),
        })

        # Update DB with latest price
        database = get_database()
        database.execute(
            "UPDATE extended_runners SET current_price=?, current_pnl_percent=?, last_updated=? WHERE id=?",
            [round(current_price, 4), round(current_pnl, 2), current_time_cst().isoformat(), runner["id"]]
        )
        database.commit()
        database.close()

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
    total_predictions = database.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    resolved_count = database.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome!='pending'").fetchone()["n"]
    hit_count = database.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome='hit'").fetchone()["n"]
    miss_count = database.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome='miss'").fetchone()["n"]
    virtual_trade_count = database.execute("SELECT COUNT(*) as n FROM virtual_trades").fetchone()["n"]
    open_position_count = database.execute("SELECT COUNT(*) as n FROM virtual_trades WHERE outcome='open'").fetchone()["n"]
    last_audit = database.execute("SELECT value FROM app_state WHERE key='last_audit'").fetchone()
    last_scan = database.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    database.close()

    return jsonify({
        "total_predictions": total_predictions,
        "resolved": resolved_count,
        "hits": hit_count,
        "misses": miss_count,
        "win_rate": round(hit_count / resolved_count * 100, 1) if resolved_count else None,
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
    """Return latest prices for VIX, SPY, QQQ + any open position tickers."""
    try:
        import yfinance as yf
        database = get_database()
        open_tickers = [r["ticker"] for r in database.execute(
            "SELECT ticker FROM virtual_trades WHERE outcome='open'"
        ).fetchall()]
        database.close()

        base = ["VIX", "SPY", "QQQ", "IWM", "NVDA", "TLT", "BTC-USD", "GLD"]
        all_tickers = list(dict.fromkeys(base + open_tickers))

        raw = yf.download(all_tickers, period="5d", interval="1d",
                          auto_adjust=True, progress=False)

        results = {}
        for ticker in all_tickers:
            try:
                if len(all_tickers) == 1:
                    close = raw["Close"].dropna()
                    prev = raw["Close"].dropna()
                else:
                    close = raw["Close"][ticker].dropna()
                    prev = raw["Close"][ticker].dropna()

                if len(close) < 2:
                    continue

                price = float(close.iloc[-1])
                prev_close = float(close.iloc[-2])
                change = price - prev_close
                change_pct = (change / prev_close) * 100

                results[ticker] = {
                    "price": round(price, 2),
                    "prev_close": round(prev_close, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                }
            except Exception as e:
                log.warning(f"Banner price error for {ticker}: {e}")

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
        return jsonify({"notify_on_close": enabled})
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
        import os
        from twilio.rest import Client
        account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
        auth_token  = os.environ.get("TWILIO_AUTH_TOKEN")
        from_number = os.environ.get("TWILIO_FROM_NUMBER")
        to_number   = os.environ.get("TWILIO_TO_NUMBER")
        if not all([account_sid, auth_token, from_number, to_number]):
            return jsonify({"success": False, "error": "Twilio env vars not configured in Railway"}), 400
        client = Client(account_sid, auth_token)
        body = "SwingDesk: Test notification working. You'll be notified on cut, force close, and overnight reversal."
        message = client.messages.create(body=body, from_=from_number, to=to_number)
        log.info(f"Test notification sent: {message.sid}")
        return jsonify({"success": True, "sid": message.sid})
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
threading.Thread(target=run_scheduler, daemon=True).start()
threading.Thread(target=keep_server_alive, daemon=True).start()
log.info("Brain v4 initialized — full trading engine with self-regulating queue system")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
