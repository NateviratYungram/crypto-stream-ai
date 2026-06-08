import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { useWebSocket, type WSMessage } from './useWebSocket'

class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  static OPEN = 1
  static CLOSED = 3

  url: string
  readyState = 0
  sent: string[] = []
  closed = false
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: (() => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(payload: string) {
    this.sent.push(payload)
  }

  close() {
    this.closed = true
    this.readyState = FakeWebSocket.CLOSED
  }

  triggerOpen() {
    this.readyState = FakeWebSocket.OPEN
    this.onopen?.()
  }

  triggerMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>)
  }

  triggerRawMessage(raw: string) {
    this.onmessage?.({ data: raw } as MessageEvent<string>)
  }

  triggerClose() {
    this.readyState = FakeWebSocket.CLOSED
    this.onclose?.()
  }

  triggerError() {
    this.onerror?.(new Event('error'))
  }
}

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

function HookHarness({ url }: { url: string }) {
  const { status, lastMessage, latency, reconnectCount, isConnected, sendMessage } = useWebSocket(url)

  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="latency">{latency === null ? 'null' : String(latency)}</span>
      <span data-testid="reconnect">{String(reconnectCount)}</span>
      <span data-testid="connected">{String(isConnected)}</span>
      <span data-testid="message">{lastMessage ? JSON.stringify(lastMessage) : 'null'}</span>
      <button data-testid="send" onClick={() => sendMessage({ type: 'CLIENT', data: 1 })}>
        send
      </button>
    </div>
  )
}

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    FakeWebSocket.instances = []
    ;(globalThis as typeof globalThis & { WebSocket: typeof FakeWebSocket }).WebSocket = FakeWebSocket as never
    document.body.innerHTML = ''
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('connects, tracks messages, pings, and sends outbound payloads', () => {
    const view = renderWithRoot(<HookHarness url="ws://test/socket" />)
    const socket = FakeWebSocket.instances[0]

    expect(socket.url).toBe('ws://test/socket')
    expect(view.container.querySelector('[data-testid="status"]')?.textContent).toBe('connecting')

    act(() => {
      socket.triggerOpen()
    })

    expect(view.container.querySelector('[data-testid="status"]')?.textContent).toBe('open')
    expect(view.container.querySelector('[data-testid="connected"]')?.textContent).toBe('true')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="send"]')?.click()
    })

    expect(socket.sent).toContain(JSON.stringify({ type: 'CLIENT', data: 1 }))

    act(() => {
      vi.advanceTimersByTime(10000)
    })

    expect(socket.sent).toContain(JSON.stringify({ type: 'PING' }))

    act(() => {
      socket.triggerMessage({ type: 'PONG' })
    })

    expect(view.container.querySelector('[data-testid="latency"]')?.textContent).not.toBe('null')

    const serverMessage: WSMessage = { type: 'SYSTEM', data: { ok: true } }
    act(() => {
      socket.triggerMessage(serverMessage)
    })

    expect(view.container.querySelector('[data-testid="message"]')?.textContent).toBe(JSON.stringify(serverMessage))

    view.unmount()
    expect(socket.closed).toBe(true)
  })

  it('ignores malformed payloads and reconnects with backoff after close', () => {
    const view = renderWithRoot(<HookHarness url="ws://retry/socket" />)
    const firstSocket = FakeWebSocket.instances[0]

    act(() => {
      firstSocket.triggerOpen()
      firstSocket.triggerRawMessage('{bad json')
      firstSocket.triggerClose()
    })

    expect(view.container.querySelector('[data-testid="status"]')?.textContent).toBe('closed')
    expect(view.container.querySelector('[data-testid="message"]')?.textContent).toBe('null')

    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(FakeWebSocket.instances).toHaveLength(2)
    expect(view.container.querySelector('[data-testid="reconnect"]')?.textContent).toBe('1')

    const secondSocket = FakeWebSocket.instances[1]
    act(() => {
      secondSocket.triggerOpen()
    })

    expect(view.container.querySelector('[data-testid="status"]')?.textContent).toBe('open')
    expect(view.container.querySelector('[data-testid="reconnect"]')?.textContent).toBe('0')

    view.unmount()
  })

  it('closes the socket on error', () => {
    const view = renderWithRoot(<HookHarness url="ws://error/socket" />)
    const socket = FakeWebSocket.instances[0]

    act(() => {
      socket.triggerError()
    })

    expect(socket.closed).toBe(true)

    view.unmount()
  })
})
