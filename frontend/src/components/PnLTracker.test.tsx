import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let fetchMock: ReturnType<typeof vi.fn>
let randomSpy: ReturnType<typeof vi.spyOn> | null = null

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, initial: _initial, animate: _animate, transition: _transition, ...props }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      transition?: unknown
    }) => <div {...props}>{children}</div>,
    p: ({ children, initial: _initial, animate: _animate, ...props }: React.HTMLAttributes<HTMLParagraphElement> & {
      initial?: unknown
      animate?: unknown
    }) => <p {...props}>{children}</p>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import { PnLTracker } from './PnLTracker'

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

describe('PnLTracker', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    randomSpy = vi.spyOn(Math, 'random').mockReturnValue(0.75)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
    randomSpy?.mockRestore()
  })

  it('bootstraps simulated positions from props, updates with websocket signals, and runs mark-to-market ticks', async () => {
    const bootstrapSignals = [
      { symbol: 'BTCUSDT', direction: 'BUY', confidence: 0.9, price: 100, timestamp: '2026-06-05T08:00:00Z' },
      { symbol: 'ETHUSDT', direction: 'SELL', confidence: 0.8, price: 200, timestamp: '2026-06-05T08:01:00Z' },
      { symbol: 'XAUUSD', direction: 'HOLD', confidence: 0.5, price: 2300, timestamp: '2026-06-05T08:02:00Z' },
    ]

    const view = renderWithRoot(
      <PnLTracker
        bootstrapSignals={bootstrapSignals}
        wsLastMessage={null}
      />,
    )

    await flush()

    expect(view.container.textContent).toContain('Intelligence Command')
    expect(view.container.textContent).toContain('Session PnL')
    expect(view.container.textContent).toContain('Total Equity')
    expect(view.container.textContent).toContain('Neural Precision')
    expect(view.container.textContent).toContain('Active Deploy')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('ETHUSDT')
    expect(view.container.textContent).toContain('0%')
    expect(view.container.textContent).toContain('2')
    expect(view.container.textContent).toContain('$100,000.00')
    expect(view.container.textContent).toContain('Institutional Sync Active')

    const signalsMessage = {
      type: 'SIGNALS',
      data: {
        signals: [
          { symbol: 'BTCUSDT', direction: 'BUY', confidence: 0.95, price: 105, timestamp: '2026-06-05T08:03:00Z' },
          { symbol: 'ETHUSDT', direction: 'SELL', confidence: 0.81, price: 190, timestamp: '2026-06-05T08:04:00Z' },
          { symbol: 'SOLUSDT', direction: 'BUY', confidence: 0.7, price: 50, timestamp: '2026-06-05T08:05:00Z' },
        ],
      },
    }

    view.rerender(
      <PnLTracker
        bootstrapSignals={bootstrapSignals}
        wsLastMessage={signalsMessage}
      />,
    )
    await flush()

    expect(view.container.textContent).toContain('SOLUSDT')
    expect(view.container.textContent).toContain('67%')
    expect(view.container.textContent).toContain('3')
    expect(view.container.textContent).toContain('+$1,000.00')
    expect(view.container.textContent).toContain('$101,000.00')

    act(() => {
      vi.advanceTimersByTime(1500)
    })
    await flush()

    expect(view.container.textContent).toContain('+$1,000.55')
    expect(view.container.textContent).toContain('$101,000.55')

    view.unmount()
  })

  it('supports initial fetch and live account sync in light theme', async () => {
    currentTheme = 'light'

    const initialSignalsResponse = {
      json: () =>
        Promise.resolve({
          signals: [
            { symbol: 'EURUSD', direction: 'BUY', confidence: 0.77, price: 1.1, timestamp: '2026-06-05T08:00:00Z' },
          ],
        }),
    }

    fetchMock.mockResolvedValue(initialSignalsResponse)

    const liveMessage = {
      type: 'ACCOUNT_UPDATE',
      data: {
        summary: {
          profit: 1250,
          equity: 101250,
        },
        positions: [
          {
            symbol: 'XAUUSD',
            price_open: 2300,
            type: 0,
            time: 1717574400,
            price_current: 2310,
            profit: 1250,
            volume: 1,
          },
        ],
      },
    }

    const view = renderWithRoot(<PnLTracker wsLastMessage={null} />)
    await flush()

    expect(fetchMock).toHaveBeenCalledWith('/api/signals')
    expect(view.container.textContent).toContain('EURUSD')
    expect(view.container.textContent).toContain('0%')

    view.rerender(<PnLTracker skipInitialFetch wsLastMessage={liveMessage} />)
    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.textContent).toContain('Live Sync')
    expect(view.container.textContent).toContain('ELITE')
    expect(view.container.textContent).toContain('+$1,250.00')
    expect(view.container.textContent).toContain('$101,250.00')
    expect(view.container.textContent).toContain('XAUUSD')

    view.unmount()
  })

  it('supports skipInitialFetch and renders the light-theme empty state', async () => {
    currentTheme = 'light'

    const skipped = renderWithRoot(<PnLTracker skipInitialFetch wsLastMessage={null} />)
    await flush()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(skipped.container.textContent).toContain('No Active Positions')
    expect(skipped.container.textContent).toContain('Awaiting Sniper Confirmation')
    skipped.unmount()
  })
})
