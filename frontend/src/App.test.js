import { render, screen } from '@testing-library/react';
import App from './App';

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
