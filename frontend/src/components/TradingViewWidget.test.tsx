import { act } from 'react'
import { createRoot } from 'react-dom/client'
import TradingViewWidget from './TradingViewWidget'

function renderWithRoot(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)

  act(() => {
    root.render(element)
  })

  return {
    container,
    rerender: (next: React.ReactNode) => {
      act(() => {
        root.render(next)
      })
    },
    unmount: () => {
      act(() => {
        root.unmount()
      })
      container.remove()
    },
  }
}

describe('TradingViewWidget', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
    vi.spyOn(Math, 'random').mockReturnValue(0.123456789)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('creates the tradingview script once after the timer fires', () => {
    const view = renderWithRoot(<TradingViewWidget symbol="BINANCE:BTCUSDT" interval="60" />)

    const widgetHost = view.container.querySelector('#tv_chart_4fzzzxjyl')
    expect(widgetHost).not.toBeNull()
    expect(widgetHost?.querySelector('script')).toBeNull()

    act(() => {
      vi.advanceTimersByTime(150)
    })

    const script = widgetHost?.querySelector('script')
    expect(script).not.toBeNull()
    expect(script?.getAttribute('src')).toContain('tradingview.com')
    expect(script?.innerHTML).toContain('"symbol":"BINANCE:BTCUSDT"')
    expect(script?.innerHTML).toContain('"interval":"60"')

    view.rerender(<TradingViewWidget symbol="BINANCE:ETHUSDT" interval="240" />)

    act(() => {
      vi.advanceTimersByTime(150)
    })

    expect(widgetHost?.querySelectorAll('script')).toHaveLength(1)

    view.unmount()
  })

  it('cleans up the widget markup on unmount', () => {
    const view = renderWithRoot(<TradingViewWidget symbol="BINANCE:BTCUSDT" />)

    act(() => {
      vi.advanceTimersByTime(150)
    })

    const widgetHost = view.container.querySelector('#tv_chart_4fzzzxjyl')
    expect(widgetHost?.innerHTML).toContain('embed-widget-advanced-chart.js')

    view.unmount()

    expect(document.body.innerHTML).toBe('')
  })
})
