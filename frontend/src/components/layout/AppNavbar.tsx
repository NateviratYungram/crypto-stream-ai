import React from 'react'
import { Menu, Moon, Sun, User } from 'lucide-react'
import { useLanguage } from '../../contexts/LanguageContext'
import { useMode } from '../../contexts/ModeContext'
import { MarketStatusClock } from './MarketStatusClock'

interface AppNavbarProps {
  onOpenCommand: () => void
  isAuthorized: boolean
  onLogout: () => void
  onMobileMenuClick?: () => void
  onNavigate?: (tab: string) => void
}

export const AppNavbar: React.FC<AppNavbarProps> = ({
  onOpenCommand: _onOpenCommand,
  isAuthorized: _isAuthorized,
  onLogout,
  onMobileMenuClick,
  onNavigate: _onNavigate,
}) => {
  const { lang, setLang, t } = useLanguage()
  const { theme, toggleTheme } = useMode()

  return (
    <header
      className={`h-16 border-b backdrop-blur-3xl flex items-center justify-between px-4 md:px-6 shrink-0 z-50 transition-all duration-500 relative overflow-hidden ${
        theme === 'dark' ? 'border-white/5 bg-[#0a0f1d]/80 shadow-2xl' : 'border-slate-200 bg-white shadow-sm'
      }`}
    >
      <div
        className={`absolute top-0 left-0 w-full h-[1px] opacity-50 ${
          theme === 'dark'
            ? 'bg-gradient-to-r from-transparent via-blue-500/50 to-transparent'
            : 'bg-gradient-to-r from-transparent via-blue-600/30 to-transparent'
        }`}
      />

      <div className="flex items-center gap-3 relative z-10">
        <button
          onClick={onMobileMenuClick}
          className={`lg:hidden p-2.5 rounded-2xl transition-all active:scale-90 ${
            theme === 'dark' ? 'hover:bg-white/5 text-slate-400 hover:text-white' : 'hover:bg-slate-100 text-slate-500 hover:text-slate-900'
          }`}
          aria-label="Open menu"
        >
          <Menu className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-4 cursor-pointer group" onClick={onLogout}>
          <div className="relative">
            <div className="absolute inset-0 bg-blue-600 blur-lg opacity-20 group-hover:opacity-40 transition-opacity" />
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center shadow-lg shadow-blue-500/20 relative z-10 group-hover:scale-105 transition-transform">
              <span className="text-white font-black text-base italic tracking-tighter">C</span>
            </div>
          </div>
          <div className="hidden md:block text-left">
            <h2
              className={`text-base font-black tracking-tighter uppercase transition-colors duration-500 leading-none ${
                theme === 'dark' ? 'text-white' : 'text-slate-900'
              }`}
            >
              CryptoStream
            </h2>
            <p
              className={`text-[9px] font-black uppercase tracking-[0.3em] mt-0.5 transition-colors duration-500 opacity-60 ${
                theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
              }`}
            >
              {t('navbar.tagline')}
            </p>
          </div>
        </div>
      </div>

      <div className="flex-1 flex justify-center px-4 relative z-10">
        <MarketStatusClock />
      </div>

      <div className="flex items-center gap-3 relative z-10">
        <button
          onClick={toggleTheme}
          className={`p-2.5 rounded-2xl border transition-all active:scale-90 shadow-sm group ${
            theme === 'dark'
              ? 'bg-white/5 border-white/10 text-slate-500 hover:text-white hover:border-blue-500/30'
              : 'bg-white border-slate-200 text-slate-500 hover:text-slate-900 hover:border-blue-500/50 hover:shadow-md'
          }`}
          title={theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode'}
        >
          {theme === 'dark' ? (
            <Sun className="w-4 h-4 group-hover:rotate-45 transition-transform" />
          ) : (
            <Moon className="w-4 h-4 group-hover:-rotate-12 transition-transform" />
          )}
        </button>

        <div className={`w-px h-6 opacity-30 ${theme === 'dark' ? 'bg-white/20' : 'bg-slate-400'}`} />

        <button
          onClick={() => setLang(lang === 'en' ? 'th' : 'en')}
          className={`px-3 py-2 rounded-2xl border transition-all active:scale-95 text-[10px] font-black uppercase tracking-widest shadow-sm ${
            theme === 'dark'
              ? 'bg-white/5 border-white/10 text-slate-400 hover:text-white hover:border-blue-500/30'
              : 'bg-white border-slate-200 text-slate-500 hover:text-slate-900 hover:border-blue-500/50 hover:shadow-md'
          }`}
          title={lang === 'en' ? 'Switch to Thai' : 'Switch to English'}
        >
          {lang === 'en' ? 'TH' : 'EN'}
        </button>

        <div className={`w-px h-6 opacity-30 ${theme === 'dark' ? 'bg-white/20' : 'bg-slate-400'}`} />

        <button
          onClick={onLogout}
          className={`flex items-center gap-2.5 p-1 pr-4 rounded-2xl border transition-all active:scale-95 shadow-xl group ${
            theme === 'dark'
              ? 'bg-white/10 hover:bg-white/20 text-slate-200 hover:text-white border-white/20'
              : 'bg-white hover:bg-slate-50 text-slate-700 hover:text-slate-900 border-slate-200 hover:shadow-2xl'
          }`}
        >
          <div
            className={`w-9 h-9 rounded-xl border flex items-center justify-center overflow-hidden transition-all duration-500 group-hover:scale-105 ${
              theme === 'dark' ? 'bg-slate-900 border-white/10 shadow-inner' : 'bg-slate-100 border-slate-200'
            }`}
          >
            <User className="w-5 h-5" />
          </div>
          <span className="text-[10px] font-black uppercase tracking-[0.2em] hidden md:block">{t('navbar.signout')}</span>
        </button>
      </div>
    </header>
  )
}
