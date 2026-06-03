import { render, screen } from '@testing-library/react';
import App, {
  averageTradesByTicker,
  calculateAggregatePortfolio,
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
