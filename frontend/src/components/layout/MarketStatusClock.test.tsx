import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../../contexts/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) =>
      ({
        'navbar.market_gold': 'FOREX',
        'navbar.market_stocks': 'STOCKS',
        'navbar.market_open': 'OPEN',
        'navbar.market_closed': 'CLOSED',
        'navbar.opens_in': 'OPENS IN',
        'navbar.closes_in': 'CLOSES IN',
      })[key] ?? key,
  }),
}))

import { MarketStatusClock } from './MarketStatusClock'

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

describe('MarketStatusClock', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders backend market status, rotates markets, and refreshes on interval', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          crypto: { status: 'OPEN', label: '24/7' },
          forex: {
            status: 'OPEN',
            next_event: 'CLOSE',
            seconds_remaining: 3661,
            event_time: '2026-06-05T12:30:00.000Z',
          },
          stocks: {
            status: 'HOLIDAY',
            next_event: 'OPEN',
            seconds_remaining: 1800,
            event_time: '2026-06-05T13:00:00.000Z',
          },
          timestamp_utc: '2026-06-05T11:29:00.000Z',
        }),
      })
      .mockResolvedValue({
        ok: true,
        json: async () => ({
          crypto: { status: 'OPEN', label: '24/7' },
          forex: {
            status: 'OPEN',
            next_event: 'CLOSE',
            seconds_remaining: 120,
            event_time: '2026-06-05T12:32:00.000Z',
          },
          stocks: {
            status: 'CLOSED',
            next_event: 'OPEN',
            seconds_remaining: 900,
            event_time: '2026-06-05T12:45:00.000Z',
          },
          timestamp_utc: '2026-06-05T11:30:00.000Z',
        }),
      })
    vi.stubGlobal('fetch', fetchSpy)

    const view = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('FOREX')
    expect(view.container.textContent).toContain('OPEN')
    expect(view.container.textContent).toContain('01:01:01')
    expect(view.container.textContent).toContain('CLOSES IN')

    act(() => {
      vi.advanceTimersByTime(6000)
    })

    expect(view.container.textContent).toContain('STOCKS')
    expect(view.container.textContent).toContain('HOLIDAY')
    expect(view.container.textContent).toContain('00:30:00')
    expect(view.container.textContent).toContain('OPENS IN')

    act(() => {
      vi.advanceTimersByTime(30000)
    })

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchSpy).toHaveBeenCalledTimes(2)

    view.unmount()
  })

  it('falls back to local status when backend fetch fails and logs the sync error', async () => {
    vi.setSystemTime(new Date('2026-06-07T22:15:00.000Z'))
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('boom')))
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})

    const view = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(errorSpy).toHaveBeenCalled()
    expect(view.container.textContent).toContain('FOREX')
    expect(view.container.textContent).toContain('OPEN')
    expect(view.container.textContent).toContain('CLOSES IN')

    act(() => {
      vi.advanceTimersByTime(6000)
    })

    expect(view.container.textContent).toContain('STOCKS')
    expect(view.container.textContent).toContain('CLOSED')
    expect(view.container.textContent).toContain('OPENS IN')

    view.unmount()
  })

  it('covers local fallback windows for forex closed and stocks open sessions', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
    vi.spyOn(console, 'error').mockImplementation(() => {})

    vi.setSystemTime(new Date('2026-06-06T10:00:00.000Z'))
    const saturdayView = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(saturdayView.container.textContent).toContain('FOREX')
    expect(saturdayView.container.textContent).toContain('CLOSED')
    expect(saturdayView.container.textContent).toContain('OPENS IN')

    saturdayView.unmount()

    vi.setSystemTime(new Date('2026-06-08T15:00:00.000Z'))
    const weekdayView = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    act(() => {
      vi.advanceTimersByTime(6000)
    })

    expect(weekdayView.container.textContent).toContain('STOCKS')
    expect(weekdayView.container.textContent).toContain('OPEN')
    expect(weekdayView.container.textContent).toContain('CLOSES IN')

    weekdayView.unmount()

    vi.setSystemTime(new Date('2026-06-05T22:00:00.000Z'))
    const fridayView = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fridayView.container.textContent).toContain('FOREX')
    expect(fridayView.container.textContent).toContain('CLOSED')

    fridayView.unmount()
  })

  it('handles closed backend responses and invalid event times gracefully', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({}),
      }),
    )
    const toLocaleTimeStringSpy = vi
      .spyOn(Date.prototype, 'toLocaleTimeString')
      .mockImplementation(function mockTime() {
        if (Number.isNaN(this.getTime())) {
          throw new RangeError('invalid time')
        }
        return '08:00 PM'
      })

    const view = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('FOREX')

    act(() => {
      vi.advanceTimersByTime(6000)
    })

    expect(view.container.textContent).toContain('STOCKS')

    ;(globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        crypto: { status: 'OPEN', label: '24/7' },
        forex: {
          status: 'CLOSED',
          next_event: 'OPEN',
          seconds_remaining: -1,
          event_time: 'not-a-date',
        },
        stocks: {
          status: 'CLOSED',
          next_event: 'OPEN',
          seconds_remaining: -5,
          event_time: '2026-06-05T12:45:00.000Z',
        },
        timestamp_utc: '2026-06-05T11:30:00.000Z',
      }),
    })

    act(() => {
      vi.advanceTimersByTime(30000)
    })

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('CLOSED')
    expect(view.container.textContent).toContain('00:00:00')
    expect(view.container.textContent).toContain('--:--')

    toLocaleTimeStringSpy.mockRestore()
    view.unmount()
  })

  it('renders holiday styling for a forex backend response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          crypto: { status: 'OPEN', label: '24/7' },
          forex: {
            status: 'HOLIDAY',
            next_event: 'OPEN',
            seconds_remaining: 60,
            event_time: '2026-06-05T12:31:00.000Z',
          },
          stocks: {
            status: 'OPEN',
            next_event: 'CLOSE',
            seconds_remaining: 3600,
            event_time: '2026-06-05T13:30:00.000Z',
          },
          timestamp_utc: '2026-06-05T11:30:00.000Z',
        }),
      }),
    )

    const view = renderWithRoot(<MarketStatusClock />)

    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(view.container.textContent).toContain('FOREX')
    expect(view.container.textContent).toContain('HOLIDAY')

    view.unmount()
  })
})
