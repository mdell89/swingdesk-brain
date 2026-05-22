"""
brain.py — Overnight Swing Desk Backend
Run: python brain.py
Serves on http://localhost:5000
"""

import os, json, sqlite3, time, logging, threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import anthropic

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────
ANTHROPIC_KEY = os.getenv("ANTHROPIC_KEY") or os.getenv("ANTHROPIC_API_KEY")
AV_KEY        = os.getenv("ALPHA_VANTAGE_KEY")
DB_PATH       = Path(__file__).parent / "portfolio_brain.db"
FEE_PER_TRADE = 0.02
INVEST_PER_PICK = 10.00
MIN_EXPECTED_MOVE = 5.0
MAX_PICKS = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)


# ── UNIVERSE ──────────────────────────────────────────────────────────────────
UNIVERSE_TICKERS = [
    "NVDA","META","AMD","TSLA","AMZN","MSFT","PLTR","SOFI","MSTR","JPM",
    "BAC","COIN","GOOGL","AAPL","NFLX","PYPL","HOOD","RBLX","SNAP","UBER",
    "LYFT","RIVN","LCID","GME","AMC","CVNA","SMCI","IONQ","XOM","RGTI",
    "INTC","MU","QCOM","ARM","AVGO","TSM","ORCL","CRM","SNOW","DDOG",
    "NET","CRWD","ZS","OKTA","PANW","SHOP","ROKU","SPOT",
    "ABNB","UBER","DASH","LYFT",
    "GME","AMC","BBBY","MEME","BB","NOK","SNDL","TLRY","ACB","CRON",
    "SPY","QQQ","IWM","ARKK","ARKG","ARKF","ARKW","ARKQ","ARKX","PRNT",
]
# Deduplicate
UNIVERSE_TICKERS = list(dict.fromkeys(UNIVERSE_TICKERS))

SECTOR_MAP = {
    "NVDA":"Tech","META":"Tech","AMD":"Tech","TSLA":"Tech","AMZN":"Consumer",
    "MSFT":"Tech","PLTR":"Tech","SOFI":"Finance","MSTR":"Finance","JPM":"Finance",
    "BAC":"Finance","COIN":"Finance","GOOGL":"Tech","AAPL":"Tech","NFLX":"Consumer",
    "PYPL":"Finance","HOOD":"Finance","RBLX":"Consumer","SNAP":"Tech","UBER":"Consumer",
    "LYFT":"Consumer","RIVN":"Tech","LCID":"Tech","GME":"Consumer","AMC":"Consumer",
    "CVNA":"Consumer","SMCI":"Tech","IONQ":"Tech","XOM":"Energy","RGTI":"Tech",
    "INTC":"Tech","MU":"Tech","QCOM":"Tech","ARM":"Tech","AVGO":"Tech",
    "TSM":"Tech","ORCL":"Tech","CRM":"Tech","SNOW":"Tech","DDOG":"Tech",
    "NET":"Tech","CRWD":"Tech","ZS":"Tech","PANW":"Tech","SHOP":"Consumer",
    "SQ":"Finance","ROKU":"Tech","SPOT":"Consumer","ABNB":"Consumer","DASH":"Consumer",
    "SPY":"ETF","QQQ":"ETF","IWM":"ETF","ARKK":"ETF","ARKG":"ETF",
}

