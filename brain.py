"""
brain.py — Overnight Swing Desk Backend v3
Foundation: cached picks, ~1500 tickers, scan schedule, schema upgrades
"""

import os, json, sqlite3, time, logging, threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_KEY   = os.getenv("ANTHROPIC_KEY") or os.getenv("ANTHROPIC_API_KEY")
AV_KEY          = os.getenv("ALPHA_VANTAGE_KEY")
DB_PATH         = Path(__file__).parent / "portfolio_brain.db"
FEE_PER_TRADE   = 0.02
INVEST_PER_PICK = 10.00
MIN_MOVE        = 5.0
MAX_PICKS       = 20

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# ── UNIVERSE — ~1500 tickers ──────────────────────────────────────────────────
def fetch_sp500():
    """Fetch S&P 500 tickers from Wikipedia"""
    try:
        import urllib.request
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        with urllib.request.urlopen(url, timeout=10) as r:
            html = r.read().decode()
        tickers = []
        rows = html.split("<tbody>")[1].split("</tbody>")[0].split("<tr>")
        for row in rows[1:]:
            cells = row.split("<td>")
            if len(cells) > 1:
                ticker = cells[1].split("</td>")[0].split(">")[-1].strip()
                if ticker and ticker.isalpha():
                    tickers.append(ticker.replace(".", "-"))
        log.info(f"Fetched {len(tickers)} S&P 500 tickers")
        return tickers
    except Exception as e:
        log.warning(f"Could not fetch S&P 500 list: {e}")
        return []

def fetch_nasdaq100():
    """Fetch Nasdaq 100 tickers"""
    try:
        import urllib.request
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        with urllib.request.urlopen(url, timeout=10) as r:
            html = r.read().decode()
        tickers = []
        rows = html.split("<tbody>")[1].split("</tbody>")[0].split("<tr>")
        for row in rows[1:]:
            cells = row.split("<td>")
            if len(cells) > 1:
                ticker = cells[1].split("</td>")[0].split(">")[-1].strip()
                if ticker and len(ticker) <= 5:
                    tickers.append(ticker.replace(".", "-"))
        log.info(f"Fetched {len(tickers)} Nasdaq 100 tickers")
        return tickers
    except Exception as e:
        log.warning(f"Could not fetch Nasdaq 100 list: {e}")
        return []

# High-volatility additions that may not be in indices
EXTRA_TICKERS = [
    "GME","AMC","BB","NOK","SOFI","MSTR","CVNA","HOOD","RBLX","SNAP",
    "RIVN","LCID","IONQ","RGTI","COIN","PLTR","SMCI","SNDL","TLRY",
    "OPEN","CLOV","WISH","SPCE","LAZR","MARA","RIOT","BITF","HUT",
    "UPST","AFRM","DKNG","PENN","RSI","STEM","PLUG","FCEL","BE",
    "CHPT","BLNK","QS","GOEV","FSR","NKLA","WKHS","RIDE",
    "SPY","QQQ","IWM","DIA","ARKK","ARKG","ARKF","ARKW",
    "XLF","XLK","XLE","XLV","XLI","XLP","XLY","XLB","XLRE","XLC","XLU",
    "SOXL","TQQQ","SQQQ","UVXY","VXX",
]

def build_universe():
    """Build full ticker universe, cache it in DB"""
    conn = get_db()
    cached = conn.execute("SELECT value FROM app_state WHERE key='universe'").fetchone()
    cache_date = conn.execute("SELECT value FROM app_state WHERE key='universe_date'").fetchone()
    today = datetime.now().strftime("%Y-%m-%d")

    if cached and cache_date and cache_date["value"] == today:
        tickers = json.loads(cached["value"])
        conn.close()
        log.info(f"Using cached universe: {len(tickers)} tickers")
        return tickers

    sp500 = fetch_sp500()
    ndx100 = fetch_nasdaq100()
    combined = list(dict.fromkeys(sp500 + ndx100 + EXTRA_TICKERS))

    if len(combined) < 100:
        if cached:
            combined = json.loads(cached["value"])
            log.warning(f"Fetch failed, using previous cache: {len(combined)} tickers")
        else:
            combined = EXTRA_TICKERS
            log.warning(f"No cache, using extras only: {len(combined)} tickers")
    else:
        conn.execute("INSERT OR REPLACE INTO app_state VALUES ('universe', ?)", [json.dumps(combined)])
        conn.execute("INSERT OR REPLACE INTO app_state VALUES ('universe_date', ?)", [today])
        conn.commit()

    conn.close()
    log.info(f"Universe built: {len(combined)} tickers")
    return combined

