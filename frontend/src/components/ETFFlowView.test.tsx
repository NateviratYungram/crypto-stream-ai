import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let fetchMock: ReturnType<typeof vi.fn>

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

import { ETFFlowView } from './ETFFlowView'

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

async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('ETFFlowView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    localStorage.setItem('crypto_terminal_key', 'etf-key')
    vi.useFakeTimers()
    vi.restoreAllMocks()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('loads ETF flow data, supports filters, refresh, and hourly polling', async () => {
    vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('09:45 AM')
    fetchMock
      .mockResolvedValueOnce({
        json: async () => ({
          flows: [
            { symbol: 'SPY', price: 540.12, return_5d_pct: 2.14, vol_ratio: 2.3, flow_signal: 'INFLOW', flow_dir: 'UP' },
            { symbol: 'QQQ', price: 467.5, return_5d_pct: -1.1, vol_ratio: 1.4, flow_signal: 'OUTFLOW', flow_dir: 'DOWN' },
            { symbol: 'GLD', price: 225.4, return_5d_pct: 0.05, vol_ratio: 0.9, flow_signal: 'NEUTRAL', flow_dir: 'FLAT' },
          ],
          top_inflows: [{ symbol: 'SPY', price: 540.12, return_5d_pct: 2.14, vol_ratio: 2.3, flow_signal: 'INFLOW', flow_dir: 'UP' }],
          top_outflows: [{ symbol: 'QQQ', price: 467.5, return_5d_pct: -1.1, vol_ratio: 1.4, flow_signal: 'OUTFLOW', flow_dir: 'DOWN' }],
          market_theme: 'RISK ON rotation into growth',
          updated_at: '2026-06-05T09:45:00Z',
          warning: 'ETF snapshot lagging by 15 minutes.',
          _meta: { data_quality: 'live', updated_at: '2026-06-05T09:45:00Z' },
        }),
      })
      .mockResolvedValueOnce({
        json: async () => ({
          flows: [
            { symbol: 'IBIT', price: 41.75, return_5d_pct: 3.5, vol_ratio: 2.8, flow_signal: 'INFLOW', flow_dir: 'UP' },
          ],
          top_inflows: [{ symbol: 'IBIT', price: 41.75, return_5d_pct: 3.5, vol_ratio: 2.8, flow_signal: 'INFLOW', flow_dir: 'UP' }],
          top_outflows: [],
          market_theme: 'RISK ON rotation into crypto beta',
          _meta: { data_quality: 'partial', updated_at: '2026-06-05T10:00:00Z' },
        }),
      })
      .mockResolvedValue({
        json: async () => ({
          flows: [
            { symbol: 'TLT', price: 92.1, return_5d_pct: -0.8, vol_ratio: 1.2, flow_signal: 'OUTFLOW', flow_dir: 'DOWN' },
          ],
          top_inflows: [],
          top_outflows: [{ symbol: 'TLT', price: 92.1, return_5d_pct: -0.8, vol_ratio: 1.2, flow_signal: 'OUTFLOW', flow_dir: 'DOWN' }],
          market_theme: 'RISK OFF rotation into defensives',
          _meta: { data_quality: 'stale', updated_at: '2026-06-05T11:00:00Z' },
        }),
      })

    const view = renderWithRoot(<ETFFlowView />)
    await flush()

    expect(fetchMock).toHaveBeenCalledWith('/api/market/etf-flows', {
      headers: { 'X-API-Key': 'etf-key' },
    })
    expect(view.container.textContent).toContain('ETF Flows')
    expect(view.container.textContent).toContain('Live')
    expect(view.container.textContent).toContain('Updated 09:45 AM')
    expect(view.container.textContent).toContain('ETF snapshot lagging by 15 minutes.')
    expect(view.container.textContent).toContain('RISK ON rotation into growth')
    expect(view.container.textContent).toContain('SPY')
    expect(view.container.textContent).toContain('QQQ')
    expect(view.container.textContent).toContain('GLD')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('INFLOW'))?.click()
    })
    expect(view.container.textContent).toContain('SPY')
    expect(view.container.textContent).not.toContain('QQQ$467.5')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'))?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(view.container.textContent).toContain('IBIT')
    expect(view.container.textContent).toContain('Partial')

    act(() => {
      vi.advanceTimersByTime(3_600_000)
    })
    await flush()

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(view.container.textContent).toContain('TLT')
    expect(view.container.textContent).toContain('Snapshot')

    view.unmount()
  })

  it('renders light-theme empty state and clears loading after fetch failure', async () => {
    currentTheme = 'light'
    fetchMock.mockRejectedValue(new Error('offline'))

    const view = renderWithRoot(<ETFFlowView />)
    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('overflow-y-auto')
    expect(view.container.textContent).toContain('ETF Flows')
    expect(view.container.textContent).toContain('No data')
    expect(view.container.textContent).toContain('Syncing')
    expect(Array.from(view.container.querySelectorAll('svg')).some((icon) => icon.className.baseVal?.includes('animate-spin'))).toBe(false)

    view.unmount()
  })
})