# ── DATABASE ──────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY,
            ticker TEXT NOT NULL,
            name TEXT,
            date TEXT NOT NULL,
            direction TEXT NOT NULL,
            conf INTEGER,
            expected_move REAL,
            entry_price REAL,
            sell_time TEXT,
            reasoning TEXT,
            sector TEXT,
            rsi REAL,
            vol_ratio REAL,
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
            invested REAL DEFAULT 10.0,
            current_value REAL,
            conf INTEGER,
            expected_move REAL,
            actual_move REAL,
            gross_pnl REAL,
            net_pnl REAL,
            fee REAL DEFAULT 0.02,
            outcome TEXT DEFAULT 'open',
            sector TEXT,
            reasoning TEXT
        );

        CREATE TABLE IF NOT EXISTS weights_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            rsi_momentum REAL,
            volume_surge REAL,
            overnight_gap_prob REAL,
            earnings_catalyst REAL,
            sector_rotation REAL,
            win_rate REAL,
            total_resolved INTEGER,
            audit_reasoning TEXT
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            weights_before TEXT,
            weights_after TEXT,
            reasoning TEXT,
            summary TEXT,
            total_predictions INTEGER,
            resolved INTEGER,
            hits INTEGER,
            misses INTEGER,
            win_rate REAL
        );

        CREATE TABLE IF NOT EXISTS portfolio (
            ticker TEXT PRIMARY KEY,
            name TEXT,
            shares REAL,
            cost_basis REAL,
            current_price REAL,
            held_days INTEGER DEFAULT 0,
            sector TEXT,
            added_at TEXT
        );

        CREATE TABLE IF NOT EXISTS perf_history (
            date TEXT PRIMARY KEY,
            virtual_gross REAL,
            virtual_net REAL,
            real_value REAL,
            daily_pnl REAL,
            daily_trades INTEGER
        );

        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    # Seed default weights if not set
    existing = c.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
    if not existing:
        default_weights = {
            "rsi_momentum": 0.20,
            "volume_surge": 0.22,
            "overnight_gap_prob": 0.25,
            "earnings_catalyst": 0.18,
            "sector_rotation": 0.15
        }
        c.execute("INSERT INTO app_state VALUES ('weights', ?)", [json.dumps(default_weights)])
    conn.commit()
    conn.close()
    log.info(f"Database ready at {DB_PATH}")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def get_weights():
    conn = get_db()
    row = conn.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
    conn.close()
    return json.loads(row["value"]) if row else {
        "rsi_momentum":0.20,"volume_surge":0.22,"overnight_gap_prob":0.25,
        "earnings_catalyst":0.18,"sector_rotation":0.15
    }

def save_weights(w):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO app_state VALUES ('weights', ?)", [json.dumps(w)])
    conn.commit()
    conn.close()

# ── PRICE DATA — FALLBACK CHAIN ───────────────────────────────────────────────
def fetch_price_data(tickers):
    """Fetch price data with fallback chain: yfinance → Alpha Vantage → cache"""
    results = {}

    # 1. Try yfinance (primary)
    try:
        import yfinance as yf
        log.info(f"Fetching {len(tickers)} tickers via yfinance...")
        batch = yf.download(
            tickers, period="5d", interval="1d",
            group_by="ticker", auto_adjust=True, progress=False, threads=True
        )
        for ticker in tickers:
            try:
                if len(tickers) == 1:
                    df = batch
                else:
                    df = batch[ticker] if ticker in batch.columns.get_level_values(0) else None
                if df is not None and len(df) >= 2:
                    prev_close = float(df["Close"].iloc[-2])
                    last_close = float(df["Close"].iloc[-1])
                    open_price = float(df["Open"].iloc[-1])   # today's open
                    volume     = float(df["Volume"].iloc[-1])
                    avg_vol    = float(df["Volume"].mean())
                    high       = float(df["High"].iloc[-1])
                    low        = float(df["Low"].iloc[-1])
                    results[ticker] = {
                        "price": last_close,
                        "open": open_price,
                        "prev_close": prev_close,
                        "overnight_gap_pct": ((open_price - prev_close) / prev_close * 100) if prev_close else 0,
                        "volume": volume,
                        "avg_volume": avg_vol,
                        "vol_ratio": (volume / avg_vol) if avg_vol else 1,
                        "high": high,
                        "low": low,
                        "source": "yfinance"
                    }
            except Exception as e:
                log.warning(f"yfinance parse error {ticker}: {e}")
        log.info(f"yfinance returned {len(results)}/{len(tickers)} tickers")
    except Exception as e:
        log.error(f"yfinance failed: {e}")

    # 2. Alpha Vantage fallback for missing tickers
    missing = [t for t in tickers if t not in results]
    if missing and AV_KEY:
        import urllib.request
        log.info(f"Alpha Vantage fallback for {len(missing)} tickers...")
        for ticker in missing[:10]:  # AV rate limit: be conservative
            try:
                url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={AV_KEY}"
                with urllib.request.urlopen(url, timeout=5) as r:
                    data = json.loads(r.read())
                q = data.get("Global Quote", {})
                if q.get("05. price"):
                    price = float(q["05. price"])
                    prev  = float(q["08. previous close"])
                    results[ticker] = {
                        "price": price,
                        "prev_close": prev,
                        "overnight_gap_pct": ((price - prev) / prev * 100) if prev else 0,
                        "volume": float(q.get("06. volume", 0)),
                        "avg_volume": float(q.get("06. volume", 0)),
                        "vol_ratio": 1.0,
                        "high": float(q.get("03. high", price)),
                        "low": float(q.get("04. low", price)),
                        "source": "alpha_vantage"
                    }
                time.sleep(0.5)  # AV rate limit
            except Exception as e:
                log.warning(f"Alpha Vantage error {ticker}: {e}")

    # 3. Cache fallback for still-missing tickers
    still_missing = [t for t in tickers if t not in results]
    if still_missing:
        conn = get_db()
        for ticker in still_missing:
            cached = conn.execute(
                "SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]
            ).fetchone()
            if cached:
                d = json.loads(cached["value"])
                d["source"] = "cache"
                results[ticker] = d
        conn.close()

    # 4. Save fresh results to cache
    conn = get_db()
    for ticker, data in results.items():
        conn.execute(
            "INSERT OR REPLACE INTO app_state VALUES (?, ?)",
            [f"cache_{ticker}", json.dumps(data)]
        )
    conn.commit()
    conn.close()

    return results

