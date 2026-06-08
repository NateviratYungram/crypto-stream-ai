import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { vi } from 'vitest'

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import { ShortcutsHelp } from './ShortcutsHelp'

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

describe('ShortcutsHelp', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('renders nothing when closed', () => {
    const view = renderWithRoot(<ShortcutsHelp open={false} onClose={vi.fn()} />)

    expect(view.container.textContent).toBe('')

    view.unmount()
  })

  it('renders the shortcut groups and closes from backdrop and button', () => {
    const onClose = vi.fn()
    const view = renderWithRoot(<ShortcutsHelp open={true} onClose={onClose} />)

    expect(view.container.textContent).toContain('Keyboard Shortcuts')
    expect(view.container.textContent).toContain('Navigation')
    expect(view.container.textContent).toContain('Quick Jump')
    expect(view.container.textContent).toContain('Quick Symbols (in Chat)')
    expect(view.container.textContent).toContain('Ctrl + K')
    expect(view.container.textContent).toContain('/btc')

    const overlay = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('bg-black/70'),
    )
    act(() => {
      ;(overlay as HTMLDivElement | undefined)?.click()
    })

    expect(onClose).toHaveBeenCalledTimes(1)

    const closeButton = view.container.querySelector('button')
    act(() => {
      closeButton?.click()
    })

    expect(onClose).toHaveBeenCalledTimes(2)

    view.unmount()
  })
})
