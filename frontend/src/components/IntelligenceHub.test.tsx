import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

let currentTheme: 'light' | 'dark' = 'dark'
let currentRetail = false

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
    isRetail: currentRetail,
  }),
}))

vi.mock('./HoverGlowCard', () => ({
  HoverGlowCard: ({
    children,
    className,
  }: {
    children: React.ReactNode
    className?: string
  }) => (
    <div data-testid="hover-card" className={className}>
      {children}
    </div>
  ),
}))

vi.mock('./SignalFeed', () => ({
  SignalFeed: ({
    bootstrapSignals,
    skipInitialFetch,
    wsLastMessage,
  }: {
    bootstrapSignals?: Array<{ symbol: string }>
    skipInitialFetch?: boolean
    wsLastMessage?: { type?: string } | null
  }) => (
    <div
      data-testid="signal-feed"
      data-count={bootstrapSignals?.length ?? 0}
      data-skip={skipInitialFetch ? 'yes' : 'no'}
      data-last={wsLastMessage?.type ?? 'none'}
    >
      {bootstrapSignals?.map((signal) => signal.symbol).join(',') ?? ''}
    </div>
  ),
}))

vi.mock('./PnLTracker', () => ({
  PnLTracker: ({
    bootstrapSignals,
    skipInitialFetch,
    wsLastMessage,
  }: {
    bootstrapSignals?: Array<{ symbol: string }>
    skipInitialFetch?: boolean
    wsLastMessage?: { type?: string } | null
  }) => (
    <div
      data-testid="pnl-tracker"
      data-count={bootstrapSignals?.length ?? 0}
      data-skip={skipInitialFetch ? 'yes' : 'no'}
      data-last={wsLastMessage?.type ?? 'none'}
    >
      pnl-{bootstrapSignals?.length ?? 0}
    </div>
  ),
}))

vi.mock('./Tooltip', () => ({
  FinancialTerm: ({
    children,
    term: _term,
  }: {
    children: React.ReactNode
    term: string
  }) => <>{children}</>,
}))

import { IntelligenceHub } from './IntelligenceHub'
import type { WSMessage } from '../hooks/useWebSocket'

function flush() {
  return act(async () => {
    await Promise.resolve()
  })
}

function renderHub(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    root,
    rerender(next: React.ReactNode) {
      act(() => {
        root.render(next)
      })
    },
    unmount() {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

function makeSignal(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    symbol: 'BTCUSDT',
    direction: 'BUY',
    confidence: 88,
    reason: 'Momentum breakout',
    price: 101234.56,
    delta_pct: 1.234,
    vol_surge: 1.4,
    ...overrides,
  }
}

describe('IntelligenceHub', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    currentTheme = 'dark'
    currentRetail = false
    document.body.innerHTML = ''
    sessionStorage.clear()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('hydrates cached signals, skips initial fetch, and reflects open websocket status', async () => {
    currentTheme = 'light'
    currentRetail = true

    sessionStorage.setItem(
      'intelligence_signals_cache_v1',
      JSON.stringify({
        signals: [
          makeSignal({ symbol: 'ETHUSDT', direction: 'SELL', confidence: 74 }),
          makeSignal({ symbol: 'SOLUSDT', direction: 'SELL', confidence: 68 }),
        ],
        dbOk: true,
        dqOk: null,
      }),
    )

    const view = renderHub(<IntelligenceHub wsStatus="open" wsLastMessage={null} />)
    await flush()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(view.container.textContent).toContain('BEARISH')
    expect(view.container.textContent).toContain('Pipeline Status')
    expect(view.container.textContent).toContain('WebSocket')
    expect(view.container.textContent).toContain('DB Metrics')
    expect(view.container.textContent).toContain('DQ Guard')
    expect(view.container.textContent).toContain('OK')
    expect(view.container.textContent).toContain('CHECKING...')
    expect(view.container.textContent).toContain('AI')

    const signalFeed = view.container.querySelector('[data-testid="signal-feed"]')
    const pnlTracker = view.container.querySelector('[data-testid="pnl-tracker"]')

    expect(signalFeed?.getAttribute('data-count')).toBe('2')
    expect(signalFeed?.getAttribute('data-skip')).toBe('yes')
    expect(signalFeed?.textContent).toContain('ETHUSDT,SOLUSDT')
    expect(pnlTracker?.getAttribute('data-count')).toBe('2')

    view.unmount()
  })

  it('loads initial signals, applies websocket updates, and persists backend health flags', async () => {
    fetchMock.mockResolvedValue({
      json: async () => ({
        signals: [makeSignal({ symbol: 'BTCUSDT', direction: 'BUY', confidence: 91 })],
      }),
    })

    const view = renderHub(<IntelligenceHub wsStatus="closed" wsLastMessage={null} />)
    await flush()
    await flush()

    expect(fetchMock).toHaveBeenCalledWith('/api/signals')
    expect(view.container.textContent).toContain('BULLISH')
    expect(view.container.textContent).toContain('FAIL')

    let signalFeed = view.container.querySelector('[data-testid="signal-feed"]')
    expect(signalFeed?.getAttribute('data-count')).toBe('1')

    const wsMessage = {
      type: 'SIGNALS',
      data: {
        signals: [
          makeSignal({ symbol: 'BTCUSDT', direction: 'BUY', confidence: 96 }),
          makeSignal({ symbol: 'ETHUSDT', direction: 'BUY', confidence: 83 }),
        ],
        db_ok: false,
        dq_ok: true,
      },
    } satisfies WSMessage

    view.rerender(<IntelligenceHub wsStatus="open" wsLastMessage={wsMessage} />)
    await flush()

    signalFeed = view.container.querySelector('[data-testid="signal-feed"]')
    const pnlTracker = view.container.querySelector('[data-testid="pnl-tracker"]')
    const cached = JSON.parse(sessionStorage.getItem('intelligence_signals_cache_v1') || '{}')

    expect(signalFeed?.getAttribute('data-count')).toBe('2')
    expect(signalFeed?.getAttribute('data-last')).toBe('SIGNALS')
    expect(pnlTracker?.getAttribute('data-count')).toBe('2')
    expect(cached.dbOk).toBe(false)
    expect(cached.dqOk).toBe(true)
    expect(cached.signals).toHaveLength(2)
    expect(view.container.textContent).toContain('OK')
    expect(view.container.textContent).toContain('FAIL')

    view.unmount()
  })
})
