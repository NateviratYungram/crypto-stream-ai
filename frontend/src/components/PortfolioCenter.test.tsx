import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme: 'light' | 'dark' = 'dark'
let fetchMock: ReturnType<typeof vi.fn>

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, initial: _initial, animate: _animate, exit: _exit, transition: _transition, ...props }: React.HTMLAttributes<HTMLDivElement> & {
      initial?: unknown
      animate?: unknown
      exit?: unknown
      transition?: unknown
    }) => <div {...props}>{children}</div>,
    tr: ({ children, initial: _initial, animate: _animate, transition: _transition, ...props }: React.HTMLAttributes<HTMLTableRowElement> & {
      initial?: unknown
      animate?: unknown
      transition?: unknown
    }) => <tr {...props}>{children}</tr>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import { PortfolioCenter } from './PortfolioCenter'

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

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

function clickByText(container: HTMLElement, text: string | RegExp) {
  const clickTargets = Array.from(container.querySelectorAll('button, th'))
  const match = clickTargets.find((element) => {
    const content = element.textContent ?? ''
    return typeof text === 'string' ? content.includes(text) : text.test(content)
  })

  if (!match) {
    throw new Error(`Button not found for ${String(text)}`)
  }

  act(() => {
    match.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function makeAssets(count: number) {
  return Array.from({ length: count }, (_, index) => ({
    symbol: `ASSET${index.toString().padStart(2, '0')}`,
    name: index % 2 === 0 ? `Asset ${index}` : undefined,
    balance: 1000 - index,
    price: index % 3 === 0 ? 0 : 10 + index,
    usd_value: 2000 - index * 10,
    change_24h: index % 2 === 0 ? index / 10 : -(index / 10),
    allocation: Math.max(0, 100 - index),
    kind: index % 2 === 0 ? 'token' : 'native',
    token_address: index % 2 === 0 ? `0x${index.toString(16).padStart(40, '0')}` : null,
    logo: index === 0 ? 'https://example.com/logo.png' : undefined,
    priced: index % 3 !== 0,
  }))
}

describe('PortfolioCenter', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    localStorage.clear()
    localStorage.setItem('crypto_terminal_key', 'test-key')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders the empty state and surfaces lookup errors from quick-load requests', async () => {
    currentTheme = 'light'
    fetchMock.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: 'Wallet lookup failed loudly.' }),
    })

    const view = renderWithRoot(<PortfolioCenter />)

    expect(view.container.textContent).toContain('Portfolio Center')
    expect(view.container.textContent).toContain('No wallet loaded')
    expect(view.container.textContent).toContain('Paste any ETH or SOL address above')

    clickByText(view.container, /Vitalik Buterin/i)
    await flush()
    await flush()

    expect(view.container.textContent).toContain('Lookup error')
    expect(view.container.textContent).toContain('Wallet lookup failed loudly.')
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/portfolio/wallet?address='),
      expect.objectContaining({
        headers: { 'X-API-Key': 'test-key' },
      }),
    )

    view.unmount()
  })

  it('loads a wallet, supports tabs, filter, pagination, and clear reset', async () => {
    const assets = makeAssets(55)
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        address: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
        chain: 'ETH',
        total_usd: 1250000,
        assets,
        source: 'etherscan',
        explorer_url: 'https://etherscan.io/address/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
        identity: {
          display_name: 'Vitalik',
          resolved_name: 'Vitalik Buterin',
          avatar: '',
          description: 'Public wallet for testing.',
          twitter: 'vitalikbuterin',
          website: 'https://vitalik.ca',
          explorer_url: 'https://etherscan.io/address/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
        },
      }),
    })

    const view = renderWithRoot(<PortfolioCenter />)

    clickByText(view.container, /Vitalik Buterin/i)
    await flush()
    await flush()

    expect(view.container.textContent).toContain('Vitalik Buterin')
    expect(view.container.textContent).toContain('Public wallet for testing.')
    expect(view.container.textContent).toContain('@vitalikbuterin')
    expect(view.container.textContent).toContain('vitalik.ca')
    expect(view.container.textContent).toContain('$1.25M')
    expect(view.container.textContent).toContain('55')
    expect(view.container.textContent).toContain('65%')

    const explorerLink = Array.from(view.container.querySelectorAll('a')).find((link) => (link.textContent ?? '').includes('View on Explorer'))
    expect(explorerLink?.getAttribute('href')).toBe('https://etherscan.io/address/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045')

    clickByText(view.container, /^assets$/i)
    clickByText(view.container, /^history$/i)
    clickByText(view.container, /^overview$/i)

    clickByText(view.container, /All/)
    expect(view.container.textContent).toContain('Priced')
    expect(view.container.textContent).toContain('36 assets')

    clickByText(view.container, 'Balance')
    clickByText(view.container, 'Balance')

    clickByText(view.container, /Priced/)

    expect(view.container.textContent).toContain('1 / 2')
    expect(view.container.textContent).toContain('Showing 1–50 of 55')

    clickByText(view.container, /Next/i)
    expect(view.container.textContent).toContain('2 / 2')
    expect(view.container.textContent).toContain('Showing 51–55 of 55')

    clickByText(view.container, /Prev/i)
    expect(view.container.textContent).toContain('1 / 2')

    clickByText(view.container, /Clear/i)
    await flush()

    expect(view.container.textContent).toContain('No wallet loaded')
    view.unmount()
  }, 10000)
})
