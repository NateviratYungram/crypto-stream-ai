import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentInView = true
let latestMotionSet: ReturnType<typeof vi.fn> | null = null
let springChangeHandler: ((value: number) => void) | null = null
let unsubscribeSpy: ReturnType<typeof vi.fn> | null = null

vi.mock('framer-motion', () => ({
  useInView: () => currentInView,
  useMotionValue: () => {
    latestMotionSet = vi.fn()
    return {
      set: latestMotionSet,
    }
  },
  useSpring: () => {
    unsubscribeSpy = vi.fn()
    return {
      on: (_event: string, handler: (value: number) => void) => {
        springChangeHandler = handler
        return unsubscribeSpy
      },
    }
  },
}))

import { AnimatedCounter } from './AnimatedCounter'

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

describe('AnimatedCounter', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    currentInView = true
    latestMotionSet = null
    springChangeHandler = null
    unsubscribeSpy = null
  })

  it('starts the animation when the counter is in view and formats updates', () => {
    const view = renderWithRoot(<AnimatedCounter value={1234.567} decimals={1} />)

    expect(latestMotionSet).not.toBeNull()
    expect(latestMotionSet).toHaveBeenCalledWith(1234.567)

    act(() => {
      springChangeHandler?.(1234.567)
    })

    expect(view.container.querySelector('span')?.textContent).toBe('1,234.6')

    view.unmount()
    expect(unsubscribeSpy).toHaveBeenCalledTimes(1)
  })

  it('skips the motion set when out of view and supports down counters', () => {
    currentInView = false
    const view = renderWithRoot(<AnimatedCounter value={25} direction="down" decimals={0} />)

    expect(latestMotionSet).not.toHaveBeenCalled()

    act(() => {
      springChangeHandler?.(25)
    })

    expect(view.container.querySelector('span')?.textContent).toBe('25')

    view.unmount()
  })
})
