import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'
import { ModeContext } from '../contexts/ModeContext'

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

function themed(element: React.ReactNode, theme: 'dark' | 'light' = 'dark') {
  return (
    <ModeContext.Provider
      value={{
        mode: 'retail',
        setMode: () => {},
        theme,
        toggleTheme: () => {},
        isRetail: true,
        isInstitutional: false,
      }}
    >
      {element}
    </ModeContext.Provider>
  )
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.restoreAllMocks()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('renders children when healthy', () => {
    const view = renderWithRoot(
      themed(
        <ErrorBoundary tabName="Signals">
          <div data-testid="child">healthy</div>
        </ErrorBoundary>,
      ),
    )

    expect(view.container.querySelector('[data-testid="child"]')?.textContent).toBe('healthy')

    view.unmount()
  })

  it('shows the network error fallback, toggles details, and resets successfully', () => {
    let shouldThrow = true

    function FlakyChild() {
      if (shouldThrow) {
        throw new Error('fetch failed while loading module')
      }
      return <div data-testid="recovered">recovered</div>
    }

    const view = renderWithRoot(
      themed(
        <ErrorBoundary tabName="Signals">
          <FlakyChild />
        </ErrorBoundary>,
        'dark',
      ),
    )

    expect(view.container.textContent).toContain('Signals Unavailable')
    expect(view.container.textContent).toContain('Connection Error')

    const buttons = view.container.querySelectorAll('button')

    act(() => {
      buttons[0]?.click()
    })

    expect(view.container.textContent).toContain('fetch failed while loading module')

    shouldThrow = false
    act(() => {
      buttons[1]?.click()
    })

    expect(view.container.querySelector('[data-testid="recovered"]')?.textContent).toBe('recovered')

    view.unmount()
  })

  it('shows the generic render error label in light theme and reloads the page', () => {
    const reloadSpy = vi.fn()
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, reload: reloadSpy },
    })

    function BrokenChild() {
      throw new Error('')
    }

    const view = renderWithRoot(
      themed(
        <ErrorBoundary tabName="Dashboard">
          <BrokenChild />
        </ErrorBoundary>,
        'light',
      ),
    )

    expect(view.container.textContent).toContain('Dashboard Unavailable')
    expect(view.container.textContent).toContain('Render Error')

    act(() => {
      view.container.querySelectorAll('button')[0]?.click()
    })

    expect(view.container.querySelector('code')?.textContent).toBeTruthy()

    act(() => {
      view.container.querySelectorAll('button')[2]?.click()
    })

    expect(reloadSpy).toHaveBeenCalledTimes(1)

    view.unmount()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
  })

  it('falls back to "Unknown error" when the boundary has no error message', () => {
    const boundaryRef = { current: null as ErrorBoundary | null }

    const view = renderWithRoot(
      themed(
        <ErrorBoundary ref={instance => { boundaryRef.current = instance }} tabName="Audit">
          <div>stable</div>
        </ErrorBoundary>,
        'light',
      ),
    )

    act(() => {
      boundaryRef.current?.setState({ hasError: true, error: null, showDetails: true })
    })

    expect(view.container.textContent).toContain('Audit Unavailable')
    expect(view.container.querySelector('code')?.textContent).toContain('Unknown error')

    view.unmount()
  })
})
