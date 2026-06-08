import { act } from 'react'
import { createRoot } from 'react-dom/client'

vi.mock('framer-motion', () => ({
  motion: {
    div: ({
      children,
      initial: _initial,
      animate: _animate,
      exit: _exit,
      transition: _transition,
      ...props
    }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      exit?: unknown
      transition?: unknown
    }) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

import { OnboardingTour } from './OnboardingTour'

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

describe('OnboardingTour', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('advances through steps, changes tabs, and completes on the last action', () => {
    const onComplete = vi.fn()
    const onTabChange = vi.fn()
    const view = renderWithRoot(<OnboardingTour onComplete={onComplete} onTabChange={onTabChange} />)

    expect(view.container.textContent).toContain('Market Trends')
    expect(view.container.querySelectorAll('.bg-blue-500').length).toBe(1)

    const nextButton = () =>
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('ถัด')) as
        | HTMLButtonElement
        | undefined

    act(() => {
      nextButton()?.click()
    })
    expect(onTabChange).toHaveBeenNthCalledWith(1, 'Whale Tracker')
    expect(view.container.textContent).toContain('Whale Tracker')

    act(() => {
      nextButton()?.click()
    })
    expect(onTabChange).toHaveBeenNthCalledWith(2, 'Intelligence Hub')
    expect(view.container.textContent).toContain('Intelligence Hub')

    act(() => {
      nextButton()?.click()
    })
    expect(onTabChange).toHaveBeenNthCalledWith(3, 'Strategy Chat')
    expect(view.container.textContent).toContain('Strategy Chat')

    act(() => {
      nextButton()?.click()
    })
    expect(view.container.textContent).toContain('พร้อมใช้งาน')

    const startButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('เริ่ม'),
    )
    act(() => {
      startButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onComplete).toHaveBeenCalledTimes(1)

    view.unmount()
  })

  it('supports dismissing the tour immediately', () => {
    const onComplete = vi.fn()
    const view = renderWithRoot(<OnboardingTour onComplete={onComplete} />)

    const closeButton = Array.from(view.container.querySelectorAll('button')).find((button) => !button.textContent)
    act(() => {
      closeButton?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onComplete).toHaveBeenCalledTimes(1)

    view.unmount()
  })
})
