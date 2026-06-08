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

vi.mock('./RiskAuditsView', () => ({
  RiskAuditsView: () => <div data-testid="risk-view">risk</div>,
}))

vi.mock('./AlertsReviewsView', () => ({
  AlertsReviewsView: () => <div data-testid="alerts-view">alerts</div>,
}))

vi.mock('./FundingRatesView', () => ({
  FundingRatesView: () => <div data-testid="funding-view">funding</div>,
}))

vi.mock('./DataAnomaliesView', () => ({
  DataAnomaliesView: () => <div data-testid="anomalies-view">anomalies</div>,
}))

vi.mock('./BestAiControlView', () => ({
  BestAiControlView: () => <div data-testid="best-ai-view">best-ai</div>,
}))

import { RiskAlerts } from './RiskAlerts'

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

describe('RiskAlerts', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    sessionStorage.clear()
  })

  it('renders the default risk tab and preserves visited tab content', async () => {
    const view = renderWithRoot(<RiskAlerts />)

    await act(async () => {
      await Promise.resolve()
    })

    expect(view.container.querySelector('[data-testid="risk-view"]')?.textContent).toBe('risk')
    expect(sessionStorage.getItem('crypto_risk_alerts_subtab')).toBe('RISK')

    for (const label of ['Alerts Hub', 'Anomalies', 'Funding', 'Best AI']) {
      act(() => {
        Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes(label))?.click()
      })
      await act(async () => {
        await Promise.resolve()
      })
    }

    expect(view.container.querySelector('[data-testid="alerts-view"]')).not.toBeNull()
    expect(view.container.querySelector('[data-testid="anomalies-view"]')).not.toBeNull()
    expect(view.container.querySelector('[data-testid="funding-view"]')).not.toBeNull()
    expect(view.container.querySelector('[data-testid="best-ai-view"]')).not.toBeNull()
    expect(sessionStorage.getItem('crypto_risk_alerts_subtab')).toBe('BEST_AI')

    view.unmount()
  })

  it('hydrates a stored tab and renders light theme styles', async () => {
    currentTheme = 'light'
    sessionStorage.setItem('crypto_risk_alerts_subtab', 'FUNDING')

    const view = renderWithRoot(<RiskAlerts />)

    await act(async () => {
      await Promise.resolve()
    })

    const sticky = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('sticky top-0'),
    )
    expect(sticky?.className).toContain('bg-white/80 border-slate-200')
    expect(view.container.querySelector('[data-testid="funding-view"]')?.textContent).toBe('funding')
    expect(view.container.querySelector('[data-testid="risk-view"]')).not.toBeNull()

    view.unmount()
  })
})
