import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { useMode } from '../contexts/ModeContext'
import {
  Bell, BellOff, Trash2, RefreshCw, TrendingUp, TrendingDown,
  AlertTriangle, CheckCircle, Clock, Award, BarChart2, Zap, Brain,
  TrendingUp as BuyIcon, TrendingDown as SellIcon
} from 'lucide-react'

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || ''
const HEADERS = () => ({ 'X-API-Key': API_KEY() })

interface Alert {
  id: number
  user_id?: string
  symbol: string
  condition: string
  message: string
  status: 'ACTIVE' | 'FIRED' | 'DISMISSED'
  created_at: string
}

interface TradeReview {
  id: number
  review_text: string
  win_rate: number
  score: number
  created_at: string
}

function ScoreRing({ score, theme }: { score: number; theme: 'light' | 'dark' }) {
  const radius = 28
  const circumference = 2 * Math.PI * radius
  const progress = circumference - (score / 100) * circumference
  const color = score >= 70 ? '#22c55e' : score >= 45 ? '#f59e0b' : '#ef4444'
  return (
    <div className="relative w-16 h-16 flex items-center justify-center">
      <svg className="absolute inset-0 w-full h-full -rotate-90" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r={radius} fill="none" stroke={theme === 'dark' ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.05)"} strokeWidth="5" />
        <circle
          cx="32" cy="32" r={radius} fill="none"
          stroke={color} strokeWidth="5"
          strokeDasharray={circumference}
          strokeDashoffset={progress}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 1s ease' }}
        />
      </svg>
      <span className="text-sm font-black" style={{ color }}>{score}</span>
    </div>
  )
}

