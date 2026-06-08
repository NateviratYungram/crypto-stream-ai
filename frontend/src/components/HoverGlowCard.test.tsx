import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { HoverGlowCard } from './HoverGlowCard'

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

describe('HoverGlowCard', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('renders children and updates glow coordinates on mouse move', () => {
    const view = renderWithRoot(
      <HoverGlowCard className="custom-card">
        <span data-testid="child">hello</span>
      </HoverGlowCard>,
    )

    const card = view.container.firstElementChild as HTMLDivElement
    expect(card.className).toContain('custom-card')
    expect(view.container.querySelector('[data-testid="child"]')?.textContent).toBe('hello')

    card.getBoundingClientRect = () =>
      ({
        left: 10,
        top: 20,
        width: 200,
        height: 100,
        right: 210,
        bottom: 120,
        x: 10,
        y: 20,
        toJSON: () => ({}),
      }) as DOMRect

    act(() => {
      const event = new MouseEvent('mousemove', { clientX: 35, clientY: 55, bubbles: true })
      card.dispatchEvent(event)
    })

    expect(card.style.getPropertyValue('--mouse-x')).toBe('25px')
    expect(card.style.getPropertyValue('--mouse-y')).toBe('35px')

    view.unmount()
  })
})
