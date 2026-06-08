import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let idleCallback = false
let canceledIdleIds: number[] = []

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

vi.mock('./TabSkeleton', () => ({
  TabSkeleton: ({ variant }: { variant: string }) => <div data-testid="tab-skeleton">{variant}</div>,
}))

vi.mock('./TrendsView', () => ({
  TrendsView: ({ wsStatus }: { wsStatus: string }) => <div data-testid="trends-view">{wsStatus}</div>,
}))

vi.mock('./NewsSentimentHub', () => ({
  NewsSentimentHub: () => <div data-testid="sentiment-view">sentiment</div>,
}))

vi.mock('./IntelligenceHub', () => ({
  IntelligenceHub: ({ wsLastMessage }: { wsLastMessage: { type?: string } | null }) => (
    <div data-testid="macro-view">{wsLastMessage?.type ?? 'none'}</div>
  ),
}))

vi.mock('./EconomicCalendarView', () => ({
  EconomicCalendarView: () => <div data-testid="calendar-view">calendar</div>,
}))

vi.mock('./TacticsHub', () => ({
  TacticsHub: () => <div data-testid="tactics-view">tactics</div>,
}))

import { MarketIntelligence } from './MarketIntelligence'

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

describe('MarketIntelligence', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    idleCallback = false
    canceledIdleIds = []
    document.body.innerHTML = ''
    sessionStorage.clear()
    vi.useRealTimers()
    delete (window as Window & {
      requestIdleCallback?: (cb: IdleRequestCallback, options?: IdleRequestOptions) => number
      cancelIdleCallback?: (id: number) => void
    }).requestIdleCallback
    delete (window as Window & {
      requestIdleCallback?: (cb: IdleRequestCallback, options?: IdleRequestOptions) => number
      cancelIdleCallback?: (id: number) => void
    }).cancelIdleCallback
  })

  it('renders the default trends tab, prefetches tabs, and keeps visited tabs mounted', async () => {
    vi.useFakeTimers()
    const view = renderWithRoot(<MarketIntelligence wsStatus="open" wsLastMessage={{ type: 'signal' }} />)

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="trends-view"]')?.textContent).toBe('open')
    expect(sessionStorage.getItem('crypto_market_intel_subtab')).toBe('TRENDS')

    for (const label of ['Sentiment', 'Tactics', 'Macro Hub', 'Calendar']) {
      const button = Array.from(view.container.querySelectorAll('button')).find((node) => node.textContent?.includes(label))
      act(() => {
        button?.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }))
        button?.dispatchEvent(new FocusEvent('focus', { bubbles: true }))
        button?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
      await act(async () => {
        await Promise.resolve()
      })
    }

    act(() => {
      vi.runAllTimers()
    })

    expect(view.container.querySelector('[data-testid="sentiment-view"]')).not.toBeNull()
    expect(view.container.querySelector('[data-testid="tactics-view"]')).not.toBeNull()
    expect(view.container.querySelector('[data-testid="macro-view"]')?.textContent).toBe('signal')
    expect(view.container.querySelector('[data-testid="calendar-view"]')).not.toBeNull()
    expect(view.container.querySelector('[data-testid="trends-view"]')).not.toBeNull()
    expect(sessionStorage.getItem('crypto_market_intel_subtab')).toBe('CALENDAR')

    view.unmount()
  })

  it('hydrates a stored tab, renders light theme styles, and cancels idle preloads on unmount', async () => {
    currentTheme = 'light'
    sessionStorage.setItem('crypto_market_intel_subtab', 'MACRO')

    ;(window as Window & {
      requestIdleCallback: (cb: IdleRequestCallback, options?: IdleRequestOptions) => number
      cancelIdleCallback: (id: number) => void
    }).requestIdleCallback = ((cb: IdleRequestCallback) => {
      idleCallback = true
      cb({ didTimeout: false, timeRemaining: () => 10 } as IdleDeadline)
      return idleCallback ? canceledIdleIds.length + 1 : 0
    }) as (cb: IdleRequestCallback, options?: IdleRequestOptions) => number

    ;(window as Window & {
      requestIdleCallback: (cb: IdleRequestCallback, options?: IdleRequestOptions) => number
      cancelIdleCallback: (id: number) => void
    }).cancelIdleCallback = (id: number) => {
      canceledIdleIds.push(id)
    }

    const view = renderWithRoot(<MarketIntelligence wsStatus="closed" wsLastMessage={{ type: 'macro' }} />)

    await act(async () => {
      await Promise.resolve()
    })

    const sticky = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('sticky top-0'),
    )
    expect(sticky?.className).toContain('bg-white/80 border-slate-200')
    expect(view.container.querySelector('[data-testid="macro-view"]')?.textContent).toBe('macro')
    expect(view.container.querySelector('[data-testid="trends-view"]')).not.toBeNull()
    expect(idleCallback).toBe(true)

    view.unmount()

    expect(canceledIdleIds).toHaveLength(3)
    expect(canceledIdleIds.every((id) => id === 1)).toBe(true)
  })
})
