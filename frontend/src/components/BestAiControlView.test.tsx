import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let fetchMock: ReturnType<typeof vi.fn>

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import BestAiControlView from './BestAiControlView'

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

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('BestAiControlView', () => {
  beforeEach(() => {
    currentTheme = 'dark'
    document.body.innerHTML = ''
    localStorage.clear()
    localStorage.setItem('crypto_terminal_key', 'secret-key')
    vi.useFakeTimers()
    fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('loads controls, supports sync/build actions, refreshes, and polls on an interval', async () => {
    const metricsPayload = {
      total_snapshots: 24,
      horizons: {
        '4h': {
          evaluated: 12,
          wins: 7,
          losses: 5,
          win_rate: 0.58,
          avg_return: 0.0123,
        },
      },
      by_symbol: {
        BTCUSDT: { snapshots: 10, evaluated_4h: 6, win_rate_4h: 0.66, avg_return_4h: 0.02 },
        ETHUSDT: { snapshots: 8, evaluated_4h: 4, win_rate_4h: 0.5, avg_return_4h: -0.01 },
      },
      recommendations: ['Keep BTC setups prioritized.'],
    }
    const guardPayload = {
      status: 'watch',
      balance_basis: 10000,
      daily_loss_limit_pct: 3,
      daily_loss_limit_usd: 300,
      paper_pnl_usd_today: -50,
      opened_trades_today: 2,
      max_daily_trades: 5,
      open_trades: 1,
      blockers: [],
      warnings: ['Daily loss is near threshold'],
    }
    const preGraphPayload = {
      ready_for_graph_rag: false,
      blockers: ['Need more feedback labels'],
      recommendations: ['Sync memory before build'],
      current: {
        evaluated_4h: 12,
        feedback_labels: 3,
        trade_memory_last_sync_at: '2026-06-05T08:00:00Z',
      },
    }
    const graphPayload = {
      status: 'PENDING',
      nodes: 18,
      edges: 42,
      last_build_at: '2026-06-05T07:30:00Z',
    }

    fetchMock
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(metricsPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(guardPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(preGraphPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(graphPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'SYNCED' }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'OK' }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(metricsPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...guardPayload, status: 'ok', warnings: [] }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ...preGraphPayload, ready_for_graph_rag: true, blockers: [] }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ status: 'OK', nodes: 25, edges: 60 }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(metricsPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(guardPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(preGraphPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(graphPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(metricsPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(guardPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(preGraphPayload) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(graphPayload) })

    const view = renderWithRoot(<BestAiControlView />)
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/best-setup/metrics', {
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/risk/daily-guard', {
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
    })
    expect(view.container.textContent).toContain('Best Setup Accuracy & Guard')
    expect(view.container.textContent).toContain('24')
    expect(view.container.textContent).toContain('58%')
    expect(view.container.textContent).toContain('1.230%')
    expect(view.container.textContent).toContain('watch')
    expect(view.container.textContent).toContain('Not Yet')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('Daily loss is near threshold')
    expect(view.container.textContent).toContain('Keep BTC setups prioritized.')
    expect(view.container.textContent).toContain('Need more feedback labels')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Sync RAG Memory'))?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(5, '/api/rag/trade-memory/sync?force=true', {
      method: 'POST',
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
    })
    expect(view.container.textContent).toContain('Trade memory synced to RAG')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Build Graph'))?.click()
    })
    await flush()
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(6, '/api/rag/graph/build', {
      method: 'POST',
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
    })
    expect(view.container.textContent).toContain('Trade graph built from outcomes, feedback, and paper trades')
    expect(view.container.textContent).toContain('Ready')
    expect(view.container.textContent).toContain('OK')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('button[title="Refresh"]')?.click()
    })
    await flush()

    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/best-setup/metrics')).toHaveLength(3)

    act(() => {
      vi.advanceTimersByTime(45_000)
    })
    await flush()

    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/best-setup/metrics')).toHaveLength(4)

    view.unmount()
  })

  it('renders light-theme error state and action failures', async () => {
    currentTheme = 'light'

    fetchMock
      .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) })
      .mockResolvedValueOnce({ ok: false, json: () => Promise.resolve({}) })

    const view = renderWithRoot(<BestAiControlView />)
    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).toContain('Unable to load Best AI controls')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Sync RAG Memory'))?.click()
    })
    await flush()
    expect(view.container.textContent).toContain('Unable to sync trade memory')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Build Graph'))?.click()
    })
    await flush()
    expect(view.container.textContent).toContain('Unable to build trade graph')

    view.unmount()
  })
})
