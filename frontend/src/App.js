import React, { useState, useEffect, useMemo } from "react";

/*
 * Overnight Swing Desk — Frontend v32 (Push 46)
 * ══════════════════════════════════════════════
 * Changes in Push 46:
 *   - SettingsDrawer: Telegram bot info section — shows configured/not configured
 *     provider label updates (Telegram vs Twilio) on notification toggle
 *     setup instructions shown when Telegram not configured
 *   - Stale threshold: 5 min regular hours, 10 min pre/post market
 *     weekends never flagged as stale
 *
 * Push 45:
 *   - CARD_METRIC_GRID: stable stock-card columns for TICKER / DAY / P&L / $ / CONF
 *     fixes +$ alignment offset caused by auto-expanding CONF column
 *   - PositionCard: DAY % shows day_change_percent from DB (monitor-written)
 *   - Confidence delta: single number when both sides equal, right side uses
 *     confidenceColor() not confDeltaColor, arrow keeps directional color
 *   - buildPerfHistory: always injects live point when positions exist
 *     seed point ts set to 30 days ago, properly marked as seed
 *   - perfFirst 1D: uses yesterday's last settled balance as baseline
 *   - Day's P&L: same yesterday baseline — consistent with perfPercent
 *
 * Push 44:
 *   - settledBalance: always from full perfHistory non-intraday points, never
 *     from timeframe-filtered window — prevents chart regressing to $1000
 *   - ping: fire-and-forget, not awaited — no longer blocks load sequence
 *   - ⚠ stale tag: shown on position cards when last_price_updated >5 min old
 *     during market hours — explicit data staleness indicator
 *
 * Push 43:
 *   - Railway keep-alive: ping /api/ping before real requests to warm cold start
 *   - getSentimentLabel rewrite: 4 clean states, CUT removed from open positions
 *     HOLD · target hit / HOLD · on target / WEAK · cut threshold not met
 *     WEAK · ⚠ 3/3 day trades used (only when threshold met AND pdtRemaining=0)
 *     pdtRemaining passed as prop to PositionCard
 *   - confluence_methods crash fix: safe Array.isArray parse before .map()
 *   - Theme toggle: perfectly centered between Net View and settings icon
 *   - isRedCard: CUT removed, only WEAK triggers red card styling
 *
 * Push 42:
 *   - ErrorBoundary: wraps entire app — crashes show RELOAD screen not black
 *   - Safe math on confidence delta: Number() coercion prevents NaN render crashes
 *   - perfPercent fix: ALL timeframe uses seed $1000 baseline, others use filtered first
 *   - todayClosed state: fetches /api/today-closed every 2.5 min refresh
 *   - Closed today section: shows above open positions with outcome label + DONE button
 *     labels: "Closed in profit" / "Losses cut" / "Force closed 2:45 PM" / "Closed at a loss"
 *     DONE button dismisses card from view (dismissedClosed state)
 *   - Auto-backfills lock_in_confidence on app load (silent POST)
 *
 * Push 41:
 *   - Confidence delta tag: lock-in% → current% with arrow on every position card
 *     lockInConfidence reads trade.lock_in_confidence (stamped at 8:15 AM scan)
 *     arrow color: green if improved, red if declined, grey if flat
 *     progress bar uses delta color to reinforce direction at a glance
 *   - isDone collapsed card: correct outcome label (CUT/SOLD/CLOSED) with matching color
 *   - DONE button: extended to force_closed and sold outcomes, not just CUT
 *
 * Push 40:
 *   - ThemeToggle: single unified SVG (ring + sphere), no containers, guaranteed centering
 *   - Settings hex nut icon: SVG hexagon + inner circle, opens notification drawer
 *   - Notification drawer: toggle + test button, persists via API
 *
 * Push 39:
 *   - Method tags softened: #fff → #ddd, rgba(255,255,255,0.3) → rgba(255,255,255,0.2)
 *   - Section box borders: rgba(255,255,255,0.15) → rgba(255,255,255,0.12)
 *   - Sub-tray dividers: rgba(255,255,255,0.1) → rgba(255,255,255,0.08)
 *
 * Push 38:
 *   - Tag order: 52W → X/9 (blue) → X/10 (white/black)
 *   - Indicator tags: blue theme, method tags: white/black theme (position + pick cards)
 *   - Signal sub-tray: human-readable values from signal_values
 *   - Score value color: #fff → T1
 *
 * Push 37:
 *   - Signal indicator tags: white text, black bg, white border
 *   - Indicator tag tap: sub-tray with score readout + definition
 *   - Pick card 52W tag: glowing state + tag-glow className
 *
 * Push 36:
 *   - Signal Indicators section on expanded position cards (white/grey tags)
 *   - X/9 fired indicator count on collapsed position cards
 *   - Trade queue fallback label shows dynamic formula
 *
 * Push 35:
 *   - VWAP Reclaim + Volatility Squeeze added to METHOD_DEFINITIONS
 *   - Confluence tag X/8 → X/10
 *   - SwingDesk Algo: 4 new indicator cards (RS, Sector RS, VWAP, HVR)
 *   - Audit label maps updated with all 9 indicator names
 *
 * Push 34:
 *   - ThemeToggle: iOS Safari centering fix — button/span display:flex removes baseline offset
 *
 * (brain.py Push 34: Alpha Vantage news, backfill-sr-confidence endpoint)
 *
 * Push 33 changes:
 *   - MiniChart 1D: prior-day close as baseline anchor on weekends/sparse days
 *   - Day's P&L: same prior-day baseline fix — no more $0.00 on weekends
 *   - ThemeToggle: radial-gradient CSS circles replacing emoji (perfectly centered)
 *   - Glow delay on method tags: 0.1s → 0.15s
 *   - SwingDesk Algo: support_resistance card added, sector_rotation removed
 *   - Audit history label maps: sector_rotation → support_resistance
 *   - Audit history empty state: hardcoded greys → T3/T2
 *   - Weight evolution chart axis: #222 → BORDER
 *   - Sentiment phrase: decoupled from label color → T2
 *   - Reasoning text in pick card: T3 → T2
 *   - Confluence tag: X/7 → X/8
 *   - News section: paddingBottom + marginBottom to match space above
 *   - BORDER bump: black #1c1c20 → #2a2a30, navy #1e3448 → #2a4460
 */

// ─── BACKEND API ──────────────────────────────────────────────────────────────
const API = "https://swingdesk-brain-production-205e.up.railway.app/api";
async function apiFetch(path, opts = {}) {
  const response = await fetch(API + path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!response.ok) throw new Error(`API ${path} → ${response.status}`);
  return response.json();
}

// Brain offline fallback — returns last known data with a stale flag
async function apiFetchWithFallback(path, fallbackPath = "/last-known") {
  try {
    return await apiFetch(path);
  } catch {
    try {
      const fallback = await apiFetch(fallbackPath);
      return { ...fallback, offline: true };
    } catch {
      return null;
    }
  }
}

// ─── HELPERS ──────────────────────────────────────────────────────────────────
function confidenceColor(score, theme) {
  if (score >= 85) return "#FFD700";
  if (score >= 75) return "#22c55e";
  if (score >= 65) return "#60a5fa";
  // Below floor — muted but theme-aware
  return theme === "navy" ? "#3a5570" : "#8a8f98";
}

function mapPickFields(pick) {
  return {
    ...pick,
    lc: pick.long_conf, sc: pick.short_conf,
    lm: pick.long_move, sm: pick.short_move,
    lr: pick.long_reasoning, sr: pick.short_reasoning,
    st: pick.sell_time,
    dayChg: pick.day_change_pct || pick.overnight_gap_pct || 0,
  };
}

function getBuyLabel(hasOpenPositions) {
  // Returns "Buy today", "Bought today", or "Bought Friday" based on context
  const now = new Date();
  const cst = new Date(now.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  const day = cst.getDay(); // 0=Sun, 1=Mon...6=Sat
  const isWeekend = day === 0 || day === 6;
  const afterOpen = cst.getHours() > 8 || (cst.getHours() === 8 && cst.getMinutes() >= 45);

  if (isWeekend || hasOpenPositions) {
    // Find last trading day name
    if (day === 0) return "Bought Friday"; // Sunday
    if (day === 6) return "Bought Friday"; // Saturday
    if (day === 1) return "Bought Friday"; // Monday (bought last Friday)
    return "Bought today";
  }
  if (afterOpen) return "Bought today";
  return "Buy today";
}

// ─── SENTIMENT ENGINE ─────────────────────────────────────────────────────────
function getTimeElapsedFraction() {
  // Returns 0-1 representing how far through the trading day we are (8:45 AM - 2:45 PM CST)
  const now = new Date();
  const cst = new Date(now.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  const isWeekday = cst.getDay() >= 1 && cst.getDay() <= 5;
  if (!isWeekday) return 0; // Weekend — no time pressure
  const minutesSinceOpen = (cst.getHours() - 8) * 60 + (cst.getMinutes() - 45);
  const totalTradingMinutes = 360; // 8:45 AM to 2:45 PM
  return Math.max(0, Math.min(1, minutesSinceOpen / totalTradingMinutes));
}

function getSentimentLabel(pnlPercent, frozenTarget, sentimentIcon, pdtRemaining) {
  const now = new Date();
  const cst = new Date(now.toLocaleString("en-US", { timeZone: "America/Chicago" }));
  const minuteOfDay = cst.getHours() * 60 + cst.getMinutes();
  const isWeekday = cst.getDay() >= 1 && cst.getDay() <= 5;

  const WINDOW1 = 9  * 60 + 30;
  const WINDOW2 = 11 * 60 + 20;
  const WINDOW3 = 13 * 60 + 10;
  const OPEN    = 8  * 60 + 30;
  const CLOSE   = 15 * 60;

  // HOLD · target hit — P&L has met or exceeded the estimated move
  if (pnlPercent >= frozenTarget) {
    return { label: "HOLD", phrase: "target hit", color: "#22c55e", priority: 1 };
  }

  // HOLD · on target — positive but below target
  if (pnlPercent >= 0) {
    return { label: "HOLD", phrase: "on target", color: "#22c55e", priority: 1 };
  }

  // Negative P&L — determine cut threshold
  let cutThreshold = null;
  if (isWeekday && minuteOfDay >= OPEN && minuteOfDay < CLOSE) {
    if (minuteOfDay >= WINDOW1 && minuteOfDay < WINDOW2) {
      cutThreshold = frozenTarget * 0.75;
    } else if (minuteOfDay >= WINDOW2 && minuteOfDay < WINDOW3) {
      cutThreshold = frozenTarget * 0.50;
    } else if (minuteOfDay >= WINDOW3) {
      cutThreshold = frozenTarget * 0.25;
    }
  }

  const thresholdMet = cutThreshold !== null && pnlPercent < -(cutThreshold);

  // WEAK · ⚠ 3/3 day trades used — threshold met but PDT blocked
  if (thresholdMet && pdtRemaining === 0) {
    return { label: "WEAK", phrase: "⚠ 3/3 day trades used", color: "#60a5fa", priority: 2 };
  }

  // WEAK · standing by — negative but not yet in cut territory
  return { label: "WEAK", phrase: "standing by", color: "#60a5fa", priority: 2 };
}

function relativeTime(dateStr, tsSeconds) {
  const diffMs = tsSeconds
    ? Date.now() - tsSeconds * 1000
    : (() => { const d = new Date(dateStr); return isNaN(d) ? null : Date.now() - d.getTime(); })();
  if (diffMs === null) return dateStr || "";
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

function formatDate(dateStr) {
  if (!dateStr) return "";
  const [year, month, day] = dateStr.split("-");
  return `${month}/${day}/${year.slice(2)}`;
}

function daysHeld(buyDate) {
  if (!buyDate) return 1;
  const buy = new Date(buyDate);
  const now = new Date();
  const diff = Math.floor((now - buy) / (1000 * 60 * 60 * 24));
  return Math.max(diff, 1);
}

// ─── DESIGN TOKENS ────────────────────────────────────────────────────────────
// ─── THEME SYSTEM ─────────────────────────────────────────────────────────────
const THEMES = {
  black: {
    BG: "#080809", CARD: "#111113", BORDER: "#2a2a30",
    T1: "#e8e8e8", T2: "#b0b0b0", T3: "#777",
    GREEN: "#22c55e", RED: "#ef4444", BLUE: "#60a5fa",
    AMBER: "#FFD700", PURPLE: "#a78bfa",
    CARD_BG_LONG: "#0a1209", CARD_BG_SHORT: "#120a09",
    CARD_BORDER_LONG: "#0f2014", CARD_BORDER_SHORT: "#200f0f",
  },
  navy: {
    BG: "#0d1b2a", CARD: "#132233", BORDER: "#2a4460",
    T1: "#e8f0f8", T2: "#8aaac8", T3: "#5a7a96",
    GREEN: "#22c55e", RED: "#ef4444", BLUE: "#5dade2",
    AMBER: "#FFD700", PURPLE: "#a569bd",
    CARD_BG_LONG: "#0d2130", CARD_BG_SHORT: "#1a0e1a",
    CARD_BORDER_LONG: "#1a3a4a", CARD_BORDER_SHORT: "#2a1020",
  },
};

function setCSSTheme(key) {
  const t = THEMES[key] || THEMES.black;
  const r = document.documentElement;
  r.style.setProperty("--bg", t.BG);
  r.style.setProperty("--card", t.CARD);
  r.style.setProperty("--border", t.BORDER);
  r.style.setProperty("--t1", t.T1);
  r.style.setProperty("--t2", t.T2);
  r.style.setProperty("--t3", t.T3);
  r.style.setProperty("--green", t.GREEN);
  r.style.setProperty("--red", t.RED);
  r.style.setProperty("--blue", t.BLUE);
  r.style.setProperty("--amber", t.AMBER);
  r.style.setProperty("--purple", t.PURPLE);
  r.style.setProperty("--card-bg-long", t.CARD_BG_LONG);
  r.style.setProperty("--card-bg-short", t.CARD_BG_SHORT);
  r.style.setProperty("--card-border-long", t.CARD_BORDER_LONG);
  r.style.setProperty("--card-border-short", t.CARD_BORDER_SHORT);
  document.body.style.background = t.BG;
  document.documentElement.style.background = t.BG;
  try { localStorage.setItem("swingdesk_theme", key); } catch {}
}

// Apply saved theme immediately on load — before first render
setCSSTheme((() => { try { return localStorage.getItem("swingdesk_theme") || "black"; } catch { return "black"; } })());

// Color tokens — these always read from CSS vars so they're always in sync
// Used directly in inline styles throughout the app
const _t = () => {
  const s = document.documentElement.style;
  return {
    BG: s.getPropertyValue("--bg") || "#080809",
    CARD: s.getPropertyValue("--card") || "#111113",
    BORDER: s.getPropertyValue("--border") || "#1c1c20",
    T1: s.getPropertyValue("--t1") || "#e8e8e8",
    T2: s.getPropertyValue("--t2") || "#b0b0b0",
    T3: s.getPropertyValue("--t3") || "#777",
    GREEN: s.getPropertyValue("--green") || "#22c55e",
    RED: s.getPropertyValue("--red") || "#f87171",
    BLUE: s.getPropertyValue("--blue") || "#60a5fa",
    AMBER: s.getPropertyValue("--amber") || "#FFD700",
    PURPLE: s.getPropertyValue("--purple") || "#a78bfa",
    CARD_BG_LONG: s.getPropertyValue("--card-bg-long") || "#0a1209",
    CARD_BG_SHORT: s.getPropertyValue("--card-bg-short") || "#120a09",
    CARD_BORDER_LONG: s.getPropertyValue("--card-border-long") || "#0f2014",
    CARD_BORDER_SHORT: s.getPropertyValue("--card-border-short") || "#200f0f",
  };
};

// These are read at render time — CSS vars are always current so no stale reads
let _theme = _t();
let BG = _theme.BG, CARD = _theme.CARD, BORDER = _theme.BORDER;
let T1 = _theme.T1, T2 = _theme.T2, T3 = _theme.T3;
let GREEN = _theme.GREEN, RED = _theme.RED, BLUE = _theme.BLUE;
let AMBER = _theme.AMBER, PURPLE = _theme.PURPLE;
let CARD_BG_LONG = _theme.CARD_BG_LONG, CARD_BG_SHORT = _theme.CARD_BG_SHORT;
let CARD_BORDER_LONG = _theme.CARD_BORDER_LONG, CARD_BORDER_SHORT = _theme.CARD_BORDER_SHORT;

// Called by App when themeKey state changes — refreshes all tokens then triggers re-render
function refreshThemeTokens(key) {
  setCSSTheme(key);
  _theme = _t();
  BG = _theme.BG; CARD = _theme.CARD; BORDER = _theme.BORDER;
  T1 = _theme.T1; T2 = _theme.T2; T3 = _theme.T3;
  GREEN = _theme.GREEN; RED = _theme.RED; BLUE = _theme.BLUE;
  AMBER = _theme.AMBER; PURPLE = _theme.PURPLE;
  CARD_BG_LONG = _theme.CARD_BG_LONG; CARD_BG_SHORT = _theme.CARD_BG_SHORT;
  CARD_BORDER_LONG = _theme.CARD_BORDER_LONG; CARD_BORDER_SHORT = _theme.CARD_BORDER_SHORT;
}

const CARD_METRIC_GRID = "0.95fr 0.72fr 1.05fr 0.72fr 0.95fr";
const CARD_GRID_GAP = "8px";
const CARD_PAD_L = "15px";
const CARD_PAD_R = "12px";
const TOOLBAR_CONTROL_H = 26;
const SPINE_VALUE_W = 66;

function SpinePercent({ value, color, fontSize = 12, fontWeight = 600, decimals = 1 }) {
  const n = Number(value) || 0;
  const sign = n >= 0 ? "+" : "-";
  const fixed = Math.abs(n).toFixed(decimals);
  const [whole, frac] = fixed.split(".");
  return (
    <span style={{
      width: SPINE_VALUE_W,
      position: "relative",
      display: "inline-block",
      color,
      fontFamily: "'DM Mono',monospace",
      fontSize,
      fontWeight,
      lineHeight: 1,
      fontVariantNumeric: "tabular-nums",
      height: `${fontSize}px`,
    }}>
      <span style={{ position: "absolute", right: "calc(50% + 3px)", top: 0, textAlign: "right", whiteSpace: "nowrap" }}>{sign}{whole}</span>
      <span style={{ position: "absolute", left: "50%", top: 0, transform: "translateX(-50%)", textAlign: "center" }}>.</span>
      <span style={{ position: "absolute", left: "calc(50% + 5px)", top: 0, textAlign: "left", whiteSpace: "nowrap" }}>{frac}%</span>
    </span>
  );
}

function SpineCell({ children }) {
  return <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minWidth: 0 }}>{children}</div>;
}

function SpineTriangle({ color, expanded }) {
  return (
    <div style={{ width: SPINE_VALUE_W, display: "flex", justifyContent: "center" }}>
      <svg width="44" height="4" viewBox="0 0 44 4" style={{ transform: expanded ? "scaleY(-1)" : "none", display: "block" }}>
        <polygon points="22,4 2,0 42,0" fill={color} />
      </svg>
    </div>
  );
}

function CardMetricGrid({ children, style = {} }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: CARD_METRIC_GRID, columnGap: CARD_GRID_GAP, alignItems: "center", ...style }}>
      {children}
    </div>
  );
}