# ── RSI CALCULATION ───────────────────────────────────────────────────────────
def calc_rsi(ticker, period=14):
    """Calculate RSI for a ticker using yfinance"""
    try:
        import yfinance as yf
        df = yf.download(ticker, period="60d", interval="1d", auto_adjust=True, progress=False)
        if len(df) < period + 1:
            return 50.0
        delta = df["Close"].diff()
        gain  = delta.clip(lower=0).rolling(period).mean()
        loss  = (-delta.clip(upper=0)).rolling(period).mean()
        rs    = gain / loss
        rsi   = 100 - (100 / (1 + rs))
        val   = float(rsi.iloc[-1])
        return val if not (val != val) else 50.0  # NaN check
    except:
        return 50.0

# ── EARNINGS CALENDAR ─────────────────────────────────────────────────────────
def get_earnings_soon(tickers):
    """Check which tickers have earnings in next 3 days"""
    earnings_soon = set()
    try:
        import yfinance as yf
        for ticker in tickers[:30]:  # limit API calls
            try:
                t = yf.Ticker(ticker)
                cal = t.calendar
                if cal is not None and not cal.empty:
                    earn_date = cal.iloc[0].get("Earnings Date")
                    if earn_date:
                        days_out = (earn_date - datetime.now()).days
                        if 0 <= days_out <= 3:
                            earnings_soon.add(ticker)
            except:
                pass
    except Exception as e:
        log.warning(f"Earnings calendar error: {e}")
    return earnings_soon

# ── SCORING ENGINE ─────────────────────────────────────────────────────────────
def score_candidate(ticker, price_data, rsi, earnings_soon, weights, direction="long"):
    w = weights
    # NaN guards
    rsi = rsi if rsi == rsi else 50.0

    # RSI signal
    if direction == "long":
        rsi_score = 1.0 if 40 <= rsi <= 65 else (0.9 if rsi < 40 else 0.5)
    else:
        rsi_score = 1.0 if rsi > 65 else (0.7 if rsi > 55 else 0.4)

    # Volume surge
    vol_ratio = price_data.get("vol_ratio", 1.0)
    vol_ratio = vol_ratio if vol_ratio == vol_ratio else 1.0
    vol_score = min(vol_ratio / 3.5, 1.0)

    # Overnight gap probability
    gap_pct = price_data.get("overnight_gap_pct", 0)
    gap_pct = gap_pct if gap_pct == gap_pct else 0.0
    gap_score = min(abs(gap_pct) / 10.0, 1.0)
    if direction == "short":
        gap_score = gap_score if gap_pct < 0 else gap_score * 0.5

    # Earnings catalyst
    earn_score = 0.9 if ticker in earnings_soon else 0.6

    # Sector rotation
    sector = SECTOR_MAP.get(ticker, "Other")
    sec_score = 0.85 if sector in ["Tech", "Finance"] else 0.7

    raw = (rsi_score * w["rsi_momentum"] +
           vol_score * w["volume_surge"] +
           gap_score * w["overnight_gap_prob"] +
           earn_score * w["earnings_catalyst"] +
           sec_score * w["sector_rotation"])

    return min(int(raw * 115), 96)

