import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

let currentTheme = 'dark'

vi.mock('../../contexts/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('../../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import { AppSidebar } from './AppSidebar'

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

describe('AppSidebar', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    currentTheme = 'dark'
  })

  it('renders navigation groups and active state for desktop sidebar', () => {
    const setActiveTab = vi.fn()
    const view = renderWithRoot(
      <AppSidebar
        activeTab="Strategy Chat"
        setActiveTab={setActiveTab}
        wsStatus="open"
        onLogout={vi.fn()}
      />,
    )

    expect(view.container.textContent).toContain('Trading & Discovery')
    expect(view.container.textContent).toContain('Analysis & Strategy')
    expect(view.container.textContent).toContain('sidebar.support_console')
    expect(view.container.textContent).toContain('navbar.signout')
    expect(view.container.textContent).toContain('OPEN')

    const searchInput = view.container.querySelector('input')
    expect(searchInput?.getAttribute('placeholder')).toBe('sidebar.search')

    const strategyButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Strategy Chat'),
    )
    expect(strategyButton?.className).toContain('bg-blue-600/15')

    view.unmount()
  })

  it('handles tab navigation, mobile close callback, and settings/logout actions', () => {
    const setActiveTab = vi.fn()
    const onNavClick = vi.fn()
    const onLogout = vi.fn()
    const view = renderWithRoot(
      <AppSidebar
        activeTab="Alpha Terminal"
        setActiveTab={setActiveTab}
        wsStatus="closed"
        onNavClick={onNavClick}
        onLogout={onLogout}
      />,
    )

    const riskButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Risk & Alerts'),
    )
    act(() => {
      riskButton?.click()
    })

    expect(setActiveTab).toHaveBeenCalledWith('Risk & Alerts')
    expect(onNavClick).toHaveBeenCalledTimes(1)

    const settingsButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('sidebar.support_console'),
    )
    act(() => {
      settingsButton?.click()
    })

    expect(setActiveTab).toHaveBeenCalledWith('Settings')
    expect(onNavClick).toHaveBeenCalledTimes(2)

    const logoutButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('navbar.signout'),
    )
    act(() => {
      logoutButton?.click()
    })

    expect(onLogout).toHaveBeenCalledTimes(1)
    expect(view.container.textContent).toContain('CLOSED')

    view.unmount()
  })

  it('renders light theme variants for mobile navigation and footer actions', () => {
    currentTheme = 'light'
    const view = renderWithRoot(
      <AppSidebar
        activeTab="Alpha Terminal"
        setActiveTab={vi.fn()}
        wsStatus="closed"
        onNavClick={vi.fn()}
        onLogout={vi.fn()}
      />,
    )

    const aside = view.container.querySelector('aside')
    expect(aside?.className).toContain('bg-white')
    expect(aside?.className).toContain('flex')

    const gradientOverlay = view.container.querySelector('.bg-gradient-to-b')
    expect(gradientOverlay).not.toBeNull()

    const alphaButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Alpha Terminal'),
    )
    expect(alphaButton?.className).toContain('bg-blue-600 border-blue-600 text-white')

    const moneyFlowButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Money Flow'),
    )
    expect(moneyFlowButton?.className).toContain('hover:bg-slate-100/80')

    const supportButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('sidebar.support_console'),
    )
    expect(supportButton?.className).toContain('bg-white hover:bg-slate-50 border-slate-200 text-slate-900')

    const logoutButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('navbar.signout'),
    )
    expect(logoutButton?.className).toContain('bg-rose-100 hover:bg-rose-200 border-rose-200 text-rose-700')

    view.unmount()
  })
})
