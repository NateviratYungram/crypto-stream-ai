import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let fetchMock: ReturnType<typeof vi.fn>

vi.mock('framer-motion', () => ({
  motion: {
    div: ({
      children,
      initial: _initial,
      animate: _animate,
      exit: _exit,
      transition: _transition,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
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

import { AlertsReviewsView } from './AlertsReviewsView'

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
  })
}

describe('AlertsReviewsView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    localStorage.setItem('crypto_terminal_key', 'secret-key')
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('renders fetched data, supports tabs, dismisses alerts, refreshes, auto-refreshes, and sends telegram tests', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    fetchMock
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            alerts: [
              {
                id: 1,
                user_id: 'ml_scanner',
                symbol: 'BTCUSDT',
                condition: 'BUY breakout',
                message: 'Win probability 78% | AUC 0.812',
                status: 'ACTIVE',
                created_at: '2026-06-05T08:00:00Z',
              },
              {
                id: 2,
                symbol: 'XAUUSD',
                condition: 'Price below support',
                price: 2280,
                timeframe: 'H1',
                entry_source: 'manual_alert',
                message: 'Watch support',
                status: 'FIRED',
                triggered_at: '2026-06-05T08:30:00Z',
                created_at: '2026-06-05T08:00:00Z',
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            reviews: [
              {
                id: 11,
                review_text: 'Solid execution.',
                win_rate: 72.5,
                score: 82,
                created_at: '2026-06-05T09:00:00Z',
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ configured: false, missing: ['bot_token', 'chat_id'] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ detail: 'ok' }),
      })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ alerts: [] }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ reviews: [] }),
      })
      .mockRejectedValueOnce(new Error('status unavailable'))
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            alerts: [
              {
                id: 1,
                user_id: 'ml_scanner',
                symbol: 'BTCUSDT',
                condition: 'BUY breakout',
                message: 'Win probability 78% | AUC 0.812',
                status: 'ACTIVE',
                created_at: '2026-06-05T08:00:00Z',
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            reviews: [
              {
                id: 11,
                review_text: 'Solid execution.',
                win_rate: 72.5,
                score: 82,
                created_at: '2026-06-05T09:00:00Z',
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ configured: true, missing: [] }),
      })

    const view = renderWithRoot(<AlertsReviewsView />)
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/alerts/ml/stale', {
      method: 'DELETE',
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/alerts', {
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/trade-reviews', {
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/notifications/telegram/status', {
      headers: { 'X-API-Key': 'secret-key' },
    })

    expect(view.container.textContent).toContain('Intelligence Center')
    expect(view.container.textContent).toContain('Telegram Missing Config')
    expect(view.container.textContent).toContain('Missing: bot_token, chat_id')
    expect(view.container.textContent).toContain('ML Signals (1)')
    expect(view.container.textContent).toContain('Smart Alerts (1)')
    expect(view.container.textContent).toContain('Trade Reviews (1)')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('LONG')
    expect(view.container.textContent).toContain('78%')
    expect(view.container.textContent).toContain('0.812')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Test Telegram'))?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(5, '/api/notifications/telegram/test', {
      method: 'POST',
      headers: {
        'X-API-Key': 'secret-key',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    })
    expect(view.container.textContent).toContain('Telegram test sent successfully')
    expect(view.container.textContent).toContain('Telegram Configured')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Smart Alerts'))?.click()
    })
    expect(view.container.textContent).toContain('XAUUSD')
    expect(view.container.textContent).toContain('$2280.00')
    expect(view.container.textContent).toContain('Triggered')
    expect(view.container.textContent).toContain('manual alert')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[title="Dismiss alert"]')?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(6, '/api/alerts/2', {
      method: 'DELETE',
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(view.container.textContent).toContain('Dismissed')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Trade Reviews'))?.click()
    })
    expect(view.container.textContent).toContain('Solid execution.')
    expect(view.container.textContent).toContain('72.5%')
    expect(view.container.textContent).toContain('Performance score is strong')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Refresh'))?.click()
    })
    await flush()
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(7, '/api/alerts/ml/stale', {
      method: 'DELETE',
      headers: { 'X-API-Key': 'secret-key' },
    })

    act(() => {
      vi.advanceTimersByTime(3200)
    })
    expect(view.container.textContent).not.toContain('Telegram test sent successfully')

    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    await flush()

    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/alerts/ml/stale')).toHaveLength(3)
    expect(fetchMock).toHaveBeenCalledWith('/api/alerts', {
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect(errorSpy).toHaveBeenCalled()

    errorSpy.mockRestore()
    view.unmount()
  })

  it('renders light-theme empty states and telegram error feedback', async () => {
    currentTheme = 'light'

    fetchMock
      .mockRejectedValueOnce(new Error('purge failed'))
      .mockRejectedValueOnce(new Error('alerts failed'))
      .mockRejectedValueOnce(new Error('reviews failed'))
      .mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ detail: 'Bot not configured' }),
      })

    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const view = renderWithRoot(<AlertsReviewsView />)
    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(errorSpy).toHaveBeenCalled()
    expect(view.container.textContent).toContain('No ML signals yet.')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Test Telegram'))?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/notifications/telegram/test', {
      method: 'POST',
      headers: {
        'X-API-Key': 'secret-key',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({}),
    })
    expect(view.container.textContent).toContain('Bot not configured')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Smart Alerts'))?.click()
    })
    expect(view.container.textContent).toContain('No smart alerts yet.')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Trade Reviews'))?.click()
    })
    expect(view.container.textContent).toContain('No trade reviews yet.')

    act(() => {
      vi.advanceTimersByTime(3200)
    })
    expect(view.container.textContent).not.toContain('Bot not configured')

    errorSpy.mockRestore()
    view.unmount()
  })
})
