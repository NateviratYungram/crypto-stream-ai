import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let lastOnAnalyze: ((sym: string) => void) | undefined

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, layoutId: _layoutId, initial: _initial, animate: _animate, transition: _transition, ...props }: React.HTMLAttributes<HTMLDivElement> & {
      layoutId?: string
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

vi.mock('./ScreenerView', () => ({
  ScreenerView: () => <div data-testid="screener-view">screener</div>,
}))

vi.mock('./WatchlistPanel', () => ({
  WatchlistPanel: ({ onAnalyze }: { onAnalyze?: (sym: string) => void }) => {
    lastOnAnalyze = onAnalyze
    return <div data-testid="watchlist-view">watchlist</div>
  },
}))

vi.mock('./BrokerExecutionPanel', () => ({
  BrokerExecutionPanel: () => <div data-testid="broker-view">broker</div>,
}))

import { AlphaTerminal } from './AlphaTerminal'

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

describe('AlphaTerminal', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    sessionStorage.clear()
    lastOnAnalyze = undefined
  })

  it('renders the default screener tab, preserves visited tabs, and supports fast execution', async () => {
    const onAnalyze = vi.fn()
    const view = renderWithRoot(<AlphaTerminal onAnalyze={onAnalyze} />)

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="screener-view"]')?.textContent).toBe('screener')
    expect(sessionStorage.getItem('crypto_alpha_terminal_subtab')).toBeNull()

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Surveillance'))?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="watchlist-view"]')?.textContent).toBe('watchlist')
    expect(lastOnAnalyze).toBe(onAnalyze)
    expect(sessionStorage.getItem('crypto_alpha_terminal_subtab')).toBe('WATCHLIST')
    expect(view.container.querySelector('[data-testid="screener-view"]')).not.toBeNull()

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Fast Execution'))?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="broker-view"]')?.textContent).toBe('broker')
    expect(sessionStorage.getItem('crypto_alpha_terminal_subtab')).toBe('BROKER')

    view.unmount()
  })

  it('hydrates the stored tab and renders light theme styles', async () => {
    currentTheme = 'light'
    sessionStorage.setItem('crypto_alpha_terminal_subtab', 'BROKER')

    const view = renderWithRoot(<AlphaTerminal />)

    await act(async () => {
      await Promise.resolve()
    })

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50 text-slate-900')
    expect(view.container.querySelector('[data-testid="broker-view"]')?.textContent).toBe('broker')
    expect(view.container.querySelector('[data-testid="screener-view"]')).not.toBeNull()

    view.unmount()
  })
})
