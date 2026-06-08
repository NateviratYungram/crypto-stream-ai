import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, initial: _initial, animate: _animate, transition: _transition, ...props }: React.HTMLAttributes<HTMLDivElement> & {
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

vi.mock('./TradingJournalView', () => ({
  TradingJournalView: () => <div data-testid="journal-view">journal</div>,
}))

vi.mock('./BacktesterView', () => ({
  BacktesterView: () => <div data-testid="backtester-view">backtester</div>,
}))

vi.mock('./PaperTradingDashboard', () => ({
  PaperTradingDashboard: () => <div data-testid="paper-view">paper</div>,
}))

import { StrategyLab } from './StrategyLab'

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

describe('StrategyLab', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    sessionStorage.clear()
  })

  it('renders the default journal tab and keeps visited tabs mounted', async () => {
    const view = renderWithRoot(<StrategyLab />)

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="journal-view"]')?.textContent).toBe('journal')
    expect(sessionStorage.getItem('crypto_strategy_lab_subtab')).toBe('JOURNAL')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Backtester'))?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="backtester-view"]')?.textContent).toBe('backtester')
    expect(view.container.querySelector('[data-testid="journal-view"]')).not.toBeNull()
    expect(sessionStorage.getItem('crypto_strategy_lab_subtab')).toBe('BACKTESTER')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Paper Trade'))?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="paper-view"]')?.textContent).toBe('paper')
    expect(sessionStorage.getItem('crypto_strategy_lab_subtab')).toBe('PAPER')

    view.unmount()
  })

  it('hydrates a stored tab and renders light theme styles', async () => {
    currentTheme = 'light'
    sessionStorage.setItem('crypto_strategy_lab_subtab', 'PAPER')

    const view = renderWithRoot(<StrategyLab />)

    await act(async () => {
      await Promise.resolve()
    })

    const sticky = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('sticky top-0'),
    )
    expect(sticky?.className).toContain('bg-white/80 border-slate-200')
    expect(view.container.querySelector('[data-testid="paper-view"]')?.textContent).toBe('paper')
    expect(view.container.querySelector('[data-testid="journal-view"]')).not.toBeNull()

    view.unmount()
  })
})
