import { act } from 'react'
import { createRoot } from 'react-dom/client'

import { LanguageProvider, useLanguage } from './LanguageContext'

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

function LanguageHarness() {
  const { lang, setLang, t } = useLanguage()

  return (
    <div>
      <span data-testid="lang">{lang}</span>
      <span data-testid="translated">{t('navbar.notifications')}</span>
      <span data-testid="missing">{t('missing.translation.key' as never)}</span>
      <button data-testid="switch" onClick={() => setLang('en')}>
        switch
      </button>
    </div>
  )
}

describe('LanguageContext', () => {
  beforeEach(() => {
    localStorage.clear()
    document.body.innerHTML = ''
  })

  it('defaults to thai when storage is empty and falls back to raw key for missing translation', () => {
    const view = renderWithRoot(
      <LanguageProvider>
        <LanguageHarness />
      </LanguageProvider>,
    )

    expect(view.container.querySelector('[data-testid="lang"]')?.textContent).toBe('th')
    expect(view.container.querySelector('[data-testid="translated"]')?.textContent).toBeTruthy()
    expect(view.container.querySelector('[data-testid="missing"]')?.textContent).toBe('missing.translation.key')

    view.unmount()
  })

  it('loads persisted language and writes updates back to storage', () => {
    localStorage.setItem('cs_lang', 'th')

    const view = renderWithRoot(
      <LanguageProvider>
        <LanguageHarness />
      </LanguageProvider>,
    )

    act(() => {
      view.container.querySelector<HTMLButtonElement>('[data-testid="switch"]')?.click()
    })

    expect(view.container.querySelector('[data-testid="lang"]')?.textContent).toBe('en')
    expect(localStorage.getItem('cs_lang')).toBe('en')
    expect(view.container.querySelector('[data-testid="translated"]')?.textContent).toBe('Notifications')

    view.unmount()
  })
})
