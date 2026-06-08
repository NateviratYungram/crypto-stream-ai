import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

let currentTheme = 'dark'
let currentLang = 'en'
const toggleTheme = vi.fn()
const setLang = vi.fn((next: 'en' | 'th') => {
  currentLang = next
})

vi.mock('../../contexts/LanguageContext', () => ({
  useLanguage: () => ({
    lang: currentLang,
    setLang,
    t: (key: string) =>
      ({
        'navbar.tagline': 'Institutional AI Trading Desk',
        'navbar.signout': 'Sign Out',
      })[key] ?? key,
  }),
}))

vi.mock('../../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
    toggleTheme,
  }),
}))

vi.mock('./MarketStatusClock', () => ({
  MarketStatusClock: () => <div data-testid="market-status">market clock</div>,
}))

import { AppNavbar } from './AppNavbar'

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

describe('AppNavbar', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    currentTheme = 'dark'
    currentLang = 'en'
    toggleTheme.mockReset()
    setLang.mockClear()
  })

  it('renders dark mode layout and handles menu, theme, language, and logout actions', () => {
    const onLogout = vi.fn()
    const onMobileMenuClick = vi.fn()
    const view = renderWithRoot(
      <AppNavbar
        onOpenCommand={vi.fn()}
        isAuthorized={true}
        onLogout={onLogout}
        onMobileMenuClick={onMobileMenuClick}
        onNavigate={vi.fn()}
      />,
    )

    const header = view.container.querySelector('header')
    expect(header?.className).toContain('bg-[#0a0f1d]/80')
    expect(view.container.textContent).toContain('CryptoStream')
    expect(view.container.textContent).toContain('Institutional AI Trading Desk')
    expect(view.container.querySelector('[data-testid="market-status"]')?.textContent).toBe('market clock')

    const buttons = view.container.querySelectorAll('button')
    act(() => {
      buttons[0]?.click()
      buttons[1]?.click()
      buttons[2]?.click()
      buttons[3]?.click()
    })

    expect(onMobileMenuClick).toHaveBeenCalledTimes(1)
    expect(toggleTheme).toHaveBeenCalledTimes(1)
    expect(setLang).toHaveBeenCalledWith('th')
    expect(onLogout).toHaveBeenCalledTimes(1)

    const brand = view.container.querySelector('.cursor-pointer')
    act(() => {
      ;(brand as HTMLDivElement | null)?.click()
    })

    expect(onLogout).toHaveBeenCalledTimes(2)
    expect(buttons[1]?.getAttribute('title')).toBe('Switch to Light Mode')
    expect(buttons[2]?.textContent).toBe('TH')

    view.unmount()
  })

  it('renders light mode styling and flips the language button label/title', () => {
    currentTheme = 'light'
    currentLang = 'th'

    const view = renderWithRoot(
      <AppNavbar
        onOpenCommand={vi.fn()}
        isAuthorized={false}
        onLogout={vi.fn()}
        onMobileMenuClick={vi.fn()}
      />,
    )

    const header = view.container.querySelector('header')
    expect(header?.className).toContain('bg-white shadow-sm')

    const buttons = view.container.querySelectorAll('button')
    expect(buttons[1]?.getAttribute('title')).toBe('Switch to Dark Mode')
    expect(buttons[2]?.getAttribute('title')).toBe('Switch to English')
    expect(buttons[2]?.textContent).toBe('EN')
    expect(buttons[3]?.className).toContain('bg-white hover:bg-slate-50 text-slate-700')

    act(() => {
      buttons[2]?.click()
    })

    expect(setLang).toHaveBeenCalledWith('en')

    view.unmount()
  })
})
