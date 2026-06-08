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

import { FundingRatesView } from './FundingRatesView'

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

describe('FundingRatesView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    vi.useFakeTimers()
    vi.restoreAllMocks()
    localStorage.setItem('crypto_terminal_key', 'demo-key')
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads funding data, shows extremes, and refreshes on interval', async () => {
    vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('10:11:12')
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        json: async () => ({
          rates: [
            { symbol: 'BTCUSDT', rate_pct: 0.25, annual_pct: 11.2, mark_price: 100000, sentiment: 'EXTREME BULLISH', signal: 'CONTRARIAN SHORT' },
            { symbol: 'ETHUSDT', rate_pct: -0.05, annual_pct: -2.4, mark_price: 2500, sentiment: 'BEARISH', signal: 'HOLD' },
          ],
        }),
      })
      .mockResolvedValue({
        json: async () => ({
          rates: [
            { symbol: 'SOLUSDT', rate_pct: -0.31, annual_pct: -15.4, mark_price: 175.45, sentiment: 'EXTREME BEARISH', signal: 'CONTRARIAN LONG' },
          ],
        }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<FundingRatesView />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/market/funding-rates', {
      headers: { 'X-API-Key': 'demo-key' },
    })
    expect(view.container.textContent).toContain('Funding Rates')
    expect(view.container.textContent).toContain('BTCUSDT (+0.250%)')
    expect(view.container.textContent).toContain('1 Long / 0 Short')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('CONTRARIAN SHORT')
    expect(view.container.textContent).toContain('10:11:12')

    act(() => {
      vi.advanceTimersByTime(300000)
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(view.container.textContent).toContain('SOLUSDT')
    expect(view.container.textContent).toContain('CONTRARIAN LONG')

    view.unmount()
  })

  it('handles empty and loading states in light theme and supports manual refresh', async () => {
    currentTheme = 'light'
    vi.spyOn(Date.prototype, 'toLocaleTimeString').mockReturnValue('01:23:45')
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        json: async () => ({ rates: [] }),
      })
      .mockResolvedValueOnce({
        json: async () => ({
          rates: [
            { symbol: 'XAUUSD', rate_pct: 0.01, annual_pct: 0.5, mark_price: 2334.12, sentiment: 'NEUTRAL', signal: 'HOLD' },
          ],
        }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<FundingRatesView />)

    expect(view.container.querySelectorAll('tbody tr').length).toBeGreaterThan(0)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).toContain('No data')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(view.container.textContent).toContain('XAUUSD')
    expect(view.container.textContent).toContain('HOLD')

    view.unmount()
  })

  it('swallows fetch errors and clears the loading state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))

    const view = renderWithRoot(<FundingRatesView />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('No data')
    expect(Array.from(view.container.querySelectorAll('svg')).some((icon) => icon.className.baseVal?.includes('animate-spin'))).toBe(false)

    view.unmount()
  })
})
