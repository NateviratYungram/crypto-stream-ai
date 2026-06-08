import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { TabSkeleton } from './TabSkeleton'

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

describe('TabSkeleton', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('renders card variant with requested card count', () => {
    const view = renderWithRoot(<TabSkeleton variant="cards" cards={4} />)

    expect(view.container.querySelectorAll('.h-60').length).toBe(4)

    view.unmount()
  })

  it('renders feed variant with heading bar and rows', () => {
    const view = renderWithRoot(<TabSkeleton variant="feed" rows={3} />)

    expect(view.container.querySelectorAll('.h-20').length).toBe(3)
    expect(view.container.querySelector('.h-8')).not.toBeNull()

    view.unmount()
  })

  it('renders table variant rows by default branch', () => {
    const view = renderWithRoot(<TabSkeleton variant="table" rows={2} />)

    expect(view.container.querySelectorAll('.w-10.h-10').length).toBe(2)

    view.unmount()
  })
})
