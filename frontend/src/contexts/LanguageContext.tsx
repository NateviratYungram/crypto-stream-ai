import { createContext, useContext, useState, type ReactNode } from 'react'
import { translations, type Lang, type TKey } from '../i18n/translations'

interface LanguageContextType {
  lang: Lang
  setLang: (l: Lang) => void
  t: (key: TKey) => string
}

const LanguageContext = createContext<LanguageContextType>({
  lang: 'th',
  setLang: () => {},
  t: (key) => key,
})

export const LanguageProvider = ({ children }: { children: ReactNode }) => {
  const [lang, setLangState] = useState<Lang>(() => {
    return (localStorage.getItem('cs_lang') as Lang) || 'th'
  })

  const setLang = (l: Lang) => {
    localStorage.setItem('cs_lang', l)
    setLangState(l)
  }

  const t = (key: TKey): string => {
    return (translations[lang] as Record<string, string>)[key]
      ?? (translations.en as Record<string, string>)[key]
      ?? key
  }

  return (
    <LanguageContext.Provider value={{ lang, setLang, t }}>
      {children}
    </LanguageContext.Provider>
  )
}

export const useLanguage = () => useContext(LanguageContext)
