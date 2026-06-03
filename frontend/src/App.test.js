import { render, screen } from '@testing-library/react';
import App, {
  averageTradesByTicker,
  calculateAggregatePortfolio,
  changedWeightDeltaRows,
  getDisplayDayChangePercent,
  sortOpenTradesByMode,
} from './App';

test('renders SwingDesk loading shell', () => {
  jest.spyOn(global, 'fetch').mockResolvedValue({
    ok: false,
    json: async () => ({}),
  });
  const { unmount } = render(<App />);
  expect(screen.getByText(/swing desk/i)).toBeInTheDocument();
  expect(screen.getByText(/not financial advice/i)).toBeInTheDocument();
  unmount();
  global.fetch.mockRestore();
});

test('sorts open trades by gain using normalized open P&L percent', () => {
  const sorted = sortOpenTradesByMode([
    { ticker: 'NEG', current_pnl_percent: -1.4, confidence: 95 },
    { ticker: 'VALUE', invested_amount: 10, current_value: 10.75, confidence: 90 },
    { ticker: 'MOVE', actual_move: 13.3, confidence: 80 },
  ], 'gain', true);

  expect(sorted.map(trade => trade.ticker)).toEqual(['MOVE', 'VALUE', 'NEG']);
});

test('averages aggregate portfolio ledgers for All view account boxes', () => {
  expect(calculateAggregatePortfolio([
    { equity: 1020, realized_pnl: 12, open_pnl: 8, starting_cash: 1000 },
    { equity: 1010, realized_pnl: 10, open_pnl: 0, starting_cash: 1000 },
  ])).toEqual({
    equity: 1015,
    realized_pnl: 11,
    open_pnl: 4,
    starting_cash: 1000,
    universe_count: 2,
  });
});

test('dedupes open trades by ticker and averages variant-specific values', () => {
  const averaged = averageTradesByTicker([
    { id: 'a', ticker: 'MU', direction: 'long', invested_amount: 10, current_value: 11, confidence: 70, strategy: 'SwingDesk' },
    { id: 'b', ticker: 'MU', direction: 'long', invested_amount: 20, current_value: 22.4, confidence: 90, strategy: 'VWAP Reclaim' },
  ], 'Nova', true);

  expect(averaged).toHaveLength(1);
  expect(averaged[0].ticker).toBe('MU');
  expect(averaged[0].source_variant_count).toBe(2);
  expect(averaged[0].invested_amount).toBe(15);
  expect(averaged[0].current_value).toBe(16.7);
  expect(averaged[0].current_pnl_dollars).toBeCloseTo(1.7);
  expect(averaged[0].confidence).toBe(80);
});

test('formats changed signal weight deltas in percent points', () => {
  const rows = changedWeightDeltaRows(
    { rsi_momentum: 0.2174, volume_surge: 0.0887, vwap_reclaim: 0.0841 },
    { rsi_momentum: 0.2095, volume_surge: 0.0939, vwap_reclaim: 0.0890 },
  );

  expect(rows.map(row => row.key)).toEqual(['rsi_momentum', 'volume_surge', 'vwap_reclaim']);
  expect(rows[0].beforePct).toBeCloseTo(21.74);
  expect(rows[0].afterPct).toBeCloseTo(20.95);
  expect(rows[0].deltaPct).toBeCloseTo(-0.79);
  expect(rows[1].deltaPct).toBeCloseTo(0.52);
});

test('card percent change never falls back to overnight gap', () => {
  expect(getDisplayDayChangePercent({
    pct_change_prev_close: 5.1,
    day_change_pct: 5.0,
    overnight_gap_pct: 12.4,
  })).toBeCloseTo(5.1);

  expect(getDisplayDayChangePercent({
    overnight_gap_pct: 12.4,
    gap_pct: 12.4,
  })).toBe(0);
});