function JournalButton({ state, onClick, compact = false }) {
  return (
    <button onClick={onClick} style={{
      background: state === "added" ? BLUE + "22" : state === "error" ? RED + "18" : "transparent",
      border: `1px solid ${state === "error" ? RED + "66" : BLUE + "55"}`,
      borderRadius: 4,
      color: state === "added" ? BLUE : state === "error" ? RED : BLUE + "99",
      fontSize: 8,
      fontWeight: 700,
      letterSpacing: 0.5,
      lineHeight: 1,
      minWidth: compact ? 34 : 64,
      textAlign: "center",
      padding: compact ? "4px 6px" : "4px 7px",
      cursor: "pointer",
      flexShrink: 0,
      transition: "all 0.2s",
    }}>
      {state === "added" ? "ADDED" : state === "error" ? "ERR" : compact ? "ADD" : "JOURNAL"}
    </button>
  );
}

function StaleBadge({ staleTime }) {
  if (!staleTime) return null;
  return (
    <span style={{
      fontSize: 7,
      fontWeight: 700,
      color: AMBER,
      padding: "2px 5px",
      background: "#1a1200",
      borderRadius: 3,
      border: `1px solid ${AMBER}44`,
      letterSpacing: .3,
      whiteSpace: "nowrap",
      flexShrink: 0,
    }}>
      scan {staleTime}
    </span>
  );
}

function CardActionRow({ statusLabel, statusPhrase, statusColor, staleTime, actions, borderColor }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
      alignItems: "center",
      gap: CARD_GRID_GAP,
      padding: "0 12px 7px",
      borderBottom: `1px solid ${borderColor}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
        {statusLabel && <span style={{ fontSize: 10, fontWeight: 800, color: statusColor, letterSpacing: .5, flexShrink: 0 }}>{statusLabel}</span>}
        {statusPhrase && <span style={{ fontSize: 9, color: T2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", minWidth: 0 }}>{statusPhrase}</span>}
        <span style={{ marginLeft: "auto", display: "flex", justifyContent: "flex-end", minWidth: 0 }}>
          <StaleBadge staleTime={staleTime} />
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 5, minWidth: 0, overflow: "hidden" }}>
        {actions}
      </div>
    </div>
  );
}

// ─── MINI CHART ───────────────────────────────────────────────────────────────
function MiniChart({ data, timeframe, feeAdjusted = false }) {
  const WIDTH = 360, HEIGHT = 90, PAD_TOP = 6, PAD_BOTTOM = 16, PAD_LEFT = 2, PAD_RIGHT = 2;
  const [hoveredPoint, setHoveredPoint] = useState(null);

  const filteredData = useMemo(() => {
    if (!data || !data.length) return [];
    if (timeframe === "D") {
      const sorted = [...data].sort((a, b) => b.ts - a.ts);
      const latestTradingPoint = sorted.find(p => {
        const d = new Date(p.ts);
        return d.getDay() >= 1 && d.getDay() <= 5;
      });
      if (!latestTradingPoint) return data.slice(-20);
      const latestDay = latestTradingPoint.date;
      const dayPoints = data.filter(p => p.date === latestDay);

      // If only 1 point for latest trading day (weekend, early session),
      // prepend last point of prior trading day as baseline anchor so
      // the 1D chart shows movement vs yesterday's close, not a flat line.
      if (dayPoints.length < 2) {
        const priorPoints = sorted.filter(p => p.date < latestDay && new Date(p.ts).getDay() >= 1 && new Date(p.ts).getDay() <= 5);
        if (priorPoints.length > 0) {
          const priorDay = priorPoints[0].date;
          const priorDayPoints = data.filter(p => p.date === priorDay);
          const anchor = priorDayPoints[priorDayPoints.length - 1];
          return anchor ? [anchor, ...dayPoints] : (dayPoints.length ? dayPoints : data.slice(-20));
        }
        return dayPoints.length ? dayPoints : data.slice(-20);
      }
      return dayPoints;
    }
    const cutoffDays = { W: 7, M: 30, "3M": 90, Y: 365, ALL: 9999 }[timeframe] || 30;
    return data.filter(point => point.ts >= Date.now() - cutoffDays * 86400000);
  }, [data, timeframe]);

  if (filteredData.length < 2) return (
    <div style={{ height: HEIGHT, display: "flex", alignItems: "center", justifyContent: "center", color: "#444", fontSize: 11 }}>
      Waiting for trade data...
    </div>
  );

  const values = filteredData.map((point, index) => feeAdjusted ? Math.max(point.virtual - index * 0.02, 0) : point.virtual);
  const minVal = Math.min(...values) * 0.997, maxVal = Math.max(...values) * 1.003, range = maxVal - minVal || 1;
  const toX = index => PAD_LEFT + (index / (filteredData.length - 1)) * (WIDTH - PAD_LEFT - PAD_RIGHT);
  const toY = value => PAD_TOP + (1 - (value - minVal) / range) * (HEIGHT - PAD_TOP - PAD_BOTTOM);

  const points = filteredData.map((point, index) => ({ x: toX(index), y: toY(values[index]), v: values[index], date: point.date }));
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const areaPath = linePath + ` L${points[points.length - 1].x.toFixed(1)},${(HEIGHT - PAD_BOTTOM).toFixed(1)} L${points[0].x.toFixed(1)},${(HEIGHT - PAD_BOTTOM).toFixed(1)} Z`;
  const isPositive = values[values.length - 1] >= values[0];
  const lineColor = isPositive ? GREEN : RED;

  const handleMouseMove = e => {
    const rect = e.currentTarget.getBoundingClientRect();
    const clientX = e.touches ? e.touches[0].clientX : e.clientX;
    const mouseX = (clientX - rect.left) * (WIDTH / rect.width);
    let closestIndex = 0, minDist = Infinity;
    points.forEach((p, i) => { const d = Math.abs(p.x - mouseX); if (d < minDist) { minDist = d; closestIndex = i; } });
    setHoveredPoint(points[closestIndex]);
  };

  // No date labels — timeframe buttons + hover tooltip provide all context needed

  return (
    <div style={{ position: "relative", userSelect: "none" }}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: "100%", height: HEIGHT, display: "block", cursor: "crosshair" }}
        onMouseMove={handleMouseMove} onMouseLeave={() => setHoveredPoint(null)} onTouchMove={handleMouseMove}>
        <defs>
          <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity=".2" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#chartGradient)" />
        <path d={linePath} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />

        {hoveredPoint && <>
          <line x1={hoveredPoint.x} y1={PAD_TOP} x2={hoveredPoint.x} y2={HEIGHT - PAD_BOTTOM} stroke="#2a2a2e" strokeWidth="1" />
          <circle cx={hoveredPoint.x} cy={hoveredPoint.y} r="3" fill={lineColor} stroke="#0a0a0b" strokeWidth="1.5" />
        </>}
      </svg>
      {hoveredPoint && (
        <div style={{ position: "absolute", top: 2, left: hoveredPoint.x > WIDTH * 0.6 ? "auto" : `${(hoveredPoint.x / WIDTH * 100).toFixed(0)}%`, right: hoveredPoint.x > WIDTH * 0.6 ? "4px" : "auto", background: "#111", border: "1px solid #222", borderRadius: 4, padding: "3px 7px", fontSize: 10, pointerEvents: "none", whiteSpace: "nowrap", transform: hoveredPoint.x > WIDTH * 0.6 ? "none" : "translateX(-50%)" }}>
          <span style={{ color: "#666", fontSize: 9 }}>{hoveredPoint.date} </span>
          <span style={{ color: T1, fontWeight: 600 }}>${hoveredPoint.v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
      )}
    </div>
  );
}

// ─── LOADING SCREEN ───────────────────────────────────────────────────────────
function LoadingScreen({ progress, statusText }) {
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100vh", flexDirection: "column", gap: 16, background: BG }}>
      <div style={{ fontSize: 20, fontWeight: 700, color: T1, letterSpacing: 1 }}>SWING DESK</div>
      <div style={{ fontSize: 10, color: T3, textTransform: "uppercase", letterSpacing: 2, marginBottom: 8 }}>Overnight Trading Brain</div>
      <div style={{ width: 200, height: 3, background: BORDER, borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${progress}%`, height: "100%", background: GREEN, borderRadius: 2, transition: "width 0.3s ease" }} />
      </div>
      <div style={{ fontSize: 11, color: T3 }}>{statusText}</div>
      <div style={{ fontSize: 9, color: T3, textAlign: "center", maxWidth: 260, lineHeight: 2, marginTop: 4 }}>
        SwingDesk is not financial advice.<br/>
        Any trades you make based on this<br/>
        data are entirely at your own risk.
      </div>
    </div>
  );
}

// ─── PICK CARD (Buy/Short recommendations) ────────────────────────────────────
const METHOD_DEFINITIONS = {
  "Darvas": "Nicholas Darvas made millions buying stocks breaking to new highs. The Darvas Box identifies stocks near their 52-week high with volume confirmation — consolidation near new highs before the next move up.",
  "Gap & Go": "The gap shows conviction from overnight buyers — momentum tends to continue intraday. Stocks that gap up more than 2% at open with strong volume have institutional participation behind the move.",
  "Donchian": "Richard Donchian's channel system identifies genuine breakouts from recent ranges. Price breaking above the highest high of the last 20 days signals the stock is trading at levels not seen in 4 weeks.",
  "Inside Day": "Compression before expansion — the tighter the coil, the stronger the spring. Today's price range fits entirely within yesterday's range, then breaks out upward.",
  "NR7": "Larry Connors popularized this as a reliable breakout precursor. The narrowest trading range of the last 7 days signals volatility contraction — which historically precedes volatility expansion.",
  "Bull Flag": "The flag is a pause, not a reversal — bulls are catching their breath before the next leg. A strong 5-day move up followed by tight consolidation today signals continuation.",
  "Pocket Pivot": "Gil Morales developed this to identify institutional buying before a breakout. An up day with volume exceeding any down day's volume over the last 10 sessions shows smart money accumulating.",
  "S&R": "ATR-adaptive support and resistance zone analysis. The brain identifies swing highs and lows over 60 days, clusters them into zones using Average True Range as the ruler, and scores based on overhead supply. Open air above current price means no resistance in range — nothing to stop the move.",
  "VWAP Reclaim": "VWAP (Volume Weighted Average Price) is the institutional benchmark price for the day. A stock closing above VWAP shows institutions are net buyers. The reclaim setup — price dips below VWAP intraday then closes above — is one of the most reliable signs of smart money accumulation.",
  "Vol Squeeze": "Historical Volatility Ratio measures compression. When a stock's recent volatility shrinks relative to its 20-day average, it's coiling. Volatility compression historically precedes explosive directional moves — the tighter the squeeze, the stronger the breakout.",
};

