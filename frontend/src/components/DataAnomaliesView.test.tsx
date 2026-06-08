import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let fetchMock: ReturnType<typeof vi.fn>

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import { DataAnomaliesView } from './DataAnomaliesView'

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

describe('DataAnomaliesView', () => {
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

  it('loads anomaly data, supports hour-range changes, refresh, and auto-refresh polling', async () => {
    fetchMock
      .mockResolvedValueOnce({
        json: () =>
          Promise.resolve({
            summary: {
              total: 5,
              critical: 1,
              high: 2,
              price_spikes: 2,
              volume_spikes: 1,
              range_spikes: 1,
              missing_gaps: 3,
            },
            top_symbols: [
              { symbol: 'BTCUSDT', count: 5, max_score: 0.98 },
              { symbol: 'ETHUSDT', count: 2, max_score: 0.71 },
            ],
          }),
      })
      .mockResolvedValueOnce({
        json: () =>
          Promise.resolve({
            anomalies: [
              {
                symbol: 'BTCUSDT',
                timeframe: '15m',
                event_ts: '2026-06-05T08:00:00Z',
                anomaly_type: 'price_spike',
                severity: 'CRITICAL',
                score: 0.98,
                detected_at: '2026-06-05T08:01:00Z',
              },
              {
                symbol: 'ETHUSDT',
                timeframe: '1h',
                event_ts: '2026-06-05T09:00:00Z',
                anomaly_type: 'volume_spike',
                severity: 'HIGH',
                score: 0.71,
                detected_at: '2026-06-05T09:01:00Z',
              },
            ],
          }),
      })
      .mockResolvedValueOnce({
        json: () =>
          Promise.resolve({
            summary: {
              total: 1,
              critical: 0,
              high: 1,
              price_spikes: 0,
              volume_spikes: 1,
              range_spikes: 0,
              missing_gaps: 0,
            },
            top_symbols: [],
          }),
      })
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ anomalies: [] }),
      })
      .mockResolvedValue({
        json: () =>
          Promise.resolve({
            summary: {
              total: 5,
              critical: 1,
              high: 2,
              price_spikes: 2,
              volume_spikes: 1,
              range_spikes: 1,
              missing_gaps: 3,
            },
            top_symbols: [{ symbol: 'BTCUSDT', count: 5, max_score: 0.98 }],
          }),
      })

    const view = renderWithRoot(<DataAnomaliesView />)
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/anomalies/summary', {
      method: 'POST',
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours: 72 }),
    })
    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/anomalies/recent', {
      method: 'POST',
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours: 72, limit: 30 }),
    })

    expect(view.container.textContent).toContain('Data Anomalies')
    expect(view.container.textContent).toContain('BTCUSDT')
    expect(view.container.textContent).toContain('Price Spike')
    expect(view.container.textContent).toContain('CRITICAL')
    expect(view.container.textContent).toContain('0.98')
    expect(view.container.textContent).toContain('Missing Gaps')

    act(() => {
      Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('24h'))?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/anomalies/summary', {
      method: 'POST',
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours: 24 }),
    })
    expect(view.container.textContent).toContain('No anomaly events found for this window.')
    expect(view.container.textContent).toContain('No anomalies in this window.')

    act(() => {
      view.container.querySelector<HTMLButtonElement>('button[title="Refresh"]')?.click()
    })
    await flush()

    expect(fetchMock).toHaveBeenNthCalledWith(5, '/api/anomalies/summary', {
      method: 'POST',
      headers: { 'X-API-Key': 'secret-key', 'Content-Type': 'application/json' },
      body: JSON.stringify({ hours: 24 }),
    })

    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    await flush()

    expect(fetchMock.mock.calls.filter(([url]) => url === '/api/anomalies/summary').length).toBeGreaterThanOrEqual(4)

    view.unmount()
  })

  it('renders light-theme error state when the anomaly API returns an error payload', async () => {
    currentTheme = 'light'

    fetchMock
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ status: 'ERROR', error: 'summary unavailable' }),
      })
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ anomalies: [] }),
      })

    const view = renderWithRoot(<DataAnomaliesView />)
    await flush()

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')
    expect(view.container.textContent).toContain('summary unavailable')
    expect(view.container.textContent).toContain('0')

    view.unmount()
  })
})
