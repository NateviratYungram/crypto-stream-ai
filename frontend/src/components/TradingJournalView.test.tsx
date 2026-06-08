import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'

vi.mock('framer-motion', () => ({
  motion: {
    tr: ({ children, initial: _initial, animate: _animate, transition: _transition, ...props }: React.HTMLAttributes<HTMLTableRowElement> & {
      initial?: unknown
      animate?: unknown
      transition?: unknown
    }) => <tr {...props}>{children}</tr>,
  },
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

vi.mock('../contexts/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) =>
      ({
        'journal.badge': 'Performance Journal',
        'journal.title': 'Trading Journal',
        'journal.subtitle': 'Closed and open paper trade review',
        'journal.refresh': 'Refresh',
        'journal.total_trades': 'Total Trades',
        'journal.win_rate': 'Win Rate',
        'journal.total_pnl': 'Total PnL',
        'journal.wins': 'Wins',
        'journal.losses': 'Losses',
        'journal.grade': 'Execution Grade',
        'journal.grade_good': 'Strong execution quality',
        'journal.grade_fair': 'Mixed execution quality',
        'journal.grade_poor': 'Needs tighter discipline',
      })[key] ?? key,
  }),
}))

import { TradingJournalView } from './TradingJournalView'

function renderWithRoot(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    unmount: () => {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

describe('TradingJournalView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    vi.restoreAllMocks()
    localStorage.setItem('crypto_terminal_key', 'journal-key')
  })

  it('loads trades and stats, renders grade, and supports filters and refresh', async () => {
    vi.spyOn(Date.prototype, 'toLocaleDateString').mockReturnValue('Jun 05, 10:00')
    const fetchSpy = vi
      .fn()
      .mockResolvedValue({
        json: async () => ({
          trades: [
            { id: 1, symbol: 'BTCUSDT', side: 'BUY', entry_price: 100, exit_price: 110, volume: 1, pnl_usd: 10, status: 'CLOSED', opened_at: '2026-06-05T10:00:00Z', closed_at: '2026-06-05T11:00:00Z' },
            { id: 2, symbol: 'ETHUSDT', side: 'SELL', entry_price: 50, exit_price: 55, volume: 2, pnl_usd: -10, status: 'CLOSED', opened_at: '2026-06-05T12:00:00Z', closed_at: '2026-06-05T13:00:00Z' },
            { id: 3, symbol: 'SOLUSDT', side: 'BUY', entry_price: 20, exit_price: null, volume: 3, pnl_usd: null, status: 'OPEN', opened_at: '2026-06-05T14:00:00Z', closed_at: null },
          ],
          stats: {
            total_trades: 3,
            win_rate_pct: 67,
            total_pnl: 42.5,
            wins: 2,
            losses: 1,
          },
        }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<TradingJournalView />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/journal?limit=100', { headers: { 'X-API-Key': 'journal-key' } })
    expect(view.container.textContent).toContain('Trading Journal')
    expect(view.container.textContent).toContain('67%')
    expect(view.container.textContent).toContain('A')
    expect(view.container.textContent).toContain('2W / 1L')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('ETHUSDT')
    expect(view.container.textContent).toContain('SOLUSDT')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'WIN')?.click()
    })
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).not.toContain('ETHUSDT')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'LOSS')?.click()
    })
    expect(view.container.textContent).toContain('ETHUSDT')
    expect(view.container.textContent).not.toContain('BTCUSDT')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent === 'OPEN')?.click()
    })
    expect(view.container.textContent).toContain('SOLUSDT')
    expect(view.container.textContent).toContain('Unrealized')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledTimes(2)

    view.unmount()
  })

  it('falls back when stats are invalid and shows the empty state in light theme', async () => {
    currentTheme = 'light'
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        json: async () => ({
          trades: [],
          stats: { nope: true },
        }),
      }),
    )

    const view = renderWithRoot(<TradingJournalView />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).not.toContain('Execution Grade')
    expect(view.container.textContent).toContain('ยังไม่มี paper trade')

    view.unmount()
  })

  it('swallows load failures and still clears loading', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    const view = renderWithRoot(<TradingJournalView />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('ยังไม่มี paper trade')

    view.unmount()
  })

  it('renders fair and poor grade messaging for lower win rates', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        json: async () => ({
          trades: [
            { id: 1, symbol: 'BTCUSDT', side: 'BUY', entry_price: 100, exit_price: 105, volume: 1, pnl_usd: 5, status: 'CLOSED', opened_at: '2026-06-05T10:00:00Z', closed_at: '2026-06-05T11:00:00Z' },
          ],
          stats: {
            total_trades: 1,
            win_rate_pct: 55,
            total_pnl: 5,
            wins: 1,
            losses: 0,
          },
        }),
      })
      .mockResolvedValueOnce({
        json: async () => ({
          trades: [
            { id: 2, symbol: 'ETHUSDT', side: 'SELL', entry_price: 50, exit_price: 52, volume: 1, pnl_usd: -2, status: 'CLOSED', opened_at: '2026-06-05T12:00:00Z', closed_at: '2026-06-05T13:00:00Z' },
          ],
          stats: {
            total_trades: 1,
            win_rate_pct: 35,
            total_pnl: -2,
            wins: 0,
            losses: 1,
          },
        }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<TradingJournalView />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('B')
    expect(view.container.textContent).toContain('Mixed execution quality')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('D')
    expect(view.container.textContent).toContain('Needs tighter discipline')

    view.unmount()
  })
})
