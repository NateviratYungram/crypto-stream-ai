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

import { AlertManager } from './AlertManager'

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

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
  setter?.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

function setSelectValue(select: HTMLSelectElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set
  setter?.call(select, value)
  select.dispatchEvent(new Event('change', { bubbles: true }))
}

describe('AlertManager', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('adds alerts, saves telegram settings, triggers, resets, and deletes alerts', () => {
    const toastSpy = vi.fn()
    const notificationSpy = vi.fn()
    const requestPermission = vi.fn()

    vi.stubGlobal(
      'Notification',
      Object.assign(notificationSpy, {
        permission: 'granted',
        requestPermission,
      }),
    )

    const view = renderWithRoot(
      <AlertManager currentPrices={{ BTCUSDT: 98000, ETHUSDT: 3200 }} onToast={toastSpy} />,
    )

    act(() => {
      view.container.querySelector('button')?.click()
    })

    const priceInput = view.container.querySelector('input[type="number"]') as HTMLInputElement
    const symbolSelects = view.container.querySelectorAll('select')

    act(() => {
      setSelectValue(symbolSelects[0] as HTMLSelectElement, 'ETHUSDT')
      setSelectValue(symbolSelects[1] as HTMLSelectElement, 'below')
      setInputValue(priceInput, '3000')
    })

    act(() => {
      const buttons = view.container.querySelectorAll('button')
      ;(buttons[2] as HTMLButtonElement).click()
    })

    expect(view.container.textContent).toContain('ETH')
    expect(view.container.textContent).toContain('Watching')
    expect(JSON.parse(localStorage.getItem('cs_price_alerts') || '[]')).toHaveLength(1)

    act(() => {
      const buttons = view.container.querySelectorAll('button')
      ;(buttons[1] as HTMLButtonElement).click()
    })

    const textInput = view.container.querySelector('input[type="text"]') as HTMLInputElement
    act(() => {
      setInputValue(textInput, '998877')
    })
    act(() => {
      const buttons = view.container.querySelectorAll('button')
      ;(buttons[2] as HTMLButtonElement).click()
    })

    expect(localStorage.getItem('cs_telegram_chat_id')).toBe('998877')
    expect(toastSpy).toHaveBeenCalledWith('✅ Telegram settings updated')

    act(() => {
      const buttons = view.container.querySelectorAll('button')
      ;(buttons[1] as HTMLButtonElement).click()
    })

    act(() => {
      if (view.container.textContent?.includes('Telegram Chat ID')) {
        const buttons = view.container.querySelectorAll('button')
        ;(buttons[1] as HTMLButtonElement).click()
      }
    })

    view.rerender(<AlertManager currentPrices={{ BTCUSDT: 98000, ETHUSDT: 2990 }} onToast={toastSpy} />)

    expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('ETHUSDT is now below $3,000'))
    expect(notificationSpy).toHaveBeenCalledWith(
      'CryptoStream Alert',
      expect.objectContaining({
        body: expect.stringContaining('ETHUSDT is now below $3,000'),
      }),
    )
    expect(view.container.textContent).toContain('Triggered')

    act(() => {
      Array.from(view.container.querySelectorAll('button'))
        .find((button) => button.querySelector('svg') && button.className.includes('hover:text-amber-400'))
        ?.click()
    })

    expect(view.container.textContent).toContain('Watching')

    act(() => {
      Array.from(view.container.querySelectorAll('button'))
        .find((button) => button.querySelector('svg') && button.className.includes('hover:text-rose-400'))
        ?.click()
    })

    expect(view.container.textContent).toContain('No active alerts')
    expect(JSON.parse(localStorage.getItem('cs_price_alerts') || '[]')).toEqual([])
    expect(requestPermission).not.toHaveBeenCalled()

    view.unmount()
  })

  it('requests notification permission on first add and ignores invalid prices', () => {
    const toastSpy = vi.fn()
    const requestPermission = vi.fn()

    vi.stubGlobal(
      'Notification',
      Object.assign(vi.fn(), {
        permission: 'default',
        requestPermission,
      }),
    )

    const view = renderWithRoot(
      <AlertManager currentPrices={{ BTCUSDT: 100000 }} onToast={toastSpy} />,
    )

    act(() => {
      view.container.querySelector('button')?.click()
    })

    const numberInput = view.container.querySelector('input[type="number"]') as HTMLInputElement
    act(() => {
      setInputValue(numberInput, '0')
    })

    act(() => {
      const buttons = view.container.querySelectorAll('button')
      ;(buttons[2] as HTMLButtonElement).click()
    })

    expect(JSON.parse(localStorage.getItem('cs_price_alerts') || '[]')).toEqual([])

    act(() => {
      setInputValue(numberInput, '105000')
    })

    act(() => {
      const buttons = view.container.querySelectorAll('button')
      ;(buttons[2] as HTMLButtonElement).click()
    })

    expect(requestPermission).toHaveBeenCalledTimes(1)
    expect(JSON.parse(localStorage.getItem('cs_price_alerts') || '[]')).toHaveLength(1)

    view.unmount()
  })
})