function StatusBadge({ status, theme }: { status: Alert['status']; theme: 'light' | 'dark' }) {
  const cfg = {
    ACTIVE:    { icon: Bell,    label: 'Active',    cls: theme === 'dark' ? 'bg-blue-500/15 text-blue-400 border-blue-500/30' : 'bg-blue-50 text-blue-600 border-blue-200' },
    FIRED:     { icon: Zap,     label: 'Triggered', cls: theme === 'dark' ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'bg-amber-50 text-amber-600 border-amber-200' },
    DISMISSED: { icon: BellOff, label: 'Dismissed', cls: theme === 'dark' ? 'bg-slate-500/15 text-slate-400 border-slate-500/30' : 'bg-slate-50 text-slate-600 border-slate-200' },
  }[status]
  const Icon = cfg.icon
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-bold uppercase tracking-wider ${cfg.cls}`}>
      <Icon className="w-2.5 h-2.5" />{cfg.label}
    </span>
  )
}

function MLSignalCard({ alert, onDismiss, theme }: { alert: Alert; onDismiss: (id: number) => void; theme: 'light' | 'dark' }) {
  const isBuy     = alert.condition.includes('BUY')
  const winMatch  = alert.message.match(/Win probability (\d+)%/)
  const aucMatch  = alert.message.match(/AUC ([\d.]+)/)
  const winPct    = winMatch ? parseInt(winMatch[1]) : 0
  const auc       = aucMatch ? parseFloat(aucMatch[1]) : 0
  
  const barColor  = winPct >= 75 ? 'bg-emerald-500' : winPct >= 65 ? 'bg-amber-500' : 'bg-blue-500'
  const textColor = winPct >= 75 
    ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') 
    : winPct >= 65 
      ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600') 
      : (theme === 'dark' ? 'text-blue-400' : 'text-blue-600')

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`group relative p-4 rounded-2xl border transition-all duration-500 ${
        theme === 'dark' 
          ? 'bg-slate-900/60 border-violet-500/20 hover:border-violet-500/40' 
          : 'bg-white border-slate-200 hover:border-violet-300 shadow-xl shadow-slate-200/40'
      }`}
    >
      {/* ML badge */}
      <div className={`absolute top-3 right-3 flex items-center gap-1 px-2 py-0.5 rounded-full border ${
        theme === 'dark' ? 'bg-violet-500/15 border-violet-500/20' : 'bg-violet-50 border-violet-200'
      }`}>
        <Brain className={`w-2.5 h-2.5 ${theme === 'dark' ? 'text-violet-400' : 'text-violet-600'}`} />
        <span className={`text-[9px] font-black uppercase tracking-widest ${theme === 'dark' ? 'text-violet-400' : 'text-violet-600'}`}>ML Signal</span>
      </div>

      <div className="flex items-start gap-4 pr-24">
        {/* Direction icon */}
        <div className={`p-2.5 rounded-xl shrink-0 ${
          isBuy 
            ? (theme === 'dark' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-emerald-50 text-emerald-600') 
            : (theme === 'dark' ? 'bg-red-500/15 text-red-400' : 'bg-red-50 text-red-600')
        }`}>
          {isBuy ? <BuyIcon className="w-4 h-4" /> : <SellIcon className="w-4 h-4" />}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <span className={`font-black text-sm ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{alert.symbol}</span>
            <span className={`text-xs font-black uppercase tracking-widest ${
              isBuy 
                ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') 
                : (theme === 'dark' ? 'text-red-400' : 'text-red-600')
            }`}>
              {isBuy ? 'LONG' : 'SHORT'}
            </span>
            <StatusBadge status={alert.status} theme={theme} />
          </div>

          {/* Win probability bar */}
          <div className="mb-2">
            <div className="flex justify-between mb-1">
              <span className={`text-[9px] uppercase tracking-widest ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>โอกาสชนะ (Win Probability)</span>
              <span className={`text-[9px] font-black tabular-nums ${textColor}`}>{winPct}%</span>
            </div>
            <div className={`w-full h-1.5 rounded-full overflow-hidden ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-100'}`}>
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${winPct}%` }}
                transition={{ duration: 0.8, ease: 'easeOut' }}
                className={`h-full rounded-full ${barColor}`}
              />
            </div>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {auc > 0 && (
              <span className={`text-[10px] ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>
                ความแม่นยำ AI (AUC) <span className={`font-bold ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>{auc.toFixed(3)}</span> <span className="text-slate-500">/ 1.0</span>
              </span>
            )}
            <span className={`text-[10px] flex items-center gap-1 ${theme === 'dark' ? 'text-slate-600' : 'text-slate-400'}`}>
              <Clock className="w-3 h-3" />
              {new Date(alert.created_at).toLocaleString('th-TH')}
            </span>
          </div>
        </div>
      </div>

      {alert.status !== 'DISMISSED' && (
        <button
          onClick={() => onDismiss(alert.id)}
          className={`absolute bottom-3 right-3 opacity-0 group-hover:opacity-100 p-1.5 rounded-lg transition-all ${
            theme === 'dark' ? 'text-slate-500 hover:text-red-400 hover:bg-red-500/10' : 'text-slate-400 hover:text-red-600 hover:bg-red-50'
          }`}
          title="Dismiss"
        >
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      )}
    </motion.div>
  )
}

export function AlertsReviewsView() {
  const { theme } = useMode()
  const [alerts,  setAlerts]  = useState<Alert[]>([])
  const [reviews, setReviews] = useState<TradeReview[]>([])
  const [tab,     setTab]     = useState<'alerts' | 'ml_signals' | 'reviews'>('ml_signals')
  const [loading, setLoading] = useState(true)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      // Purge stale/low-confidence ML alerts before fetching
      await fetch('/api/alerts/ml/stale', { method: 'DELETE', headers: HEADERS() }).catch(() => {})
      const [ar, rr] = await Promise.all([
        fetch('/api/alerts',       { headers: HEADERS() }).then(r => r.json()),
        fetch('/api/trade-reviews',{ headers: HEADERS() }).then(r => r.json()),
      ])
      setAlerts(ar.alerts  || [])
      setReviews(rr.reviews || [])
    } catch (e) {
      console.error('Dashboard fetch error', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const iv = setInterval(fetchAll, 60_000) // auto-refresh every minute
    return () => clearInterval(iv)
  }, [fetchAll])

  const dismissAlert = async (id: number) => {
    await fetch(`/api/alerts/${id}`, { method: 'DELETE', headers: HEADERS() })
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, status: 'DISMISSED' } : a))
  }

  const userAlerts = alerts.filter(a => a.user_id !== 'ml_scanner')
  // Only show ACTIVE ML alerts with win probability ≥ 70%
  const mlAlerts   = alerts.filter(a => {
    if (a.user_id !== 'ml_scanner') return false
    if (a.status === 'DISMISSED') return false
    const winMatch = a.message.match(/Win probability (\d+)%/)
    const winPct   = winMatch ? parseInt(winMatch[1]) : 0
    return winPct >= 70
  })
  const avgScore   = reviews.length ? Math.round(reviews.reduce((s, r) => s + r.score,    0) / reviews.length) : 0
  const avgWinRate = reviews.length ? Math.round(reviews.reduce((s, r) => s + r.win_rate, 0) / reviews.length) : 0

  const activeML   = mlAlerts.filter(a => a.status === 'ACTIVE').length
  const activeUser = userAlerts.filter(a => a.status === 'ACTIVE').length

  return (
    <div className={`flex flex-col h-full p-6 gap-6 overflow-y-auto transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950' : 'bg-slate-50'
    }`}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className={`text-2xl font-black tracking-tight ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Intelligence Center</h1>
          <p className={`${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'} text-sm mt-0.5`}>ML Signals · Smart Alerts · AI Trade Reviews</p>
        </div>
        <button
          onClick={fetchAll}
          disabled={loading}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl border text-sm font-semibold transition-all ${
            theme === 'dark' 
              ? 'bg-slate-800 border-slate-700 text-slate-300 hover:text-white hover:border-slate-500' 
              : 'bg-white border-slate-200 text-slate-600 hover:text-slate-900 hover:border-slate-300 shadow-sm'
          }`}
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Disclaimer */}
      <div className={`flex items-center gap-3 p-3 border rounded-2xl ${
        theme === 'dark' ? 'bg-amber-500/5 border-amber-500/20' : 'bg-amber-50 border-amber-100'
      }`}>
        <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />
        <p className={`text-xs ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>
          <span className="text-amber-600 font-black mr-2">⚠ NOT Financial Advice</span>
          สัญญาณ ML และการแจ้งเตือนทั้งหมดเป็นข้อมูลเพื่อการศึกษาเท่านั้น — ไม่ใช่คำแนะนำการซื้อขาย
        </p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'ML Signals',       value: activeML,          icon: Brain,    
            dark: 'from-violet-600/20 to-violet-900/10 border-violet-500/20 text-violet-400', 
            light: 'bg-white border-slate-200 text-violet-600 shadow-sm' },
          { label: 'Smart Alerts',     value: activeUser,        icon: Bell,     
            dark: 'from-blue-600/20 to-blue-900/10 border-blue-500/20 text-blue-400', 
            light: 'bg-white border-slate-200 text-blue-600 shadow-sm' },
          { label: 'Avg Review Score', value: `${avgScore}/100`, icon: Award,    
            dark: 'from-emerald-600/20 to-emerald-900/10 border-emerald-500/20 text-emerald-400', 
            light: 'bg-white border-slate-200 text-emerald-600 shadow-sm' },
          { label: 'Avg Win Rate',     value: `${avgWinRate}%`,  icon: BarChart2,
            dark: 'from-amber-600/20 to-amber-900/10 border-amber-500/20 text-amber-400', 
            light: 'bg-white border-slate-200 text-amber-600 shadow-sm' },
        ].map(k => {
          const Icon = k.icon
          return (
            <motion.div
              key={k.label}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              className={`rounded-[2rem] border p-5 flex items-center gap-4 transition-all duration-500 ${
                theme === 'dark' ? `bg-gradient-to-br ${k.dark}` : `${k.light} shadow-xl shadow-slate-200/40 hover:shadow-2xl hover:shadow-slate-300/50 hover:bg-white`
              }`}
            >
              <div className={`p-2.5 rounded-xl ${theme === 'dark' ? 'bg-white/5 text-current' : 'bg-slate-100 text-current shadow-inner'}`}>
                <Icon className="w-5 h-5 transition-transform group-hover:scale-110" />
              </div>
              <div>
                <p className={`${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'} text-xs font-medium`}>{k.label}</p>
                <p className={`text-2xl font-black ${theme === 'dark' ? 'text-current' : 'text-slate-900'}`}>{k.value}</p>
              </div>
            </motion.div>
          )
        })}
      </div>

      {/* Tab Switcher */}
      <div className={`flex gap-2 p-1.5 rounded-[1.5rem] border w-fit transition-all duration-500 ${
        theme === 'dark' ? 'bg-[#0a0f1d]/80 border-white/10' : 'bg-white border-slate-200 shadow-sm'
      }`}>
        {([
          { id: 'ml_signals', label: `ML Signals (${mlAlerts.length})` },
          { id: 'alerts',     label: `Smart Alerts (${userAlerts.length})` },
          { id: 'reviews',    label: `Trade Reviews (${reviews.length})` },
        ] as const).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-5 py-2 rounded-lg text-sm font-black transition-all uppercase tracking-widest ${
              tab === t.id
                ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20'
                : theme === 'dark' ? 'text-slate-400 hover:text-white' : 'text-slate-500 hover:text-slate-900 border border-transparent hover:border-slate-100 hover:bg-slate-50'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <AnimatePresence mode="wait">

        {/* ── ML SIGNALS TAB ── */}
        {tab === 'ml_signals' && (
          <motion.div key="ml_signals" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }} className="flex flex-col gap-3">
            <div className="flex items-center gap-2 px-1 mb-1">
              <Brain className={`w-4 h-4 ${theme === 'dark' ? 'text-violet-400' : 'text-violet-600'}`} />
              <p className={`text-xs ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>
                Auto-generated every 15 min · threshold ≥70% win probability · {mlAlerts.filter(a => a.status === 'ACTIVE').length} active
              </p>
            </div>

            {loading && <div className="text-slate-500 text-center py-12">Scanning...</div>}
            {!loading && mlAlerts.length === 0 && (
              <div className="text-center py-16 text-slate-500">
                <Brain className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="font-semibold">No ML signals yet.</p>
                <p className="text-sm mt-1 text-slate-600">Scanner runs every 15 min after server start (~90s delay)</p>
              </div>
            )}
            {mlAlerts.map((alert, i) => (
              <motion.div key={alert.id} initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: i * 0.04 }}>
                <MLSignalCard alert={alert} onDismiss={dismissAlert} theme={theme} />
              </motion.div>
            ))}
          </motion.div>
        )}

        {/* ── SMART ALERTS TAB ── */}
        {tab === 'alerts' && (
          <motion.div key="alerts" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }} className="flex flex-col gap-3">
            {loading && <div className="text-slate-500 text-center py-12">Loading alerts...</div>}
            {!loading && userAlerts.length === 0 && (
              <div className="text-center py-16 text-slate-500">
                <Bell className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="font-semibold">No smart alerts yet.</p>
                <p className="text-sm mt-1">Ask the AI: <span className="text-blue-500 italic">"เฝ้าทองให้ ถ้าต่ำกว่า 2280 แจ้งเตือน"</span></p>
              </div>
            )}
            {userAlerts.map((alert, i) => (
              <motion.div
                key={alert.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.04 }}
                className={`group flex items-start gap-4 p-4 rounded-2xl border transition-all duration-500 ${
                  theme === 'dark' ? 'bg-slate-900/60 border-slate-800 hover:border-slate-600' : 'bg-white border-slate-200 hover:border-slate-300 shadow-xl shadow-slate-200/40'
                }`}
              >
                <div className={`p-2 rounded-xl shrink-0 ${
                  alert.status === 'FIRED'  ? (theme === 'dark' ? 'bg-amber-500/15 text-amber-400' : 'bg-amber-50 text-amber-600') :
                  alert.status === 'ACTIVE' ? (theme === 'dark' ? 'bg-blue-500/15 text-blue-400' : 'bg-blue-50 text-blue-600')  :
                  (theme === 'dark' ? 'bg-slate-700/30 text-slate-500' : 'bg-slate-100 text-slate-400')
                }`}>
                  <AlertTriangle className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className={`font-black text-sm ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{alert.symbol}</span>
                    <StatusBadge status={alert.status} theme={theme} />
                  </div>
                  <p className={`text-sm font-mono px-2 py-0.5 rounded-lg inline-block ${
                    theme === 'dark' ? 'text-slate-300 bg-slate-800/50' : 'text-slate-700 bg-slate-100'
                  }`}>{alert.condition}</p>
                  <p className={`text-xs mt-1.5 ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>{alert.message}</p>
                  <p className={`text-[10px] mt-1 flex items-center gap-1 ${theme === 'dark' ? 'text-slate-600' : 'text-slate-400'}`}>
                    <Clock className="w-3 h-3" />
                    {new Date(alert.created_at).toLocaleString('th-TH')}
                  </p>
                </div>
                {alert.status !== 'DISMISSED' && (
                  <button
                    onClick={() => dismissAlert(alert.id)}
                    className={`opacity-0 group-hover:opacity-100 p-2 rounded-lg transition-all ${
                      theme === 'dark' ? 'text-slate-500 hover:text-red-400 hover:bg-red-500/10' : 'text-slate-400 hover:text-red-600 hover:bg-red-50'
                    }`}
                    title="Dismiss alert"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
              </motion.div>
            ))}
          </motion.div>
        )}

        {/* ── TRADE REVIEWS TAB ── */}
        {tab === 'reviews' && (
          <motion.div key="reviews" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} className="flex flex-col gap-4">
            {loading && <div className="text-slate-500 text-center py-12">Loading reviews...</div>}
            {!loading && reviews.length === 0 && (
              <div className="text-center py-16 text-slate-500">
                <BarChart2 className="w-10 h-10 mx-auto mb-3 opacity-30" />
                <p className="font-semibold">No trade reviews yet.</p>
                <p className="text-sm mt-1">Ask the AI: <span className="text-blue-500 italic">"รีวิวการเทรดของฉันหน่อย"</span></p>
              </div>
            )}
            {reviews.map((review, i) => {
              const wr = review.win_rate
              return (
                <motion.div
                  key={review.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={`p-5 rounded-2xl border transition-all duration-500 ${
                    theme === 'dark' ? 'bg-slate-900/60 border-slate-800 hover:border-slate-600' : 'bg-white border-slate-200 hover:border-slate-300 shadow-xl shadow-slate-200/40'
                  }`}
                >
                  <div className="flex items-start gap-4">
                    <ScoreRing score={review.score} theme={theme} />
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-2 flex-wrap">
                        <span className={`font-black text-sm ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>AI Trade Review</span>
                        <span className={`flex items-center gap-1 text-xs font-bold ${wr >= 50 ? 'text-emerald-500' : 'text-red-500'}`}>
                          {wr >= 50 ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                          Win Rate: {wr.toFixed(1)}%
                        </span>
                        <span className={`text-[10px] flex items-center gap-1 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>
                          <Clock className="w-3 h-3" />
                          {new Date(review.created_at).toLocaleString('th-TH')}
                        </span>
                      </div>
                      <p className={`text-sm leading-relaxed ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>{review.review_text}</p>
                    </div>
                  </div>
                  <div className="mt-4">
                    <div className={`flex justify-between text-xs mb-1 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>
                      <span>Win Rate</span>
                      <span className={`font-bold ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>{wr.toFixed(1)}%</span>
                    </div>
                    <div className={`h-1.5 rounded-full overflow-hidden ${theme === 'dark' ? 'bg-slate-800' : 'bg-slate-100'}`}>
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${wr}%` }}
                        transition={{ duration: 0.8, ease: 'easeOut' }}
                        className={`h-full rounded-full ${wr >= 60 ? 'bg-emerald-500' : wr >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                      />
                    </div>
                  </div>
                  {review.score >= 70 && (
                    <div className={`mt-3 flex items-center gap-2 text-xs rounded-lg px-3 py-1.5 border ${
                      theme === 'dark' ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-emerald-700 bg-emerald-50 border-emerald-100'
                    }`}>
                      <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                      Performance score is strong. Keep consistent discipline.
                    </div>
                  )}
                </motion.div>
              )
            })}
          </motion.div>
        )}

      </AnimatePresence>
    </div>
  )
}