function PickCard({ pick, isLong = true, expanded, onToggle, themeKey = "black", onAddToPersonal }) {
  const [expandedMethod, setExpandedMethod] = React.useState(null);
  const [glowing, setGlowing] = React.useState(false);
  const [journalAdded, setJournalAdded] = React.useState(false);
  React.useEffect(() => {
    if (expanded) {
      const t = setTimeout(() => setGlowing(true), 50);
      return () => clearTimeout(t);
    } else {
      setGlowing(false);
    }
  }, [expanded]);
  const confidence = isLong ? pick.lc : pick.sc;
  const estimatedMove = isLong ? pick.lm : pick.sm;
  const reasoningText = isLong ? pick.lr : pick.sr;
  const borderColor = confidenceColor(confidence, themeKey);
  const dayChange = pick.dayChg || 0;
  const dayUp = dayChange >= 0;
  const cardKey = pick.ticker + "_" + (isLong ? "l" : "s");

  return (
    <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, overflow: "hidden", cursor: "pointer", borderLeft: `3px solid ${borderColor}` }}
      onClick={() => onToggle(cardKey)}>
      {/* Header row: TICKER | % CHG | EST. MOVE | blank | CONF */}
      <CardMetricGrid style={{ padding: "12px" }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 14, fontWeight: 600, color: T1, lineHeight: 1.2 }}>{pick.ticker}</span>
          </div>
          {pick.name && <span style={{ fontSize: 9, color: T3, lineHeight: 1.2, marginTop: 1 }}>{pick.name}</span>}
        </div>
        <div style={{ fontSize: 11, fontWeight: 600, color: dayUp ? GREEN : RED, textAlign: "center" }}>{dayUp ? "+" : ""}{dayChange.toFixed(1)}%</div>
        <SpineCell>
          <SpinePercent value={isLong ? estimatedMove : -estimatedMove} color={isLong ? GREEN : RED} fontSize={12} />
        </SpineCell>
        <div></div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", justifyContent: "center", alignSelf: "center" }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: borderColor, lineHeight: 1, fontFamily: "'DM Mono',monospace" }}>{confidence}%</div>
        </div>
      </CardMetricGrid>

      {/* Action row: status/staleness left of spine, journal/tags right of spine */}
      <CardActionRow
        borderColor={BORDER}
        actions={<>
          {pick.broke_52w_high_days_ago != null && pick.broke_52w_high_days_ago <= 7 && (
            <span className={glowing ? "tag-glow" : ""} style={{ fontSize: 7, fontWeight: 800, color: GREEN, letterSpacing: .3, padding: "1px 4px", background: "#0e1a0e", borderRadius: 3, border: "1px solid #1a3a1a", flexShrink: 0 }}>52W</span>
          )}
          {pick.confluence_count > 0 && (
            <span className={glowing ? "tag-glow" : ""} style={{ fontFamily: "'DM Mono',monospace", fontSize: 7, fontWeight: 800, color: "#ddd", letterSpacing: .3, padding: "1px 4px", background: "#000", borderRadius: 3, border: "1px solid rgba(255,255,255,0.2)", textAlign: "center", flexShrink: 0 }}>{pick.confluence_count}/10</span>
          )}
          {onAddToPersonal && <JournalButton
            compact
            state={journalAdded}
            onClick={(e) => {
              e.stopPropagation();
              Promise.resolve(onAddToPersonal(pick)).then(ok => {
                setJournalAdded(ok === false ? "error" : "added");
                setTimeout(() => setJournalAdded(false), 1500);
              });
            }}
          />}
        </>}
      />
      {expanded && (
        <div style={{ padding: "0 12px 12px", borderTop: `1px solid ${CARD_BORDER_LONG}` }}>
            {pick.broke_52w_high_days_ago != null && pick.broke_52w_high_days_ago <= 7 && (
              <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px", background: "#0e1a0e", borderRadius: 6, border: "1px solid #1a3a1a" }}>
                <span style={{ fontSize: 9, fontWeight: 800, color: GREEN, letterSpacing: .5 }}>52W HIGH</span>
                <span style={{ fontSize: 9, color: T3 }}>broke {pick.broke_52w_high_days_ago === 1 ? "yesterday" : `${pick.broke_52w_high_days_ago}d ago`}</span>
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px" }}>
              {[
                ["Sector", pick.sector],
                ["Price", `$${pick.price?.toFixed(2)}`],
                ["RSI", pick.rsi],
                ["Volume ratio", `${pick.vol_ratio}x`],
                ["Gap", `${pick.overnight_gap_pct >= 0 ? "+" : ""}${pick.overnight_gap_pct?.toFixed(1)}%`],
                ["Day change", `${pick.day_change_pct >= 0 ? "+" : ""}${pick.day_change_pct?.toFixed(1)}%`],
              ].map(([label, value]) => (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", borderBottom: `1px solid ${CARD_BORDER_LONG}`, paddingBottom: 3 }}>
                  <span style={{ fontSize: 9, color: T3 }}>{label}</span>
                  <span style={{ fontSize: 9, color: T1, fontFamily: "'DM Mono',monospace" }}>{value}</span>
                </div>
              ))}
            </div>
            <div style={{ padding: "6px 10px", background: "#0e0e10", borderRadius: 7 }}>
              <span style={{ fontSize: 10, color: T2, fontStyle: "italic" }}>"{reasoningText}"</span>
            </div>
            {pick.confluence_methods && pick.confluence_methods.length > 0 && (
              <div style={{ padding: "6px 10px 6px 4px", background: "#000", borderRadius: 7, marginBottom: 6, border: "1px solid rgba(255,255,255,0.12)" }}>
                <span style={{ fontSize: 8, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, display: "block", marginBottom: 6, textAlign: "center" }}>Method confluence</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {pick.confluence_methods.map(m => (
                    <span key={m} onClick={(e) => { e.stopPropagation(); setExpandedMethod(expandedMethod === m ? null : m); }}
                      className={glowing ? "tag-glow" : ""}
                      style={{ fontSize: 9, color: expandedMethod === m ? "#000" : "#ddd", background: expandedMethod === m ? "#ddd" : "#000", padding: "2px 6px", borderRadius: 3, border: "1px solid rgba(255,255,255,0.2)", cursor: "pointer" }}>{m}</span>
                  ))}
                </div>
                {expandedMethod && METHOD_DEFINITIONS[expandedMethod] && (
                  <div style={{ marginTop: 8, fontSize: 10, color: T1, lineHeight: 1.5, borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
                    {METHOD_DEFINITIONS[expandedMethod]}
                  </div>
                )}
              </div>
            )}
            <div style={{ borderTop: `1px solid ${CARD_BORDER_LONG}`, paddingTop: 6 }}>
              {pick.news && pick.news.filter(item => {
                if (!item.ts || item.ts === 0) return true;
                return (Date.now() - item.ts * 1000) <= 7 * 86400000;
              }).length > 0 ? (
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {pick.news.filter(item => {
                    if (!item.ts || item.ts === 0) return true;
                    return (Date.now() - item.ts * 1000) <= 7 * 86400000;
                  }).map((item, i) => (
                    <a key={i} href={item.url} target="_blank" rel="noopener noreferrer"
                      style={{ fontSize: 10, color: BLUE, textDecoration: "none", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{item.title}</span>
                      <span style={{ fontSize: 8, color: T3, whiteSpace: "nowrap", flexShrink: 0 }}>{relativeTime(item.date, item.ts)}</span>
                    </a>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 9, color: T3, fontStyle: "italic" }}>No recent news</div>
              )}
            </div>
          </div>
      )}
      {/* ── Expand triangle — apex at col3 right edge = decimal position ── */}
      <CardMetricGrid style={{ padding: "8px 12px 6px", alignItems: "start" }}>
        <div style={{ gridColumn: "1 / 3" }}></div>
        <SpineCell><SpineTriangle color={borderColor} expanded={expanded} /></SpineCell>
        <div></div>
        <div></div>
      </CardMetricGrid>
    </div>
  );
}
// ─── POST-CLOSE CARD ──────────────────────────────────────────────────────────
function PostCloseCard({ trade, onDismiss }) {
  const pnl = trade.actual_move || 0;
  const pnlColor = pnl >= 0 ? GREEN : RED;
  const isWin = pnl >= 0;
  const closeReason = trade.sell_reason === "forced_close" ? "Force-closed at 2:45 PM" :
                      trade.sell_reason === "stop_loss" ? "Brain cut losses" : "Brain closed";
  return (
    <div style={{ background: isWin ? "#0a1a0a" : "#1a0a0a", border: `1px solid ${isWin ? "#1a3a1a" : "#3a1a1a"}`, borderRadius: 10, borderLeft: `3px solid ${pnlColor}`, padding: "10px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 14, fontWeight: 600, color: T1 }}>{trade.ticker}</span>
          <span style={{ fontSize: 8, fontWeight: 700, color: pnlColor, letterSpacing: .5, padding: "1px 5px", background: pnlColor + "22", borderRadius: 3, border: `1px solid ${pnlColor}44` }}>{isWin ? "WIN" : "LOSS"}</span>
        </div>
        <span style={{ fontSize: 9, color: T3 }}>{closeReason} · {trade.sell_time || ""}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: pnlColor, fontFamily: "'DM Mono',monospace" }}>{pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%</div>
          <div style={{ fontSize: 9, color: T3 }}>${trade.sell_price ? trade.sell_price.toFixed(2) : "—"}</div>
        </div>
        <button onClick={() => onDismiss && onDismiss(trade.id)}
          style={{ background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 3, color: T3, fontSize: 8, fontWeight: 700, padding: "2px 6px", cursor: "pointer" }}>DONE</button>
      </div>
    </div>
  );
}

function PositionCard({ trade, isLong = true, expanded, onToggle, isDone, isClosed, onDone, onView, onClose, pdtRemaining = 3, themeKey = "black", onAddToPersonal }) {
  const [expandedMethod, setExpandedMethod] = React.useState(null);
  const [expandedSignal, setExpandedSignal] = React.useState(null);
  const [glowing, setGlowing] = React.useState(false);
  const [journalAdded, setJournalAdded] = React.useState(false);
  const longPressTimer = React.useRef(null);

  React.useEffect(() => {
    if (expanded) {
      setGlowing(true);
      const t = setTimeout(() => setGlowing(false), 1120);
      return () => clearTimeout(t);
    }
  }, [expanded]);

  const handlePressStart = () => {
    longPressTimer.current = setTimeout(() => {
      navigator.clipboard?.writeText(trade.ticker).catch(() => {});
      setGlowing(true);
      setTimeout(() => setGlowing(false), 400);
    }, 600);
  };

  const handlePressEnd = () => {
    clearTimeout(longPressTimer.current);
  };

  const buyPrice = trade.buy_price || 0;
  const investedAmount = trade.invested_amount || 10;
  const currentValue = trade.current_value || investedAmount;
  const rawPnlPercent = trade.current_pnl_percent != null ? trade.current_pnl_percent :
    (buyPrice > 0 ? (currentValue - investedAmount) / investedAmount * 100 : 0);
  // Clamp -0 to 0 to avoid negative zero display
  const pnlPercent = rawPnlPercent === 0 ? 0 : (Math.abs(rawPnlPercent) < 0.005 ? 0 : rawPnlPercent);
  const rawPnlDollars = currentValue - investedAmount;
  const pnlDollars = Math.abs(rawPnlDollars) < 0.005 ? 0 : rawPnlDollars;
  const isPositive = isLong ? pnlPercent >= 0 : pnlPercent <= 0;
  const pnlColor = pnlPercent === 0 ? T2 : (isPositive ? GREEN : RED);

  const frozenTarget = trade.expected_move || 10;
  const frozenConfidence = Number(trade.confidence) || 0;
  const dynamicConfidence = Number(trade.dynamic_confidence) || frozenConfidence;
  const dynamicEstimate = Number(trade.dynamic_estimate) || frozenTarget;
  const lockInConfidence = Number(trade.lock_in_confidence) || frozenConfidence;
  const confDelta = dynamicConfidence - lockInConfidence;
  const confDeltaColor = confDelta > 0 ? GREEN : confDelta < 0 ? RED : T3;

  // Safe parse — confluence_methods may arrive as JSON string from DB
  const confluenceMethods = Array.isArray(trade.confluence_methods)
    ? trade.confluence_methods
    : (() => { try { return JSON.parse(trade.confluence_methods || "[]"); } catch { return []; } })();

  const sentiment = getSentimentLabel(pnlPercent, frozenTarget, trade.sentiment_icon, pdtRemaining);

  // Stale data detection — flag if last_price_updated is >5 min old during regular hours
  // or >10 min old during pre/post market (monitor runs every 5 min there)
  const { isStale, staleTime } = (() => {
    if (!trade.last_price_updated) return { isStale: false, staleTime: null };
    const now = new Date();
    const cst = new Date(now.toLocaleString("en-US", { timeZone: "America/Chicago" }));
    const h = cst.getHours(), wd = cst.getDay();
    if (wd === 0 || wd === 6) return { isStale: false, staleTime: null };
    const regularHours = h >= 8 && h < 15;
    const extendedHours = (h >= 4 && h < 8) || (h >= 15 && h < 20);
    if (!regularHours && !extendedHours) return { isStale: false, staleTime: null };
    const threshold = regularHours ? 5 * 60 * 1000 : 10 * 60 * 1000;
    const updated = new Date(trade.last_price_updated);
    const stale = (now - updated) > threshold;
    const scanCst = new Date(updated.toLocaleString("en-US", { timeZone: "America/Chicago" }));
    const hh = scanCst.getHours(), mm = scanCst.getMinutes();
    const ampm = hh >= 12 ? "PM" : "AM";
    const h12 = hh % 12 || 12;
    const timeStr = `${h12}:${String(mm).padStart(2, "0")} ${ampm}`;
    return { isStale: stale, staleTime: timeStr };
  })();
  const cardKey = trade.id || trade.ticker;
  const isRedCard = sentiment.label === "WEAK";
  const rulingColor = isRedCard
    ? (CARD_BORDER_LONG === "#1a3a4a" ? CARD_BORDER_LONG : "#252525")
    : CARD_BORDER_LONG;

  if (isClosed) return null;

  if (isDone) {
    const closedLabel = trade.sell_reason === "force_close" ? "CLOSED" : trade.sell_reason === "cut" ? "CUT" : "SOLD";
    const closedColor = closedLabel === "CUT" ? RED : closedLabel === "SOLD" ? GREEN : T2;
    return (
      <div style={{ display: "flex", alignItems: "center", padding: "6px 12px", gap: 8, background: CARD, borderRadius: 10, border: `1px solid ${BORDER}` }}>
        <span style={{ fontSize: 10, color: T3, fontFamily: "'DM Mono',monospace", whiteSpace: "nowrap", flexShrink: 0 }}>
          {trade.ticker} · <span style={{ color: closedColor }}>{closedLabel}</span> · {pnlPercent >= 0 ? "+" : ""}{pnlPercent.toFixed(1)}%
        </span>
        <div style={{ flex: 1, height: 1, background: BORDER }} />
        <button onClick={(e) => { e.stopPropagation(); onView && onView(cardKey); }}
          style={{ background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 3, color: T3, fontSize: 8, fontWeight: 700, letterSpacing: 0.3, padding: "2px 6px", cursor: "pointer", flexShrink: 0 }}>VIEW</button>
        <button onClick={(e) => { e.stopPropagation(); onClose && onClose(cardKey); }}
          style={{ background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 3, color: T3, fontSize: 8, fontWeight: 700, letterSpacing: 0.3, padding: "2px 6px", cursor: "pointer", flexShrink: 0 }}>CLOSE</button>
      </div>
    );
  }

  return (
    <div style={{ background: isLong ? CARD_BG_LONG : CARD_BG_SHORT, border: `1px solid ${isLong ? CARD_BORDER_LONG : CARD_BORDER_SHORT}`, borderRadius: 10, borderLeft: `3px solid ${pnlColor}`, overflow: "hidden", cursor: "pointer" }}
      onClick={() => onToggle && onToggle(cardKey)}
      onMouseDown={handlePressStart} onMouseUp={handlePressEnd} onMouseLeave={handlePressEnd}
      onTouchStart={handlePressStart} onTouchEnd={handlePressEnd}>
      {/* ── Header row: TICKER | DAY % | OPEN P&L | +$ | CONF ── */}
      <CardMetricGrid style={{ padding: "12px" }}>
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 14, fontWeight: 600, color: T1, lineHeight: 1.2 }}>{trade.ticker}</span>
          {trade.name && <span style={{ fontSize: 9, color: T3, lineHeight: 1.2, marginTop: 1 }}>{trade.name}</span>}
        </div>
        <div style={{ fontSize: 11, fontWeight: 600, color: (() => { const d = Number(trade.day_change_percent) || 0; return d > 0 ? GREEN : d < 0 ? RED : T3; })(), fontFamily: "'DM Mono',monospace", textAlign: "center" }}>
          {(() => { const d = Number(trade.day_change_percent) || 0; return `${d >= 0 ? "+" : ""}${d.toFixed(1)}%`; })()}
        </div>
        <SpineCell>
          <SpinePercent value={pnlPercent} color={pnlColor} fontSize={12} />
        </SpineCell>
        <div style={{ fontSize: 13, fontWeight: 700, color: pnlColor, fontFamily: "'DM Mono',monospace", textAlign: "right", paddingRight: 6, whiteSpace: "nowrap" }}>{pnlDollars >= 0 ? "+" : "-"}${Math.abs(pnlDollars).toFixed(2)}</div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", justifyContent: "center", alignSelf: "center" }}>
          {confDelta === 0 ? (
            <div style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, fontWeight: 700, color: confidenceColor(lockInConfidence, themeKey), lineHeight: 1 }}>{lockInConfidence}%</div>
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 2, fontFamily: "'DM Mono',monospace", lineHeight: 1 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: confidenceColor(lockInConfidence, themeKey) }}>{lockInConfidence}%</span>
              <span style={{ fontSize: 9, color: confDeltaColor, margin: "0 1px" }}>→</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: confidenceColor(dynamicConfidence, themeKey) }}>{dynamicConfidence}%</span>
            </div>
          )}
        </div>
      </CardMetricGrid>

      {/* ── Sentiment row ── */}
      <CardActionRow
        statusLabel={sentiment.label}
        statusPhrase={sentiment.phrase}
        statusColor={sentiment.color}
        staleTime={isStale ? staleTime : null}
        borderColor={rulingColor}
        actions={<>
          {trade.broke_52w_high_days_ago != null && trade.broke_52w_high_days_ago <= 7 && (
            <span className={glowing ? "tag-glow" : ""} style={{ fontSize: 7, fontWeight: 800, color: GREEN, letterSpacing: .3, padding: "1px 4px", background: "#0e1a0e", borderRadius: 3, border: "1px solid #1a3a1a", flexShrink: 0 }}>52W</span>
          )}
          {trade.confluence_count > 0 && (
            <span className={glowing ? "tag-glow" : ""} style={{ fontFamily: "'DM Mono',monospace", fontSize: 7, fontWeight: 800, color: "#ddd", letterSpacing: .3, padding: "1px 4px", background: "#000", borderRadius: 3, border: "1px solid rgba(255,255,255,0.2)", textAlign: "center", flexShrink: 0 }}>{trade.confluence_count}/10</span>
          )}
          {trade.signal_fired?.length > 0 && (
            <span className={glowing ? "tag-glow" : ""} style={{ fontFamily: "'DM Mono',monospace", fontSize: 7, fontWeight: 800, color: BLUE, letterSpacing: .3, padding: "1px 4px", background: "#0a1020", borderRadius: 3, border: "1px solid #1a2a40", textAlign: "center", flexShrink: 0 }}>{trade.signal_fired.length}/9</span>
          )}
          {(sentiment.label === "CUT" || trade.outcome === "sold" || trade.outcome === "force_closed") && (
            <button onClick={(e) => { e.stopPropagation(); onDone && onDone(cardKey); }}
              style={{ background: "#222", border: `1px solid ${CARD_BORDER_LONG === "#1a3a4a" ? BLUE + "66" : "#444"}`, borderRadius: 4, color: "#ccc", fontSize: 9, fontWeight: 700, letterSpacing: 0.5, padding: "2px 8px", cursor: "pointer", flexShrink: 0 }}>
              DONE
            </button>
          )}
          {onAddToPersonal && <JournalButton
            compact
            state={journalAdded}
            onClick={(e) => {
              e.stopPropagation();
              Promise.resolve(onAddToPersonal(trade)).then(ok => {
                setJournalAdded(ok === false ? "error" : "added");
                setTimeout(() => setJournalAdded(false), 1500);
              });
            }}
          />}
        </>}
      />

      {/* ── Expanded detail — 2-column grid ── */}
      {expanded && (
        <div style={{ padding: "4px 12px 0", borderTop: `1px solid ${rulingColor}` }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px" }}>
            {[
              ["Entry price", `$${buyPrice.toFixed(2)}`],
              ["Current price", (() => { const cp = trade.current_value && investedAmount > 0 ? (trade.current_value / investedAmount) * buyPrice : null; return cp ? `$${cp.toFixed(2)}` : "—"; })()],
              ["Sector", trade.sector],
              ["Opened", formatDate(trade.buy_date)],
              ["Held", `${daysHeld(trade.buy_date)}d`],
              trade.current_rsi != null ? ["RSI", trade.current_rsi] : null,
              trade.current_volume_ratio != null ? ["Volume ratio", `${trade.current_volume_ratio}x`] : null,
              ["Entry estimate", `+${frozenTarget.toFixed(1)}%`],
              ["Entry confidence", `${frozenConfidence}%`],
              ["Current estimate", `+${dynamicEstimate.toFixed(1)}%`],
              ["Current confidence", `${dynamicConfidence}%`],
            ].filter(Boolean).map(([label, value]) => (
              <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: `1px solid ${rulingColor}` }}>
                <span style={{ fontSize: 9, color: T3, paddingBottom: 3 }}>{label}</span>
                <span style={{ fontSize: 9, color: T1, fontFamily: "'DM Mono',monospace" }}>{value}</span>
              </div>
            ))}
          </div>
          {(confluenceMethods.length > 0 || (trade.broke_52w_high_days_ago != null && trade.broke_52w_high_days_ago <= 7)) && (
            <div style={{ padding: "6px 10px 6px 4px", background: "#000", borderRadius: 7, marginTop: 4, border: "1px solid rgba(255,255,255,0.12)" }}>
              <span style={{ fontSize: 8, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, display: "block", marginBottom: 6, textAlign: "center" }}>Method confluence</span>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {confluenceMethods.map(m => (
                  <span key={m} className={glowing ? "tag-glow" : ""} onClick={(e) => { e.stopPropagation(); setExpandedMethod(expandedMethod === m ? null : m); setExpandedSignal(null); }}
                    style={{ fontSize: 9, color: expandedMethod === m ? "#000" : "#ddd", background: expandedMethod === m ? "#ddd" : "#000", padding: "2px 6px", borderRadius: 3, border: "1px solid rgba(255,255,255,0.2)", cursor: "pointer" }}>{m}</span>
                ))}
                {trade.broke_52w_high_days_ago != null && trade.broke_52w_high_days_ago <= 7 && (
                  <span key="52w" onClick={(e) => { e.stopPropagation(); setExpandedMethod(expandedMethod === "52W High" ? null : "52W High"); setExpandedSignal(null); }}
                    style={{ fontSize: 9, color: expandedMethod === "52W High" ? T1 : GREEN, background: expandedMethod === "52W High" ? "#0e2a1a" : "#0a1a0e", padding: "2px 6px", borderRadius: 3, border: `1px solid ${expandedMethod === "52W High" ? GREEN : "#1a3a1a"}`, cursor: "pointer" }}>52 Week High</span>
                )}
              </div>
              {expandedMethod && (expandedMethod === "52W High" ? (
                <div style={{ marginTop: 8, fontSize: 10, color: T1, lineHeight: 1.5, borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
                  {trade.broke_52w_high_days_ago === 1
                    ? "This stock broke its 52-week high yesterday."
                    : `This stock broke its 52-week high ${trade.broke_52w_high_days_ago} days ago.`}
                  {"\n\n"}
                  A 52-week high is the highest price a stock has traded in the past year. Breaking one signals renewed momentum — past resistance becomes new support, and big money often follows.
                </div>
              ) : METHOD_DEFINITIONS[expandedMethod] ? (
                <div style={{ marginTop: 8, fontSize: 10, color: T1, lineHeight: 1.5, borderTop: "1px solid rgba(255,255,255,0.08)", paddingTop: 8 }}>
                  {METHOD_DEFINITIONS[expandedMethod]}
                </div>
              ) : null)}
            </div>
          )}
          {/* ── Signal Indicators — which of the 9 scored above threshold ── */}
          {trade.signal_fired && trade.signal_fired.length > 0 && (() => {
            const SIGNAL_INFO = {
              rsi_momentum:       { label: "RSI",       def: "Relative Strength Index measures price momentum. Sweet spot is 40-65 — strong enough to show conviction but not so high the stock is overbought and due for a reversal." },
              volume_surge:       { label: "Volume",    def: "Today's volume vs the 20-day average. A surge above 1.5x means real institutional participation, not just retail noise. We score up to 3.5x average." },
              overnight_gap:      { label: "Gap",       def: "How much the stock gapped up at open vs yesterday's close. A positive gap shows the market opened with conviction — buyers stepped in before the bell." },
              earnings_catalyst:  { label: "Earnings",  def: "Earnings 2-7 days out create a run-up window as traders position ahead of results. The closer the date, the stronger the signal. Tonight or tomorrow is a hard disqualifier." },
              support_resistance: { label: "S&R",       def: "ATR-adaptive swing pivot analysis. Open air above current price means no resistance in the expected move range — nothing to stop the run. Price at resistance scores low." },
              relative_strength:  { label: "Rel Str",   def: "This stock's 5-day return vs SPY's 5-day return. Outperforming the market signals institutional accumulation — money is flowing into this name specifically." },
              sector_rs:          { label: "Sector RS", def: "This stock's sector ETF 5-day return vs SPY. When a sector has tailwind, stocks in it have higher base rates of continuation. Swimming with the current." },
              vwap_reclaim:       { label: "VWAP",      def: "VWAP is the price institutions use as their daily execution benchmark. Closing above it means institutions were net buyers all day — institutional conviction." },
              volatility_squeeze: { label: "Vol Squeeze", def: "Ratio of recent 5-day volatility to 20-day volatility. A low ratio means the stock is coiling — energy compressing. Compression historically precedes explosive directional moves." },
            };

            const buildValueLine = (key, vals) => {
              if (!vals) return null;
              const v = vals[key];
              if (v == null) return null;
              switch(key) {
                case "rsi_momentum": {
                  const zone = v >= 40 && v <= 65 ? "in sweet spot (40-65)" : v < 40 ? "oversold, still favorable" : "overbought, weak signal";
                  return `RSI: ${v} — ${zone}`;
                }
                case "volume_surge":
                  return `Volume: ${v}x average — ${v >= 2 ? "strong institutional participation" : v >= 1.5 ? "above-average activity" : "modest activity"}`;
                case "overnight_gap":
                  return `Gap: ${v >= 0 ? "+" : ""}${v}% — ${Math.abs(v) >= 3 ? "strong conviction at open" : Math.abs(v) >= 1 ? "moderate gap" : "mild gap, modest signal"}`;
                case "earnings_catalyst":
                  return v != null ? `Earnings in ${v} day${v === 1 ? "" : "s"} — run-up window active` : "No earnings this week — neutral";
                case "support_resistance": {
                  const sig = v.signal || "";
                  if (sig.includes("open_air")) return `Open air above${v.resistance ? ` — nearest resistance $${v.resistance}` : " — no resistance detected"}`;
                  if (sig.includes("at_resistance")) return `At resistance${v.resistance ? ` $${v.resistance}` : ""} — likely ceiling`;
                  if (sig.includes("resistance_in_range")) return `Resistance${v.resistance ? ` at $${v.resistance}` : ""} within expected move`;
                  return `S&R: ${sig || "neutral"}`;
                }
                case "relative_strength":
                  if (v.stock_5d != null && v.spy_5d != null) {
                    const diff = (v.stock_5d - v.spy_5d).toFixed(1);
                    return `Stock ${v.stock_5d >= 0 ? "+" : ""}${v.stock_5d}% vs SPY ${v.spy_5d >= 0 ? "+" : ""}${v.spy_5d}% — ${diff >= 0 ? "outperforming" : "underperforming"} by ${Math.abs(diff)}%`;
                  }
                  return null;
                case "sector_rs":
                  if (v.etf && v.etf_5d != null && v.spy_5d != null) {
                    const diff = (v.etf_5d - v.spy_5d).toFixed(1);
                    return `${v.etf} ${v.etf_5d >= 0 ? "+" : ""}${v.etf_5d}% vs SPY ${v.spy_5d >= 0 ? "+" : ""}${v.spy_5d}% — sector ${diff >= 0 ? "tailwind" : "headwind"}`;
                  }
                  return null;
                case "vwap_reclaim":
                  if (v.dist != null) {
                    const modeLabel = v.mode === "real" ? "VWAP" : "est. VWAP";
                    return `${v.dist >= 0 ? "+" : ""}${v.dist}% vs ${modeLabel} — ${v.dist >= 1 ? "well above, institutional buy-side" : v.dist >= 0 ? "just above VWAP" : "below VWAP"}`;
                  }
                  return null;
                case "volatility_squeeze":
                  if (v != null) {
                    const label = v < 0.5 ? "extreme compression — coiled spring" : v < 0.7 ? "strong compression" : v < 0.9 ? "mild compression" : "neutral volatility";
                    return `HV ratio: ${v} — ${label}`;
                  }
                  return null;
                default: return null;
              }
            };

            return (
              <div style={{ padding: "6px 10px 6px 4px", background: "#0a1020", borderRadius: 7, marginTop: 4, border: "1px solid #1a2a40" }}>
                <span style={{ fontSize: 8, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, display: "block", marginBottom: 6, textAlign: "center" }}>Signal indicators</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {trade.signal_fired.map(key => {
                    const info = SIGNAL_INFO[key] || { label: key, def: "" };
                    const isActive = expandedSignal === key;
                    return (
                      <span key={key} className={glowing ? "tag-glow" : ""}
                        onClick={(e) => { e.stopPropagation(); setExpandedSignal(isActive ? null : key); setExpandedMethod(null); }}
                        style={{ fontSize: 9, color: isActive ? T1 : BLUE, background: isActive ? "#1a2a40" : "#111a2a", padding: "2px 6px", borderRadius: 3, border: `1px solid ${isActive ? BLUE : "#1a2a40"}`, cursor: "pointer" }}>
                        {info.label}
                      </span>
                    );
                  })}
                </div>
                {expandedSignal && (() => {
                  const info = SIGNAL_INFO[expandedSignal] || { label: expandedSignal, def: "" };
                  const valueLine = buildValueLine(expandedSignal, trade.signal_values);
                  return (
                    <div style={{ marginTop: 8, fontSize: 10, color: T1, lineHeight: 1.5, borderTop: "1px solid #1a2a40", paddingTop: 8 }}>
                      {valueLine && <div style={{ color: T1, fontWeight: 500, marginBottom: 4 }}>{valueLine}</div>}
                      <div style={{ color: T3, fontSize: 9, lineHeight: 1.5 }}>{info.def}</div>
                    </div>
                  );
                })()}
              </div>
            );
          })()}
          <div style={{ borderTop: `1px solid ${rulingColor}`, paddingTop: 8, paddingBottom: 8, marginTop: 4, marginBottom: 4 }}>
            {trade.news && trade.news.filter(item => {
              if (!item.ts || item.ts === 0) return true; // no timestamp = show it
              return (Date.now() - item.ts * 1000) <= 7 * 86400000;
            }).length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {trade.news.filter(item => {
                  if (!item.ts || item.ts === 0) return true;
                  return (Date.now() - item.ts * 1000) <= 7 * 86400000;
                }).map((item, i) => (
                  <a key={i} href={item.url} target="_blank" rel="noopener noreferrer"
                    style={{ fontSize: 10, color: BLUE, textDecoration: "none", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 }}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{item.title}</span>
                    <span style={{ fontSize: 8, color: T3, whiteSpace: "nowrap", flexShrink: 0 }}>{relativeTime(item.date, item.ts)}</span>
                  </a>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 9, color: T3, fontStyle: "italic" }}>No recent news</div>
            )}
          </div>
        </div>
      )}
      {expanded && <div style={{ borderTop: `1px solid ${rulingColor}`, margin: "0 12px" }} />}
      {/* ── Expand triangle — apex at col3 right edge = decimal position ── */}
      <CardMetricGrid style={{ padding: "8px 12px 6px", alignItems: "start" }}>
        <div style={{ gridColumn: "1 / 3" }}></div>
        <SpineCell><SpineTriangle color={pnlColor} expanded={expanded} /></SpineCell>
        <div></div>
        <div></div>
      </CardMetricGrid>
    </div>
  );
}