def estimated_move(price_data, conf, earnings_soon_flag):
    base = 4 + (conf - 60) * 0.25
    vol_bonus = (price_data.get("vol_ratio", 1) - 1) * 1.5
    earn_bonus = 3 if earnings_soon_flag else 0
    gap_boost  = min(abs(price_data.get("overnight_gap_pct", 0)) * 0.3, 3)
    return round(min(base + vol_bonus + earn_bonus + gap_boost, 25), 1)

def sell_time_cst(conf):
    if conf >= 85: return "8:45–9:30 AM"
    if conf >= 75: return "9:30–10:30 AM"
    if conf >= 65: return "10:30–12 PM"
    return "12–1:30 PM"

def build_reasoning(ticker, price_data, rsi, conf, earnings_soon_flag, direction):
    parts = []
    if direction == "long":
        if rsi < 45: parts.append(f"RSI {rsi:.0f} oversold")
        elif rsi > 60: parts.append(f"RSI {rsi:.0f} momentum intact")
        else: parts.append(f"RSI {rsi:.0f} neutral")
    else:
        parts.append(f"RSI {rsi:.0f} overbought" if rsi > 65 else f"RSI {rsi:.0f} weakening")
    vol = price_data.get("vol_ratio", 1)
    if vol > 1.8: parts.append(f"{vol:.1f}x vol surge")
    gap = price_data.get("overnight_gap_pct", 0)
    if abs(gap) > 2: parts.append(f"{gap:+.1f}% overnight gap")
    if earnings_soon_flag: parts.append("earnings catalyst")
    return " · ".join(parts[:3])

def sentiment_for_position(current_pct):
    if current_pct >= 8:  return {"icon":"⚡","label":"Sell early — target nearly hit","color":"amber"}
    if current_pct >= 5:  return {"icon":"✓","label":"Hold window — on track","color":"green"}
    if current_pct >= 2:  return {"icon":"✓","label":"Hold window — momentum intact","color":"green"}
    if current_pct >= 0:  return {"icon":"⚠","label":"Consider selling — weak move","color":"amber"}
    return {"icon":"✕","label":"Sell now — reversal signal","color":"red"}

