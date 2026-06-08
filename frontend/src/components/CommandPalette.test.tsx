import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

let institutionalMode = true

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    isInstitutional: institutionalMode,
  }),
}))

import { CommandPalette } from './CommandPalette'

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

describe('CommandPalette', () => {
  beforeEach(() => {
    institutionalMode = true
    document.body.innerHTML = ''
    vi.restoreAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('returns null outside institutional mode', () => {
    institutionalMode = false
    const view = renderWithRoot(
      <CommandPalette open={true} onClose={vi.fn()} onNavigate={vi.fn()} />,
    )

    expect(view.container.textContent).toBe('')

    view.unmount()
  })

  it('resets query/selection and focuses the search input when opened', () => {
    const onClose = vi.fn()
    const onNavigate = vi.fn()
    const focusSpy = vi.spyOn(HTMLInputElement.prototype, 'focus').mockImplementation(() => {})
    const view = renderWithRoot(
      <CommandPalette open={false} onClose={onClose} onNavigate={onNavigate} />,
    )

    expect(view.container.textContent).toBe('')

    view.rerender(<CommandPalette open={true} onClose={onClose} onNavigate={onNavigate} />)

    const input = view.container.querySelector('input')
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      nativeSetter?.call(input, 'whale')
      input?.dispatchEvent(new Event('input', { bubbles: true }))
      vi.advanceTimersByTime(50)
    })

    expect(focusSpy).toHaveBeenCalled()
    expect(view.container.textContent).toContain('Whale Tracker')

    view.rerender(<CommandPalette open={false} onClose={onClose} onNavigate={onNavigate} />)
    expect(view.container.textContent).toBe('')

    view.unmount()
  })

  it('filters commands, navigates with keyboard, and closes on escape', () => {
    const onClose = vi.fn()
    const onNavigate = vi.fn()
    const reloadSpy = vi.fn()
    const originalLocation = window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, reload: reloadSpy },
    })

    const view = renderWithRoot(
      <CommandPalette open={true} onClose={onClose} onNavigate={onNavigate} />,
    )

    const input = view.container.querySelector('input')
    act(() => {
      input?.dispatchEvent(new Event('focus'))
    })

    expect(view.container.textContent).toContain('Market Trends')
    expect(view.container.textContent).toContain('Refresh Signal Feed')

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
    })

    expect(view.container.textContent).toContain('Risk Audits')

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    })

    expect(onNavigate).toHaveBeenCalledWith('Risk Audits')
    expect(onClose).toHaveBeenCalledTimes(1)

    view.rerender(<CommandPalette open={true} onClose={onClose} onNavigate={onNavigate} />)

    const refreshedInput = view.container.querySelector('input')
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      nativeSetter?.call(refreshedInput, 'refresh')
      refreshedInput?.dispatchEvent(new Event('input', { bubbles: true }))
    })

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    })

    expect(reloadSpy).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(2)

    act(() => {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    })

    expect(onClose).toHaveBeenCalledTimes(3)

    view.unmount()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
  })

  it('supports empty results, arrow navigation, and export action', () => {
    const onClose = vi.fn()
    const onNavigate = vi.fn()
    const originalCreateElement = document.createElement.bind(document)
    const createElementSpy = vi.spyOn(document, 'createElement')
    const linkClick = vi.fn()
    createElementSpy.mockImplementation(((tagName: string) => {
      const element = originalCreateElement(tagName)
      if (tagName.toLowerCase() === 'a') {
        Object.defineProperty(element, 'click', {
          configurable: true,
          value: linkClick,
        })
      }
      return element as HTMLElement
    }) as typeof document.createElement)

    const view = renderWithRoot(
      <CommandPalette open={true} onClose={onClose} onNavigate={onNavigate} />,
    )

    const input = view.container.querySelector('input')
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      nativeSetter?.call(input, 'zzzz')
      input?.dispatchEvent(new Event('input', { bubbles: true }))
    })

    expect(view.container.textContent).toContain('No commands found')

    view.rerender(<CommandPalette open={true} onClose={onClose} onNavigate={onNavigate} />)

    const nextInput = view.container.querySelector('input')
    act(() => {
      const nativeSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      nativeSetter?.call(nextInput, 'export')
      nextInput?.dispatchEvent(new Event('input', { bubbles: true }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown' }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp' }))
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
    })

    expect(linkClick).toHaveBeenCalledTimes(1)
    expect(onClose).toHaveBeenCalledTimes(1)
    expect(onNavigate).not.toHaveBeenCalled()

    view.unmount()
  })
})
