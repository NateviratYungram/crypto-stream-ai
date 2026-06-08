import { act } from 'react'
import { createRoot } from 'react-dom/client'

let currentTheme = 'dark'
let fetchMock: ReturnType<typeof vi.fn>

vi.mock('framer-motion', () => ({
  motion: {
    textarea: ({
      initial: _initial,
      animate: _animate,
      ...props
    }: React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
      initial?: unknown
      animate?: unknown
    }) => <textarea {...props} />,
  },
}))

vi.mock('../contexts/ModeContext', () => ({
  useMode: () => ({
    theme: currentTheme,
  }),
}))

import { PersonaSettings } from './PersonaSettings'

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

describe('PersonaSettings', () => {
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

  it('loads, reloads, applies presets, saves, and clears the saved state after the timer', async () => {
    fetchMock
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ persona: 'Loaded persona' }),
      })
      .mockResolvedValueOnce({
        json: () => Promise.resolve({ persona: 'Reloaded persona' }),
      })
      .mockResolvedValueOnce({
        ok: true,
      })

    const view = renderWithRoot(<PersonaSettings />)

    await act(async () => {
      await Promise.resolve()
    })

    expect(fetchMock).toHaveBeenNthCalledWith(1, '/api/persona', {
      headers: { 'X-API-Key': 'secret-key' },
    })

    const textarea = view.container.querySelector('textarea') as HTMLTextAreaElement | null
    expect(textarea?.value).toBe('Loaded persona')
    expect(view.container.textContent).toContain('14 chars')

    const presetButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Aggressive'),
    )
    act(() => {
      presetButton?.click()
    })

    const updatedTextarea = view.container.querySelector('textarea') as HTMLTextAreaElement | null
    expect(updatedTextarea?.value).toContain('Aggressive Scalper Persona')

    const reloadButton = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Reload'),
    )
    act(() => {
      reloadButton?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/persona', {
      headers: { 'X-API-Key': 'secret-key' },
    })
    expect((view.container.querySelector('textarea') as HTMLTextAreaElement | null)?.value).toBe('Reloaded persona')

    const saveButton = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Save'))
    act(() => {
      saveButton?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(fetchMock).toHaveBeenNthCalledWith(3, '/api/persona', {
      method: 'PUT',
      headers: {
        'X-API-Key': 'secret-key',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ persona: 'Reloaded persona' }),
    })
    expect(view.container.textContent).toContain('Saved!')

    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(view.container.textContent).toContain('Save')

    view.unmount()
  })

  it('handles load failure, light theme, preset selection, and save completion cleanup', async () => {
    fetchMock
      .mockRejectedValueOnce(new Error('load failed'))
      .mockResolvedValueOnce({
        ok: true,
      })

    currentTheme = 'light'
    const view = renderWithRoot(<PersonaSettings />)

    const loadingPanel = Array.from(view.container.querySelectorAll('div')).find((node) =>
      node.className.includes('animate-pulse'),
    )
    expect(loadingPanel?.className).toContain('bg-slate-100 border-slate-200')

    await act(async () => {
      await Promise.resolve()
    })

    const root = view.container.firstElementChild as HTMLDivElement | null
    expect(root?.className).toContain('bg-slate-50')

    const textarea = view.container.querySelector('textarea') as HTMLTextAreaElement | null
    expect(textarea).not.toBeNull()

    const cryptoPreset = Array.from(view.container.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Crypto'),
    )
    act(() => {
      cryptoPreset?.click()
    })

    expect((view.container.querySelector('textarea') as HTMLTextAreaElement | null)?.value).toContain('Crypto DeFi Persona')

    const saveButton = Array.from(view.container.querySelectorAll('button')).find((button) => button.textContent?.includes('Save'))
    act(() => {
      saveButton?.click()
    })

    await act(async () => {
      await Promise.resolve()
    })

    expect(fetchMock).toHaveBeenNthCalledWith(2, '/api/persona', expect.objectContaining({
      method: 'PUT',
      headers: {
        'X-API-Key': 'secret-key',
        'Content-Type': 'application/json',
      },
    }))
    expect(JSON.parse(fetchMock.mock.calls[1][1].body as string).persona).toContain('Crypto DeFi Persona')

    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(view.container.textContent).toContain('Save')

    view.unmount()
  })
})
