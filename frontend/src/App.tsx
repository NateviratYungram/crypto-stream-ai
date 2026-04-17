import { useState, useEffect, Suspense, lazy } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { ModeProvider, useMode } from './contexts/ModeContext'
import { useWebSocket } from './hooks/useWebSocket'
import { TabSkeleton } from './components/TabSkeleton'
import { ErrorBoundary } from './components/ErrorBoundary'
import { CommandPalette } from './components/CommandPalette'
import { AlertManager } from './components/AlertManager'
import { OnboardingTour } from './components/OnboardingTour'
import { ShortcutsHelp } from './components/ShortcutsHelp'
import { AuthModal, type UserProfile } from './components/AuthModal'
import { BellRing } from 'lucide-react'

// Layout Components
import { MainLayout } from './components/layout/MainLayout'
import { LandingHero } from './components/layout/LandingHero'

// Views (Lazy loaded)
const TrendsView       = lazy(() => import('./components/TrendsView').then(m => ({ default: m.TrendsView })))
const WhaleTrackerView = lazy(() => import('./components/WhaleTrackerView').then(m => ({ default: m.WhaleTrackerView })))
const RiskAuditsView   = lazy(() => import('./components/RiskAuditsView').then(m => ({ default: m.RiskAuditsView })))
const IntelligenceHub  = lazy(() => import('./components/IntelligenceHub').then(m => ({ default: m.IntelligenceHub })))
const PortfolioCenter  = lazy(() => import('./components/PortfolioCenter').then(m => ({ default: m.PortfolioCenter })))
const TacticsHub       = lazy(() => import('./components/TacticsHub').then(m => ({ default: m.TacticsHub })))
const NewsSentimentHub = lazy(() => import('./components/NewsSentimentHub').then(m => ({ default: m.NewsSentimentHub })))
const ChatWindow       = lazy(() => import('./components/ChatWindow').then(m => ({ default: m.ChatWindow })))
const AlertsReviewsView = lazy(() => import('./components/AlertsReviewsView').then(m => ({ default: m.AlertsReviewsView })))
// Phase 15 — New Views
const FundingRatesView = lazy(() => import('./components/FundingRatesView').then(m => ({ default: m.FundingRatesView })))
const WatchlistPanel   = lazy(() => import('./components/WatchlistPanel').then(m => ({ default: m.WatchlistPanel })))
const ScreenerView     = lazy(() => import('./components/ScreenerView').then(m => ({ default: m.ScreenerView })))
const TradingJournalView = lazy(() => import('./components/TradingJournalView').then(m => ({ default: m.TradingJournalView })))
const ETFFlowView      = lazy(() => import('./components/ETFFlowView').then(m => ({ default: m.ETFFlowView })))
const PersonaSettings  = lazy(() => import('./components/PersonaSettings').then(m => ({ default: m.PersonaSettings })))
const ProfileSettings  = lazy(() => import('./components/ProfileSettings').then(m => ({ default: m.ProfileSettings })))
const PaperTrading     = lazy(() => import('./components/PaperTradingDashboard').then(m => ({ default: m.PaperTradingDashboard })))
const EconomicCalendar = lazy(() => import('./components/EconomicCalendarView').then(m => ({ default: m.EconomicCalendarView })))
const MLStats          = lazy(() => import('./components/MLStatsPanel'))
const BacktesterView   = lazy(() => import('./components/BacktesterView').then(m => ({ default: m.BacktesterView })))

interface Toast { id: string; message: string }