# ── GENERATE PICKS ─────────────────────────────────────────────────────────────
def generate_picks(weights=None):
    if weights is None:
        weights = get_weights()

    log.info("Generating picks — fetching price data...")
    price_data = fetch_price_data(UNIVERSE_TICKERS)
    earnings_soon = get_earnings_soon(UNIVERSE_TICKERS)

    scored = []
    for ticker in UNIVERSE_TICKERS:
        if ticker not in price_data:
            continue
        pd = price_data[ticker]
        rsi = calc_rsi(ticker)
        price = pd["price"]

        long_conf = score_candidate(ticker, pd, rsi, earnings_soon, weights, "long")
        long_move = estimated_move(pd, long_conf, ticker in earnings_soon)

        short_conf = score_candidate(ticker, pd, rsi, earnings_soon, weights, "short")
        short_move = estimated_move(pd, short_conf, ticker in earnings_soon)

        scored.append({
            "ticker": ticker,
            "name": ticker,
            "sector": SECTOR_MAP.get(ticker, "Other"),
            "price": price,
            "open_price": pd.get("open", price),
            "prev_close": pd.get("prev_close", price),
            "rsi": round(rsi, 1),
            "vol_ratio": round(pd.get("vol_ratio", 1), 2),
            "overnight_gap_pct": round(pd.get("overnight_gap_pct", 0), 2),
            "earnings_soon": ticker in earnings_soon,
            "long_conf": long_conf,
            "long_move": long_move,
            "long_reasoning": build_reasoning(ticker, pd, rsi, long_conf, ticker in earnings_soon, "long"),
            "short_conf": short_conf,
            "short_move": short_move,
            "short_reasoning": build_reasoning(ticker, pd, rsi, short_conf, ticker in earnings_soon, "short"),
            "sell_time": sell_time_cst(long_conf),
            "data_source": pd.get("source", "unknown"),
        })

    longs  = [s for s in sorted(scored, key=lambda x: x["long_conf"], reverse=True)  if s["long_move"]  >= MIN_EXPECTED_MOVE]
    shorts = [s for s in sorted(scored, key=lambda x: x["short_conf"], reverse=True) if s["short_move"] >= MIN_EXPECTED_MOVE]

    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_db()

    # Log predictions to DB
    for i, pick in enumerate(longs[:MAX_PICKS] + shorts[:10]):
        direction = "long" if i < MAX_PICKS else "short"
        conf  = pick["long_conf"]  if direction == "long" else pick["short_conf"]
        move  = pick["long_move"]  if direction == "long" else pick["short_move"]
        reason = pick["long_reasoning"] if direction == "long" else pick["short_reasoning"]
        pred_id = f"{pick['ticker']}_{today}_{direction}"
        existing = conn.execute("SELECT id FROM predictions WHERE id=?", [pred_id]).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO predictions (id,ticker,name,date,direction,conf,expected_move,
                entry_price,sell_time,reasoning,sector,rsi,vol_ratio,weights_snapshot,logged_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, [pred_id, pick["ticker"], pick["name"], today, direction, conf, move,
                  pick["price"], pick["sell_time"], reason, pick["sector"],
                  pick["rsi"], pick["vol_ratio"], json.dumps(weights),
                  datetime.now().isoformat()])

        # Virtual trade for ALL picks meeting threshold
        # Buy price = today's open (simulating entry at 9:45 AM CST, 15 min after open)
        buy_price = pick.get("open_price", pick["price"])  # open price if available
        vt_id = f"{pick['ticker']}_{today}_{direction}_vt"
        existing_vt = conn.execute("SELECT id FROM virtual_trades WHERE id=?", [vt_id]).fetchone()
        if not existing_vt:
            conn.execute("""
                INSERT INTO virtual_trades (id,ticker,direction,buy_date,buy_time,buy_price,
                invested,conf,expected_move,outcome,sector,reasoning)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, [vt_id, pick["ticker"], direction, today,
                  "09:45:00", buy_price,
                  INVEST_PER_PICK, conf, move, "open",
                  pick["sector"], reason])
        else:
            # Backfill: update existing trades that used close price to use open price
            conn.execute("""
                UPDATE virtual_trades SET buy_price=?, buy_time='09:45:00'
                WHERE id=? AND buy_time != '09:45:00'
            """, [buy_price, vt_id])

    conn.commit()
    conn.close()

    return {
        "longs": longs[:MAX_PICKS],
        "shorts": shorts[:10],
        "all_virtual": scored,
        "generated_at": datetime.now().isoformat(),
        "data_sources": list(set(s["data_source"] for s in scored)),
    }

# ── AUTO-SCORE YESTERDAY'S VIRTUAL TRADES ─────────────────────────────────────
def score_yesterday_trades():
    """Fetch actual prices and auto-score open virtual trades from yesterday"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    conn = get_db()
    open_trades = conn.execute(
        "SELECT * FROM virtual_trades WHERE buy_date=? AND outcome='open'", [yesterday]
    ).fetchall()
    conn.close()

    if not open_trades:
        log.info("No open trades to score from yesterday")
        return

    tickers = list(set(t["ticker"] for t in open_trades))
    log.info(f"Scoring {len(open_trades)} yesterday trades for {len(tickers)} tickers...")
    price_data = fetch_price_data(tickers)

    conn = get_db()
    scored = 0
    for trade in open_trades:
        ticker = trade["ticker"]
        if ticker not in price_data:
            continue
        current_price = price_data[ticker]["price"]
        buy_price     = trade["buy_price"]
        invested      = trade["invested"]

        pct       = (current_price - buy_price) / buy_price * 100
        gross_pnl = invested * (pct / 100)
        net_pnl   = gross_pnl - FEE_PER_TRADE

        if trade["direction"] == "long":
            outcome = "hit" if pct >= MIN_EXPECTED_MOVE else ("partial" if pct > 0 else "miss")
        else:
            outcome = "hit" if pct <= -MIN_EXPECTED_MOVE else ("partial" if pct < 0 else "miss")

        conn.execute("""
            UPDATE virtual_trades SET sell_date=?, sell_price=?, current_value=?,
            actual_move=?, gross_pnl=?, net_pnl=?, outcome=?, sell_time=?
            WHERE id=?
        """, [datetime.now().strftime("%Y-%m-%d"), current_price,
              invested + gross_pnl, round(pct, 2), round(gross_pnl, 4),
              round(net_pnl, 4), outcome,
              datetime.now().strftime("%H:%M:%S"), trade["id"]])

        # Also update prediction outcome
        pred_id = f"{ticker}_{yesterday}_{trade['direction']}"
        conn.execute("""
            UPDATE predictions SET outcome=?, actual_move=?, actual_sell_price=?,
            gross_pnl=?, net_pnl=?, resolved_at=? WHERE id=?
        """, [outcome, round(pct, 2), current_price,
              round(gross_pnl, 4), round(net_pnl, 4),
              datetime.now().isoformat(), pred_id])

        scored += 1

    conn.commit()
    conn.close()
    log.info(f"Scored {scored} trades")

# ── SELF-AUDIT ENGINE ──────────────────────────────────────────────────────────
def run_audit():
    """Call Claude API to analyze prediction history and update weights"""
    log.info("Running self-audit...")
    conn = get_db()
    preds     = conn.execute("SELECT * FROM predictions WHERE outcome != 'pending' ORDER BY date DESC LIMIT 200").fetchall()
    all_preds = conn.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    conn.close()

    resolved = [dict(p) for p in preds]
    hits     = [p for p in resolved if p["outcome"] == "hit"]
    misses   = [p for p in resolved if p["outcome"] == "miss"]
    partials = [p for p in resolved if p["outcome"] == "partial"]
    win_rate = len(hits) / len(resolved) if resolved else None

    current_weights = get_weights()

    # Sector accuracy
    sector_acc = {}
    for p in resolved:
        s = p.get("sector", "Other")
        if s not in sector_acc: sector_acc[s] = {"hits": 0, "total": 0}
        sector_acc[s]["total"] += 1
        if p["outcome"] == "hit": sector_acc[s]["hits"] += 1

    digest = {
        "total_predictions": all_preds,
        "resolved": len(resolved),
        "hits": len(hits),
        "misses": len(misses),
        "partials": len(partials),
        "win_rate": win_rate,
        "current_weights": current_weights,
        "sector_accuracy": sector_acc,
        "high_conf_miss_rate": len([p for p in resolved if p["conf"] >= 80 and p["outcome"] == "miss"]) / max(len([p for p in resolved if p["conf"] >= 80]), 1),
        "sample_hits":   [{"t": p["ticker"], "c": p["conf"], "r": p["rsi"], "v": p["vol_ratio"], "s": p["sector"]} for p in hits[:5]],
        "sample_misses": [{"t": p["ticker"], "c": p["conf"], "r": p["rsi"], "v": p["vol_ratio"], "s": p["sector"]} for p in misses[:5]],
    }

    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    prompt = f"""You are the self-audit engine for an overnight swing trading prediction app.

The app predicts which stocks will move 5%+ overnight (buy at open, sell next day).
It screens ~80 tickers daily, generates picks, executes virtual $10 trades, and learns from outcomes.
Goal: maximize predictions hitting 5%+ overnight move. Equal weight on frequency of gains vs magnitude.

CURRENT WEIGHTS (must sum to 1.0):
{json.dumps(current_weights, indent=2)}

PERFORMANCE DATA:
{json.dumps(digest, indent=2)}

INSTRUCTIONS:
1. If resolved < 10: make small exploratory adjustments (+/- 0.02-0.03), note "insufficient data"
2. If resolved >= 10: analyze which signals correlate with hits vs misses
3. Consider: high-conf misses = overweighted signals; low-conf hits = underweighted
4. Sector accuracy reveals which sectors are actually predictable overnight
5. Weights must sum to exactly 1.0, each between 0.05 and 0.45
6. Be terse — trading desk style reasoning

Respond ONLY with valid JSON:
{{
  "weights": {{"rsi_momentum": 0.XX, "volume_surge": 0.XX, "overnight_gap_prob": 0.XX, "earnings_catalyst": 0.XX, "sector_rotation": 0.XX}},
  "reasoning": ["line1", "line2", "line3"],
  "summary": "one terse sentence",
  "confidence": "low|medium|high"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        raw    = response.content[0].text
        clean  = raw.replace("```json", "").replace("```", "").strip()
        result = json.loads(clean)

        new_weights = result["weights"]
        total = sum(new_weights.values())
        if 0.85 < total < 1.15:
            factor = 1.0 / total
            new_weights = {k: round(v * factor, 4) for k, v in new_weights.items()}
            save_weights(new_weights)
            log.info(f"Weights updated: {new_weights}")
        else:
            log.warning(f"Invalid weight sum {total}, keeping current weights")
            new_weights = current_weights

        # Log audit
        conn = get_db()
        conn.execute("""
            INSERT INTO audit_log (timestamp,weights_before,weights_after,reasoning,summary,
            total_predictions,resolved,hits,misses,win_rate)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, [datetime.now().isoformat(), json.dumps(current_weights), json.dumps(new_weights),
              json.dumps(result.get("reasoning", [])), result.get("summary", ""),
              all_preds, len(resolved), len(hits), len(misses), win_rate])

        # Save weights history
        conn.execute("""
            INSERT INTO weights_history (timestamp,rsi_momentum,volume_surge,overnight_gap_prob,
            earnings_catalyst,sector_rotation,win_rate,total_resolved,audit_reasoning)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, [datetime.now().isoformat(),
              new_weights["rsi_momentum"], new_weights["volume_surge"],
              new_weights["overnight_gap_prob"], new_weights["earnings_catalyst"],
              new_weights["sector_rotation"], win_rate, len(resolved),
              json.dumps(result.get("reasoning", []))])

        conn.execute("INSERT OR REPLACE INTO app_state VALUES ('last_audit', ?)",
                     [datetime.now().isoformat()])
        conn.commit()
        conn.close()

        return {
            "success": True,
            "weights": new_weights,
            "reasoning": result.get("reasoning", []),
            "summary": result.get("summary", ""),
            "confidence": result.get("confidence", "medium"),
            "stats": {"hits": len(hits), "misses": len(misses), "win_rate": win_rate}
        }

    except Exception as e:
        log.error(f"Audit error: {e}")
        return {"success": False, "error": str(e)}

# ── API ROUTES ─────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

@app.route("/api/picks")
def api_picks():
    try:
        weights = get_weights()
        picks   = generate_picks(weights)
        return jsonify(picks)
    except Exception as e:
        log.error(f"Picks error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/weights")
def api_weights():
    return jsonify(get_weights())

@app.route("/api/predictions")
def api_predictions():
    conn  = get_db()
    preds = conn.execute("SELECT * FROM predictions ORDER BY logged_at DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify([dict(p) for p in preds])

@app.route("/api/predictions/<pred_id>/outcome", methods=["POST"])
def api_update_outcome(pred_id):
    data    = request.json
    outcome = data.get("outcome")
    if outcome not in ["hit", "miss", "partial"]:
        return jsonify({"error": "invalid outcome"}), 400
    conn = get_db()
    conn.execute("UPDATE predictions SET outcome=?, resolved_at=? WHERE id=?",
                 [outcome, datetime.now().isoformat(), pred_id])
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/virtual-trades")
def api_virtual_trades():
    conn   = get_db()
    trades = conn.execute("SELECT * FROM virtual_trades ORDER BY buy_date DESC LIMIT 500").fetchall()
    conn.close()
    return jsonify([dict(t) for t in trades])

@app.route("/api/portfolio")
def api_portfolio():
    conn      = get_db()
    portfolio = conn.execute("SELECT * FROM portfolio").fetchall()
    conn.close()
    return jsonify([dict(p) for p in portfolio])

@app.route("/api/portfolio", methods=["POST"])
def api_add_position():
    data = request.json
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO portfolio (ticker,name,shares,cost_basis,current_price,held_days,sector,added_at)
        VALUES (?,?,?,?,?,?,?,?)
    """, [data["ticker"], data.get("name", data["ticker"]), data["shares"],
          data["cost"], data["price"], data.get("held", 1),
          data.get("sector", "Other"), datetime.now().isoformat()])
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/audit", methods=["POST"])
def api_audit():
    result = run_audit()
    return jsonify(result)

