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

vi.mock('./WhaleTrackerView', () => ({
  WhaleTrackerView: () => <div data-testid="whales-view">whales</div>,
}))

vi.mock('./ETFFlowView', () => ({
  ETFFlowView: () => <div data-testid="etf-view">etf</div>,
}))

vi.mock('./PortfolioCenter', () => ({
  PortfolioCenter: ({ tickerPrices }: { tickerPrices: unknown }) => (
    <div data-testid="institutional-view">{JSON.stringify(tickerPrices)}</div>
  ),
}))

import { MoneyFlow } from './MoneyFlow'

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

describe('MoneyFlow', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    sessionStorage.clear()
  })

  it('renders the default whales tab and persists tab visits', async () => {
    const tickerPrices = { BTC: { price: 100, delta: 1 } }
    const view = renderWithRoot(<MoneyFlow tickerPrices={tickerPrices} />)

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="whales-view"]')?.textContent).toBe('whales')
    expect(sessionStorage.getItem('crypto_money_flow_subtab')).toBe('WHALES')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('ETF Flows'))?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="etf-view"]')?.textContent).toBe('etf')
    expect(sessionStorage.getItem('crypto_money_flow_subtab')).toBe('ETF')
    expect(view.container.querySelector('[data-testid="whales-view"]')).not.toBeNull()

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Inst. Assets'))?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="institutional-view"]')?.textContent).toContain('"BTC"')
    expect(sessionStorage.getItem('crypto_money_flow_subtab')).toBe('INSTITUTIONAL')

    view.unmount()
  })

  it('hydrates from session storage and renders light theme styling', async () => {
    currentTheme = 'light'
    sessionStorage.setItem('crypto_money_flow_subtab', 'ETF')

    const view = renderWithRoot(<MoneyFlow tickerPrices={{}} />)

    await act(async () => {
      await Promise.resolve()
    })

    const sticky = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('sticky top-0'),
    )
    expect(sticky?.className).toContain('bg-white/80 border-slate-200')
    expect(view.container.querySelector('[data-testid="etf-view"]')?.textContent).toBe('etf')
    expect(view.container.querySelector('[data-testid="whales-view"]')).not.toBeNull()

    view.unmount()
  })
})
