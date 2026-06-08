import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, initial: _initial, animate: _animate, exit: _exit, transition: _transition, ...props }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      exit?: unknown
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

import { WatchlistPanel } from './WatchlistPanel'

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

describe('WatchlistPanel', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    vi.restoreAllMocks()
    vi.useFakeTimers()
    localStorage.setItem('crypto_terminal_key', 'watch-key')
    vi.stubGlobal('alert', vi.fn())
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads items, renders cards, refreshes, analyzes, and removes items', async () => {
    const onAnalyze = vi.fn()
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          watchlist: [
            { id: 1, symbol: 'BTC', note: 'Momentum', price: 100000, change_pct: 1.2 },
            { id: 2, symbol: 'ETH', price: null, change_pct: -2.5 },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          watchlist: [
            { id: 1, symbol: 'BTC', note: 'Momentum', price: 100000, change_pct: 1.2 },
          ],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<WatchlistPanel onAnalyze={onAnalyze} />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/watchlist', {
      headers: { 'X-API-Key': 'watch-key', 'Content-Type': 'application/json' },
    })
    expect(view.container.textContent).toContain('Priority')
    expect(view.container.textContent).toContain('BTC')
    expect(view.container.textContent).toContain('ETH')
    expect(view.container.textContent).toContain('+1.20%')
    expect(view.container.textContent).toContain('-2.50%')
    expect(view.container.textContent).toContain('Momentum')
    expect(view.container.textContent).toContain('---')

    const btcLabel = Array.from(view.container.querySelectorAll('span')).find((node) => node.textContent === 'BTC')
    const btcCard = btcLabel?.closest('.cursor-pointer')
    act(() => {
      ;(btcCard as HTMLDivElement | undefined)?.click()
    })
    expect(onAnalyze).toHaveBeenCalledWith('BTC')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.getAttribute('title') === 'Remove from surveillance')?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/watchlist/BTC', {
      method: 'DELETE',
      headers: { 'X-API-Key': 'watch-key', 'Content-Type': 'application/json' },
    })
    expect(alert).toHaveBeenCalledWith('Removed BTC from watchlist')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Synchronize Data'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledTimes(3)

    view.unmount()
  })

  it('supports add success and empty-state rendering in light theme', async () => {
    currentTheme = 'light'
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ watchlist: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ ok: true }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          watchlist: [
            { id: 3, symbol: 'SOL', note: 'Breakout', price: 175.12, change_pct: 0.75 },
          ],
        }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<WatchlistPanel />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).toContain('Zero Surveillance Assets')

    const inputs = view.container.querySelectorAll('input')
    act(() => {
      const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      valueSetter?.call(inputs[0], 'sol')
      inputs[0]?.dispatchEvent(new Event('input', { bubbles: true }))
      valueSetter?.call(inputs[1], 'Breakout')
      inputs[1]?.dispatchEvent(new Event('input', { bubbles: true }))
    })

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Deploy Target'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledWith('/api/watchlist', {
      method: 'POST',
      headers: { 'X-API-Key': 'watch-key', 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol: 'SOL', note: 'Breakout' }),
    })
    expect(view.container.textContent).toContain('SOL')

    view.unmount()
  })

  it('reports API and network failures through alerts', async () => {
    const consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ watchlist: [] }),
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 400,
        json: async () => ({ detail: 'duplicate' }),
      })
      .mockRejectedValueOnce(new Error('offline'))
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<WatchlistPanel />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(console.error).not.toBeUndefined()

    const inputs = view.container.querySelectorAll('input')
    act(() => {
      const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      valueSetter?.call(inputs[0], 'btc')
      inputs[0]?.dispatchEvent(new Event('input', { bubbles: true }))
    })

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Deploy Target'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(alert).toHaveBeenCalledWith('Failed to add: duplicate')
    ;(alert as ReturnType<typeof vi.fn>).mockClear()

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Synchronize Data'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(consoleErrorSpy).toHaveBeenCalled()

    view.unmount()
  })

  it('reports network failure while adding and remove failure messages', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          watchlist: [
            { id: 1, symbol: 'BTC', price: 100000, change_pct: 1.2 },
          ],
        }),
      })
      .mockRejectedValueOnce(new Error('link down'))
      .mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: async () => ({ detail: 'nope' }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<WatchlistPanel />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    const inputs = view.container.querySelectorAll('input')
    act(() => {
      const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      valueSetter?.call(inputs[0], 'eth')
      inputs[0]?.dispatchEvent(new Event('input', { bubbles: true }))
    })

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Deploy Target'))?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(alert).toHaveBeenCalledWith('Network error: link down')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.getAttribute('title') === 'Remove from surveillance')?.click()
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(alert).toHaveBeenCalledWith('Failed to delete: 503')

    view.unmount()
  })
})
