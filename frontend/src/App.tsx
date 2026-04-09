import { useState, useEffect } from 'react'
import { Sidebar } from './components/Sidebar'
import { ChatWindow } from './components/ChatWindow'
import { MarketFeed } from './components/MarketFeed'
import { TrendsView } from './components/TrendsView'
import { WhaleTrackerView } from './components/WhaleTrackerView'
import { RiskAuditsView } from './components/RiskAuditsView'
import { IntelligenceHub } from './components/IntelligenceHub'
import { CommandPalette } from './components/CommandPalette'
import { AlertManager } from './components/AlertManager'
import { OnboardingTour } from './components/OnboardingTour'
import { ModeProvider, useMode } from './contexts/ModeContext'
import { useWebSocket } from './hooks/useWebSocket'
import { motion, AnimatePresence } from 'framer-motion'
import { Lock, ShieldCheck, ChevronRight, Sparkles, BellRing, Command } from 'lucide-react'

// Toast system
interface Toast { id: string; message: string }

function AppShell() {
  const [activeTab, setActiveTab] = useState('Market Trends')
  const [isAuthorized, setIsAuthorized] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [authError, setAuthError] = useState('')
  const [cmdOpen, setCmdOpen] = useState(false)
  const [toasts, setToasts] = useState<Toast[]>([])
  const [showTour, setShowTour] = useState(false)
  const [tickerPrices, setTickerPrices] = useState<Record<string, { price: number; delta: number }>>({
    'BTCUSDT': { price: 71850.22, delta: 0.45 },
    'ETHUSDT': { price: 3452.12, delta: -0.12 },
    'SOLUSDT': { price: 142.34, delta: 1.25 },
    'BNBUSDT': { price: 612.45, delta: 0.05 },
  })
  const [currentPrices, setCurrentPrices] = useState<Record<string,number>>({})

  const { isRetail, setMode, mode } = useMode()
  const { status, lastMessage } = useWebSocket()

  // Auth check
  useEffect(() => {
    const saved = localStorage.getItem('crypto_terminal_key')
    if (saved === 'institutional-secret-key' || saved === 'demo') {
      setIsAuthorized(true)
      if (saved === 'demo') setMode('retail')
    }
  }, []) // eslint-disable-line

  // Onboarding tour — retail mode, first login
  useEffect(() => {
    if (isAuthorized && isRetail) {
      const seen = localStorage.getItem('cs_tour_seen')
      if (!seen) setShowTour(true)
    }
  }, [isAuthorized, isRetail])

  // Command palette shortcut
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setCmdOpen(o => !o)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Live ticker from WS
  useEffect(() => {
    if (lastMessage?.type === 'TICK') {
      const { symbol, price } = lastMessage.data
      if (!symbol || !price) return
      const newPrice = parseFloat(price)
      setCurrentPrices(prev => ({ ...prev, [symbol]: newPrice }))
      setTickerPrices(prev => {
        const prev_p = prev[symbol]?.price || newPrice
        const delta = ((newPrice - prev_p) / prev_p) * 100
        return { ...prev, [symbol]: { price: newPrice, delta } }
      })
    }
  }, [lastMessage])

  const addToast = (message: string) => {
    const id = Date.now().toString()
    setToasts(p => [...p, { id, message }])
    setTimeout(() => setToasts(p => p.filter(t => t.id !== id)), 5000)
  }

  const handleAuth = (e: React.FormEvent, key: string) => {
    e.preventDefault()
    const k = key || apiKey
    if (k === 'institutional-secret-key') {
      localStorage.setItem('crypto_terminal_key', k)
      setMode('institutional')
      setIsAuthorized(true)
    } else if (k === 'demo') {
      localStorage.setItem('crypto_terminal_key', k)
      setMode('retail')
      setIsAuthorized(true)
    } else {
      setAuthError('INVALID ACCESS CREDENTIALS')
      setTimeout(() => setAuthError(''), 3000)
    }
  }

  // Top 3 ticker symbols
  const TICKER_SYMBOLS = ['BTCUSDT','ETHUSDT','SOLUSDT']

  if (!isAuthorized) {
    return (
      <div className="h-screen w-screen bg-slate-950 flex items-center justify-center relative overflow-hidden">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/10 blur-[120px] rounded-full" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-indigo-600/10 blur-[120px] rounded-full" />

        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="w-full max-w-md p-10 bg-slate-900/40 backdrop-blur-3xl border border-white/5 rounded-[2.5rem] shadow-2xl relative z-10 space-y-8"
        >
          <div className="flex flex-col items-center text-center space-y-4">
            <div className="w-16 h-16 bg-blue-600/10 rounded-2xl flex items-center justify-center border border-blue-500/20 shadow-xl shadow-blue-500/5">
              <Lock className="w-8 h-8 text-blue-400" />
            </div>
            <div className="space-y-1">
              <h1 className="text-2xl font-black text-white tracking-tighter uppercase">CryptoStream</h1>
              <p className="text-[10px] text-slate-500 font-bold uppercase tracking-[0.2em]">Intelligence Terminal</p>
            </div>
          </div>

          <form onSubmit={e => handleAuth(e, apiKey)} className="space-y-4">
            <div className="space-y-2">
              <label className="text-[9px] font-black text-slate-500 uppercase tracking-widest px-1">Access Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="Institutional key..."
                className="w-full bg-slate-950/50 border border-white/10 rounded-2xl px-6 py-4 text-sm text-white placeholder:text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500/30 transition-all font-mono"
              />
            </div>

            <AnimatePresence>
              {authError && (
                <motion.p initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className="text-[10px] text-rose-500 font-bold text-center uppercase tracking-widest">
                  {authError}
                </motion.p>
              )}
            </AnimatePresence>

            <button type="submit"
              className="w-full h-14 bg-blue-600 hover:bg-blue-500 text-white rounded-2xl flex items-center justify-center gap-3 font-black text-xs uppercase tracking-widest transition-all shadow-xl shadow-blue-600/20 active:scale-95">
              <Lock className="w-4 h-4" /> Institutional Access
              <ChevronRight className="w-4 h-4" />
            </button>
          </form>

          {/* Divider */}
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-white/5" />
            <span className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">or</span>
            <div className="flex-1 h-px bg-white/5" />
          </div>

          {/* Demo / Retail access */}
          <button
            onClick={e => handleAuth(e as any, 'demo')}
            className="w-full h-12 border border-blue-500/20 hover:border-blue-500/40 bg-blue-600/5 hover:bg-blue-600/10 text-blue-400 rounded-2xl flex items-center justify-center gap-2 font-black text-xs uppercase tracking-widest transition-all active:scale-95"
          >
            <Sparkles className="w-4 h-4" />
            🌐 ทดลองใช้ฟรี (Demo Mode)
          </button>

          <div className="flex items-center justify-center gap-2 opacity-40">
            <ShieldCheck className="w-3 h-3 text-emerald-500" />
            <span className="text-[8px] font-black text-slate-500 uppercase tracking-[0.2em]">End-to-End Encrypted Tunnel</span>
          </div>
        </motion.div>
      </div>
    )
  }

  return (
    <div className="flex h-screen w-screen bg-slate-950 text-slate-200 overflow-hidden font-inter select-none">
      {/* Background */}
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/10 blur-[120px] rounded-full" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-indigo-600/10 blur-[120px] rounded-full" />
      </div>

      {/* Command Palette */}
      <CommandPalette open={cmdOpen} onClose={() => setCmdOpen(false)} onNavigate={setActiveTab} />

      {/* Onboarding Tour */}
      {showTour && (
        <OnboardingTour
          onComplete={() => { setShowTour(false); localStorage.setItem('cs_tour_seen', '1') }}
          onTabChange={setActiveTab}
        />
      )}

      {/* Toast system */}
      <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
        <AnimatePresence>
          {toasts.map(t => (
            <motion.div key={t.id}
              initial={{ opacity: 0, x: 60, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 60, scale: 0.95 }}
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              className="bg-slate-900/95 backdrop-blur-2xl border border-amber-500/20 rounded-2xl px-5 py-3 shadow-2xl flex items-center gap-3 max-w-xs"
            >
              <BellRing className="w-4 h-4 text-amber-400 shrink-0" />
              <p className="text-xs font-bold text-slate-200">{t.message}</p>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <Sidebar wsStatus={status} activeTab={activeTab} setActiveTab={setActiveTab} />

      <main className="flex-1 flex flex-col min-w-0 relative z-10">
        {/* Live Global Ticker */}
        <div className="h-10 bg-slate-900 border-b border-white/5 flex items-center overflow-hidden relative z-50">
          <div className="absolute left-0 top-0 bottom-0 w-24 bg-gradient-to-r from-slate-950 to-transparent z-20 pointer-events-none" />
          
          {/* Scrolling ticker */}
          <div className="flex-1 relative overflow-hidden h-full flex items-center">
            <motion.div
              animate={{ x: [0, -2000] }}
              transition={{ duration: 60, repeat: Infinity, ease: 'linear' }}
              className="flex items-center gap-20 whitespace-nowrap px-12"
            >
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="flex items-center gap-20">
                  {TICKER_SYMBOLS.map(sym => {
                    const tick = tickerPrices[sym]
                    const up = (tick?.delta ?? 0) >= 0
                    return (
                      <div key={sym} className="flex items-center gap-2.5">
                        <span className="text-[10px] font-black text-slate-500 font-mono tracking-wider">{sym.replace('USDT', '')}</span>
                        <span className="text-[10px] font-black text-slate-100 font-mono tabular-nums tracking-tight">
                          {tick ? `$${tick.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '---'}
                        </span>
                        {tick && (
                          <span className={`text-[9px] font-black px-1.5 py-0.5 rounded bg-white/5 ${up ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {up ? '▲' : '▼'} {Math.abs(tick.delta).toFixed(3)}%
                          </span>
                        )}
                      </div>
                    )
                  })}
                  <div className="flex items-center gap-2 px-3 py-1 bg-blue-500/5 rounded-full border border-blue-500/10">
                    <div className="w-1 h-1 bg-blue-500 rounded-full animate-ping" />
                    <span className="text-[9px] font-black text-blue-400/80 uppercase tracking-[0.2em] font-mono">
                      {isRetail ? 'DATA REAL-TIME · BINANCE' : 'QUANT FEED · STREAM ACTIVE'}
                    </span>
                  </div>
                </div>
              ))}
            </motion.div>
          </div>

          {/* RIGHT GLASS CONTROL PANEL - Resolved Overlap */}
          <div className="relative h-full flex items-center pl-16 pr-4 bg-slate-950 z-40 border-l border-white/5 shadow-[-20px_0_30px_rgba(2,6,23,0.9)]">
            {/* Smooth transition from scrolling text */}
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-slate-950/80 to-slate-950 -z-10 w-[150%] -left-[50%]" />
            
            <div className="flex items-center gap-2.5 relative">
              <AlertManager currentPrices={currentPrices} onToast={addToast} />
              {!isRetail && (
                <button onClick={() => setCmdOpen(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/10 hover:border-blue-500/30 bg-white/5 hover:bg-blue-600/10 transition-all group"
                >
                  <Command className="w-3 h-3 text-slate-400 group-hover:text-blue-400 transition-colors" />
                  <span className="text-[9px] font-black text-slate-500 group-hover:text-slate-300 uppercase tracking-widest">K</span>
                </button>
              )}
              <button
                onClick={() => setMode(mode === 'institutional' ? 'retail' : 'institutional')}
                className={`flex items-center gap-2 px-4 py-1.5 rounded-xl text-[9px] font-black uppercase tracking-widest border transition-all shadow-lg overflow-hidden relative group ${
                  isRetail
                    ? 'bg-blue-600/20 border-blue-500/30 text-blue-400'
                    : 'bg-emerald-600/10 border-emerald-500/20 text-emerald-500'
                }`}
              >
                <div className={`w-1.5 h-1.5 rounded-full ${isRetail ? 'bg-blue-400' : 'bg-emerald-400'} animate-pulse`} />
                {isRetail ? '🌐 Retail' : '🏦 Pro'}
              </button>
            </div>
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 overflow-hidden flex flex-col">
          {(() => {
            switch (activeTab) {
              case 'Market Trends': return <TrendsView />
              case 'Intelligence Hub': return <IntelligenceHub />
              case 'Whale Tracker': return <WhaleTrackerView />
              case 'Risk Audits': return <RiskAuditsView />
              case 'Strategy Chat':
              default: return <ChatWindow />
            }
          })()}
        </div>
      </main>

      <div className="shrink-0 z-20">
        <MarketFeed />
      </div>
    </div>
  )
}

function App() {
  return (
    <ModeProvider>
      <AppShell />
    </ModeProvider>
  )
}

export default App
