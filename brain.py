"""
brain.py — Overnight Swing Desk Backend
"""

import os, json, sqlite3, time, logging, threading
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────────────────────
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

UNIVERSE = [
    "NVDA","META","AMD","TSLA","AMZN","MSFT","PLTR","SOFI","MSTR","JPM",
    "BAC","COIN","GOOGL","AAPL","NFLX","PYPL","HOOD","RBLX","SNAP","UBER",
    "LYFT","RIVN","LCID","GME","AMC","SMCI","IONQ","XOM","RGTI","INTC",
    "MU","QCOM","ARM","AVGO","TSM","ORCL","CRM","SNOW","DDOG","NET",
    "CRWD","ZS","PANW","SHOP","ROKU","SPOT","ABNB","DASH","BB","NOK",
    "TLRY","SPY","QQQ","IWM","ARKK","ARKG",
]
UNIVERSE = list(dict.fromkeys(UNIVERSE))

SECTORS = {
    "NVDA":"Tech","META":"Tech","AMD":"Tech","TSLA":"Tech","AMZN":"Consumer",
    "MSFT":"Tech","PLTR":"Tech","SOFI":"Finance","MSTR":"Finance","JPM":"Finance",
    "BAC":"Finance","COIN":"Finance","GOOGL":"Tech","AAPL":"Tech","NFLX":"Consumer",
    "PYPL":"Finance","HOOD":"Finance","RBLX":"Consumer","SNAP":"Tech","UBER":"Consumer",
    "LYFT":"Consumer","RIVN":"Tech","LCID":"Tech","GME":"Consumer","AMC":"Consumer",
    "SMCI":"Tech","IONQ":"Tech","XOM":"Energy","RGTI":"Tech","INTC":"Tech",
    "MU":"Tech","QCOM":"Tech","ARM":"Tech","AVGO":"Tech","TSM":"Tech",
    "ORCL":"Tech","CRM":"Tech","SNOW":"Tech","DDOG":"Tech","NET":"Tech",
    "CRWD":"Tech","ZS":"Tech","PANW":"Tech","SHOP":"Consumer","ROKU":"Tech",
    "SPOT":"Consumer","ABNB":"Consumer","DASH":"Consumer","BB":"Tech","NOK":"Tech",
    "TLRY":"Consumer","SPY":"ETF","QQQ":"ETF","IWM":"ETF","ARKK":"ETF","ARKG":"ETF",
}

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
            sector TEXT, reasoning TEXT
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
        CREATE TABLE IF NOT EXISTS perf_history (
            date TEXT PRIMARY KEY, virtual_gross REAL, virtual_net REAL,
            daily_pnl REAL, daily_trades INTEGER
        );
    """)
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
            "earnings_catalyst":0.18,"sector_rotation":0.15
        }
    except:
        return {"rsi_momentum":0.20,"volume_surge":0.22,"overnight_gap_prob":0.25,
                "earnings_catalyst":0.18,"sector_rotation":0.15}

def save_weights(w):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO app_state VALUES ('weights', ?)", [json.dumps(w)])
    conn.commit()
    conn.close()

# ── PRICE DATA ────────────────────────────────────────────────────────────────
def fetch_prices(tickers):
    results = {}
    try:
        import yfinance as yf
        log.info(f"Fetching {len(tickers)} tickers via yfinance...")
        batch = yf.download(tickers, period="5d", interval="1d",
                            group_by="ticker", auto_adjust=True, progress=False, threads=True)
        for ticker in tickers:
            try:
                df = batch if len(tickers)==1 else (batch[ticker] if ticker in batch.columns.get_level_values(0) else None)
                if df is not None and len(df) >= 2:
                    results[ticker] = {
                        "price":   float(df["Close"].iloc[-1]),
                        "open":    float(df["Open"].iloc[-1]),
                        "prev":    float(df["Close"].iloc[-2]),
                        "high":    float(df["High"].iloc[-1]),
                        "low":     float(df["Low"].iloc[-1]),
                        "volume":  float(df["Volume"].iloc[-1]),
                        "avg_vol": float(df["Volume"].mean()),
                        "vol_ratio": float(df["Volume"].iloc[-1]) / max(float(df["Volume"].mean()), 1),
                        "gap_pct": (float(df["Open"].iloc[-1]) - float(df["Close"].iloc[-2])) / max(float(df["Close"].iloc[-2]), 1) * 100,
                        "source":  "yfinance"
                    }
            except: pass
        log.info(f"yfinance returned {len(results)}/{len(tickers)}")
    except Exception as e:
        log.error(f"yfinance error: {e}")

    # Alpha Vantage fallback
    missing = [t for t in tickers if t not in results]
    if missing and AV_KEY:
        import urllib.request
        for ticker in missing[:5]:
            try:
                url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={AV_KEY}"
                with urllib.request.urlopen(url, timeout=5) as r:
                    q = json.loads(r.read()).get("Global Quote", {})
                if q.get("05. price"):
                    p, prev = float(q["05. price"]), float(q["08. previous close"])
                    results[ticker] = {"price":p,"open":p,"prev":prev,"high":p,"low":p,
                                       "volume":0,"avg_vol":1,"vol_ratio":1.0,
                                       "gap_pct":(p-prev)/max(prev,1)*100,"source":"alpha_vantage"}
                time.sleep(0.5)
            except: pass

    # Cache fallback
    conn = get_db()
    for ticker in [t for t in tickers if t not in results]:
        cached = conn.execute("SELECT value FROM app_state WHERE key=?", [f"cache_{ticker}"]).fetchone()
        if cached:
            d = json.loads(cached["value"]); d["source"] = "cache"; results[ticker] = d
    for ticker, data in results.items():
        conn.execute("INSERT OR REPLACE INTO app_state VALUES (?,?)", [f"cache_{ticker}", json.dumps(data)])
    conn.commit(); conn.close()
    return results

def calc_rsi(ticker, period=14):
    try:
        import yfinance as yf
        df = yf.download(ticker, period="60d", interval="1d", auto_adjust=True, progress=False)
        if len(df) < period+1: return 50.0
        delta = df["Close"].diff()
        rs = delta.clip(lower=0).rolling(period).mean() / (-delta.clip(upper=0)).rolling(period).mean()
        val = float((100 - 100/(1+rs)).iloc[-1])
        return val if val==val else 50.0
    except: return 50.0

def get_earnings_soon(tickers):
    soon = set()
    try:
        import yfinance as yf
        for t in tickers[:20]:
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
    rsi_s = (1.0 if 40<=rsi<=65 else (0.9 if rsi<40 else 0.5)) if direction=="long" else (1.0 if rsi>65 else (0.7 if rsi>55 else 0.4))
    vr = pd.get("vol_ratio",1.0); vr = vr if vr==vr else 1.0
    gp = pd.get("gap_pct",0); gp = gp if gp==gp else 0.0
    gap_s = min(abs(gp)/10.0, 1.0)
    if direction=="short": gap_s = gap_s if gp<0 else gap_s*0.5
    sec_s = 0.85 if SECTORS.get(ticker,"Other") in ["Tech","Finance"] else 0.7
    raw = rsi_s*w["rsi_momentum"] + min(vr/3.5,1.0)*w["volume_surge"] + gap_s*w["overnight_gap_prob"] + (0.9 if ticker in earn_soon else 0.6)*w["earnings_catalyst"] + sec_s*w["sector_rotation"]
    return min(int(raw*115), 96)

def est_move(pd, conf, earn):
    vr = pd.get("vol_ratio",1); vr = vr if vr==vr else 1.0
    gp = pd.get("gap_pct",0); gp = gp if gp==gp else 0.0
    return round(min(4+(conf-60)*0.25+(vr-1)*1.5+(3 if earn else 0)+min(abs(gp)*0.3,3), 25), 1)

def sell_time(conf):
    if conf>=85: return "8:45–9:30 AM"
    if conf>=75: return "9:30–10:30 AM"
    if conf>=65: return "10:30–12 PM"
    return "12–1:30 PM"

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
    if earn: p.append("earnings soon")
    return " · ".join(p[:3])

# ── PICKS ─────────────────────────────────────────────────────────────────────
def generate_picks(weights=None):
    if weights is None: weights = get_weights()
    log.info("Generating picks...")
    prices = fetch_prices(UNIVERSE)
    earn_soon = get_earnings_soon(UNIVERSE)
    scored = []
    for ticker in UNIVERSE:
        if ticker not in prices: continue
        pd = prices[ticker]
        rsi = calc_rsi(ticker)
        lc = score(ticker, pd, rsi, earn_soon, weights, "long")
        sc = score(ticker, pd, rsi, earn_soon, weights, "short")
        lm = est_move(pd, lc, ticker in earn_soon)
        sm = est_move(pd, sc, ticker in earn_soon)
        scored.append({
            "ticker":ticker,"name":ticker,"sector":SECTORS.get(ticker,"Other"),
            "price":pd["price"],"open_price":pd.get("open",pd["price"]),
            "prev_close":pd.get("prev",pd["price"]),"rsi":round(rsi,1),
            "vol_ratio":round(pd.get("vol_ratio",1),2),
            "overnight_gap_pct":round(pd.get("gap_pct",0),2),
            "earnings_soon":ticker in earn_soon,
            "long_conf":lc,"long_move":lm,
            "long_reasoning":reasoning(ticker,pd,rsi,ticker in earn_soon,"long"),
            "short_conf":sc,"short_move":sm,
            "short_reasoning":reasoning(ticker,pd,rsi,ticker in earn_soon,"short"),
            "sell_time":sell_time(lc),"data_source":pd.get("source","unknown"),
        })
    longs  = sorted([s for s in scored if s["long_move"] >=MIN_MOVE], key=lambda x:x["long_conf"], reverse=True)
    shorts = sorted([s for s in scored if s["short_move"]>=MIN_MOVE], key=lambda x:x["short_conf"], reverse=True)
    today  = datetime.now().strftime("%Y-%m-%d")
    conn   = get_db()
    for i, pick in enumerate(longs[:MAX_PICKS]+shorts[:10]):
        dir_  = "long" if i<MAX_PICKS else "short"
        conf  = pick["long_conf"]  if dir_=="long" else pick["short_conf"]
        move  = pick["long_move"]  if dir_=="long" else pick["short_move"]
        rsn   = pick["long_reasoning"] if dir_=="long" else pick["short_reasoning"]
        pid   = f"{pick['ticker']}_{today}_{dir_}"
        if not conn.execute("SELECT id FROM predictions WHERE id=?", [pid]).fetchone():
            conn.execute("INSERT INTO predictions (id,ticker,name,date,direction,conf,expected_move,entry_price,sell_time,reasoning,sector,rsi,vol_ratio,weights_snapshot,logged_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid,pick["ticker"],pick["name"],today,dir_,conf,move,pick["price"],pick["sell_time"],rsn,pick["sector"],pick["rsi"],pick["vol_ratio"],json.dumps(weights),datetime.now().isoformat()])
        buy_p = pick.get("open_price",pick["price"])
        vtid  = f"{pick['ticker']}_{today}_{dir_}_vt"
        if not conn.execute("SELECT id FROM virtual_trades WHERE id=?", [vtid]).fetchone():
            conn.execute("INSERT INTO virtual_trades (id,ticker,direction,buy_date,buy_time,buy_price,invested,conf,expected_move,outcome,sector,reasoning) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [vtid,pick["ticker"],dir_,today,"09:45:00",buy_p,INVEST_PER_PICK,conf,move,"open",pick["sector"],rsn])
        else:
            conn.execute("UPDATE virtual_trades SET buy_price=?,buy_time='09:45:00' WHERE id=? AND buy_time!='09:45:00'", [buy_p,vtid])
    conn.commit(); conn.close()
    return {"longs":longs[:MAX_PICKS],"shorts":shorts[:10],"generated_at":datetime.now().isoformat()}

# ── SCORE YESTERDAY ───────────────────────────────────────────────────────────
def score_yesterday():
    yesterday = (datetime.now()-timedelta(days=1)).strftime("%Y-%m-%d")
    conn = get_db()
    trades = conn.execute("SELECT * FROM virtual_trades WHERE buy_date=? AND outcome='open'", [yesterday]).fetchall()
    conn.close()
    if not trades: log.info("No open trades to score"); return
    tickers = list(set(t["ticker"] for t in trades))
    prices  = fetch_prices(tickers)
    conn = get_db(); n=0
    for t in trades:
        if t["ticker"] not in prices: continue
        cur = prices[t["ticker"]]["price"]
        pct = (cur-t["buy_price"])/t["buy_price"]*100
        pnl = t["invested"]*(pct/100)
        outcome = ("hit" if (pct>=MIN_MOVE if t["direction"]=="long" else pct<=-MIN_MOVE) else ("partial" if (pct>0 if t["direction"]=="long" else pct<0) else "miss"))
        conn.execute("UPDATE virtual_trades SET sell_date=?,sell_price=?,current_value=?,actual_move=?,gross_pnl=?,net_pnl=?,outcome=?,sell_time=? WHERE id=?",
            [datetime.now().strftime("%Y-%m-%d"),cur,t["invested"]+pnl,round(pct,2),round(pnl,4),round(pnl-FEE_PER_TRADE,4),outcome,datetime.now().strftime("%H:%M:%S"),t["id"]])
        conn.execute("UPDATE predictions SET outcome=?,actual_move=?,resolved_at=? WHERE id=?",
            [outcome,round(pct,2),datetime.now().isoformat(),f"{t['ticker']}_{yesterday}_{t['direction']}"])
        n+=1
    conn.commit(); conn.close(); log.info(f"Scored {n} trades")

# ── AUDIT ─────────────────────────────────────────────────────────────────────
def run_audit():
    log.info("Running audit...")
    conn = get_db()
    preds = [dict(p) for p in conn.execute("SELECT * FROM predictions WHERE outcome!='pending' ORDER BY date DESC LIMIT 200").fetchall()]
    total = conn.execute("SELECT COUNT(*) as n FROM predictions").fetchone()["n"]
    conn.close()
    hits    = [p for p in preds if p["outcome"]=="hit"]
    misses  = [p for p in preds if p["outcome"]=="miss"]
    wr      = len(hits)/len(preds) if preds else None
    w       = get_weights()
    sec_acc = {}
    for p in preds:
        s = p.get("sector","Other")
        if s not in sec_acc: sec_acc[s]={"hits":0,"total":0}
        sec_acc[s]["total"]+=1
        if p["outcome"]=="hit": sec_acc[s]["hits"]+=1
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        resp = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=800, messages=[{"role":"user","content":
            f"Self-audit engine for overnight swing trading app. Analyze and return updated weights.\nWEIGHTS:{json.dumps(w)}\nDATA:{json.dumps({'total':total,'resolved':len(preds),'hits':len(hits),'misses':len(misses),'win_rate':wr,'sector_acc':sec_acc,'hcmr':len([p for p in preds if p['conf']>=80 and p['outcome']=='miss'])/max(len([p for p in preds if p['conf']>=80]),1)})}\nRules:sum=1.0,each 0.05-0.45. Respond ONLY JSON:{{'weights':{{...}},'reasoning':['...'],'summary':'...','confidence':'low|medium|high'}}"
        }])
        result = json.loads(resp.content[0].text.replace("```json","").replace("```","").strip())
        nw = result["weights"]
        s  = sum(nw.values())
        if 0.85<s<1.15:
            nw = {k:round(v/s,4) for k,v in nw.items()}
            save_weights(nw); log.info(f"Weights: {nw}")
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
    schedule.every().day.at("08:30").do(lambda: (score_yesterday(), generate_picks()))
    schedule.every().day.at("09:00").do(run_audit)
    while True: schedule.run_pending(); time.sleep(60)

# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status":"ok","time":datetime.now().isoformat()})

@app.route("/api/picks")
def api_picks():
    try: return jsonify(generate_picks())
    except Exception as e: return jsonify({"error":str(e)}), 500

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
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM virtual_trades ORDER BY buy_date DESC LIMIT 500").fetchall()]
    conn.close(); return jsonify(rows)

@app.route("/api/portfolio")
def api_portfolio():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM portfolio").fetchall()] if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='portfolio'").fetchone() else []
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
    conn.close()
    return jsonify({"total_predictions":tp,"resolved":res,"hits":h,"misses":m,
        "win_rate":round(h/res*100,1) if res else None,"virtual_trades":vt,
        "virtual_open":vo,"last_audit":la["value"] if la else None,"weights":get_weights()})

# ── INIT & START ──────────────────────────────────────────────────────────────
init_db()
threading.Thread(target=scheduler, daemon=True).start()
log.info("Brain initialized")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
