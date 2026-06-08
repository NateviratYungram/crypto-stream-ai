import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

let currentTheme = 'dark'

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, layoutId: _layoutId, ...props }: React.HTMLAttributes<HTMLDivElement> & { layoutId?: string }) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

vi.mock('./AppNavbar', () => ({
  AppNavbar: ({
    onMobileMenuClick,
    onLogout,
  }: {
    onMobileMenuClick: () => void
    onLogout: () => void
  }) => (
    <div>
      <button data-testid="open-mobile-nav" onClick={onMobileMenuClick}>
        open nav
      </button>
      <button data-testid="navbar-logout" onClick={onLogout}>
        logout
      </button>
    </div>
  ),
}))

vi.mock('./AppSidebar', () => ({
  AppSidebar: ({
    activeTab,
    setActiveTab,
    onNavClick,
    onLogout,
  }: {
    activeTab: string
    setActiveTab: (tab: string) => void
    onNavClick?: () => void
    onLogout: () => void
  }) => (
    <div data-testid={onNavClick ? 'mobile-sidebar' : 'desktop-sidebar'}>
      <span>{activeTab}</span>
      <button
        data-testid={onNavClick ? 'mobile-sidebar-action' : 'desktop-sidebar-action'}
        onClick={() => {
          setActiveTab('Risk & Alerts')
          onNavClick?.()
        }}
      >
        nav
      </button>
      <button data-testid={onNavClick ? 'mobile-sidebar-logout' : 'desktop-sidebar-logout'} onClick={onLogout}>
        logout
      </button>
    </div>
  ),
}))

import { MainLayout } from './MainLayout'

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

describe('MainLayout', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    currentTheme = 'dark'
  })

  it('renders dark layout, ticker content, mobile nav overlay, and strategy chat overflow state', () => {
    const setActiveTab = vi.fn()
    const onLogout = vi.fn()
    const view = renderWithRoot(
      <MainLayout
        activeTab="Strategy Chat"
        setActiveTab={setActiveTab}
        wsStatus="open"
        onOpenCommand={vi.fn()}
        tickerPrices={{
          BTC: { price: 100000, delta: 1.234 },
          ETH: { price: 2500, delta: -0.5 },
        }}
        onLogout={onLogout}
      >
        <div data-testid="content">body</div>
      </MainLayout>,
    )

    expect(view.container.querySelector('[data-testid="desktop-sidebar"]')?.textContent).toContain('Strategy Chat')
    expect(view.container.textContent).toContain('BTC')
    expect(view.container.textContent).toContain('$100,000.00')
    expect(view.container.textContent).toContain('+1.234%')
    expect(view.container.textContent).toContain('ETH')
    expect(view.container.textContent).toContain('-0.500%')
    expect(view.container.textContent).toContain('SOL')
    expect(view.container.textContent).toContain('---')
    expect(view.container.textContent).toContain('LIVE MARKET SYNC')

    const scrollRegion = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('custom-scrollbar'),
    )
    expect(scrollRegion?.className).toContain('overflow-hidden')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="open-mobile-nav"]')?.click()
    })

    expect(view.container.querySelector('[data-testid="mobile-sidebar"]')).not.toBeNull()

    const overlay = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('bg-black/80'),
    )
    act(() => {
      ;(overlay as HTMLDivElement | undefined)?.click()
    })

    expect(view.container.querySelector('[data-testid="mobile-sidebar"]')).toBeNull()

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[aria-label="Alpha"]')?.click()
    })

    expect(setActiveTab).toHaveBeenCalledWith('Alpha Terminal')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="navbar-logout"]')?.click()
    })

    expect(onLogout).toHaveBeenCalledTimes(1)

    view.unmount()
  })

  it('renders light theme variants and closes the mobile drawer after sidebar navigation', () => {
    currentTheme = 'light'
    const setActiveTab = vi.fn()
    const onLogout = vi.fn()
    const view = renderWithRoot(
      <MainLayout
        activeTab="Alpha Terminal"
        setActiveTab={setActiveTab}
        wsStatus="closed"
        onOpenCommand={vi.fn()}
        tickerPrices={{
          NASDAQ: { price: 18000, delta: 0.25 },
        }}
        onLogout={onLogout}
      >
        <div data-testid="content">body</div>
      </MainLayout>,
    )

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50 text-slate-900')
    expect(view.container.textContent).toContain('NASDAQ')
    expect(view.container.textContent).toContain('$18,000.00')

    const main = view.container.querySelector('main')
    expect(main?.className).toContain('bg-slate-100/30')
    expect(view.container.querySelector('[aria-current="page"]')?.getAttribute('aria-label')).toBe('Alpha')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="open-mobile-nav"]')?.click()
    })

    expect(view.container.querySelector('[data-testid="mobile-sidebar"]')).not.toBeNull()

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="mobile-sidebar-action"]')?.click()
    })

    expect(setActiveTab).toHaveBeenCalledWith('Risk & Alerts')
    expect(view.container.querySelector('[data-testid="mobile-sidebar"]')).toBeNull()

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="desktop-sidebar-logout"]')?.click()
    })

    expect(onLogout).toHaveBeenCalledTimes(1)

    view.unmount()
  })
})
