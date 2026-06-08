import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let wsStatus = 'connected'
let lastMessage: unknown = null
let fetchMock: ReturnType<typeof vi.fn>

vi.mock('framer-motion', () => ({
  motion: {
    div: ({
      children,
      initial: _initial,
      animate: _animate,
      transition: _transition,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      transition?: unknown
    }) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

vi.mock('../hooks/useWebSocket', () => ({
  useWebSocket: () => ({
    wsStatus,
    lastMessage,
  }),
}))

import { RiskAuditsView } from './RiskAuditsView'

function renderWithRoot(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    rerender: (next: React.ReactNode) => {
      act(() => {
        root.render(next)
      })
    },
    unmount: () => {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('RiskAuditsView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    wsStatus = 'connected'
    lastMessage = null
    document.body.innerHTML = ''
    localStorage.clear()
    localStorage.setItem('crypto_terminal_key', 'secret-key')
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders fetched stats and logs, supports filters, show-all, refresh, and websocket DQ alerts', async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            open_trades: [
              {
                id: '1',
                symbol: 'BTCUSDT',
                side: 'BUY',
                quantity: 2,
                entry_price: 65000,
                status: 'OPEN',
                opened_at: '2026-06-05T08:00:00Z',
              },
            ],
            closed_trades: [
              {
                id: '2',
                symbol: 'ETHUSDT',
                side: 'SELL',
                quantity: 1,
                entry_price: 3000,
                exit_price: 2800,
                pnl: 200,
                status: 'CLOSED',
                opened_at: '2026-06-05T07:00:00Z',
                closed_at: '2026-06-05T08:00:00Z',
              },
              {
                id: '3',
                symbol: 'SOLUSDT',
                side: 'BUY',
                quantity: 3,
                entry_price: 180,
                exit_price: 160,
                pnl: -60,
                status: 'CLOSED',
                opened_at: '2026-06-05T06:00:00Z',
                closed_at: '2026-06-05T07:00:00Z',
              },
            ],
            total_simulated_pnl: 140,
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            data: Array.from({ length: 13 }, (_, index) => ({
              type: index === 0 ? 'PAPER_TRADE' : index === 1 ? 'USER_LOGIN' : index === 2 ? 'SNIPER_SIGNAL' : 'DQ_ERROR',
              detail: `Log ${index}`,
              time: `2026-06-05T0${index % 10}:00:00Z`,
            })),
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            open_trades: [],
            closed_trades: [],
            total_simulated_pnl: 0,
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            data: [],
          }),
      })

    const view = renderWithRoot(<RiskAuditsView />)
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/paper-trades', {
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/data/audits')

    expect(view.container.textContent).toContain('Performance & Log')
    expect(view.container.textContent).toContain('+$140.00')
    expect(view.container.textContent).toContain('50%')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('ETHUSDT')
    expect(view.container.textContent).toContain('SOLUSDT')
    expect(view.container.textContent).toContain('Show all 13 entries')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Signal'))?.click()
    })
    expect(view.container.textContent).toContain('Log 2')
    expect(view.container.textContent).not.toContain('Log 1')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('All'))?.click()
    })
    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Show all 13 entries'))?.click()
    })
    expect(view.container.textContent).toContain('Show less')
    expect(view.container.textContent).toContain('Log 12')

    lastMessage = {
      type: 'DQ_ALERT',
      data: { error_reason: 'gap detected', symbol: 'XAUUSD' },
    }
    view.rerender(<RiskAuditsView />)
    expect(view.container.textContent).toContain('DQ Violation: gap detected | XAUUSD')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'))?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/paper-trades', {
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(view.container.textContent).toContain('$0.00')
    expect(view.container.textContent).toContain('No activity in this category')

    view.unmount()
  })

  it('renders light-theme loading and handles fetch failures silently', async () => {
    currentTheme = 'light'
    wsStatus = 'closed'
    fetchMock.mockRejectedValue(new Error('network failed'))

    const view = renderWithRoot(<RiskAuditsView />)

    const loadingCard = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('animate-pulse'),
    )
    expect(loadingCard).not.toBeNull()

    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).toContain('No activity in this category')

    view.unmount()
  })
})
