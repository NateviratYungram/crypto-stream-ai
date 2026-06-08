import { useState, useEffect, useCallback, Suspense, lazy } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ModeProvider, useMode } from './contexts/ModeContext'
import { LanguageProvider, useLanguage } from './contexts/LanguageContext'
import { useWebSocket } from './hooks/useWebSocket'
import { TabSkeleton } from './components/TabSkeleton'
import { ErrorBoundary } from './components/ErrorBoundary'
import { CommandPalette } from './components/CommandPalette'

import { OnboardingTour } from './components/OnboardingTour'
import { ShortcutsHelp } from './components/ShortcutsHelp'
import { AuthModal, type UserProfile } from './components/AuthModal'
import { BellRing } from 'lucide-react'

// Layout Components
import { MainLayout } from './components/layout/MainLayout'
import { LandingHero } from './components/layout/LandingHero'

// Views (Lazy loaded)
const AlphaTerminal      = lazy(() => import('./components/AlphaTerminal').then(m => ({ default: m.AlphaTerminal })))
const MarketIntelligence = lazy(() => import('./components/MarketIntelligence').then(m => ({ default: m.MarketIntelligence })))
const MoneyFlow          = lazy(() => import('./components/MoneyFlow').then(m => ({ default: m.MoneyFlow })))
const RiskAlerts         = lazy(() => import('./components/RiskAlerts').then(m => ({ default: m.RiskAlerts })))
const StrategyLab        = lazy(() => import('./components/StrategyLab').then(m => ({ default: m.StrategyLab })))
const ChatWindow         = lazy(() => import('./components/ChatWindow').then(m => ({ default: m.ChatWindow })))
const UnifiedSettings   = lazy(() => import('./components/UnifiedSettingsView').then(m => ({ default: m.UnifiedSettingsView })))
const RagOpsDashboard   = lazy(() => import('./components/RagOpsDashboard').then(m => ({ default: m.RagOpsDashboard })))

interface Toast { id: string; message: string }
const TICKER_CACHE_KEY = 'crypto_ticker_prices_v1'

const TAB_SLUGS: Record<string, string> = {
  'Market Intelligence': 'market-intel',
  'Money Flow':          'money-flow',
  'Alpha Terminal':      'alpha-terminal',
  'Risk & Alerts':       'risk-alerts',
  'Strategy Lab':        'strategy-lab',
  'RAG Ops':             'rag-ops',
  'Strategy Chat':       'chat',
  'Settings':            'settings',
}
const SLUG_TO_TAB = Object.fromEntries(Object.entries(TAB_SLUGS).map(([k, v]) => [v, k]))

function tabFromHash(): string {
  const slug = window.location.hash.slice(1)
  return SLUG_TO_TAB[slug] ?? 'Alpha Terminal'
}