function AppShell() {
  const [activeTab, setActiveTab] = useState('Market Trends')
  const [isAuthorized, setIsAuthorized] = useState(false)
  const [authModalOpen, setAuthModalOpen]   = useState(false)
  const [authModalTab,  setAuthModalTab]    = useState<'login' | 'register'>('login')
  const [_currentUser,  setCurrentUser]     = useState<UserProfile | null>(null)
  const [cmdOpen,       setCmdOpen]         = useState(false)
  const [shortcutsOpen, setShortcutsOpen]   = useState(false)
  const [toasts,        setToasts]          = useState<Toast[]>([])
  // G + key chord state
  const [gPressed, setGPressed] = useState(false)
  const [showTour, setShowTour] = useState(false)
  const [pendingSearchQuery, setPendingSearchQuery] = useState('')
  const [tickerPrices, setTickerPrices] = useState<Record<string, { price: number; delta: number }>>({
    'BTC':    { price: 0, delta: 0 },
    'ETH':    { price: 0, delta: 0 },
    'SOL':    { price: 0, delta: 0 },
    'GOLD':   { price: 0, delta: 0 },
    'NASDAQ': { price: 0, delta: 0 },
    'SP500':  { price: 0, delta: 0 },
    'NVDA':   { price: 0, delta: 0 },
    'TSLA':   { price: 0, delta: 0 },
  })
  const [currentPrices, setCurrentPrices] = useState<Record<string, number>>({})

  const { isRetail, setMode, mode } = useMode()
  const { status, lastMessage } = useWebSocket()

  // Auth check — JWT-based
  useEffect(() => {
    const token = localStorage.getItem('cs_jwt')
    const userStr = localStorage.getItem('cs_user')
    if (token && userStr) {
      try {
        const user: UserProfile = JSON.parse(userStr)
        setCurrentUser(user)
        setIsAuthorized(true)
        setMode(user.account_type === 'institutional' ? 'institutional' : 'retail')
      } catch { /* corrupted — ignore, will re-login */ }
    }
  }, [setMode])

  // Onboarding tour
  useEffect(() => {
    if (isAuthorized && isRetail) {
      const seen = localStorage.getItem('cs_tour_seen')
      if (!seen) setShowTour(true)
    }
  }, [isAuthorized, isRetail])

  // KB Shortcuts
  useEffect(() => {
    let gTimer: ReturnType<typeof setTimeout>
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable

      // Ctrl+K → Command Palette
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault(); setCmdOpen(o => !o); return
      }
      // Esc → close modals
      if (e.key === 'Escape') {
        setCmdOpen(false); setShortcutsOpen(false); return
      }
      if (inInput) return

      // ? → shortcuts help
      if (e.key === '?') { setShortcutsOpen(o => !o); return }

      // G + key chord → quick nav
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
  }, [gPressed])

  // Poll real stock prices (NVDA, TSLA, GOLD) every 60s
  useEffect(() => {
    if (!isAuthorized) return
    const fetchStocks = async () => {
      try {
        const res = await fetch('/api/market/stocks', { headers: { 'X-API-Key': 'institutional-secret-key' } })
        if (!res.ok) return
        const data = await res.json()
        setTickerPrices(prev => {
          const next = { ...prev }
          for (const [key, val] of Object.entries(data) as [string, { price: number; change_pct: number }][]) {
            if (val.price > 0) next[key] = { price: val.price, delta: val.change_pct }
          }
          return next
        })
      } catch { /* silent */ }
    }
    fetchStocks()
    const id = setInterval(fetchStocks, 60_000)
    return () => clearInterval(id)
  }, [isAuthorized])

  // WS Updates
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

  const addToast = (message: string) => {
    const id = Date.now().toString()
    setToasts(p => [...p, { id, message }])
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 5000)
  }

  const handleAuthSuccess = (_token: string, user: UserProfile) => {
    setCurrentUser(user)
    setMode(user.account_type === 'institutional' ? 'institutional' : 'retail')
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
    setMode('retail')
    setIsAuthorized(true)
  }

  const handleLandingSearch = (query: string) => {
    setPendingSearchQuery(query)
    handleDemoAccess()
    setActiveTab('Strategy Chat')
  }

  const handleLandingNavigate = (_key: 'chart' | 'markets' | 'news' | 'community' | 'more') => {
    handleDemoAccess()
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
      mode={mode}
      setMode={setMode}
      onOpenCommand={() => setCmdOpen(true)}
      tickerPrices={tickerPrices}
      onLogout={handleLogout}
    >
      {/* Dynamic View Injection */}
      <Suspense fallback={<TabSkeleton variant="cards" />}>
        {(() => {
          switch (activeTab) {
            case 'Market Trends':         return <ErrorBoundary tabName="Market Trends"><TrendsView /></ErrorBoundary>
            case 'Institutional Assets': return <ErrorBoundary tabName="Portfolio"><PortfolioCenter tickerPrices={tickerPrices} /></ErrorBoundary>
            case 'Sentiment Hub':        return <ErrorBoundary tabName="Sentiment Hub"><NewsSentimentHub /></ErrorBoundary>
            case 'Intelligence Hub':     return <ErrorBoundary tabName="Intelligence Hub"><IntelligenceHub /></ErrorBoundary>
            case 'Trading Tactics':      return <ErrorBoundary tabName="Trading Tactics"><TacticsHub /></ErrorBoundary>
            case 'Whale Tracker':        return <ErrorBoundary tabName="Whale Tracker"><WhaleTrackerView /></ErrorBoundary>
            case 'Risk Audits':          return <ErrorBoundary tabName="Risk Audits"><RiskAuditsView /></ErrorBoundary>
            case 'Alerts & Reviews':     return <ErrorBoundary tabName="Alerts & Reviews"><AlertsReviewsView /></ErrorBoundary>
            // Phase 15
            case 'Funding Rates':        return <ErrorBoundary tabName="Funding Rates"><FundingRatesView /></ErrorBoundary>
            case 'Watchlist':            return <ErrorBoundary tabName="Watchlist"><WatchlistPanel onAnalyze={sym => { setPendingSearchQuery(`วิเคราะห์ ${sym}`); setActiveTab('Strategy Chat') }} /></ErrorBoundary>
            case 'Screener':             return <ErrorBoundary tabName="Screener"><ScreenerView /></ErrorBoundary>
            case 'Trading Journal':      return <ErrorBoundary tabName="Trading Journal"><TradingJournalView /></ErrorBoundary>
            case 'ETF Flows':            return <ErrorBoundary tabName="ETF Flows"><ETFFlowView /></ErrorBoundary>
            case 'AI Persona':           return <ErrorBoundary tabName="AI Persona"><PersonaSettings /></ErrorBoundary>
            case 'Profile Settings':     return <ErrorBoundary tabName="Profile Settings"><ProfileSettings /></ErrorBoundary>
            case 'Paper Trading':        return <ErrorBoundary tabName="Paper Trading"><PaperTrading /></ErrorBoundary>
            case 'Backtester':           return <ErrorBoundary tabName="Backtester"><BacktesterView /></ErrorBoundary>
            case 'Economic Calendar':    return <ErrorBoundary tabName="Economic Calendar"><EconomicCalendar /></ErrorBoundary>
            case 'ML Model':             return <ErrorBoundary tabName="ML Model"><MLStats /></ErrorBoundary>
            case 'Strategy Chat':
            default:                     return (
              <ErrorBoundary tabName="Strategy Chat">
                <ChatWindow 
                  initialMessage={pendingSearchQuery} 
                  onClearInitialMessage={() => setPendingSearchQuery('')} 
                />
              </ErrorBoundary>
            )
          }
        })()}
      </Suspense>

      {/* Global Modals/Tools */}
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} onNavigate={setActiveTab} />
      <ShortcutsHelp open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
      <AuthModal open={authModalOpen} defaultTab={authModalTab} onClose={() => setAuthModalOpen(false)} onSuccess={handleAuthSuccess} />
      <AlertManager currentPrices={currentPrices} onToast={addToast} />
      {showTour && (
        <OnboardingTour
          onComplete={() => { setShowTour(false); localStorage.setItem('cs_tour_seen', '1') }}
          onTabChange={setActiveTab}
        />
      )}

      {/* Toast Overlay */}
      <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div key={t.id}
              initial={{ opacity: 0, x: 60, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 60, scale: 0.95 }}
              className="bg-slate-900/95 backdrop-blur-2xl border border-amber-500/20 rounded-2xl px-5 py-3 shadow-2xl flex items-center gap-3 max-w-xs"
            >
              <BellRing className="w-4 h-4 text-amber-400 shrink-0" />
              <p className="text-xs font-bold text-slate-200">{t.message}</p>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </MainLayout>
  )
}

export default function App() {
  return (
    <ModeProvider>
      <AppShell />
    </ModeProvider>
  )
}