// ─── EXTENDED RUNNER CARD ─────────────────────────────────────────────────────
function ExtendedRunnerCard({ trade, onHide, expanded, onToggle }) {
  const buyPrice = trade.buy_price || 0;
  const currentValue = trade.current_value || trade.invested_amount || 10;
  const investedAmount = trade.invested_amount || 10;
  const brainPnlPercent = trade.actual_move || 0;
  const totalPnlPercent = buyPrice > 0 ? (currentValue - investedAmount) / investedAmount * 100 : 0;
  const extraPercent = totalPnlPercent - brainPnlPercent;
  const pnlColor = totalPnlPercent >= 0 ? GREEN : RED;

  const getSentiment = () => {
    if (totalPnlPercent > brainPnlPercent + 3) return `I sold at +${brainPnlPercent.toFixed(1)}%. Currently at +${totalPnlPercent.toFixed(1)}%. Still climbing.`;
    if (totalPnlPercent > brainPnlPercent) return `I sold at +${brainPnlPercent.toFixed(1)}%. Currently at +${totalPnlPercent.toFixed(1)}%. Holding steady.`;
    if (totalPnlPercent > 0) return `I sold at +${brainPnlPercent.toFixed(1)}%. Currently at +${totalPnlPercent.toFixed(1)}%. Momentum fading.`;
    return `URGENT: I sold at +${brainPnlPercent.toFixed(1)}%. Now at ${totalPnlPercent.toFixed(1)}%. Close immediately.`;
  };

  return (
    <div style={{ background: "#0f0a18", border: `1px solid #1a1030`, borderRadius: 10, borderLeft: `3px solid ${PURPLE}`, overflow: "hidden" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 12px 6px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 14, fontWeight: 600, color: T1 }}>{trade.ticker}</span>
          <span style={{ fontSize: 8, fontWeight: 700, color: PURPLE, textTransform: "uppercase", letterSpacing: .5, padding: "2px 6px", background: "#1a1030", borderRadius: 4 }}>Extended play</span>
        </div>
        <button onClick={(e) => { e.stopPropagation(); onHide(trade.id); }} style={{ background: "transparent", border: "none", color: T3, fontSize: 14, cursor: "pointer", padding: "2px 6px" }}>×</button>
      </div>
      <div style={{ padding: "0 12px 8px", cursor: "pointer" }} onClick={() => onToggle(trade.id)}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: pnlColor, fontFamily: "'DM Mono',monospace" }}>{totalPnlPercent >= 0 ? "+" : ""}{totalPnlPercent.toFixed(1)}%</span>
          <span style={{ fontSize: 12, color: pnlColor, fontFamily: "'DM Mono',monospace" }}>{(currentValue - investedAmount) >= 0 ? "+" : ""}${Math.abs(currentValue - investedAmount).toFixed(2)}</span>
        </div>
        <div style={{ fontSize: 10, color: PURPLE, lineHeight: 1.5 }}>{getSentiment()}</div>
      </div>
      {expanded && (
        <div style={{ padding: "8px 12px 12px", borderTop: `1px solid #1a1030` }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Brain's P&L</span>
              <span style={{ fontSize: 10, color: GREEN }}>+{brainPnlPercent.toFixed(1)}%</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Your total P&L</span>
              <span style={{ fontSize: 10, color: pnlColor }}>{totalPnlPercent >= 0 ? "+" : ""}{totalPnlPercent.toFixed(1)}%</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Extra by holding</span>
              <span style={{ fontSize: 10, color: extraPercent >= 0 ? GREEN : RED }}>{extraPercent >= 0 ? "+" : ""}{extraPercent.toFixed(1)}%</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Buy price</span>
              <span style={{ fontSize: 10, color: T1 }}>${buyPrice.toFixed(2)}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Total days held</span>
              <span style={{ fontSize: 10, color: T1 }}>{trade.closed_days || 1}d</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Opened</span>
              <span style={{ fontSize: 10, color: T1 }}>{trade.buy_date}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ fontSize: 10, color: T3 }}>Brain sold</span>
              <span style={{ fontSize: 10, color: T1 }}>{trade.sell_date}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── EXPAND BUTTON ────────────────────────────────────────────────────────────
function ExpandButton({ isExpanded, onToggle, totalCount, label }) {
  if (totalCount <= 20) return null;
  return (
    <button onClick={onToggle} style={{ width: "100%", padding: "10px", background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 10, cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
      <span style={{ fontSize: 10, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5 }}>{isExpanded ? "Show top 20 only" : `Show all ${totalCount} ${label}`}</span>
      <svg width="44" height="4" viewBox="0 0 44 4"><polygon points={isExpanded ? "22,0 2,4 42,4" : "22,4 2,0 42,0"} fill={T3} /></svg>
    </button>
  );
}

// ─── TICKER BANNER ────────────────────────────────────────────────────────────
const BANNER_TICKERS = ["VIX", "SPY", "QQQ", "IWM", "NVDA", "TLT", "BTC-USD", "GLD"];
const TICKER_GREEN   = "#22c55e";
const TICKER_RED     = "#ef4444";
const TICKER_FLAT    = "#666";

function TickerBanner({ openPositions }) {
  const [prices, setPrices] = React.useState({});
  const intervalRef = React.useRef(null);

  const fetchPrices = async () => {
    try {
      const data = await apiFetch("/banner-prices");
      if (data && Object.keys(data).length > 0) {
        setPrices(data);
      }
    } catch {}
  };

  React.useEffect(() => {
    fetchPrices();
    intervalRef.current = setInterval(fetchPrices, 2.5 * 60 * 1000);
    return () => clearInterval(intervalRef.current);
  }, [openPositions]);

  const positionTickers = openPositions.filter(p => p.outcome === "open").map(p => p.ticker);
  // Positions first, then macro tickers — deduplicated
  const orderedTickers = [
    ...positionTickers,
    ...BANNER_TICKERS.filter(t => !positionTickers.includes(t))
  ];
  const items = orderedTickers.filter(t => prices[t]);

  if (items.length === 0) return <div style={{ height: 28 }} />;

  // Duplicate for seamless loop
  const doubled = [...items, ...items];

  const animDuration = Math.max(doubled.length * 2.5, 20);

  return (
    <div style={{
      height: 28, overflow: "hidden", position: "relative",
      borderBottom: `1px solid ${BORDER}`,
    }}>
      {/* Fade left edge */}
      <div style={{ position: "absolute", left: 0, top: 0, width: 28, height: "100%", background: `linear-gradient(to right, ${BG}, transparent)`, zIndex: 2, pointerEvents: "none" }} />
      {/* Fade right edge */}
      <div style={{ position: "absolute", right: 0, top: 0, width: 28, height: "100%", background: `linear-gradient(to left, ${BG}, transparent)`, zIndex: 2, pointerEvents: "none" }} />

      <style>{`
        @keyframes bannerScroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>

      <div style={{
        display: "flex", alignItems: "center", height: "100%",
        width: "max-content",
        animation: `bannerScroll ${animDuration}s linear infinite`,
      }}>
        {doubled.map((ticker, idx) => {
          const d = prices[ticker];
          if (!d) return null;
          const dir = d.change > 0.005 ? "up" : d.change < -0.005 ? "down" : "flat";
          const color = dir === "up" ? TICKER_GREEN : dir === "down" ? TICKER_RED : TICKER_FLAT;
          const sign = d.change >= 0 ? "+" : "";
          return (
            <div key={`${ticker}-${idx}`} style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "0 14px", height: "100%",
              borderRight: `1px solid ${BORDER}`, whiteSpace: "nowrap",
            }}>
              <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 9, fontWeight: 600, color: "#777", letterSpacing: .5 }}>{ticker}</span>
              <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 10, fontWeight: 500, color: "#e8e8e8" }}>
                {d.price < 100 ? d.price.toFixed(2) : d.price.toFixed(1)}
              </span>
              <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 9, fontWeight: 600, color }}>
                {sign}{(d.change_pct || d.changePct || 0).toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── THEME TOGGLE ─────────────────────────────────────────────────────────────
function ThemeToggle({ themeKey, onToggle, T3: t3Color }) {
  const isNavy = themeKey === "navy";
  const gradId = isNavy ? "sphereNavy" : "sphereBlack";
  const ringColor = t3Color || (isNavy ? "#5a7a96" : "#777");
  return (
    <button onClick={onToggle} style={{ cursor: "pointer", flexShrink: 0, lineHeight: 0, width: TOOLBAR_CONTROL_H, height: TOOLBAR_CONTROL_H, padding: 0, border: "none", background: "transparent", display: "flex", alignItems: "center", justifyContent: "center" }} title={`Theme: ${themeKey}`}>
      <svg width={TOOLBAR_CONTROL_H} height={TOOLBAR_CONTROL_H} viewBox="0 0 26 26" style={{ verticalAlign: "middle", display: "block" }}>
        <defs>
          <radialGradient id={gradId} cx="35%" cy="32%" r="60%">
            {isNavy ? <>
              <stop offset="0%" stopColor="#a8d4f5"/>
              <stop offset="48%" stopColor="#1a6bbf"/>
              <stop offset="100%" stopColor="#0d4a8a"/>
            </> : <>
              <stop offset="0%" stopColor="#555"/>
              <stop offset="48%" stopColor="#1a1a1a"/>
              <stop offset="100%" stopColor="#000"/>
            </>}
          </radialGradient>
        </defs>
        <circle cx="13" cy="13" r="11" stroke={ringColor} strokeWidth="1.5" fill="none"/>
        <circle cx="13" cy="13" r="7.5" fill={`url(#${gradId})`}/>
      </svg>
    </button>
  );
}


function SettingsIcon({ color }) {
  // Hex nut icon — hexagon outline with inner circle, same as WeBull settings icon
  return (
    <svg width={TOOLBAR_CONTROL_H} height={TOOLBAR_CONTROL_H} viewBox="0 0 26 26" style={{ verticalAlign: "middle", display: "block" }}>
      <polygon points="13,3 22,8 22,18 13,23 4,18 4,8"
        stroke={color} strokeWidth="2" fill="none" strokeLinejoin="round"/>
      <circle cx="13" cy="13" r="4" stroke={color} strokeWidth="2" fill="none"/>
    </svg>
  );
}

function SettingsDrawer({ open, onClose, T1, T2, T3, BORDER, BG, CARD, GREEN, BLUE, AMBER }) {
  const API = "https://swingdesk-brain-production-205e.up.railway.app";
  const [notifyOn, setNotifyOn] = React.useState(true);
  const [testStatus, setTestStatus] = React.useState(null);
  const [loaded, setLoaded] = React.useState(false);
  const [settings, setSettings] = React.useState({});

  React.useEffect(() => {
    if (open && !loaded) {
      fetch(`${API}/api/notification-settings`)
        .then(r => r.json())
        .then(d => { setNotifyOn(d.notify_on_close !== false); setSettings(d); setLoaded(true); })
        .catch(() => setLoaded(true));
    }
  }, [open]);

  const toggle = async () => {
    const newVal = !notifyOn;
    setNotifyOn(newVal);
    try {
      await fetch(`${API}/api/notification-settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notify_on_close: newVal })
      });
    } catch(e) {}
  };

  const sendTest = async () => {
    setTestStatus("sending");
    try {
      const r = await fetch(`${API}/api/test-notification`, { method: "POST" });
      const d = await r.json();
      setTestStatus(d.success ? "sent" : "error");
    } catch(e) {
      setTestStatus("error");
    }
    setTimeout(() => setTestStatus(null), 4000);
  };

  const provider = settings.provider || "twilio";
  const telegramConfigured = settings.telegram_configured;

  if (!open) return null;
  return (
    <>
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,0.5)" }}/>
      <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 101, background: CARD, borderRadius: "16px 16px 0 0", border: `1px solid ${BORDER}`, padding: "20px 20px 36px" }}>
        <div style={{ width: 36, height: 4, background: BORDER, borderRadius: 2, margin: "0 auto 20px" }}/>
        <div style={{ fontSize: 14, fontWeight: 700, color: T1, marginBottom: 16 }}>Settings</div>

        {/* Notifications section */}
        <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .5, marginBottom: 10 }}>Notifications</div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 12px", background: BG, borderRadius: 10, border: `1px solid ${BORDER}`, marginBottom: 8 }}>
          <div>
            <div style={{ fontSize: 13, color: T1, fontWeight: 500 }}>Notify when a position closes</div>
            <div style={{ fontSize: 10, color: T3, marginTop: 2 }}>
              {provider === "telegram" ? "via Telegram bot" : "SMS via Twilio"} — cut, force close, or reversal
            </div>
          </div>
          <div onClick={toggle} style={{ cursor: "pointer", width: 44, height: 24, borderRadius: 12, background: notifyOn ? GREEN : BORDER, transition: "background 0.2s", position: "relative", flexShrink: 0, marginLeft: 12 }}>
            <div style={{ position: "absolute", top: 2, left: notifyOn ? 22 : 2, width: 20, height: 20, borderRadius: "50%", background: "#fff", transition: "left 0.2s" }}/>
          </div>
        </div>

        {/* Telegram setup info */}
        <div style={{ padding: "10px 12px", background: BG, borderRadius: 10, border: `1px solid ${telegramConfigured ? BLUE + "44" : BORDER}`, marginBottom: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ fontSize: 12, color: T1, fontWeight: 500 }}>Telegram Bot</div>
            <div style={{ fontSize: 10, fontWeight: 600, color: telegramConfigured ? GREEN : T3 }}>
              {telegramConfigured ? "✓ configured" : "not configured"}
            </div>
          </div>
          {!telegramConfigured && (
            <div style={{ fontSize: 10, color: T3, marginTop: 4, lineHeight: 1.5 }}>
              To enable: message @BotFather on Telegram, create a bot, then add TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID + NOTIFY_PROVIDER=telegram to Railway env vars.
            </div>
          )}
        </div>

        {/* Test button */}
        <button onClick={sendTest} disabled={testStatus === "sending"}
          style={{ width: "100%", padding: "10px 0", borderRadius: 10, border: `1px solid ${BLUE}`, background: "transparent", color: testStatus === "sent" ? GREEN : testStatus === "error" ? "#f87171" : BLUE, fontSize: 13, fontWeight: 600, cursor: "pointer", marginTop: 4 }}>
          {testStatus === "sending" ? "Sending..." : testStatus === "sent" ? "✓ Test sent" : testStatus === "error" ? "Failed — check Railway vars" : "Send Test Notification"}
        </button>
      </div>
    </>
  );
}

// ─── MAIN APP ─────────────────────────────────────────────────────────────────
// ─── ERROR BOUNDARY ───────────────────────────────────────────────────────────
class ErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { hasError: false, error: null }; }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, info) { console.error("SwingDesk crash:", error, info?.componentStack); }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", minHeight: "100vh", background: "#080809", color: "#e8e8e8", padding: 24, gap: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#f87171", letterSpacing: 1 }}>RENDER ERROR</div>
          <div style={{ fontSize: 11, color: "#777", textAlign: "center", maxWidth: 280, lineHeight: 1.6 }}>Something crashed. Usually caused by unexpected data from the brain.</div>
          <div style={{ fontSize: 9, color: "#555", fontFamily: "monospace", background: "#111", border: "1px solid #222", borderRadius: 6, padding: "8px 12px", maxWidth: 320, wordBreak: "break-all" }}>{this.state.error?.message || "Unknown error"}</div>
          <button onClick={() => window.location.reload()} style={{ marginTop: 8, padding: "10px 24px", background: "transparent", border: "1px solid #444", borderRadius: 8, color: "#e8e8e8", fontSize: 12, fontWeight: 600, cursor: "pointer", letterSpacing: .5 }}>RELOAD</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [loadProgress, setLoadProgress] = useState(0);
  const [loadStatus, setLoadStatus] = useState("Connecting to brain...");
  const [loaded, setLoaded] = useState(false);
  const [themeKey, setThemeKey] = useState(() => {
    try { return localStorage.getItem("swingdesk_theme") || "black"; } catch { return "black"; }
  });

  // Refresh all color tokens + body bg synchronously before render
  refreshThemeTokens(themeKey);

  const [picks, setPicks] = useState({ longs: [], shorts: [] });
  const [extendedRunners, setExtendedRunners] = useState([]);
  const [openPositions, setOpenPositions] = useState([]);
  const [todayClosed, setTodayClosed] = useState([]);
  const [dismissedClosed, setDismissedClosed] = useState({});
  const [virtualTrades, setVirtualTrades] = useState([]);
  const [predictions, setPredictions] = useState([]);
  const [weights, setWeights] = useState({});
  const [pdtUsed, setPdtUsed] = useState(0);
  const [pdtRemaining, setPdtRemaining] = useState(3);
  const [methodStats, setMethodStats] = useState(null);
  const [expandedMethods, setExpandedMethods] = useState({});
  const [weightsHistory, setWeightsHistory] = useState([]);
  const [perfHistory, setPerfHistory] = useState([]);
  const [lastAudit, setLastAudit] = useState(null);
  const [lastScan, setLastScan] = useState(null);
  const [totalScanned, setTotalScanned] = useState(0);
  const [queueStatus, setQueueStatus] = useState(null);
  const [openExecution, setOpenExecution] = useState(null);
  const [recoveringOpen, setRecoveringOpen] = useState(false);

  const [tab, setTab] = useState("today");
  const [tabLoading, setTabLoading] = useState(false);
  const [longSub, setLongSub] = useState("buy");
  const [closedTab, setClosedTab] = useState("all");
  const [analyticsPage, setAnalyticsPage] = useState("performance"); // performance | closed
  const [portfolioTab, setPortfolioTab] = useState("brain"); // brain | neural | personal
  const [nnPositions, setNnPositions] = useState([]);
  const [nnPicks, setNnPicks] = useState({ recommended_longs: [], recommended_shorts: [] });
  const [nnStats, setNnStats] = useState(null);
  const [personalTrades, setPersonalTrades] = useState([]);
  const [addingToPersonal, setAddingToPersonal] = useState({});
  const [sortMode, setSortMode] = useState("smart");
  const SORT_OPTIONS = [
    { id: "smart",      label: "Smart"      },
    { id: "gain",       label: "% Gain"     },
    { id: "loss",       label: "% Loss"     },
    { id: "conf_hi",    label: "Conf ↑"     },
    { id: "conf_lo",    label: "Conf ↓"     },
    { id: "method_hi",  label: "Methods ↑"  },
    { id: "method_lo",  label: "Methods ↓"  },
    { id: "oldest",     label: "Oldest"     },
    { id: "newest",     label: "Newest"     },
  ];
  const [expandedCards, setExpandedCards] = useState({});
  const [doneCuts, setDoneCuts] = useState({});
  const [expandedRunners, setExpandedRunners] = useState({});
  const [hiddenRunners, setHiddenRunners] = useState({});
  const [buyListExpanded, setBuyListExpanded] = useState(false);
  const [sellListExpanded, setSellListExpanded] = useState(false);
  const [dismissedPostClose, setDismissedPostClose] = useState({});

  const [perfTimeframe, setPerfTimeframe] = useState("M");
  const [feeAdjusted, setFeeAdjusted] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [showNetInfo, setShowNetInfo] = useState(false);


  const handleAddToPersonal = async (item, sourcePortfolio = "brain") => {
    const ticker = item.ticker || item.pick?.ticker;
    if (!ticker || addingToPersonal[ticker]) return;
    setAddingToPersonal(prev => ({ ...prev, [ticker]: true }));
    try {
      const body = {
        ticker,
        direction: item.direction || "long",
        buy_price: item.buy_price || item.price || 0,
        invested_amount: item.invested_amount || 10,
        sector: item.sector,
        source_portfolio: sourcePortfolio,
      };
      const result = await apiFetch("/personal-trades/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (result.success) {
        const fresh = await apiFetch("/personal-trades").catch(() => []);
        setPersonalTrades(fresh);
        setAddingToPersonal(prev => ({ ...prev, [ticker]: false }));
        return true;
      }
    } catch {}
    setAddingToPersonal(prev => ({ ...prev, [ticker]: false }));
    return false;
  };

  const recoverMissedOpen = async () => {
    if (recoveringOpen) return;
    setRecoveringOpen(true);
    try {
      const result = await apiFetch("/recover-missed-open", { method: "POST" });
      setOpenExecution(result);
      const [positions, perfData, statsData] = await Promise.all([
        apiFetch("/open-positions-dynamic").catch(() => apiFetch("/open-positions").catch(() => [])),
        apiFetch("/perf-history").catch(() => []),
        apiFetch("/stats").catch(() => null),
      ]);
      setOpenPositions(positions);
      if (statsData?.open_execution) setOpenExecution(statsData.open_execution);
      if (statsData?.queue) setQueueStatus(statsData.queue);
      buildPerfHistory(perfData, positions);
    } catch (error) {
      setOpenExecution(prev => ({ ...(prev || {}), last_error: error.message }));
    }
    setRecoveringOpen(false);
  };
  // ── Initial data load ──
  useEffect(() => {
    (async () => {
      try {
        setLoadStatus("Waking up the brain..."); setLoadProgress(20);

        // Show cached picks instantly while fresh data loads
        const cachedPicks = localStorage.getItem("swingdesk_picks");
        if (cachedPicks) {
          try {
            const p = JSON.parse(cachedPicks);
            setPicks({ longs: (p.longs || []).map(mapPickFields), shorts: (p.shorts || []).map(mapPickFields) });
            setTotalScanned(p.total_scanned || 0);
            setLastScan(p.cache_time || p.generated_at || null);
          } catch {}
        }

        setLoadStatus("Loading SwingDesk..."); setLoadProgress(50);

        // Fire ping in background to warm Railway — don't await, don't block
        apiFetch("/ping").catch(() => {});

        // Fire all requests in parallel
        const [picksData, positions, statsData, runnersData, perfData, closedData,
               nnPicksData, nnPositionsData, nnStatsData, personalData] = await Promise.all([
          apiFetch("/picks").catch(() => ({ longs: [], shorts: [] })),
          apiFetch("/open-positions-dynamic").catch(() => apiFetch("/open-positions").catch(() => [])),
          apiFetch("/stats").catch(() => ({})),
          apiFetch("/extended-runners").catch(() => []),
          apiFetch("/perf-history").catch(() => []),
          apiFetch("/today-closed").catch(() => []),
          apiFetch("/nn-picks").catch(() => ({ recommended_longs: [], recommended_shorts: [] })),
          apiFetch("/nn-positions").catch(() => []),
          apiFetch("/nn-stats").catch(() => null),
          apiFetch("/personal-trades").catch(() => []),
        ]);

        // Auto-backfill lock_in_confidence for existing trades silently
        apiFetch("/backfill-lock-in-confidence", { method: "POST" }).catch(() => {});

        setPicks({ longs: (picksData.longs || []).map(mapPickFields), shorts: (picksData.shorts || []).map(mapPickFields) });
        setTotalScanned(picksData.total_scanned || 0);
        setLastScan(picksData.cache_time || picksData.generated_at || null);
        localStorage.setItem("swingdesk_picks", JSON.stringify(picksData));

        setOpenPositions(positions);
        setTodayClosed(closedData || []);
        setExtendedRunners(runnersData);
        setWeights(statsData.weights || {});
        setLastAudit(statsData.last_audit || null);
        setQueueStatus(statsData.queue || null);
        setOpenExecution(statsData.open_execution || null);
        setPdtUsed(statsData.pdt_used || 0);
        setPdtRemaining(statsData.pdt_remaining ?? 3);
        buildPerfHistory(perfData, positions);
        setNnPicks(nnPicksData || { recommended_longs: [], recommended_shorts: [] });
        setNnPositions(nnPositionsData || []);
        setNnStats(nnStatsData);
        setPersonalTrades(personalData || []);

        setLoadStatus("Ready"); setLoadProgress(100);
      } catch (error) {
        console.error("Init error:", error);
        setLoadStatus("Connected with errors");
        setLoadProgress(100);
      }
      setTimeout(() => setLoaded(true), 300);
    })();
  }, []);

  // ── Build perf history including unrealized open position gains ──
  function buildPerfHistory(perfData, positions) {
    const allPoints = perfData || [];
    const closedHistory = allPoints.filter(p => !p.intraday);
    const intradayHistory = allPoints.filter(p => p.intraday);

    // Base settled balance — last closed trade result
    const baseBalance = closedHistory.filter(p => !p.seed).length > 0
      ? closedHistory.filter(p => !p.seed)[closedHistory.filter(p => !p.seed).length - 1].virtual
      : 1000.0;

    // Seed point — always $1000, 30 days ago, marked as seed
    const seedPoint = {
      date: new Date(Date.now() - 86400000 * 30).toISOString().split("T")[0],
      virtual: 1000.0,
      ts: Date.now() - 86400000 * 30,
      seed: true,
    };

    // Live "now" point — always inject if positions exist, even if unrealizedPnl is 0
    // This ensures today always has at least one data point for chart and Day's P&L
    const unrealizedPnl = (positions || []).reduce((total, trade) => {
      const invested = trade.invested_amount || 10;
      const current = trade.current_value || invested;
      return total + (current - invested);
    }, 0);

    const todayStr = new Date().toISOString().split("T")[0];
    const livePoint = (positions || []).some(t => t.outcome === "open") ? [{
      date: todayStr,
      virtual: round2(baseBalance + unrealizedPnl),
      ts: Date.now(),
      intraday: true,
      live: true,
    }] : [];

    // Build combined — seed + closed + intraday from backend + live now
    const combined = [seedPoint, ...closedHistory.filter(p => !p.seed), ...intradayHistory, ...livePoint];
    combined.sort((a, b) => a.ts - b.ts);
    setPerfHistory(combined);
  }

  function round2(n) { return Math.round(n * 100) / 100; }

  // ── Lazy load tab data ──
  useEffect(() => {
    if (!loaded) return;
    if (tab === "virtual" && virtualTrades.length === 0) {
      setTabLoading(true);
      apiFetch("/virtual-trades").then(data => { setVirtualTrades(data); setTabLoading(false); }).catch(() => setTabLoading(false));
    }
    if ((tab === "virtual" || tab === "intel") && !methodStats) {
      apiFetch("/method-stats").then(data => {
        setMethodStats(data.methods || {});
        setWeightsHistory(data.weights_history || []);
      }).catch(() => {});
    }
    if (tab === "intel" && predictions.length === 0) {
      setTabLoading(true);
      apiFetch("/predictions").then(data => { setPredictions(data); setTabLoading(false); }).catch(() => setTabLoading(false));
    }
  }, [tab, loaded]);

  // ── 5-minute refresh ──
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const [positions, perfData, closedData, statsData] = await Promise.all([
          apiFetch("/open-positions-dynamic").catch(() => apiFetch("/open-positions").catch(() => [])),
          apiFetch("/perf-history").catch(() => []),
          apiFetch("/today-closed").catch(() => []),
          apiFetch("/stats").catch(() => null),
        ]);
        setOpenPositions(positions);
        setTodayClosed(closedData || []);
        if (statsData?.open_execution) setOpenExecution(statsData.open_execution);
        buildPerfHistory(perfData, positions);
      } catch {}
    }, 2.5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // ── Computed values ──
  const openTickers = new Set(openPositions.filter(t => t.outcome === "open").map(t => t.ticker));
  const allBuyPicks = picks.longs.filter(pick => !openTickers.has(pick.ticker));
  const allShortPicks = picks.shorts.filter(pick => !openTickers.has(pick.ticker));
  const today = new Date().toISOString().split("T")[0];

  const openLongPositions = openPositions.filter(t => t.direction === "long" && t.outcome === "open");
  const openShortPositions = openPositions.filter(t => t.direction === "short" && t.outcome === "open");

  const isWeekendNow = (() => { const d = new Date().getDay(); return d === 0 || d === 6; })();
  // Sell Today = previous session positions (buy_date < today), active on trading days
  const sellTodayPositions = isWeekendNow ? openLongPositions : openLongPositions.filter(t => t.buy_date < today);
  // Holding = current session positions (opened today)
  const holdingPositions = openLongPositions.filter(t => t.buy_date === today);
  // Keep for legacy compat
  const longSellList = sellTodayPositions;
  const shortCoverList = isWeekendNow ? [] : openPositions.filter(t => t.buy_date < today && t.outcome === "open" && t.direction === "short");

  // Recently closed = closed positions not yet dismissed, within 30 days
  const thirtyDaysAgo = new Date(Date.now() - 30 * 86400000).toISOString().split("T")[0];
  const recentlyClosed = openPositions.filter(t =>
    t.outcome !== "open" &&
    !dismissedClosed[t.id] &&
    (t.sell_date == null || t.sell_date >= thirtyDaysAgo)
  );

  // Sort positions: CUT first (worst P&L), then rest by P&L descending
  function getSentimentPriority(trade) {
    const pnl = trade.current_pnl_percent || 0;
    const icon = trade.sentiment_icon;
    if (trade.is_post_close) return -1;
    if (icon === "x") return 0;
    if (pnl < 0) return 2;
    return 1;
  }

  function sortPositions(positions) {
    const arr = [...positions];
    switch (sortMode) {
      case "gain":      return arr.sort((a, b) => (b.current_pnl_percent || 0) - (a.current_pnl_percent || 0));
      case "loss":      return arr.sort((a, b) => (a.current_pnl_percent || 0) - (b.current_pnl_percent || 0));
      case "conf_hi":   return arr.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));
      case "conf_lo":   return arr.sort((a, b) => (a.confidence || 0) - (b.confidence || 0));
      case "method_hi": return arr.sort((a, b) => (b.confluence_count || 0) - (a.confluence_count || 0));
      case "method_lo": return arr.sort((a, b) => (a.confluence_count || 0) - (b.confluence_count || 0));
      case "oldest":    return arr.sort((a, b) => (a.buy_date || "").localeCompare(b.buy_date || ""));
      case "newest":    return arr.sort((a, b) => (b.buy_date || "").localeCompare(a.buy_date || ""));
      default:          return arr.sort((a, b) => {
        const ap = getSentimentPriority(a), bp = getSentimentPriority(b);
        if (ap !== bp) return ap - bp;
        const confDiff = (b.confidence || 0) - (a.confidence || 0);
        if (confDiff !== 0) return confDiff;
        return (b.current_pnl_percent || 0) - (a.current_pnl_percent || 0);
      });
    }
  }

  const sortedSellToday = sortPositions(sellTodayPositions);
  const sortedHolding = sortPositions(holdingPositions);
  const sortedLongPositions = sortPositions(openLongPositions);
  const sortedShortPositions = sortPositions(openShortPositions);

  const buyVisible = buyListExpanded ? allBuyPicks : allBuyPicks.slice(0, 20);
  const sellVisible = sellListExpanded ? longSellList : longSellList.slice(0, 20);

  // Live P&L from open positions
  const livePnl = openPositions.reduce((total, trade) => {
    const invested = trade.invested_amount || 10;
    const current = trade.current_value || invested;
    return total + (current - invested);
  }, 0);

  const resolved = predictions.filter(p => p.outcome !== "pending");
  // Single source of truth: win rate from virtual_trades closed outcomes only
  const _closedForWinRate = virtualTrades.filter(t => t.outcome !== "open");
  const winRate = _closedForWinRate.length > 0
    ? Math.round(_closedForWinRate.filter(t => t.outcome === "hit").length / _closedForWinRate.length * 100)
    : null;

  // Portfolio balance = last closed balance + unrealized P&L
  const tradingPerfPoints = perfHistory.filter(p => {
    const d = new Date(p.ts);
    return d.getDay() >= 1 && d.getDay() <= 5;
  });
  const lastTradingDate = tradingPerfPoints.length > 0
    ? tradingPerfPoints.reduce((max, p) => p.date > max ? p.date : max, "")
    : today;

  const perfFiltered = useMemo(() => {
    if (!perfHistory.length) return [];
    const cutoffDays = { D: 1, W: 7, M: 30, "3M": 90, Y: 365, ALL: 9999 }[perfTimeframe] || 30;
    const filtered = perfHistory.filter(point => point.ts >= Date.now() - cutoffDays * 86400000);
    return filtered.length > 0 ? filtered : perfHistory.filter(p => p.date === lastTradingDate);
  }, [perfHistory, perfTimeframe, lastTradingDate]);

  // settledBalance: always use the last non-intraday point from FULL history
  // never from filtered window — prevents chart regressing to $1000 on narrow timeframes
  const settledBalance = (() => {
    const allSettled = perfHistory.filter(p => !p.intraday && !p.seed);
    return allSettled.length ? allSettled[allSettled.length - 1].virtual : 1000;
  })();
  const perfLast = round2(settledBalance + livePnl);

  // perfFirst: baseline for percent gain calculation
  // 1D → yesterday's last settled balance (what we started today with)
  // ALL → always $1000 seed
  // other timeframes → first point in filtered window
  const seedPoint = perfHistory.find(p => p.seed);
  const perfFirst = (() => {
    if (perfTimeframe === "ALL") return seedPoint?.virtual || 1000;
    if (perfTimeframe === "D") {
      // Use yesterday's last non-intraday, non-seed point as today's baseline
      const todayStr = new Date().toISOString().split("T")[0];
      const yesterday = perfHistory.filter(p => !p.intraday && !p.seed && p.date < todayStr);
      if (yesterday.length > 0) return yesterday[yesterday.length - 1].virtual;
      return settledBalance; // fallback
    }
    return perfFiltered.length ? perfFiltered[0].virtual : 1000;
  })();

  const perfChange = perfLast - perfFirst;
  const perfPercent = perfFirst > 0 ? (perfChange / perfFirst * 100) : 0;
  const perfUp = perfChange >= 0;

  if (!loaded) return <LoadingScreen progress={loadProgress} statusText={loadStatus} />;

  // ── NAV ──
  const NAV = [
    { id: "today", label: "Today", icon: "M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" },
    { id: "virtual", label: "Analytics", icon: "M22 12h-4l-3 9L9 3l-3 9H2" },
    { id: "intel", label: "Brain", brain: true },
  ];

  return (
    <ErrorBoundary>
    <div style={{ fontFamily: "'DM Sans',system-ui,sans-serif", background: BG, color: T1, minHeight: "100vh", maxWidth: 390, margin: "0 auto", position: "relative", paddingBottom: 64 }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');
        *{box-sizing:border-box;margin:0;padding:0}
        html,body{background:#000;}
        ::-webkit-scrollbar{width:0}
        @keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
        .fadeIn{animation:fadeUp .2s ease}
        @keyframes tagGlow{0%{box-shadow:none;opacity:1}50%{box-shadow:0 0 4px 1px currentColor;opacity:0.85}100%{box-shadow:none;opacity:1}}
        .tag-glow{animation:tagGlow 0.9s ease-in-out 0.3s}
      `}</style>

      <TickerBanner openPositions={openPositions} />

      {/* ════════ TODAY TAB ════════ */}
      {tab === "today" && (
        <div className="fadeIn">

          {/* ── Portfolio Tab Bar: Brain | Neural | Personal ── */}
          <div style={{ display: "flex", gap: 4, padding: "10px 16px 0", marginBottom: 2 }}>
            {[
              ["brain",    "Brain",    BLUE],
              ["neural",   "Neural",   "#a78bfa"],
              ["personal", "Personal", AMBER],
            ].map(([id, label, color]) => (
              <button key={id} onClick={() => setPortfolioTab(id)} style={{
                flex: 1, padding: "7px 0", borderRadius: 8, fontSize: 11, fontWeight: 700,
                border: `1px solid ${portfolioTab === id ? color + "66" : BORDER}`,
                cursor: "pointer", letterSpacing: .4, transition: ".15s",
                background: portfolioTab === id ? color + "18" : "transparent",
                color: portfolioTab === id ? color : T3,
              }}>{label}</button>
            ))}
          </div>

          {/* ── BRAIN PORTFOLIO ── */}
          {portfolioTab === "brain" && <div>
          <div style={{ padding: "10px 16px 14px" }}>
            {/* SwingDesk Brain row — evenly spaced across full width */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, minHeight: 24 }}>
              <div style={{ fontSize: 10, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .8 }}>SwingDesk Brain</div>
              {lastScan && <div style={{ fontSize: 9, color: T3 }}>Scanned {totalScanned} tickers</div>}
              <div style={{ display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
                <div style={{ position: "relative", display: "flex", alignItems: "center" }}>
                  <button onClick={() => setShowNetInfo(v => !v)}
                    style={{ background: "transparent", border: "none", cursor: "pointer", color: T3, fontSize: 11, padding: "0 2px", lineHeight: 1, display: "flex", alignItems: "center" }}>ⓘ</button>
                  {showNetInfo && (
                    <div style={{ position: "absolute", right: 0, top: 20, width: 200, background: "#1a1a1e", border: `1px solid ${BORDER}`, borderRadius: 8, padding: "8px 10px", zIndex: 50 }}>
                      <div style={{ fontSize: 10, color: T2, lineHeight: 1.5 }}>Deducts an estimated $0.02 fee per position to reflect real-world trading costs. Toggle off to see gross P&L.</div>
                    </div>
                  )}
                </div>
                <button onClick={() => setFeeAdjusted(f => !f)} style={{ height: TOOLBAR_CONTROL_H, padding: "0 10px", borderRadius: 20, fontSize: 9, fontWeight: 600, border: `1px solid ${feeAdjusted ? AMBER + "55" : BORDER}`, cursor: "pointer", background: feeAdjusted ? "#1a1500" : "transparent", color: feeAdjusted ? AMBER : T3, letterSpacing: .3, whiteSpace: "nowrap", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  {feeAdjusted ? "● Net view" : "○ Net view"}
                </button>
                <div style={{ flex: 1, display: "flex", justifyContent: "center", alignItems: "center" }}>
                  <ThemeToggle themeKey={themeKey} onToggle={() => setThemeKey(k => k === "black" ? "navy" : "black")} T3={T3} />
                </div>
                <button onClick={() => setSettingsOpen(true)} style={{ cursor: "pointer", flexShrink: 0, lineHeight: 0, width: TOOLBAR_CONTROL_H, height: TOOLBAR_CONTROL_H, padding: 0, border: "none", background: "transparent", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <SettingsIcon color={T3} />
                </button>
              </div>
            </div>

            {/* Big balance + Day's P&L baseline-aligned */}
            <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 2 }}>
              <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-1px", color: T1, fontFamily: "'DM Mono',monospace", lineHeight: 1 }}>
                ${(feeAdjusted ? Math.max(perfLast - openPositions.filter(t=>t.outcome==="open").length * 0.02, 0) : perfLast).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              {(() => {
                // Day's P&L: today's portfolio value vs yesterday's closing balance
                const todayStr = new Date().toISOString().split("T")[0];
                const yesterdaySettled = perfHistory.filter(p => !p.intraday && !p.seed && p.date < todayStr);
                const baseline = yesterdaySettled.length
                  ? yesterdaySettled[yesterdaySettled.length - 1].virtual
                  : (perfHistory.find(p => p.seed)?.virtual || 1000);
                const dayPnl = perfLast - baseline;
                const dayUp2 = dayPnl >= 0;
                return (
                  <div style={{ textAlign: "right", lineHeight: 1 }}>
                    <div style={{ fontSize: 9, color: T3, marginBottom: 2 }}>Day's P&L</div>
                    <div style={{ fontSize: 16, fontWeight: 600, color: dayUp2 ? GREEN : RED, fontFamily: "'DM Mono',monospace" }}>{dayUp2 ? "+" : ""}${dayPnl.toFixed(2)}</div>
                    <div style={{ fontSize: 8, color: T3, marginTop: 3 }}>age: {Math.floor((Date.now() - new Date("2026-05-22T00:00:00").getTime()) / 86400000)}d</div>
                  </div>
                );
              })()}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <span style={{ fontSize: 13, fontWeight: 500, color: perfUp ? GREEN : RED }}>{perfUp ? "↑" : "↓"} {Math.abs(perfPercent).toFixed(2)}%</span>
              <span style={{ fontSize: 12, color: T3 }}>{perfUp ? "+" : ""}${perfChange.toFixed(2)}</span>
            </div>
            <MiniChart data={perfHistory} timeframe={perfTimeframe} feeAdjusted={feeAdjusted} />
            <div style={{ display: "flex", alignItems: "center", marginTop: 8, position: "relative" }}>
              <div style={{ flex: 1, display: "flex", justifyContent: "center", gap: 4 }}>
                {["D", "W", "M", "3M", "Y", "ALL"].map(tf => (
                  <button key={tf} onClick={() => setPerfTimeframe(tf)} style={{ padding: "5px 12px", borderRadius: 20, fontSize: 11, fontWeight: 500, border: "none", cursor: "pointer", background: perfTimeframe === tf ? "#1e1e24" : BG, color: perfTimeframe === tf ? T1 : T3 }}>
                    {tf === "D" ? "1D" : tf === "W" ? "1W" : tf === "M" ? "1M" : tf === "Y" ? "1Y" : tf}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* METRIC STRIP */}
          <div style={{ display: "flex", gap: 8, padding: "0 16px 14px" }}>
            <div style={{ flex: 1, background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "7px 12px" }}>
              <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .6, marginBottom: 3 }}>Live P&L</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: livePnl >= 0 ? GREEN : RED, fontFamily: "'DM Mono',monospace" }}>{livePnl >= 0 ? "+" : ""}${Math.abs(feeAdjusted ? livePnl - openPositions.filter(t=>t.outcome==="open").length * 0.02 : livePnl).toFixed(2)}</div>
            </div>
            <div style={{ flex: 1, background: CARD, border: `1px solid ${pdtRemaining === 0 ? RED : pdtRemaining === 1 ? AMBER : BORDER}`, borderRadius: 10, padding: "7px 12px" }}>
              <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .6, marginBottom: 3 }}>Day trades</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                <span style={{ fontSize: 16, fontWeight: 600, color: pdtRemaining === 0 ? RED : pdtRemaining === 1 ? AMBER : GREEN, fontFamily: "'DM Mono',monospace" }}>{pdtUsed}/3</span>
                <span style={{ fontSize: 8, color: pdtRemaining === 0 ? RED : T3 }}>{pdtRemaining === 0 ? "limit reached" : `${pdtRemaining} left`}</span>
              </div>
            </div>
            <div style={{ flex: 1, background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "7px 12px" }}>
              <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .6, marginBottom: 3 }}>Open</div>
              <div style={{ fontSize: 16, fontWeight: 600, color: openPositions.length > 0 ? GREEN : T2 }}>{openPositions.filter(t => t.outcome === "open").length}</div>
            </div>
          </div>

          {openExecution?.missed_open_alert && (
            <div style={{ margin: "0 16px 10px", background: "#1a0f05", border: `1px solid ${AMBER}66`, borderRadius: 8, padding: "9px 10px", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 10, color: AMBER, fontWeight: 800, textTransform: "uppercase", letterSpacing: .5 }}>Open execution missed</div>
                <div style={{ fontSize: 9, color: T2, marginTop: 2 }}>
                  {openExecution.cached_pick_count_live || openExecution.cached_pick_count || 0} picks, {openExecution.open_position_count_live || 0} open
                </div>
              </div>
              <button onClick={recoverMissedOpen} disabled={recoveringOpen}
                style={{ background: AMBER + "22", border: `1px solid ${AMBER}77`, color: AMBER, borderRadius: 5, padding: "5px 8px", fontSize: 9, fontWeight: 800, cursor: recoveringOpen ? "default" : "pointer", whiteSpace: "nowrap", opacity: recoveringOpen ? .7 : 1 }}>
                {recoveringOpen ? "OPENING..." : "RECOVER"}
              </button>
            </div>
          )}

          {!openExecution?.missed_open_alert && openExecution?.last_error && (
            <div style={{ margin: "0 16px 10px", background: "#160909", border: `1px solid ${RED}55`, borderRadius: 8, padding: "8px 10px", fontSize: 9, color: RED }}>
              Open execution issue: {openExecution.last_error}
            </div>
          )}

          {/* CONFIDENCE LEGEND */}
          <div style={{ margin: "0 16px 10px", background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "10px 14px" }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              {[[AMBER, "85%+ elite"], [GREEN, "75-84 strong"], [BLUE, "65-74 decent"], [T3, "<65 skip"]].map(([color, label]) => (
                <div key={label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 3, background: color, flexShrink: 0 }} />
                  <span style={{ fontSize: 9, color: color, fontWeight: 600 }}>{label}</span>
                </div>
              ))}
            </div>
          </div>



          {/* SUB TOGGLE — Picks/Open + Sort */}
          <div style={{ display: "flex", margin: "0 16px 12px", gap: 4, alignItems: "stretch" }}>
            {[
              ["buy", `Picks (${allBuyPicks.length})`, BLUE, "#0f1e35", `1px solid ${BLUE}44`],
              ["sell", `Open (${openLongPositions.length})`, GREEN, "#091a0d", `1px solid ${GREEN}44`]
            ].map(([id, label, color, activeBg, border]) => (
              <button key={id} onClick={() => setLongSub(id)} style={{
                flex: 1, padding: "7px 0", borderRadius: 6, fontSize: 11, fontWeight: 600,
                border: longSub === id ? border : border,
                cursor: "pointer", transition: ".15s",
                background: longSub === id ? activeBg : "transparent", color: color,
              }}>{label}</button>
            ))}
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "transparent", borderRadius: 6, padding: "7px 0", gap: 4, border: `1px solid ${BORDER}` }}>
              <span style={{ fontSize: 10, color: T3, fontWeight: 600, whiteSpace: "nowrap", lineHeight: "1", display: "block" }}>Sort:</span>
              <select
                value={sortMode}
                onChange={e => setSortMode(e.target.value)}
                style={{
                  border: "none", cursor: "pointer",
                  background: "transparent",
                  color: T1,
                  fontSize: 10, fontWeight: 600,
                  appearance: "none", outline: "none",
                  margin: 0, padding: 0,
                  lineHeight: "1",
                  textAlign: "center", textAlignLast: "center",
                  display: "block",
                }}
              >
                {SORT_OPTIONS.map(o => (
                  <option key={o.id} value={o.id} style={{ background: "#111", color: T1 }}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* CONTENT AREA */}
          <div style={{ padding: "0 16px" }}>

            {/* PICKS TAB */}
            {longSub === "buy" && (
              <>
                {allBuyPicks.length === 0 ? (
                  <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 20, fontSize: 13, color: T3, textAlign: "center" }}>
                    {portfolioTab === "neural" ? "Neural picks will appear after the NN scan runs." : "No picks yet — pre-market scan runs from 4–8:15 AM CST."}
                  </div>
                ) : (
                  <>
                    <CardMetricGrid style={{ padding: `0 ${CARD_PAD_R} 5px ${CARD_PAD_L}` }}>
                      <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5 }}>Ticker</div>
                      <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "center" }}>% Chg</div>
                      <SpineCell><div style={{ width: SPINE_VALUE_W, fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "center", whiteSpace: "nowrap" }}>Move</div></SpineCell>
                      <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5 }}></div>
                      <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "right" }}>Conf</div>
                    </CardMetricGrid>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {buyVisible.map(pick => (
                        <PickCard key={pick.ticker + "_l"} pick={pick} isLong={true}
                          expanded={expandedCards[pick.ticker + "_l"]}
                          themeKey={themeKey}
                          onAddToPersonal={pick => handleAddToPersonal(pick, "brain")}
                          onToggle={key => setExpandedCards(prev => ({ ...prev, [key]: !prev[key] }))} />
                      ))}
                      <ExpandButton isExpanded={buyListExpanded} onToggle={() => setBuyListExpanded(e => !e)} totalCount={allBuyPicks.length} label="picks" />
                    </div>
                  </>
                )}
              </>
            )}

            {/* OPEN TAB */}
            {longSub === "sell" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>

                {/* ── Recently Closed (top, no label, vanishes when empty) ── */}
                {recentlyClosed.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
                    {recentlyClosed.map(trade => {
                      const pnlPct = trade.actual_move || 0;
                      const gross = trade.gross_pnl || 0;
                      const pnlColor = pnlPct >= 0 ? GREEN : RED;
                      const isExpanded = expandedCards["closed_" + trade.id];
                      const outcomeColor = trade.outcome === "hit" ? GREEN : trade.outcome === "partial" ? AMBER : RED;
                      const outcomeLabel = trade.outcome === "hit" ? "WIN" : trade.outcome === "partial" ? "PARTIAL" : trade.sell_reason === "forced_close" ? "FORCE CLOSED" : "LOSS";
                      const sellReasonLabel = trade.sell_reason === "forced_close" ? "Force closed 2:45 PM" : trade.sell_reason === "cut_loss" ? "Cut at loss" : trade.sell_reason === "stop_loss" ? "Stop loss" : trade.sell_reason || "Closed";
                      return (
                        <div key={trade.id} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, borderLeft: `3px solid ${outcomeColor}`, overflow: "hidden" }}>
                          <div style={{ display: "flex", alignItems: "center", padding: "8px 12px", gap: 8 }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, fontWeight: 600, color: T1 }}>{trade.ticker}</span>
                                <span style={{ fontSize: 8, fontWeight: 700, color: outcomeColor, textTransform: "uppercase", letterSpacing: .4, padding: "1px 4px", background: outcomeColor + "22", borderRadius: 3 }}>{outcomeLabel}</span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
                                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 11, fontWeight: 600, color: pnlColor }}>{pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(1)}%</span>
                                <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 11, color: pnlColor }}>{gross >= 0 ? "+" : ""}${Math.abs(gross).toFixed(2)}</span>
                                <span style={{ fontSize: 9, color: T3 }}>{sellReasonLabel}</span>
                              </div>
                            </div>
                            <div style={{ display: "flex", gap: 4 }}>
                              <button onClick={() => setExpandedCards(prev => ({ ...prev, ["closed_" + trade.id]: !prev["closed_" + trade.id] }))}
                                style={{ background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 4, color: T3, fontSize: 9, fontWeight: 700, padding: "3px 8px", cursor: "pointer" }}>
                                {isExpanded ? "HIDE" : "VIEW"}
                              </button>
                              <button onClick={() => setDismissedClosed(prev => ({ ...prev, [trade.id]: true }))}
                                style={{ background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 4, color: T3, fontSize: 9, fontWeight: 700, padding: "3px 8px", cursor: "pointer" }}>
                                CLOSE
                              </button>
                            </div>
                          </div>
                          {isExpanded && (
                            <div style={{ padding: "0 12px 10px", borderTop: `1px solid ${BORDER}` }}>
                              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 12px", paddingTop: 8 }}>
                                {[
                                  ["Buy date", trade.buy_date],
                                  ["Sell date", trade.sell_date],
                                  ["Entry", trade.buy_price ? `$${Number(trade.buy_price).toFixed(2)}` : "—"],
                                  ["Exit", trade.sell_price ? `$${Number(trade.sell_price).toFixed(2)}` : "—"],
                                  ["Invested", `$${Number(trade.invested_amount || 10).toFixed(2)}`],
                                  ["Net P&L", trade.net_pnl != null ? `${trade.net_pnl >= 0 ? "+" : ""}$${Math.abs(trade.net_pnl).toFixed(2)}` : "—"],
                                ].map(([label, value]) => (
                                  <div key={label} style={{ display: "flex", justifyContent: "space-between", borderBottom: `1px solid ${BORDER}`, paddingBottom: 3 }}>
                                    <span style={{ fontSize: 9, color: T3 }}>{label}</span>
                                    <span style={{ fontSize: 9, color: T1, fontFamily: "'DM Mono',monospace" }}>{value}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* ── Column header (shared for both sections) ── */}
                {(sellTodayPositions.length > 0 || holdingPositions.length > 0) && (
                  <CardMetricGrid style={{ padding: `0 ${CARD_PAD_R} 5px ${CARD_PAD_L}` }}>
                    <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5 }}>Ticker</div>
                    <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "left" }}>Day %</div>
                    <SpineCell><div style={{ width: SPINE_VALUE_W, fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "center", whiteSpace: "nowrap" }}>Open P&L</div></SpineCell>
                    <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "right", paddingRight: 6 }}>+$</div>
                    <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, textAlign: "right" }}>Conf</div>
                  </CardMetricGrid>
                )}

                {/* ── Sell Today ── */}
                {sellTodayPositions.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 9, color: AMBER, fontWeight: 700, textTransform: "uppercase", letterSpacing: .8, padding: "4px 0 6px" }}>
                      Sell Today ({sellTodayPositions.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {sortedSellToday.map(trade => (
                        <PositionCard key={trade.id} trade={trade} isLong={true}
                          expanded={expandedCards[trade.id || trade.ticker]}
                          isDone={doneCuts[trade.id || trade.ticker] === "done"}
                          isClosed={doneCuts[trade.id || trade.ticker] === "closed"}
                          pdtRemaining={pdtRemaining}
                          themeKey={themeKey}
                          onToggle={key => setExpandedCards(prev => ({ ...prev, [key]: !prev[key] }))}
                          onDone={key => { setDoneCuts(prev => ({ ...prev, [key]: "done" })); setExpandedCards(prev => ({ ...prev, [key]: false })); }}
                          onView={key => setDoneCuts(prev => ({ ...prev, [key]: "open" }))}
                          onClose={key => setDoneCuts(prev => ({ ...prev, [key]: "closed" }))}
                          onAddToPersonal={trade => handleAddToPersonal(trade, "brain")}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* ── Holding ── */}
                {holdingPositions.length > 0 && (
                  <div style={{ marginBottom: 12 }}>
                    <div style={{ fontSize: 9, color: T3, fontWeight: 700, textTransform: "uppercase", letterSpacing: .8, padding: "4px 0 6px" }}>
                      Holding ({holdingPositions.length})
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                      {sortedHolding.map(trade => (
                        <PositionCard key={trade.id} trade={trade} isLong={true}
                          expanded={expandedCards[trade.id || trade.ticker]}
                          isDone={doneCuts[trade.id || trade.ticker] === "done"}
                          isClosed={doneCuts[trade.id || trade.ticker] === "closed"}
                          pdtRemaining={pdtRemaining}
                          themeKey={themeKey}
                          onToggle={key => setExpandedCards(prev => ({ ...prev, [key]: !prev[key] }))}
                          onDone={key => { setDoneCuts(prev => ({ ...prev, [key]: "done" })); setExpandedCards(prev => ({ ...prev, [key]: false })); }}
                          onView={key => setDoneCuts(prev => ({ ...prev, [key]: "open" }))}
                          onClose={key => setDoneCuts(prev => ({ ...prev, [key]: "closed" }))}
                          onAddToPersonal={trade => handleAddToPersonal(trade, "brain")}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Empty state */}
                {openLongPositions.length === 0 && recentlyClosed.length === 0 && (
                  <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 20, fontSize: 13, color: T3, textAlign: "center" }}>
                    No open positions. Positions appear here after 8:45 AM execution.
                  </div>
                )}

              </div>
            )}


          </div>
          </div>} {/* end Brain portfolio */}

          {/* ── NEURAL PORTFOLIO ── */}
          {portfolioTab === "neural" && (
            <div style={{ padding: "10px 16px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: "#a78bfa", fontWeight: 700, textTransform: "uppercase", letterSpacing: .8 }}>SwingDeskNet — Neural Brain</div>
                {nnStats && nnStats.win_rate != null && (
                  <div style={{ fontSize: 10, color: nnStats.win_rate >= 60 ? GREEN : nnStats.win_rate >= 45 ? AMBER : RED, fontWeight: 600 }}>{nnStats.win_rate}% win rate</div>
                )}
              </div>

              {/* NN Open Positions */}
              {nnPositions.filter(t => t.outcome === "open").length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .6, marginBottom: 6 }}>Open positions</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {nnPositions.filter(t => t.outcome === "open").map(trade => (
                      <PositionCard key={trade.id} trade={trade} isLong={true}
                        themeKey={themeKey}
                        pdtRemaining={pdtRemaining}
                        expanded={expandedCards[trade.id]}
                        onToggle={key => setExpandedCards(prev => ({ ...prev, [key]: !prev[key] }))}
                        onAddToPersonal={trade => handleAddToPersonal(trade, "neural")} />
                    ))}
                  </div>
                </div>
              )}

              {/* NN Picks */}
              {nnPicks.recommended_longs && nnPicks.recommended_longs.length > 0 ? (
                <div>
                  <div style={{ fontSize: 9, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .6, marginBottom: 6 }}>NN Picks</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {nnPicks.recommended_longs.map(pick => (
                      <PickCard key={pick.ticker + "_nn"} pick={mapPickFields(pick)} isLong={true}
                        themeKey={themeKey}
                        expanded={expandedCards[pick.ticker + "_nn"]}
                        onAddToPersonal={pick => handleAddToPersonal(pick, "neural")}
                        onToggle={key => setExpandedCards(prev => ({ ...prev, [key]: !prev[key] }))} />
                    ))}
                  </div>
                </div>
              ) : (
                <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 20, textAlign: "center", fontSize: 12, color: T3 }}>
                  No neural picks are currently cached above threshold.
                </div>
              )}
            </div>
          )}

          {/* ── PERSONAL PORTFOLIO ── */}
          {portfolioTab === "personal" && (
            <div style={{ padding: "10px 16px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: AMBER, fontWeight: 700, textTransform: "uppercase", letterSpacing: .8 }}>Personal Portfolio</div>
                <div style={{ fontSize: 9, color: T3 }}>Add positions from Brain or Neural tabs</div>
              </div>

              {personalTrades.length === 0 ? (
                <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 24, textAlign: "center" }}>
                  <div style={{ fontSize: 13, color: T2, marginBottom: 6 }}>No personal positions yet.</div>
                  <div style={{ fontSize: 11, color: T3 }}>Tap ADD on any Brain or Neural stock card.</div>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {personalTrades.map(trade => {
                    const pnl = trade.pnl_percent || 0;
                    const pnlColor = pnl >= 0 ? GREEN : RED;
                    return (
                      <div key={trade.id} style={{ display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center", padding: "11px 14px", background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, borderLeft: `3px solid ${AMBER}` }}>
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 14, fontWeight: 600, color: T1 }}>{trade.ticker}</span>
                            <span style={{ fontSize: 8, color: AMBER, fontWeight: 700, letterSpacing: .3 }}>PERSONAL</span>
                            {trade.source_portfolio && <span style={{ fontSize: 8, color: T3 }}>via {trade.source_portfolio}</span>}
                          </div>
                          <div style={{ fontSize: 9, color: T3, marginTop: 2 }}>{trade.buy_date} · {trade.sector || "—"}</div>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 13, fontWeight: 700, color: pnlColor, fontFamily: "'DM Mono',monospace" }}>{pnl >= 0 ? "+" : ""}{pnl.toFixed(1)}%</div>
                            <div style={{ fontSize: 9, color: T3, marginTop: 1 }}>${Number(trade.buy_price || 0).toFixed(2)} entry</div>
                          </div>
                          <button onClick={async () => {
                            try {
                              await apiFetch("/personal-trades/remove", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: trade.id }) });
                              setPersonalTrades(prev => prev.filter(t => t.id !== trade.id));
                            } catch {}
                          }} style={{ background: "transparent", border: `1px solid ${BORDER}`, borderRadius: 4, color: T3, fontSize: 9, padding: "3px 7px", cursor: "pointer" }}>✕</button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

        </div>
      )}

      {/* ════════ VIRTUAL TAB ════════ */}
      {tab === "virtual" && (
        <div className="fadeIn" style={{ padding: "10px 16px 0" }}>
          {tabLoading && <div style={{ textAlign: "center", padding: 20, fontSize: 11, color: T3 }}>Loading...</div>}

          {/* ── Analytics internal nav: Performance | Closed Trades ── */}
          <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
            {[["performance", "Performance"], ["closed", "Closed Trades"]].map(([id, label]) => (
              <button key={id} onClick={() => setAnalyticsPage(id)} style={{
                flex: 1, padding: "8px 0", border: `1px solid ${analyticsPage === id ? BLUE + "66" : BORDER}`,
                borderRadius: 8, background: analyticsPage === id ? BLUE + "18" : "transparent",
                color: analyticsPage === id ? BLUE : T3, fontSize: 11, fontWeight: 700,
                letterSpacing: .4, cursor: "pointer", textTransform: "uppercase"
              }}>{label}</button>
            ))}
          </div>

          {analyticsPage === "performance" && (<>
          {/* ── Extended Runners ── */}
          {extendedRunners.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: PURPLE, textTransform: "uppercase", letterSpacing: .8, marginBottom: 8 }}>Extended plays</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {extendedRunners.map(runner => (
                  <ExtendedRunnerCard key={runner.id} trade={runner}
                    expanded={expandedCards[runner.id]}
                    onToggle={key => setExpandedCards(prev => ({ ...prev, [key]: !prev[key] }))}
                    onHide={key => setExtendedRunners(prev => prev.filter(r => r.id !== key))} />
                ))}
              </div>
            </div>
          )}

          {/* ── Cut Log ── */}
          {(() => {
            const today = new Date().toISOString().split("T")[0];
            const yesterday = new Date(Date.now() - 86400000).toISOString().split("T")[0];
            const cutTrades = virtualTrades.filter(t =>
              (t.sell_reason === "stop_loss" || (t.actual_move != null && t.actual_move < -1)) &&
              (t.sell_date === today || t.sell_date === yesterday)
            );
            if (cutTrades.length === 0) return null;
            return (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: RED, textTransform: "uppercase", letterSpacing: .8, marginBottom: 8 }}>Cut log</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  {cutTrades.map(trade => (
                    <div key={trade.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "10px 14px", background: "#120a0a", border: `1px solid #200f0f`, borderRadius: 10, borderLeft: `3px solid ${RED}` }}>
                      <div>
                        <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 13, fontWeight: 600, color: T1 }}>{trade.ticker}</span>
                        <span style={{ fontSize: 9, color: T3, marginLeft: 8 }}>{trade.buy_date}</span>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: 11, color: RED, fontWeight: 500 }}>{trade.actual_move != null ? `${trade.actual_move >= 0 ? "+" : ""}${trade.actual_move.toFixed(1)}%` : "open"}</div>
                        <div style={{ fontSize: 9, color: RED, fontWeight: 700, marginTop: 2 }}>CUT</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })()}

          {/* ── Analytics Stats ── */}
          {(() => {
            const closedTrades = virtualTrades.filter(t => t.outcome !== "open");
            const hits = closedTrades.filter(t => t.outcome === "hit");
            const misses = closedTrades.filter(t => t.outcome === "miss");
            const winRate = closedTrades.length > 0 ? Math.round(hits.length / closedTrades.length * 100) : null;
            const avgWin = hits.length > 0 ? hits.reduce((s, t) => s + (t.actual_move || 0), 0) / hits.length : null;
            const avgLoss = misses.length > 0 ? misses.reduce((s, t) => s + (t.actual_move || 0), 0) / misses.length : null;

            // Close time analysis
            const hitsWithTime = hits.filter(t => t.sell_time);
            const missesWithTime = misses.filter(t => t.sell_time);
            const avgHitTime = hitsWithTime.length > 0 ? hitsWithTime[hitsWithTime.length >> 1]?.sell_time : null;
            const avgMissTime = missesWithTime.length > 0 ? missesWithTime[missesWithTime.length >> 1]?.sell_time : null;

            // Sector breakdown
            const sectorMap = {};
            closedTrades.forEach(t => {
              const s = t.sector || "Other";
              if (!sectorMap[s]) sectorMap[s] = { hits: 0, total: 0 };
              sectorMap[s].total++;
              if (t.outcome === "hit") sectorMap[s].hits++;
            });

            return (
              <div>
                <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 10 }}>Performance</div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 16 }}>
                  {[
                    ["Win rate", winRate !== null ? `${winRate}%` : "—", winRate >= 60 ? GREEN : winRate >= 45 ? AMBER : T2],
                    ["Avg win", avgWin !== null ? `+${avgWin.toFixed(1)}%` : "—", GREEN],
                    ["Avg loss", avgLoss !== null ? `${avgLoss.toFixed(1)}%` : "—", RED],
                    ["Total trades", closedTrades.length, T1],
                    ["Hits", hits.length, GREEN],
                    ["Misses", misses.length, RED],
                  ].map(([label, value, color]) => (
                    <div key={label} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "10px 12px" }}>
                      <div style={{ fontSize: 8, color: T3, textTransform: "uppercase", letterSpacing: .5, marginBottom: 3, fontWeight: 600 }}>{label}</div>
                      <div style={{ fontSize: 18, fontWeight: 700, color }}>{value}</div>
                    </div>
                  ))}
                </div>

                {(avgHitTime || avgMissTime) && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 8 }}>Avg close time</div>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                      {avgHitTime && <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "10px 12px" }}>
                        <div style={{ fontSize: 9, color: T3, marginBottom: 3 }}>Winners close</div>
                        <div style={{ fontSize: 14, fontWeight: 600, color: GREEN }}>{avgHitTime}</div>
                      </div>}
                      {avgMissTime && <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "10px 12px" }}>
                        <div style={{ fontSize: 9, color: T3, marginBottom: 3 }}>Losers close</div>
                        <div style={{ fontSize: 14, fontWeight: 600, color: RED }}>{avgMissTime}</div>
                      </div>}
                    </div>
                  </div>
                )}

                {Object.keys(sectorMap).length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 8 }}>Win rate by sector</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {Object.entries(sectorMap).sort((a, b) => b[1].total - a[1].total).map(([sector, data]) => {
                        const wr = Math.round(data.hits / data.total * 100);
                        return (
                          <div key={sector} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "8px 12px" }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                              <span style={{ fontSize: 11, color: T1 }}>{sector}</span>
                              <span style={{ fontSize: 11, fontWeight: 600, color: wr >= 60 ? GREEN : wr >= 45 ? AMBER : RED }}>{wr}% ({data.hits}/{data.total})</span>
                            </div>
                            <div style={{ height: 2, background: BORDER, borderRadius: 1, overflow: "hidden" }}>
                              <div style={{ width: `${wr}%`, height: "100%", background: wr >= 60 ? GREEN : wr >= 45 ? AMBER : RED }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {closedTrades.length === 0 && (
                  <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 20, fontSize: 13, color: T3, textAlign: "center" }}>
                    Analytics populate after first closed trade.
                  </div>
                )}
              </div>
            );
          })()}
          </>)}

          {/* ── Closed Trades Subpage ── */}
          {analyticsPage === "closed" && (() => {
            const allClosed = virtualTrades.filter(t => t.outcome !== "open");
            const wins = allClosed.filter(t => t.outcome === "hit");
            const cuts = allClosed.filter(t => t.outcome === "miss" || t.sell_reason === "cut_loss" || t.sell_reason === "stop_loss");
            const partials = allClosed.filter(t => t.outcome === "partial");
            const winRate = allClosed.length > 0 ? Math.round(wins.length / allClosed.length * 100) : null;
            const totalPnl = allClosed.reduce((s, t) => s + (t.gross_pnl || 0), 0);
            const tabData = closedTab === "wins" ? wins : closedTab === "cuts" ? cuts : allClosed;

            return (
              <div style={{ marginTop: 16 }}>
                {/* Header row: label + win rate */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                  <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8 }}>Closed trades</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {winRate !== null && (
                      <span style={{ fontSize: 11, fontWeight: 700, color: winRate >= 60 ? GREEN : winRate >= 45 ? AMBER : RED }}>{winRate}% win rate</span>
                    )}
                    <span style={{ fontSize: 10, color: T3, fontFamily: "'DM Mono',monospace" }}>{totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}</span>
                  </div>
                </div>

                {/* Sub-tabs */}
                <div style={{ display: "flex", gap: 4, marginBottom: 10 }}>
                  {[["all", `All (${allClosed.length})`], ["wins", `Wins (${wins.length})`], ["cuts", `Cuts (${cuts.length})`]].map(([id, label]) => (
                    <button key={id} onClick={() => setClosedTab(id)} style={{
                      padding: "5px 12px", borderRadius: 20, fontSize: 10, fontWeight: 600,
                      border: "none", cursor: "pointer",
                      background: closedTab === id ? (id === "wins" ? GREEN + "22" : id === "cuts" ? RED + "22" : BORDER) : "transparent",
                      color: closedTab === id ? (id === "wins" ? GREEN : id === "cuts" ? RED : T1) : T3,
                    }}>{label}</button>
                  ))}
                </div>

                {tabData.length === 0 ? (
                  <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: 20, fontSize: 12, color: T3, textAlign: "center" }}>
                    {allClosed.length === 0 ? "No closed trades yet." : "No trades in this category."}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    {tabData.map(trade => {
                      const tradeColor = trade.outcome === "hit" ? GREEN : trade.outcome === "partial" ? AMBER : RED;
                      const pnl = trade.actual_move;
                      const conf = trade.lock_in_confidence || trade.confidence;
                      return (
                        <div key={trade.id} style={{ display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center", padding: "10px 14px", background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, borderLeft: `3px solid ${tradeColor}` }}>
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ fontFamily: "'DM Mono',monospace", fontSize: 14, fontWeight: 600, color: T1 }}>{trade.ticker}</span>
                              <span style={{ fontSize: 9, fontWeight: 700, color: tradeColor, letterSpacing: .3 }}>{trade.outcome === "hit" ? "WIN" : trade.outcome === "partial" ? "PARTIAL" : "LOSS"}</span>
                              {conf > 0 && <span style={{ fontSize: 8, color: confidenceColor(conf, themeKey), fontFamily: "'DM Mono',monospace" }}>{conf}%</span>}
                            </div>
                            <div style={{ fontSize: 9, color: T3, marginTop: 2 }}>
                              {trade.sell_date} · {trade.sector || "—"}
                              {trade.sell_reason && <span style={{ marginLeft: 6, color: T3 }}>· {trade.sell_reason.replace(/_/g, " ")}</span>}
                            </div>
                          </div>
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 13, fontWeight: 700, color: pnl >= 0 ? GREEN : RED, fontFamily: "'DM Mono',monospace" }}>{pnl >= 0 ? "+" : ""}{pnl != null ? pnl.toFixed(1) : "—"}%</div>
                            {trade.gross_pnl != null && <div style={{ fontSize: 9, color: trade.gross_pnl >= 0 ? GREEN : RED, fontFamily: "'DM Mono',monospace", marginTop: 1 }}>{trade.gross_pnl >= 0 ? "+" : ""}${trade.gross_pnl.toFixed(2)}</div>}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })()}

          {analyticsPage === "performance" && (<>
          {queueStatus && (
            <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "12px 14px", marginTop: 16 }}>
              <div style={{ fontSize: 10, color: T3, fontWeight: 600, textTransform: "uppercase", letterSpacing: .5, marginBottom: 8 }}>Trade queue</div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: T2 }}>Available amounts</span>
                <span style={{ fontSize: 11, color: T1 }}>{queueStatus.available_count}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: T2 }}>Total queued</span>
                <span style={{ fontSize: 11, color: T1, fontFamily: "'DM Mono',monospace" }}>${queueStatus.available_total?.toFixed(2)}</span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ fontSize: 11, color: T2 }}>Fallback <span style={{ fontSize: 9, color: T3 }}>(1% of portfolio)</span></span>
                <span style={{ fontSize: 11, color: T3, fontFamily: "'DM Mono',monospace" }}>${queueStatus.default_fallback?.toFixed(2)}</span>
              </div>
            </div>
          )}

          {/* ── Method Intelligence ── */}
          {(() => {
            const METHOD_INFO = METHOD_DEFINITIONS;
            const allMethods = Object.keys(METHOD_INFO);
            const openPositionTickers = new Set(openPositions.filter(t => t.outcome === "open").map(t => t.ticker));

            return (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 10 }}>Method Intelligence</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {allMethods.map(method => {
                    const stats = methodStats?.[method];
                    const isExpanded = expandedMethods[method];
                    const flaggedPositions = openPositions.filter(p => p.confluence_methods?.includes(method));
                    const flaggedPicks = picks.longs.filter(p => p.confluence_methods?.includes(method));
                    const totalFlagged = flaggedPositions.length + flaggedPicks.length;

                    return (
                      <div key={method} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, overflow: "hidden" }}>
                        <div onClick={() => setExpandedMethods(p => ({ ...p, [method]: !p[method] }))}
                          style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px", cursor: "pointer" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ fontSize: 12, fontWeight: 600, color: T1 }}>{method}</span>
                            {totalFlagged > 0 && (
                              <span style={{ fontSize: 9, color: BLUE, background: "#0a1020", padding: "1px 6px", borderRadius: 10, border: `1px solid #1a2a40` }}>{totalFlagged} flagged</span>
                            )}
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            {stats?.win_rate != null ? (
                              <span style={{ fontSize: 11, fontWeight: 600, color: stats.win_rate >= 60 ? GREEN : stats.win_rate >= 45 ? AMBER : RED }}>{stats.win_rate}%</span>
                            ) : (
                              <span style={{ fontSize: 9, color: T3 }}>No data yet</span>
                            )}
                            <span style={{ color: T3, fontSize: 10 }}>{isExpanded ? "▲" : "▼"}</span>
                          </div>
                        </div>

                        {isExpanded && (
                          <div style={{ padding: "0 14px 14px", borderTop: `1px solid ${BORDER}` }}>
                            <div style={{ fontSize: 10, color: T3, lineHeight: 1.6, paddingTop: 10, marginBottom: 12 }}>{METHOD_INFO[method]}</div>

                            {stats && stats.total_signals > 0 ? (
                              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 12 }}>
                                {[
                                  ["Win rate", stats.win_rate != null ? `${stats.win_rate}%` : "—", stats.win_rate >= 60 ? GREEN : stats.win_rate >= 45 ? AMBER : RED],
                                  ["Avg move", stats.avg_move != null ? `+${stats.avg_move.toFixed(1)}%` : "—", GREEN],
                                  ["Best trade", stats.best_trade != null ? `+${stats.best_trade.toFixed(1)}%` : "—", GREEN],
                                  ["Hits", stats.hits, GREEN],
                                  ["Misses", stats.misses, RED],
                                ].map(([label, value, color]) => (
                                  <div key={label} style={{ background: "#0a0a0c", borderRadius: 8, padding: "8px 10px" }}>
                                    <div style={{ fontSize: 8, color: T3, textTransform: "uppercase", letterSpacing: .5, marginBottom: 2 }}>{label}</div>
                                    <div style={{ fontSize: 14, fontWeight: 700, color }}>{value}</div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div style={{ background: "#0a0a0c", borderRadius: 8, padding: "12px", textAlign: "center", marginBottom: 12 }}>
                                <div style={{ fontSize: 10, color: T3 }}>Accumulating data...</div>
                                <div style={{ fontSize: 9, color: "#444", marginTop: 4 }}>Performance stats appear after first signals resolve</div>
                              </div>
                            )}

                            {totalFlagged > 0 && (
                              <div>
                                <div style={{ fontSize: 9, color: T3, textTransform: "uppercase", letterSpacing: .5, marginBottom: 6 }}>Currently flagged</div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                  {[...flaggedPositions, ...flaggedPicks].map(item => (
                                    <div key={item.ticker} style={{ background: "#0a1020", border: `1px solid #1a2a40`, borderRadius: 6, padding: "4px 8px" }}>
                                      <span style={{ fontSize: 10, color: T1, fontFamily: "'DM Mono',monospace", fontWeight: 600 }}>{item.ticker}</span>
                                      {item.current_pnl_percent != null && (
                                        <span style={{ fontSize: 9, color: item.current_pnl_percent >= 0 ? GREEN : RED, marginLeft: 4 }}>
                                          {item.current_pnl_percent >= 0 ? "+" : ""}{item.current_pnl_percent.toFixed(1)}%
                                        </span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}

          {/* ── SwingDesk Algo ── */}
          {(() => {
            const INDICATOR_INFO = {
              rsi_momentum: {
                name: "RSI Momentum",
                desc: "Relative Strength Index measures how fast a stock is moving. We look for RSI between 40-65 — strong enough to show momentum but not so high that it's overbought and due for a reversal. An overnight swing needs momentum, not exhaustion.",
              },
              volume_surge: {
                name: "Volume Surge",
                desc: "Volume ratio compares today's volume to the average. A surge (1.5x+) means real conviction behind the move — institutions and big money are participating, not just retail noise. We score up to 3.5x average.",
              },
              overnight_gap_probability: {
                name: "Overnight Gap",
                desc: "How much the stock gapped up at open versus yesterday's close. A positive gap shows the market opened with conviction. We score based on gap size — bigger gaps mean stronger overnight thesis.",
              },
              earnings_catalyst: {
                name: "Earnings Catalyst",
                desc: "Earnings in 2-7 days create a run-up effect as traders position ahead of results. We give a mild positive signal for this window. Earnings tonight or tomorrow are a hard disqualifier — we never hold through earnings.",
              },
              support_resistance: {
                name: "Support & Resistance",
                desc: "ATR-adaptive swing pivot analysis. The brain identifies swing highs and lows over 60 days, clusters them into zones using Average True Range as the ruler, and scores based on overhead supply. Open air above current price scores high — no resistance in the expected move range means nothing to stop the run. Price sitting at resistance scores low.",
              },
              relative_strength: {
                name: "Relative Strength",
                desc: "Compares the stock's 5-day return to SPY's 5-day return. A stock outperforming the market is showing genuine institutional accumulation — money is flowing into this name specifically, not just riding the broader market tide. Strong outperformance is one of the most reliable predictors of overnight continuation.",
              },
              sector_relative_strength: {
                name: "Sector Relative Strength",
                desc: "Compares the stock's sector ETF 5-day return to SPY. Institutional money rotates by sector — when a sector has tailwind, all stocks in it have a higher base rate of success. A tech stock in a week where XLK is outperforming SPY by 3% has structural support the other signals can't see.",
              },
              vwap_reclaim: {
                name: "VWAP Reclaim",
                desc: "VWAP (Volume Weighted Average Price) is the benchmark institutions use to measure their execution quality. A stock closing above VWAP means institutions were net buyers all day. The reclaim setup — dipping below VWAP intraday then closing above — is a classic institutional accumulation signal.",
              },
              volatility_squeeze: {
                name: "Volatility Squeeze",
                desc: "Measures the ratio of recent 5-day historical volatility to 20-day historical volatility. When this ratio drops below 0.7, the stock is in compression — volatility is contracting like a coiled spring. Compression historically precedes expansion: the tighter the squeeze, the more explosive the eventual breakout.",
              },
            };

            return (
              <div style={{ marginTop: 16, marginBottom: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 10 }}>SwingDesk Algo</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {Object.entries(INDICATOR_INFO).map(([key, info]) => {
                    const currentWeight = weights[key] || 0;
                    const history = weightsHistory.map(h => ({ ts: h.timestamp, val: h[key] || 0 })).reverse();
                    const isExpanded = expandedMethods[`algo_${key}`];

                    return (
                      <div key={key} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, overflow: "hidden" }}>
                        <div onClick={() => setExpandedMethods(p => ({ ...p, [`algo_${key}`]: !p[`algo_${key}`] }))}
                          style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px", cursor: "pointer" }}>
                          <span style={{ fontSize: 12, fontWeight: 600, color: T1 }}>{info.name}</span>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <span style={{ fontSize: 12, fontWeight: 700, color: BLUE, fontFamily: "'DM Mono',monospace" }}>{(currentWeight * 100).toFixed(0)}%</span>
                            <span style={{ color: T3, fontSize: 10 }}>{isExpanded ? "▲" : "▼"}</span>
                          </div>
                        </div>
                        {isExpanded && (
                          <div style={{ padding: "0 14px 14px", borderTop: `1px solid ${BORDER}` }}>
                            <div style={{ fontSize: 10, color: T3, lineHeight: 1.6, paddingTop: 10, marginBottom: 12 }}>{info.desc}</div>
                            <div style={{ marginBottom: 8 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                                <span style={{ fontSize: 9, color: T3 }}>Current weight</span>
                                <span style={{ fontSize: 9, color: BLUE, fontFamily: "'DM Mono',monospace" }}>{(currentWeight * 100).toFixed(1)}%</span>
                              </div>
                              <div style={{ height: 3, background: BORDER, borderRadius: 2, overflow: "hidden" }}>
                                <div style={{ width: `${Math.min(currentWeight * 100, 100)}%`, height: "100%", background: BLUE, borderRadius: 2 }} />
                              </div>
                            </div>
                            {history.length >= 1 && (
                              <div>
                                <div style={{ fontSize: 9, color: T3, marginBottom: 6 }}>Weight evolution ({history.length} audit{history.length !== 1 ? "s" : ""})</div>
                                <svg viewBox={`0 0 300 50`} style={{ width: "100%", height: 50 }}>
                                  {(() => {
                                    const vals = history.map(h => h.val);
                                    const min = Math.max(0, Math.min(...vals) * 0.8);
                                    const max = Math.max(...vals) * 1.2 || 0.5;
                                    const toX = i => history.length === 1 ? 150 : (i / (history.length - 1)) * 300;
                                    const toY = v => 44 - ((v - min) / (max - min || 1)) * 40;
                                    const path = history.length > 1
                                      ? history.map((h, i) => `${i === 0 ? "M" : "L"}${toX(i).toFixed(1)},${toY(h.val).toFixed(1)}`).join(" ")
                                      : null;
                                    return (
                                      <>
                                        <line x1="0" y1="48" x2="300" y2="48" stroke={BORDER} strokeWidth="1" />
                                        {path && <path d={path} fill="none" stroke={BLUE} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />}
                                        {history.map((h, i) => (
                                          <circle key={i} cx={toX(i)} cy={toY(h.val)} r="3" fill={BLUE} />
                                        ))}
                                      </>
                                    );
                                  })()}
                                </svg>
                              </div>
                            )}
                            {history.length === 0 && (
                              <div style={{ fontSize: 9, color: T3, fontStyle: "italic" }}>Weight history builds after first audit</div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}
          </>)}

        </div>
      )}

      {/* ════════ BRAIN TAB ════════ */}
      {tab === "intel" && (
        <div className="fadeIn" style={{ padding: "10px 16px 0" }}>
          {tabLoading && <div style={{ textAlign: "center", padding: 20, fontSize: 11, color: T3 }}>Loading...</div>}
          <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "12px 14px", marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: T1, marginBottom: 4 }}>Self-audit engine</div>
            <div style={{ fontSize: 10, color: T3 }}>{lastAudit ? `Last audit: ${new Date(lastAudit).toLocaleString()}` : "No audit yet — runs weekdays at 7:00 PM CST"}</div>
            <div style={{ fontSize: 10, color: T3, marginTop: 2 }}>Fully automated. No manual intervention needed.</div>
          </div>

          {/* Audit history */}
          <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, marginBottom: 16, overflow: "hidden" }}>
            <div onClick={() => setExpandedMethods(p => ({ ...p, audit_history: !p.audit_history }))}
              style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "12px 14px", cursor: "pointer" }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: T1 }}>Audit history</span>
              <span style={{ color: T3, fontSize: 10 }}>{expandedMethods.audit_history ? "▲" : "▼"}</span>
            </div>
            {expandedMethods.audit_history && (
              <div style={{ padding: "0 14px 14px", borderTop: `1px solid ${BORDER}` }}>
                {weightsHistory.length === 0 ? (
                  <div style={{ paddingTop: 12 }}>
                    <div style={{ fontSize: 10, color: T3, marginBottom: 10 }}>No audits yet — first audit runs tonight at 7:00 PM CST.</div>
                    <div style={{ fontSize: 9, color: T3, fontStyle: "italic", marginBottom: 6 }}>Example of what audit entries look like:</div>
                    {[
                      "RSI Momentum weight increased from 18% → 22% (strong correlation with overnight gains this week)",
                      "Volume Surge weight decreased from 24% → 20% (lower signal quality on low-volume Fridays)",
                      "Earnings Catalyst weight unchanged at 18% (insufficient new data to adjust)",
                    ].map((example, i) => (
                      <div key={i} style={{ fontSize: 9, color: T2, padding: "6px 0", borderBottom: i < 2 ? `1px solid ${BORDER}` : "none", lineHeight: 1.5 }}>
                        {example}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div style={{ paddingTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
                    {weightsHistory.slice(0, 10).map((entry, i) => (
                      <div key={i} style={{ fontSize: 9, color: T1, padding: "6px 0", borderBottom: i < weightsHistory.length - 1 ? `1px solid ${BORDER}` : "none", lineHeight: 1.6 }}>
                        <div style={{ fontSize: 8, color: T3, marginBottom: 3 }}>{new Date(entry.timestamp).toLocaleString()}</div>
                        {Object.entries(entry).filter(([k]) => k !== "timestamp" && k !== "id").map(([key, val]) => {
                          const labels = { rsi_momentum: "RSI Momentum", volume_surge: "Volume Surge", overnight_gap_probability: "Overnight Gap", earnings_catalyst: "Earnings Catalyst", support_resistance: "S&R", relative_strength: "Relative Strength", sector_relative_strength: "Sector RS", vwap_reclaim: "VWAP Reclaim", volatility_squeeze: "Vol Squeeze" };
                          return <div key={key} style={{ color: T2 }}>{labels[key] || key}: <span style={{ color: BLUE, fontFamily: "'DM Mono',monospace" }}>{((val || 0) * 100).toFixed(1)}%</span></div>;
                        })}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "12px 14px", marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: T3, lineHeight: 1.8 }}>SwingDesk is not financial advice.<br/>Any trades you make based on this<br/>data are entirely at your own risk.</div>
          </div>

          <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 10 }}>Signal weights</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 16 }}>
            {Object.entries(weights).map(([key, value]) => {
              const labels = { rsi_momentum: "RSI Momentum", volume_surge: "Volume Surge", overnight_gap_probability: "Overnight Gap", earnings_catalyst: "Earnings Catalyst", support_resistance: "S&R", relative_strength: "Relative Strength", sector_relative_strength: "Sector RS", vwap_reclaim: "VWAP Reclaim", volatility_squeeze: "Vol Squeeze" };
              return (
                <div key={key} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "10px 14px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
                    <span style={{ fontSize: 12, color: T2 }}>{labels[key] || key}</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: BLUE, fontFamily: "'DM Mono',monospace" }}>{((value || 0) * 100).toFixed(0)}%</span>
                  </div>
                  <div style={{ height: 3, background: BORDER, borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ width: `${Math.min((value || 0) * 100, 100)}%`, height: "100%", background: BLUE, borderRadius: 2 }} />
                  </div>
                </div>
              );
            })}
          </div>

          <div style={{ fontSize: 11, fontWeight: 600, color: T3, textTransform: "uppercase", letterSpacing: .8, marginBottom: 10 }}>Performance</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6 }}>
            {[["Win rate", winRate !== null ? winRate + "%" : "—", winRate >= 60 ? GREEN : winRate >= 45 ? AMBER : T2],
              ["Predictions", predictions.length, T1], ["Resolved", resolved.length, T2],
            ].map(([label, value, color]) => (
              <div key={label} style={{ background: CARD, border: `1px solid ${BORDER}`, borderRadius: 10, padding: "10px" }}>
                <div style={{ fontSize: 8, color: T3, textTransform: "uppercase", letterSpacing: .5, marginBottom: 3, fontWeight: 600 }}>{label}</div>
                <div style={{ fontSize: 18, fontWeight: 700, color: color }}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ════════ BOTTOM NAV ════════ */}
      <div style={{ position: "fixed", bottom: 0, left: "50%", transform: "translateX(-50%)", width: 390, background: BG, borderTop: `1px solid ${BORDER}`, display: "flex", zIndex: 100 }}>
        {NAV.map(({ id, label, icon, brain }) => {
          const isActive = tab === id;
          const iconColor = isActive ? GREEN : T3;
          return (
            <button key={id} onClick={() => setTab(id)} style={{ flex: 1, padding: "10px 0 12px", border: "none", background: "transparent", cursor: "pointer", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              {brain ? (
                <svg width="20" height="20" viewBox="0 0 256 256" fill="none" stroke={iconColor} strokeWidth="10" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M110 40 C90 40,70 55,65 78 C50 82,40 98,40 116 C40 134,50 150,64 156 C60 170,64 186,76 196 C84 203,95 207,106 206 C110 220,122 230,136 230 C150 230,162 220,166 206 C180 205,192 196,198 184 C206 170,204 154,196 144 C210 136,218 122,218 108 C218 88,206 72,188 68 C184 52,170 40,152 40 C142 40,132 44,124 50 C120 46,115 43,110 40 Z"/>
                  <path d="M132 52 C126 64,124 80,124 96 C124 112,126 128,130 140 C134 152,136 164,136 176"/>
                  <path d="M144 54 C140 66,138 82,138 98 C138 114,140 130,144 142 C148 154,150 166,150 178"/>
                  <path d="M78 82 C88 78,98 78,108 82"/>
                  <path d="M72 110 C84 106,96 106,108 112"/>
                  <path d="M150 80 C160 78,170 80,180 86"/>
                  <path d="M150 112 C162 110,174 112,184 118"/>
                  <path d="M124 206 C120 216,120 224,124 232"/>
                  <path d="M140 206 C144 216,144 224,140 232"/>
                </svg>
              ) : (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={iconColor} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                  <path d={icon} />
                </svg>
              )}
              <span style={{ fontSize: 9, fontWeight: 600, color: iconColor, letterSpacing: .3 }}>{label}</span>
            </button>
          );
        })}
      </div>
      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        T1={T1} T2={T2} T3={T3} BORDER={BORDER} BG={BG} CARD={CARD}
        GREEN={GREEN} BLUE={BLUE} AMBER={AMBER}
      />
    </div>
    </ErrorBoundary>
  );
}