function AppShell() {
  const { lang } = useLanguage()
  const [activeTab, setActiveTabState] = useState<string>(tabFromHash)
  const [visitedTabs, setVisitedTabs] = useState<string[]>([tabFromHash()])

  const setActiveTab = useCallback((tab: string) => {
    setActiveTabState(tab)
    const slug = TAB_SLUGS[tab]
    if (slug) window.location.hash = slug
  }, [])

  useEffect(() => {
    const onHashChange = () => setActiveTabState(tabFromHash())
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  useEffect(() => {
    if (!visitedTabs.includes(activeTab)) {
      setVisitedTabs(prev => [...prev, activeTab])
    }
  }, [activeTab, visitedTabs])

  const [isAuthorized, setIsAuthorized] = useState(false)
  const [authModalOpen, setAuthModalOpen]   = useState(false)
  const [authModalTab,  setAuthModalTab]    = useState<'login' | 'register'>('login')
  const [_currentUser,  setCurrentUser]     = useState<UserProfile | null>(null)
  const [cmdOpen,       setCmdOpen]         = useState(false)
  const [shortcutsOpen, setShortcutsOpen]   = useState(false)
  const [toasts,        setToasts]          = useState<Toast[]>([])
  const [gPressed, setGPressed] = useState(false)
  const [showTour, setShowTour] = useState(false)
  const [pendingSearchQuery, setPendingSearchQuery] = useState('')
  const [tickerPrices, setTickerPrices] = useState<Record<string, { price: number; delta: number }>>(() => {
    const fallback = {
      'BTC':    { price: 0, delta: 0 },
      'ETH':    { price: 0, delta: 0 },
      'SOL':    { price: 0, delta: 0 },
      'AAPL':   { price: 0, delta: 0 },
      'MSFT':   { price: 0, delta: 0 },
      'NVDA':   { price: 0, delta: 0 },
      'TSLA':   { price: 0, delta: 0 },
      'AMD':    { price: 0, delta: 0 },
      'GOLD':   { price: 0, delta: 0 },
      'OIL':    { price: 0, delta: 0 },
      'NASDAQ': { price: 0, delta: 0 },
      'SP500':  { price: 0, delta: 0 },
    }
    try {
      const raw = localStorage.getItem(TICKER_CACHE_KEY)
      if (!raw) return fallback
      const parsed = JSON.parse(raw) as Record<string, { price?: unknown; delta?: unknown }>
      const restored = { ...fallback }
      for (const [key, value] of Object.entries(parsed)) {
        const price = typeof value?.price === 'number' ? value.price : Number(value?.price)
        const delta = typeof value?.delta === 'number' ? value.delta : Number(value?.delta)
        if (Number.isFinite(price) && Number.isFinite(delta) && key in restored) {
          restored[key as keyof typeof restored] = { price, delta }
        }
      }
      return restored
    } catch {
      return fallback
    }
  })
  const [_currentPrices, setCurrentPrices] = useState<Record<string, number>>({})

  const { theme } = useMode()
  const { status, lastMessage } = useWebSocket()

  useEffect(() => {
    const token   = localStorage.getItem('cs_jwt')
    const userStr = localStorage.getItem('cs_user')
    if (userStr) {
      try {
        const user: UserProfile = JSON.parse(userStr)
        if (token || user.id === 'demo') {
          setCurrentUser(user)
          setIsAuthorized(true)
          localStorage.setItem('crypto_terminal_key', 'demo')
        }
      } catch { }
    }
  }, [])

  useEffect(() => {
    if (isAuthorized) {
      const seen = localStorage.getItem('cs_tour_seen')
      if (!seen) setShowTour(true)
    }
  }, [isAuthorized])

  useEffect(() => {
    let gTimer: ReturnType<typeof setTimeout>
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); setCmdOpen(o => !o); return }
      if (e.key === 'Escape') { setCmdOpen(false); setShortcutsOpen(false); return }
      if (inInput) return
      if (e.key === '?') { setShortcutsOpen(o => !o); return }
      if (e.key === 'g' || e.key === 'G') {
        setGPressed(true)
        gTimer = setTimeout(() => setGPressed(false), 1500)
        return
      }
      if (gPressed) {
        clearTimeout(gTimer)
        setGPressed(false)
        const map: Record<string, string> = {
          t: 'Market Trends', c: 'Strategy Chat', w: 'Whale Tracker',
          s: 'Screener',      j: 'Trading Journal', f: 'Funding Rates',
          e: 'ETF Flows',     l: 'Watchlist',        p: 'AI Persona',
        }
        const dest = map[e.key.toLowerCase()]
        if (dest) { e.preventDefault(); setActiveTab(dest) }
      }
    }
    window.addEventListener('keydown', handler)
    return () => { window.removeEventListener('keydown', handler); clearTimeout(gTimer) }
  }, [gPressed, setActiveTab])

  useEffect(() => {
    if (!isAuthorized) return
    const fetchStocks = async () => {
      try {
        const res = await fetch('/api/market/stocks', { headers: { 'X-API-Key': localStorage.getItem('crypto_terminal_key') || '' } })
        if (!res.ok) return
        const data = await res.json()
        setTickerPrices(prev => {
          const next = { ...prev }
          for (const [key, val] of Object.entries(data) as [string, { price: number; change_pct: number }][]) {
            if (val.price > 0) next[key] = { price: val.price, delta: val.change_pct }
          }
          return next
        })
      } catch { }
    }
    fetchStocks()
    const id = setInterval(fetchStocks, 60_000)
    return () => clearInterval(id)
  }, [isAuthorized])

  useEffect(() => {
    if (lastMessage?.type === 'TICK') {
      const { symbol, price } = lastMessage.data
      if (!symbol || !price) return
      const normalizedSym = symbol.replace('USDT', '')
      const newPrice = parseFloat(price)
      setCurrentPrices(prev => ({ ...prev, [normalizedSym]: newPrice }))
      setTickerPrices(prev => {
        const prev_p = prev[normalizedSym]?.price || newPrice
        const delta = ((newPrice - prev_p) / prev_p) * 100
        return { ...prev, [normalizedSym]: { price: newPrice, delta } }
      })
    }
  }, [lastMessage])

  useEffect(() => {
    try {
      localStorage.setItem(TICKER_CACHE_KEY, JSON.stringify(tickerPrices))
    } catch { }
  }, [tickerPrices])

  const handleAuthSuccess = (_token: string, user: UserProfile) => {
    setCurrentUser(user)
    setIsAuthorized(true)
    setAuthModalOpen(false)
  }

  const handleLogout = () => {
    localStorage.removeItem('cs_jwt')
    localStorage.removeItem('cs_user')
    setCurrentUser(null)
    setIsAuthorized(false)
  }

  const openLogin = () => { setAuthModalTab('login');    setAuthModalOpen(true) }
  const openRegister = () => { setAuthModalTab('register'); setAuthModalOpen(true) }

  const handleDemoAccess = () => {
    const demoUser: UserProfile = {
      id: 'demo', email: 'demo@cryptostream.ai', username: 'demo_trader',
      full_name: 'Demo Trader', account_type: 'retail', phone: '', country: '', bio: ''
    }
    localStorage.setItem('cs_user', JSON.stringify(demoUser))
    setCurrentUser(demoUser)
    setIsAuthorized(true)
  }

  const handleLandingSearch = (query: string) => {
    setPendingSearchQuery(query)
    handleDemoAccess()
    setActiveTab('Strategy Chat')
  }

  const handleLandingNavigate = () => { handleDemoAccess() }

  const handleWatchlistAnalyze = (symbol: string) => {
    setPendingSearchQuery(`Analyze ${symbol} for me. Provide institutional insights, technical levels, and potential tactical setups.`);
    setActiveTab('Strategy Chat');
  };

  const renderTabView = (tab: string) => {
    switch (tab) {
      case 'Market Intelligence': return <MarketIntelligence wsStatus={status} wsLastMessage={lastMessage} />
      case 'Money Flow':          return <MoneyFlow tickerPrices={tickerPrices} />
      case 'Alpha Terminal':      return <AlphaTerminal onAnalyze={handleWatchlistAnalyze} />
      case 'Risk & Alerts':       return <RiskAlerts />
      case 'Strategy Lab':        return <StrategyLab />
      case 'RAG Ops':             return <RagOpsDashboard />
      case 'Settings':            return <UnifiedSettings />
      case 'Strategy Chat':
      default:                    return (
        <ChatWindow 
          initialMessage={pendingSearchQuery} 
          onClearInitialMessage={() => setPendingSearchQuery('')} 
        />
      )
    }
  }

  if (!isAuthorized) {
    return (
      <>
        <LandingHero
          onStartTrading={openRegister}
          onTryDemo={handleDemoAccess}
          onSearch={handleLandingSearch}
          onNavigate={handleLandingNavigate}
          onLoginClick={openLogin}
        />
        <AuthModal
          open={authModalOpen}
          defaultTab={authModalTab}
          onClose={() => setAuthModalOpen(false)}
          onSuccess={handleAuthSuccess}
        />
      </>
    )
  }

  return (
    <MainLayout
      activeTab={activeTab}
      setActiveTab={setActiveTab}
      wsStatus={status}
      onOpenCommand={() => setCmdOpen(true)}
      tickerPrices={tickerPrices}
      onLogout={handleLogout}
    >
      <Suspense fallback={<TabSkeleton variant="cards" />}>
        <div className="relative w-full h-full">
          {Object.keys(TAB_SLUGS).map(tabName => {
            const isVisited = visitedTabs.includes(tabName)
            if (!isVisited) return null
            return (
              <div 
                key={tabName} 
                className={`w-full transition-opacity duration-500 ${
                  activeTab === tabName 
                    ? 'opacity-100 z-10 pointer-events-auto relative flex flex-col h-full' 
                    : 'opacity-0 -z-10 pointer-events-none overflow-hidden absolute inset-0'
                }`}
              >
                <ErrorBoundary tabName={tabName}>
                  {renderTabView(tabName)}
                </ErrorBoundary>
              </div>
            )
          })}
        </div>
      </Suspense>

      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} onNavigate={setActiveTab} />
      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <AuthModal open={authModalOpen} defaultTab={authModalTab} onClose={() => setAuthModalOpen(false)} onSuccess={handleAuthSuccess} />
      {showTour && (
        <OnboardingTour
          onComplete={() => { setShowTour(false); localStorage.setItem('cs_tour_seen', '1') }}
          onTabChange={setActiveTab}
        />
      )}

      <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div key={t.id}
              initial={{ opacity: 0, x: 60, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 60, scale: 0.95 }}
              className={`backdrop-blur-2xl border rounded-2xl px-5 py-3 shadow-2xl flex items-center gap-3 max-w-xs transition-all duration-500 ${
                theme === 'dark' ? 'bg-slate-900/95 border-amber-500/20' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
              }`}
            >
              <BellRing className={`w-4 h-4 shrink-0 ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`} />
              <p className={`text-xs font-bold ${theme === 'dark' ? 'text-slate-200' : 'text-slate-900'}`}>{t.message}</p>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </MainLayout>
  )
}

export default function App() {
  return (
    <LanguageProvider>
      <ModeProvider>
        <AppShell />
      </ModeProvider>
    </LanguageProvider>
  )
}