# Sector mapping — we'll expand this dynamically but start with known sectors
SECTORS = {
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
    "SOXL":"ETF","TQQQ":"ETF","SQQQ":"ETF","UVXY":"ETF",
    "LLY":"Healthcare","UNH":"Healthcare","JNJ":"Healthcare","PFE":"Healthcare",
    "ABBV":"Healthcare","MRK":"Healthcare","TMO":"Healthcare","ABT":"Healthcare",
    "GILD":"Healthcare","VRTX":"Healthcare","REGN":"Healthcare","BIIB":"Healthcare",
    "CVX":"Energy","SLB":"Energy","HAL":"Energy","BKR":"Energy","EOG":"Energy",
    "V":"Finance","MA":"Finance","GS":"Finance","BLK":"Finance","WFC":"Finance",
    "BK":"Finance","AIG":"Finance","AFL":"Finance",
    "PG":"Consumer","KO":"Consumer","PEP":"Consumer","WMT":"Consumer","COST":"Consumer",
    "HD":"Consumer","LOW":"Consumer","TGT":"Consumer","MCD":"Consumer","SBUX":"Consumer",
    "BA":"Industrial","CAT":"Industrial","DE":"Industrial","GE":"Industrial",
    "HON":"Industrial","UNP":"Industrial","RTX":"Defense","NOC":"Defense","LHX":"Defense","GD":"Defense",
}

def get_sector(ticker):
    return SECTORS.get(ticker, "Other")

