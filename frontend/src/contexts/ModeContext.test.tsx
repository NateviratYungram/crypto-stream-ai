import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { ModeProvider, useMode } from './ModeContext'

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

function ModeHarness() {
  const { mode, theme, toggleTheme, isRetail, isInstitutional } = useMode()

  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="theme">{theme}</span>
      <span data-testid="retail">{String(isRetail)}</span>
      <span data-testid="institutional">{String(isInstitutional)}</span>
      <button data-testid="toggle" onClick={toggleTheme}>
        toggle
      </button>
    </div>
  )
}

describe('ModeContext', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.innerHTML = ''
    document.documentElement.className = ''
  })

  it('defaults to retail mode and dark theme', () => {
    const view = renderWithRoot(
      <ModeProvider>
        <ModeHarness />
      </ModeProvider>,
    )

    expect(view.container.querySelector('[data-testid="mode"]')?.textContent).toBe('retail')
    expect(view.container.querySelector('[data-testid="theme"]')?.textContent).toBe('dark')
    expect(view.container.querySelector('[data-testid="retail"]')?.textContent).toBe('true')
    expect(view.container.querySelector('[data-testid="institutional"]')?.textContent).toBe('false')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('cs_theme')).toBe('dark')

    view.unmount()
  })

  it('loads stored theme and toggles between light and dark', () => {
    localStorage.setItem('cs_theme', 'light')

    const view = renderWithRoot(
      <ModeProvider>
        <ModeHarness />
      </ModeProvider>,
    )

    expect(view.container.querySelector('[data-testid="theme"]')?.textContent).toBe('light')
    expect(document.documentElement.classList.contains('light')).toBe(true)

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="toggle"]')?.click()
    })

    expect(view.container.querySelector('[data-testid="theme"]')?.textContent).toBe('dark')
    expect(document.documentElement.classList.contains('dark')).toBe(true)
    expect(localStorage.getItem('cs_theme')).toBe('dark')

    view.unmount()
  })
})
