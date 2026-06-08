import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { FinancialTerm } from './Tooltip'
import { ModeContext, type AppMode, type ThemeMode } from '../contexts/ModeContext'

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

function modeValue(overrides: Partial<{
  mode: AppMode
  theme: ThemeMode
  isRetail: boolean
  isInstitutional: boolean
}> = {}) {
  return {
    mode: 'retail' as AppMode,
    setMode: () => {},
    theme: 'dark' as ThemeMode,
    toggleTheme: () => {},
    isRetail: true,
    isInstitutional: false,
    ...overrides,
  }
}

describe('FinancialTerm', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('shows plain content when retail mode is off', () => {
    const view = renderWithRoot(
      <ModeContext.Provider value={modeValue({ isRetail: false, isInstitutional: true, mode: 'institutional' })}>
        <FinancialTerm term="VWAP">Visible Label</FinancialTerm>
      </ModeContext.Provider>,
    )

    expect(view.container.textContent).toContain('Visible Label')
    expect(view.container.querySelector('svg')).toBeNull()

    view.unmount()
  })

  it('shows tooltip content for known terms on hover in retail mode', () => {
    const view = renderWithRoot(
      <ModeContext.Provider value={modeValue()}>
        <FinancialTerm term="VWAP" />
      </ModeContext.Provider>,
    )

    const wrapper = view.container.querySelector('span.relative') as HTMLSpanElement
    expect(wrapper.textContent).toContain('VWAP')

    act(() => {
      wrapper.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    })

    expect(view.container.textContent).toContain('Volume-Weighted Average Price')

    view.unmount()
  })

  it('falls back to plain term when dictionary entry is missing', () => {
    const view = renderWithRoot(
      <ModeContext.Provider value={modeValue()}>
        <FinancialTerm term="UNKNOWN_TERM" />
      </ModeContext.Provider>,
    )

    expect(view.container.textContent).toBe('UNKNOWN_TERM')
    expect(view.container.querySelector('svg')).toBeNull()

    view.unmount()
  })
})
