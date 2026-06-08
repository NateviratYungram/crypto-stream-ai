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
      transition: _transition,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      transition?: unknown
    }) => <div {...props}>{children}</div>,
  },
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import { EconomicCalendarView } from './EconomicCalendarView'

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

function isoDate(offsetDays: number) {
  const date = new Date()
  date.setHours(0, 0, 0, 0)
  date.setDate(date.getDate() + offsetDays)
  return date.toISOString()
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('EconomicCalendarView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('renders live calendar data, supports filters, range changes, refresh, and generated source links', async () => {
    const todayEvent = {
      date: isoDate(0),
      time: '14:30',
      type: 'MACRO',
      name: 'US CPI',
      impact: 'CRITICAL',
      currency: 'USD',
      actual: '3.1%',
      forecast: '3.0%',
      previous: '2.9%',
      desc: 'Inflation print',
      source: 'macro_feed',
    }
    const tomorrowEvent = {
      date: isoDate(1),
      type: 'EARNINGS',
      name: 'NVIDIA Earnings',
      symbol: 'NVDA',
      impact: 'HIGH',
      estimate_eps: 1.23,
      is_estimated: true,
    }

    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({
            events: [todayEvent, tomorrowEvent],
            macro_watch: [{ name: 'Fed Watch', abbrev: 'FOMC', impact: 'HIGH', desc: 'Rate path risk' }],
            trading_note: 'Reduce size around CPI.',
            source_status: 'live_feed',
            _meta: { data_quality: 'live', updated_at: '2026-06-05T08:00:00Z' },
          }),
      })
      .mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            events: [todayEvent, tomorrowEvent],
            macro_watch: [{ name: 'Fed Watch', abbrev: 'FOMC', impact: 'HIGH', desc: 'Rate path risk' }],
            trading_note: 'Reduce size around CPI.',
            source_status: 'live_feed',
            _meta: { data_quality: 'live', updated_at: '2026-06-05T08:00:00Z' },
          }),
      })

    const view = renderWithRoot(<EconomicCalendarView />)
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/market/calendar?days=7', {
      headers: { 'X-API-Key': 'demo' },
    })
    expect(view.container.textContent).toContain('Economic Calendar')
    expect(view.container.textContent).toContain('US CPI')
    expect(view.container.textContent).toContain('NVIDIA Earnings')
    expect(view.container.textContent).toContain('Live Feed')
    expect(view.container.textContent).toContain('Reduce size around CPI.')
    expect(view.container.textContent).toContain('Avoid fresh entries into critical windows.')
    expect(view.container.textContent).toContain('2')
    expect(view.container.textContent).toContain('FOMC')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('EARNINGS'))?.click()
    })
    expect(view.container.textContent).toContain('NVIDIA Earnings')
    expect(view.container.textContent).toContain('EPS Est.')
    expect(view.container.textContent).toContain('Total Events1')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('14D'))?.click()
    })
    await flush()
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/market/calendar?days=14', {
      headers: { 'X-API-Key': 'demo' },
    })

    act(() => {
      view.container.querySelector<HTMLButtonElement>('button[title^="Last updated"]')?.click()
    })
    await flush()
    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/market/calendar?days=14', {
      headers: { 'X-API-Key': 'demo' },
    })

    act(() => {
      vi.advanceTimersByTime(30 * 60 * 1000)
    })
    await flush()
    expect(fetchMock).toHaveBeenNthCalledWith(4, '/api/market/calendar?days=14', {
      headers: { 'X-API-Key': 'demo' },
    })

    view.unmount()
  })

  it('hydrates cached watch-only data and shows light-theme fallback messaging for empty or unavailable feeds', async () => {
    currentTheme = 'light'
    localStorage.setItem(
      'economic_calendar_cache_v1',
      JSON.stringify({
        savedAt: Date.now(),
        data: {
          upcoming_events: [],
          macro_watch: [{ name: 'Jobs Watch', impact: 'MEDIUM', desc: 'Labor data due soon' }],
          trading_note: 'Monitor spreads into data releases.',
          source_status: 'watch_only',
          status: 'ERROR',
          error: 'Calendar source unavailable.',
          updated_at: 'invalid-date',
        },
      }),
    )

    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
    })

    const view = renderWithRoot(<EconomicCalendarView />)
    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).toContain('Monitor spreads into data releases.')
    expect(view.container.textContent).toContain('Estimated')
    expect(view.container.textContent).toContain('Jobs Watch')
    expect(view.container.textContent).toContain('No dated events in feed yet. Use Macro Watch above.')
    expect(view.container.textContent).toContain('Calendar is still usable through the macro watchlist and trading note.')
    expect(view.container.textContent).toContain('Calendar request failed (503)')
    expect(view.container.textContent).toContain('No critical window detected.')

    view.unmount()
  })
})