# ── DATABASE ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS predictions (
            id TEXT PRIMARY KEY, ticker TEXT, name TEXT, date TEXT, direction TEXT,
            conf INTEGER, expected_move REAL, entry_price REAL, sell_time TEXT,
            reasoning TEXT, sector TEXT, rsi REAL, vol_ratio REAL,
            weights_snapshot TEXT, outcome TEXT DEFAULT 'pending',
            actual_move REAL, actual_sell_price REAL, gross_pnl REAL,
            net_pnl REAL, logged_at TEXT, resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS virtual_trades (
            id TEXT PRIMARY KEY, ticker TEXT, direction TEXT, buy_date TEXT,
            buy_time TEXT, buy_price REAL, sell_date TEXT, sell_time TEXT,
            sell_price REAL, invested REAL DEFAULT 10.0, current_value REAL,
            conf INTEGER, expected_move REAL, actual_move REAL, gross_pnl REAL,
            net_pnl REAL, fee REAL DEFAULT 0.02, outcome TEXT DEFAULT 'open',
            sector TEXT, reasoning TEXT, weekend_hold INTEGER DEFAULT 0,
            sell_reason TEXT, sell_sentiment_history TEXT,
            intraday_high REAL, intraday_low REAL
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
            weights_before TEXT, weights_after TEXT, reasoning TEXT,
            summary TEXT, total_predictions INTEGER, resolved INTEGER,
            hits INTEGER, misses INTEGER, win_rate REAL
        );
        CREATE TABLE IF NOT EXISTS weights_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
            rsi_momentum REAL, volume_surge REAL, overnight_gap_prob REAL,
            earnings_catalyst REAL, sector_rotation REAL, win_rate REAL,
            total_resolved INTEGER, audit_reasoning TEXT
        );
        CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS scan_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT, scan_type TEXT, ticker_count INTEGER,
            picks_json TEXT, all_scores_json TEXT
        );
        CREATE TABLE IF NOT EXISTS position_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id TEXT, check_time TEXT, price REAL,
            pnl_pct REAL, sentiment TEXT
        );
    """)
    # Add new columns to virtual_trades if they don't exist
    try:
        conn.execute("ALTER TABLE virtual_trades ADD COLUMN weekend_hold INTEGER DEFAULT 0")
    except: pass
    try:
        conn.execute("ALTER TABLE virtual_trades ADD COLUMN sell_reason TEXT")
    except: pass
    try:
        conn.execute("ALTER TABLE virtual_trades ADD COLUMN sell_sentiment_history TEXT")
    except: pass
    try:
        conn.execute("ALTER TABLE virtual_trades ADD COLUMN intraday_high REAL")
    except: pass
    try:
        conn.execute("ALTER TABLE virtual_trades ADD COLUMN intraday_low REAL")
    except: pass

    existing = conn.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
    if not existing:
        conn.execute("INSERT INTO app_state VALUES ('weights', ?)", [json.dumps({
            "rsi_momentum":0.20,"volume_surge":0.22,"overnight_gap_prob":0.25,
            "earnings_catalyst":0.18,"sector_rotation":0.15
        })])
    conn.commit()
    conn.close()
    log.info(f"Database ready at {DB_PATH}")

def get_weights():
    try:
        conn = get_db()
        row = conn.execute("SELECT value FROM app_state WHERE key='weights'").fetchone()
        conn.close()
        return json.loads(row["value"]) if row else {
            "rsi_momentum":0.20,"volume_surge":0.22,"overnight_gap_prob":0.25,
            "earnings_catalyst":0.18,"sector_rotation":0.15}
    except:
        return {"rsi_momentum":0.20,"volume_surge":0.22,"overnight_gap_prob":0.25,
                "earnings_catalyst":0.18,"sector_rotation":0.15}

def save_weights(w):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO app_state VALUES ('weights', ?)", [json.dumps(w)])
    conn.commit(); conn.close()

# ── PRICE DATA ────────────────────────────────────────────────────────────────
def fetch_prices(tickers, batch_size=100):
    """Fetch prices in batches to handle large universes"""
    results = {}
    try:
        import yfinance as yf
        log.info(f"Fetching {len(tickers)} tickers via yfinance in batches of {batch_size}...")
        for i in range(0, len(tickers), batch_size):
            batch_tickers = tickers[i:i+batch_size]
            try:
                batch = yf.download(batch_tickers, period="5d", interval="1d",
                                    group_by="ticker", auto_adjust=True, progress=False, threads=True)
                for ticker in batch_tickers:
                    try:
                        df = batch if len(batch_tickers)==1 else (batch[ticker] if ticker in batch.columns.get_level_values(0) else None)
                        if df is not None and len(df) >= 2:
                            price = float(df["Close"].iloc[-1])
                            if price != price: continue  # NaN check
                            prev = float(df["Close"].iloc[-2])
                            opn = float(df["Open"].iloc[-1])
                            vol = float(df["Volume"].iloc[-1])
                            avg_v = float(df["Volume"].mean())
                            results[ticker] = {
                                "price": price, "open": opn, "prev": prev,
                                "high": float(df["High"].iloc[-1]),
                                "low": float(df["Low"].iloc[-1]),
                                "volume": vol, "avg_vol": avg_v,
                                "vol_ratio": vol/max(avg_v,1),
                                "gap_pct": (opn-prev)/max(prev,0.01)*100,
                                "source": "yfinance"
                            }
                    except: pass
            except Exception as e:
                log.warning(f"Batch {i}-{i+batch_size} error: {e}")
            time.sleep(0.5)  # Brief pause between batches
        log.info(f"yfinance returned {len(results)}/{len(tickers)}")
    except Exception as e:
        log.error(f"yfinance error: {e}")

    # Alpha Vantage fallback for missing
    missing = [t for t in tickers if t not in results]
    if missing and AV_KEY:
        import urllib.request
        for ticker in missing[:10]:
            try:
                url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={AV_KEY}"
                with urllib.request.urlopen(url, timeout=5) as r:
                    q = json.loads(r.read()).get("Global Quote", {})
                if q.get("05. price"):
                    p = float(q["05. price"]); prev = float(q["08. previous close"])
                    results[ticker] = {"price":p,"open":p,"prev":prev,"high":p,"low":p,
                        "volume":0,"avg_vol":1,"vol_ratio":1.0,
                        "gap_pct":(p-prev)/max(prev,0.01)*100,"source":"alpha_vantage"}
                time.sleep(0.5)
            except: pass

    # Cache prices
    conn = get_db()
    for ticker, data in results.items():
        conn.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)",
                     [f"cache_{ticker}", json.dumps(data)])
    conn.commit(); conn.close()
    return results

def calc_rsi_batch(tickers, period=14):
    """Calculate RSI for multiple tickers efficiently"""
    rsi_map = {}
    try:
        import yfinance as yf
        log.info(f"Calculating RSI for {len(tickers)} tickers...")
        for i in range(0, len(tickers), 50):
            batch = tickers[i:i+50]
            try:
                data = yf.download(batch, period="60d", interval="1d",
                                   auto_adjust=True, progress=False, threads=True)
                for ticker in batch:
                    try:
                        df = data if len(batch)==1 else (data[ticker] if ticker in data.columns.get_level_values(0) else None)
                        if df is not None and len(df) >= period+1:
                            delta = df["Close"].diff()
                            rs = delta.clip(lower=0).rolling(period).mean() / (-delta.clip(upper=0)).rolling(period).mean()
                            val = float((100 - 100/(1+rs)).iloc[-1])
                            rsi_map[ticker] = val if val==val else 50.0
                        else:
                            rsi_map[ticker] = 50.0
                    except:
                        rsi_map[ticker] = 50.0
            except: pass
            time.sleep(0.3)
    except: pass
    # Fill missing with 50
    for t in tickers:
        if t not in rsi_map: rsi_map[t] = 50.0
    log.info(f"RSI calculated for {len(rsi_map)} tickers")
    return rsi_map

def get_earnings_soon(tickers):
    soon = set()
    try:
        import yfinance as yf
        for t in tickers[:30]:
            try:
                cal = yf.Ticker(t).calendar
                if cal is not None and not cal.empty:
                    d = cal.iloc[0].get("Earnings Date")
                    if d and 0 <= (d - datetime.now()).days <= 3: soon.add(t)
            except: pass
    except: pass
    return soon

# ── SCORING ───────────────────────────────────────────────────────────────────
def score(ticker, pd, rsi, earn_soon, w, direction="long"):
    rsi = rsi if rsi==rsi else 50.0
    if direction=="long":
        rsi_s = 1.0 if 40<=rsi<=65 else (0.9 if rsi<40 else 0.5)
    else:
        rsi_s = 1.0 if rsi>65 else (0.7 if rsi>55 else 0.4)
    vr = pd.get("vol_ratio",1.0); vr = vr if vr==vr else 1.0
    gp = pd.get("gap_pct",0); gp = gp if gp==gp else 0.0
    gap_s = min(abs(gp)/10.0, 1.0)
    if direction=="short": gap_s = gap_s if gp<0 else gap_s*0.5
    sec_s = 0.85 if get_sector(ticker) in ["Tech","Finance","Crypto"] else 0.7
    raw = (rsi_s*w["rsi_momentum"] + min(vr/3.5,1.0)*w["volume_surge"] +
           gap_s*w["overnight_gap_prob"] + (0.9 if ticker in earn_soon else 0.6)*w["earnings_catalyst"] +
           sec_s*w["sector_rotation"])
    return min(int(raw*115), 96)

def est_move(pd, conf, earn):
    vr = pd.get("vol_ratio",1); vr = vr if vr==vr else 1.0
    gp = pd.get("gap_pct",0); gp = gp if gp==gp else 0.0
    return round(min(4+(conf-60)*0.25+(vr-1)*1.5+(3 if earn else 0)+min(abs(gp)*0.3,3), 25), 1)

def sell_time(conf):
    if conf>=85: return "8:45-9:30 AM"
    if conf>=75: return "9:30-10:30 AM"
    if conf>=65: return "10:30-12 PM"
    return "12-1:30 PM"

def reasoning(ticker, pd, rsi, earn, direction):
    p = []
    if direction=="long":
        p.append(f"RSI {rsi:.0f} oversold" if rsi<45 else (f"RSI {rsi:.0f} momentum" if rsi>60 else f"RSI {rsi:.0f} neutral"))
    else:
        p.append(f"RSI {rsi:.0f} overbought" if rsi>65 else f"RSI {rsi:.0f} weakening")
    vr = pd.get("vol_ratio",1)
    if vr>1.8: p.append(f"{vr:.1f}x vol")
    gp = pd.get("gap_pct",0)
    if abs(gp)>2: p.append(f"{gp:+.1f}% gap")
    if earn: p.append("earnings catalyst")
    return " . ".join(p[:3])

# ── GENERATE PICKS (with caching) ─────────────────────────────────────────────
def generate_picks(weights=None, scan_type="scheduled"):
    if weights is None: weights = get_weights()
    universe = build_universe()
    log.info(f"Generating picks from {len(universe)} tickers (scan: {scan_type})...")

    prices = fetch_prices(universe)
    rsi_map = calc_rsi_batch(list(prices.keys()))
    earn_soon = get_earnings_soon(list(prices.keys()))

    scored = []
    for ticker in universe:
        if ticker not in prices: continue
        pd = prices[ticker]
        rsi = rsi_map.get(ticker, 50.0)
        lc = score(ticker, pd, rsi, earn_soon, weights, "long")
        sc = score(ticker, pd, rsi, earn_soon, weights, "short")
        lm = est_move(pd, lc, ticker in earn_soon)
        sm = est_move(pd, sc, ticker in earn_soon)
        scored.append({
            "ticker":ticker, "name":ticker, "sector":get_sector(ticker),
            "price":pd["price"], "open_price":pd.get("open",pd["price"]),
            "prev_close":pd.get("prev",pd["price"]), "rsi":round(rsi,1),
            "vol_ratio":round(pd.get("vol_ratio",1),2),
            "overnight_gap_pct":round(pd.get("gap_pct",0),2),
            "earnings_soon":ticker in earn_soon,
            "long_conf":lc, "long_move":lm,
            "long_reasoning":reasoning(ticker,pd,rsi,ticker in earn_soon,"long"),
            "short_conf":sc, "short_move":sm,
            "short_reasoning":reasoning(ticker,pd,rsi,ticker in earn_soon,"short"),
            "sell_time":sell_time(lc), "data_source":pd.get("source","unknown"),
        })

    longs  = sorted([s for s in scored if s["long_move"]>=MIN_MOVE], key=lambda x:x["long_conf"], reverse=True)
    shorts = sorted([s for s in scored if s["short_move"]>=MIN_MOVE], key=lambda x:x["short_conf"], reverse=True)

    result = {
        "longs": longs[:MAX_PICKS],
        "shorts": shorts[:10],
        "all_longs": len(longs),
        "all_shorts": len(shorts),
        "total_scanned": len(scored),
        "generated_at": datetime.now().isoformat(),
        "scan_type": scan_type,
    }

    # Cache the picks
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_picks', ?)", [json.dumps(result)])
    conn.execute("INSERT OR REPLACE INTO app_state VALUES ('cached_picks_time', ?)", [datetime.now().isoformat()])

    # Save to scan_cache for historical analysis
    conn.execute("INSERT INTO scan_cache (scan_time,scan_type,ticker_count,picks_json) VALUES (?,?,?,?)",
                 [datetime.now().isoformat(), scan_type, len(scored), json.dumps(result)])

    # Log predictions & virtual trades
    today = datetime.now().strftime("%Y-%m-%d")
    is_friday = datetime.now().weekday() == 4

    for i, pick in enumerate(longs[:MAX_PICKS] + shorts[:10]):
        dir_ = "long" if i < MAX_PICKS else "short"
        conf = pick["long_conf"] if dir_=="long" else pick["short_conf"]
        move = pick["long_move"] if dir_=="long" else pick["short_move"]
        rsn  = pick["long_reasoning"] if dir_=="long" else pick["short_reasoning"]
        pid  = f"{pick['ticker']}_{today}_{dir_}"
        if not conn.execute("SELECT id FROM predictions WHERE id=?", [pid]).fetchone():
            conn.execute("INSERT INTO predictions (id,ticker,name,date,direction,conf,expected_move,entry_price,sell_time,reasoning,sector,rsi,vol_ratio,weights_snapshot,logged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid,pick["ticker"],pick["name"],today,dir_,conf,move,pick["price"],
                 pick["sell_time"],rsn,pick["sector"],pick["rsi"],pick["vol_ratio"],
                 json.dumps(weights),datetime.now().isoformat()])
        buy_p = pick.get("open_price", pick["price"])
        vtid = f"{pick['ticker']}_{today}_{dir_}_vt"
        if not conn.execute("SELECT id FROM virtual_trades WHERE id=?", [vtid]).fetchone():
            conn.execute("INSERT INTO virtual_trades (id,ticker,direction,buy_date,buy_time,buy_price,invested,conf,expected_move,outcome,sector,reasoning,weekend_hold) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [vtid,pick["ticker"],dir_,today,"09:30:00",buy_p,
                 INVEST_PER_PICK,conf,move,"open",pick["sector"],rsn,
                 1 if is_friday else 0])
        else:
            conn.execute("UPDATE virtual_trades SET buy_price=?,buy_time='09:30:00' WHERE id=? AND buy_time!='09:30:00'",
                         [buy_p, vtid])

    conn.commit(); conn.close()
    log.info(f"Picks generated: {len(longs)} longs, {len(shorts)} shorts from {len(scored)} scanned")
    return result

def get_cached_picks():
    """Return cached picks instantly — no yfinance calls"""
    conn = get_db()
    cached = conn.execute("SELECT value FROM app_state WHERE key='cached_picks'").fetchone()
    cache_time = conn.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    conn.close()
    if cached:
        result = json.loads(cached["value"])
        result["cached"] = True
        result["cache_time"] = cache_time["value"] if cache_time else None
        return result
    return None

# ── SCORE YESTERDAY ───────────────────────────────────────────────────────────
def score_yesterday():
    yesterday = (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
    conn = get_db()
    trades = conn.execute("SELECT * FROM virtual_trades WHERE buy_date=? AND outcome='open'", [yesterday]).fetchall()
    conn.close()
    if not trades: log.info("No open trades to score"); return
    tickers = list(set(t["ticker"] for t in trades))
    prices = fetch_prices(tickers)
    conn = get_db(); n=0
    for t in trades:
        if t["ticker"] not in prices: continue
        cur = prices[t["ticker"]]["price"]
        pct = (cur-t["buy_price"])/t["buy_price"]*100
        pnl = t["invested"]*(pct/100)
        if t["direction"]=="long":
            outcome = "hit" if pct>=MIN_MOVE else ("partial" if pct>0 else "miss")
        else:
            outcome = "hit" if pct<=-MIN_MOVE else ("partial" if pct<0 else "miss")
        conn.execute("UPDATE virtual_trades SET sell_date=?,sell_price=?,current_value=?,actual_move=?,gross_pnl=?,net_pnl=?,outcome=?,sell_time=?,sell_reason=? WHERE id=?",
            [datetime.now().strftime("%Y-%m-%d"),cur,t["invested"]+pnl,round(pct,2),
             round(pnl,4),round(pnl-FEE_PER_TRADE,4),outcome,
             datetime.now().strftime("%H:%M:%S"),"end_of_day",t["id"]])
        conn.execute("UPDATE predictions SET outcome=?,actual_move=?,resolved_at=? WHERE id=?",
            [outcome,round(pct,2),datetime.now().isoformat(),
             f"{t['ticker']}_{yesterday}_{t['direction']}"])
        n+=1
    conn.commit(); conn.close(); log.info(f"Scored {n} trades")

# ── AUDIT ─────────────────────────────────────────────────────────────────────
def run_audit():
    log.info("Running audit...")
    conn = get_db()
    preds = [dict(p) for p in conn.execute("SELECT * FROM predictions WHERE outcome!='pending' ORDER BY date DESC LIMIT 200").fetchall()]
    total = conn.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    conn.close()
    hits   = [p for p in preds if p["outcome"]=="hit"]
    misses = [p for p in preds if p["outcome"]=="miss"]
    wr     = len(hits)/len(preds) if preds else None
    w      = get_weights()
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        resp = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=800, messages=[{"role":"user","content":
            f"Self-audit for overnight swing trading. Analyze and return updated weights.\nWEIGHTS:{json.dumps(w)}\nDATA:{json.dumps({'total':total,'resolved':len(preds),'hits':len(hits),'misses':len(misses),'win_rate':wr})}\nRules:sum=1.0,each 0.05-0.45. ONLY JSON:{{'weights':{{...}},'reasoning':['...'],'summary':'...','confidence':'low|medium|high'}}"
        }])
        result = json.loads(resp.content[0].text.replace("```json","").replace("```","").strip())
        nw = result["weights"]
        s = sum(nw.values())
        if 0.85<s<1.15:
            nw = {k:round(v/s,4) for k,v in nw.items()}
            save_weights(nw)
        else: nw = w
        conn = get_db()
        conn.execute("INSERT INTO audit_log (timestamp,weights_before,weights_after,reasoning,summary,total_predictions,resolved,hits,misses,win_rate) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [datetime.now().isoformat(),json.dumps(w),json.dumps(nw),json.dumps(result.get("reasoning",[])),result.get("summary",""),total,len(preds),len(hits),len(misses),wr])
        conn.execute("INSERT OR REPLACE INTO app_state VALUES ('last_audit',?)", [datetime.now().isoformat()])
        conn.commit(); conn.close()
        return {"success":True,"weights":nw,"reasoning":result.get("reasoning",[]),"summary":result.get("summary",""),"confidence":result.get("confidence","medium")}
    except Exception as e:
        log.error(f"Audit error: {e}"); return {"success":False,"error":str(e)}

# ── SCHEDULER ─────────────────────────────────────────────────────────────────
def scheduler():
    import schedule
    w = get_weights

    # Post-market scans (CST = UTC-5 during CDT, but Railway runs UTC)
    # We'll use UTC times: CST+5 = UTC
    # 4 PM CST = 21:00 UTC, 5 PM = 22:00, 6 PM = 23:00
    schedule.every().day.at("21:00").do(lambda: generate_picks(scan_type="post_market_1"))
    schedule.every().day.at("22:00").do(lambda: generate_picks(scan_type="post_market_2"))
    schedule.every().day.at("23:00").do(lambda: generate_picks(scan_type="post_market_3"))

    # Pre-market scans
    # 4 AM CST = 09:00 UTC, 5 AM = 10:00, ... 9 AM = 14:00
    schedule.every().day.at("09:00").do(lambda: generate_picks(scan_type="pre_market_1"))
    schedule.every().day.at("10:00").do(lambda: generate_picks(scan_type="pre_market_2"))
    schedule.every().day.at("11:00").do(lambda: generate_picks(scan_type="pre_market_3"))
    schedule.every().day.at("12:00").do(lambda: generate_picks(scan_type="pre_market_4"))
    schedule.every().day.at("13:00").do(lambda: generate_picks(scan_type="pre_market_5"))
    schedule.every().day.at("14:00").do(lambda: generate_picks(scan_type="final_scan"))

    # Score yesterday's trades at 8:30 AM CST = 13:30 UTC
    schedule.every().day.at("13:30").do(score_yesterday)

    # Audit at 8:45 AM CST = 13:45 UTC (before final scan)
    schedule.every().day.at("13:45").do(run_audit)

    log.info("Scheduler started with full scan schedule")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status":"ok","time":datetime.now().isoformat()})

@app.route("/api/picks")
def api_picks():
    """Serve cached picks instantly. Use ?fresh=true to force new scan."""
    fresh = request.args.get("fresh","false").lower() == "true"
    if not fresh:
        cached = get_cached_picks()
        if cached:
            return jsonify(cached)
    try:
        return jsonify(generate_picks(scan_type="manual"))
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/picks/fresh")
def api_picks_fresh():
    """Force a fresh scan — use sparingly"""
    try:
        return jsonify(generate_picks(scan_type="manual_fresh"))
    except Exception as e:
        return jsonify({"error":str(e)}), 500

@app.route("/api/weights")
def api_weights():
    return jsonify(get_weights())

@app.route("/api/predictions")
def api_predictions():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM predictions ORDER BY logged_at DESC LIMIT 200").fetchall()]
    conn.close(); return jsonify(rows)

@app.route("/api/predictions/<pid>/outcome", methods=["POST"])
def api_outcome(pid):
    o = request.json.get("outcome")
    if o not in ["hit","miss","partial"]: return jsonify({"error":"invalid"}), 400
    conn = get_db()
    conn.execute("UPDATE predictions SET outcome=?,resolved_at=? WHERE id=?", [o,datetime.now().isoformat(),pid])
    conn.commit(); conn.close(); return jsonify({"success":True})

@app.route("/api/virtual-trades")
def api_vt():
    direction = request.args.get("direction")  # optional filter: "long" or "short"
    conn = get_db()
    if direction:
        rows = [dict(r) for r in conn.execute("SELECT * FROM virtual_trades WHERE direction=? ORDER BY buy_date DESC LIMIT 500", [direction]).fetchall()]
    else:
        rows = [dict(r) for r in conn.execute("SELECT * FROM virtual_trades ORDER BY buy_date DESC LIMIT 500").fetchall()]
    conn.close(); return jsonify(rows)

@app.route("/api/audit", methods=["POST"])
def api_audit():
    return jsonify(run_audit())

@app.route("/api/audit/log")
def api_audit_log():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 30").fetchall()]
    conn.close(); return jsonify(rows)

@app.route("/api/score-yesterday", methods=["POST"])
def api_score():
    score_yesterday(); return jsonify({"success":True})

@app.route("/api/perf-history")
def api_perf():
    conn = get_db()
    rows = conn.execute("SELECT buy_date as date, SUM(COALESCE(gross_pnl,0)) as daily_pnl, COUNT(*) as trades FROM virtual_trades GROUP BY buy_date ORDER BY buy_date ASC").fetchall()
    conn.close()
    hist=[]; running=1000.0
    for r in rows:
        running+=float(r["daily_pnl"] or 0)
        hist.append({"date":r["date"],"virtual":round(running,2),"daily_pnl":round(float(r["daily_pnl"] or 0),4),"trades":r["trades"]})
    return jsonify(hist)

@app.route("/api/stats")
def api_stats():
    conn = get_db()
    tp  = conn.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    res = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome!='pending'").fetchone()["n"]
    h   = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome='hit'").fetchone()["n"]
    m   = conn.execute("SELECT COUNT(*) as n FROM predictions WHERE outcome='miss'").fetchone()["n"]
    vt  = conn.execute("SELECT COUNT(*) as n FROM virtual_trades").fetchone()["n"]
    vo  = conn.execute("SELECT COUNT(*) as n FROM virtual_trades WHERE outcome='open'").fetchone()["n"]
    la  = conn.execute("SELECT value FROM app_state WHERE key='last_audit'").fetchone()
    ct  = conn.execute("SELECT value FROM app_state WHERE key='cached_picks_time'").fetchone()
    conn.close()
    return jsonify({
        "total_predictions":tp,"resolved":res,"hits":h,"misses":m,
        "win_rate":round(h/res*100,1) if res else None,
        "virtual_trades":vt,"virtual_open":vo,
        "last_audit":la["value"] if la else None,
        "last_scan":ct["value"] if ct else None,
        "weights":get_weights()
    })

@app.route("/api/scan-history")
def api_scan_history():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT id,scan_time,scan_type,ticker_count FROM scan_cache ORDER BY scan_time DESC LIMIT 50").fetchall()]
    conn.close(); return jsonify(rows)

@app.route("/api/intraday-pnl")
def api_intraday_pnl():
    """Fetch retroactive 5-min intraday data for open positions to build smooth performance chart"""
    conn = get_db()
    open_trades = conn.execute("SELECT * FROM virtual_trades WHERE outcome='open'").fetchall()
    conn.close()
    if not open_trades:
        return jsonify({"points":[],"message":"No open positions"})
    try:
        import yfinance as yf
        total_invested = sum(t["invested"] for t in open_trades)
        # Fetch 5-min data for all open position tickers
        tickers = list(set(t["ticker"] for t in open_trades))
        data = yf.download(tickers, period="2d", interval="5m",
                           group_by="ticker", auto_adjust=True, progress=False)
        points = []
        if data is not None and len(data) > 0:
            for idx in range(len(data)):
                ts = data.index[idx]
                total_pnl = 0
                for t in open_trades:
                    try:
                        if len(tickers) == 1:
                            price = float(data["Close"].iloc[idx])
                        else:
                            price = float(data[t["ticker"]]["Close"].iloc[idx])
                        if price != price: continue
                        pct = (price - t["buy_price"]) / t["buy_price"] * 100
                        total_pnl += t["invested"] * (pct / 100)
                    except: pass
                points.append({
                    "ts": int(ts.timestamp() * 1000),
                    "time": ts.strftime("%H:%M"),
                    "date": ts.strftime("%Y-%m-%d"),
                    "virtual": round(1000 + total_pnl, 2),
                    "pnl": round(total_pnl, 4)
                })
        return jsonify({"points": points, "positions": len(open_trades)})
    except Exception as e:
        log.error(f"Intraday PnL error: {e}")
        return jsonify({"points":[],"error":str(e)})

# ── INIT ──────────────────────────────────────────────────────────────────────
init_db()
threading.Thread(target=scheduler, daemon=True).start()
log.info("Brain v3 initialized — expanded universe, scan schedule, caching")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