@app.route("/api/audit/log")
def api_audit_log():
    conn = get_db()
    logs = conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 30").fetchall()
    conn.close()
    return jsonify([dict(l) for l in logs])

@app.route("/api/score-yesterday", methods=["POST"])
def api_score_yesterday():
    score_yesterday_trades()
    return jsonify({"success": True})

@app.route("/api/perf-history")
def api_perf_history():
    conn = get_db()
    # Build from virtual trades
    rows = conn.execute("""
        SELECT buy_date as date,
               SUM(CASE WHEN outcome='open' THEN invested ELSE current_value END) as value,
               SUM(COALESCE(gross_pnl,0)) as daily_pnl,
               COUNT(*) as trades
        FROM virtual_trades
        GROUP BY buy_date
        ORDER BY buy_date ASC
    """).fetchall()
    conn.close()

    history = []
    running = 1000.0
    for row in rows:
        running += float(row["daily_pnl"] or 0)
        history.append({
            "date": row["date"],
            "virtual": round(running, 2),
            "daily_pnl": round(float(row["daily_pnl"] or 0), 4),
            "trades": row["trades"]
        })
    return jsonify(history)

@app.route("/api/stats")
def api_stats():
    conn = get_db()
    total_preds  = conn.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    resolved     = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome != 'pending'").fetchone()["n"]
    hits         = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome='hit'").fetchone()["n"]
    misses       = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome='miss'").fetchone()["n"]
    vt_total     = conn.execute("SELECT COUNT(*) as n FROM virtual_trades").fetchone()["n"]
    vt_open      = conn.execute("SELECT COUNT(*) as n FROM virtual_trades WHERE outcome='open'").fetchone()["n"]
    last_audit   = conn.execute("SELECT value FROM app_state WHERE key='last_audit'").fetchone()
    weights      = get_weights()
    conn.close()

    return jsonify({
        "total_predictions": total_preds,
        "resolved": resolved,
        "hits": hits,
        "misses": misses,
        "win_rate": round(hits / resolved * 100, 1) if resolved else None,
        "virtual_trades": vt_total,
        "virtual_open": vt_open,
        "last_audit": last_audit["value"] if last_audit else None,
        "weights": weights,
    })

# ── BACKGROUND SCHEDULER ───────────────────────────────────────────────────────
def scheduler():
    """Run background tasks on schedule"""
    import schedule

    def morning_run():
        log.info("=== Morning run: scoring yesterday + generating picks ===")
        score_yesterday_trades()
        generate_picks()

    def daily_audit():
        log.info("=== Daily audit ===")
        run_audit()

    schedule.every().day.at("08:30").do(morning_run)
    schedule.every().day.at("09:00").do(daily_audit)

    while True:
        schedule.run_pending()
        time.sleep(60)

# ── MAIN ───────────────────────────────────────────────────────────────────────
init_db()
if __name__ == "__main__":
    if not ANTHROPIC_KEY:
        log.warning("No ANTHROPIC_API_KEY found in .env — audit engine will not work")
    if not AV_KEY:
        log.warning("No ALPHA_VANTAGE_KEY found in .env — fallback chain limited")

    init_db()

    # Start scheduler in background thread
    try:
        import schedule
        t = threading.Thread(target=scheduler, daemon=True)
        t.start()
        log.info("Background scheduler started")
    except ImportError:
        log.warning("schedule not installed — auto-scheduling disabled")

    log.info("Starting Overnight Swing Desk backend on http://localhost:5000")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
