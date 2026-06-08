import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, AlertTriangle, BarChart3, Brain, Network, RefreshCw, ShieldCheck, TrendingUp } from 'lucide-react'
import { useMode } from '../contexts/ModeContext'

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || 'demo'
const HEADERS = () => ({ 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' })

interface HorizonMetric {
  evaluated: number
  wins: number
  losses: number
  win_rate: number
  avg_return: number
}

interface BestMetrics {
  total_snapshots: number
  horizons: Record<string, HorizonMetric>
  by_symbol: Record<string, { snapshots: number; evaluated_4h: number; win_rate_4h: number; avg_return_4h: number }>
  recommendations: string[]
}

interface RiskGuard {
  status: string
  balance_basis: number
  daily_loss_limit_pct: number
  daily_loss_limit_usd: number
  paper_pnl_usd_today: number
  opened_trades_today: number
  max_daily_trades: number
  open_trades: number
  blockers: string[]
  warnings: string[]
}

interface PreGraphReadiness {
  ready_for_graph_rag: boolean
  blockers: string[]
  recommendations: string[]
  current: {
    evaluated_4h: number
    feedback_labels: number
    trade_memory_last_sync_at?: string
  }
}

interface TradeGraphStatus {
  status: string
  nodes: number
  edges: number
  last_build_at?: string
}

function Tile({
  icon: Icon,
  label,
  value,
  detail,
  tone,
  dark,
}: {
  icon: any
  label: string
  value: string | number
  detail?: string
  tone?: 'ok' | 'warn' | 'bad'
  dark: boolean
}) {
  const toneCls = tone === 'bad' ? 'text-rose-500' : tone === 'warn' ? 'text-amber-500' : 'text-emerald-500'
  return (
    <div className={`rounded-xl border p-4 ${dark ? 'border-white/10 bg-slate-900/70' : 'border-slate-200 bg-white'}`}>
      <div className="flex items-center justify-between gap-3">
        <Icon className={`h-4 w-4 ${toneCls}`} />
        <span className={`text-xl font-black tabular-nums ${dark ? 'text-white' : 'text-slate-950'}`}>{value}</span>
      </div>
      <p className={`mt-3 text-[10px] font-black uppercase tracking-widest ${dark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</p>
      {detail && <p className={`mt-1 text-xs font-bold ${dark ? 'text-slate-400' : 'text-slate-600'}`}>{detail}</p>}
    </div>
  )
}

export function BestAiControlView() {
  const { theme } = useMode()
  const dark = theme === 'dark'
  const [metrics, setMetrics] = useState<BestMetrics | null>(null)
  const [guard, setGuard] = useState<RiskGuard | null>(null)
  const [preGraph, setPreGraph] = useState<PreGraphReadiness | null>(null)
  const [graph, setGraph] = useState<TradeGraphStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [buildingGraph, setBuildingGraph] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [synced, setSynced] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [metricsRes, guardRes, preGraphRes, graphRes] = await Promise.all([
        fetch('/api/best-setup/metrics', { headers: HEADERS() }),
        fetch('/api/risk/daily-guard', { headers: HEADERS() }),
        fetch('/api/rag/pre-graph-readiness', { headers: HEADERS() }),
        fetch('/api/rag/graph/status', { headers: HEADERS() }),
      ])
      if (!metricsRes.ok || !guardRes.ok || !preGraphRes.ok || !graphRes.ok) throw new Error('Unable to load Best AI controls')
      setMetrics(await metricsRes.json())
      setGuard(await guardRes.json())
      setPreGraph(await preGraphRes.json())
      setGraph(await graphRes.json())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load Best AI controls')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 45_000)
    return () => clearInterval(timer)
  }, [load])

  const syncMemory = async () => {
    setSyncing(true)
    setSynced(null)
    setError(null)
    try {
      const res = await fetch('/api/rag/trade-memory/sync?force=true', { method: 'POST', headers: HEADERS() })
      if (!res.ok) throw new Error('Unable to sync trade memory')
      const data = await res.json()
      setSynced(data.status === 'SKIPPED' ? 'Trade memory already fresh' : 'Trade memory synced to RAG')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sync trade memory')
    } finally {
      setSyncing(false)
    }
  }

  const buildGraph = async () => {
    setBuildingGraph(true)
    setSynced(null)
    setError(null)
    try {
      const res = await fetch('/api/rag/graph/build', { method: 'POST', headers: HEADERS() })
      if (!res.ok) throw new Error('Unable to build trade graph')
      await res.json()
      setSynced('Trade graph built from outcomes, feedback, and paper trades')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to build trade graph')
    } finally {
      setBuildingGraph(false)
    }
  }

  const h4 = metrics?.horizons?.['4h']
  const symbols = useMemo(() => {
    return Object.entries(metrics?.by_symbol || {})
      .sort((a, b) => (b[1].evaluated_4h - a[1].evaluated_4h) || (b[1].win_rate_4h - a[1].win_rate_4h))
      .slice(0, 8)
  }, [metrics])

  return (
    <div className={`min-h-screen p-6 space-y-6 ${dark ? 'bg-slate-950/40' : 'bg-slate-50'}`}>
      <header className={`flex flex-col gap-4 border-b pb-5 md:flex-row md:items-center md:justify-between ${dark ? 'border-white/5' : 'border-slate-200'}`}>
        <div>
          <div className={`flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] ${dark ? 'text-emerald-400' : 'text-emerald-600'}`}>
            <Brain className="h-3.5 w-3.5" />
            AI Finance Agent Controls
          </div>
          <h1 className={`mt-1 text-2xl font-black uppercase tracking-tight ${dark ? 'text-white' : 'text-slate-950'}`}>Best Setup Accuracy & Guard</h1>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={syncMemory} disabled={syncing} className={`rounded-lg px-3 py-2 text-xs font-black uppercase tracking-widest transition ${dark ? 'bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25' : 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100'}`}>
            {syncing ? 'Syncing' : 'Sync RAG Memory'}
          </button>
          <button onClick={buildGraph} disabled={buildingGraph} className={`rounded-lg px-3 py-2 text-xs font-black uppercase tracking-widest transition ${dark ? 'bg-blue-500/15 text-blue-300 hover:bg-blue-500/25' : 'bg-blue-50 text-blue-700 hover:bg-blue-100'}`}>
            {buildingGraph ? 'Building' : 'Build Graph'}
          </button>
          <button onClick={load} className={`rounded-lg p-2 transition ${dark ? 'text-slate-400 hover:bg-white/5 hover:text-white' : 'text-slate-500 hover:bg-white hover:text-slate-900'}`} title="Refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {error && <div className={`rounded-xl border p-4 text-sm font-bold ${dark ? 'border-rose-500/30 bg-rose-500/10 text-rose-300' : 'border-rose-200 bg-rose-50 text-rose-700'}`}>{error}</div>}
      {synced && <div className={`rounded-xl border p-4 text-sm font-bold ${dark ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>{synced}</div>}

      <section className="grid grid-cols-2 gap-4 xl:grid-cols-6">
        <Tile icon={BarChart3} label="Snapshots" value={metrics?.total_snapshots ?? 0} detail="Best setup records" dark={dark} />
        <Tile icon={TrendingUp} label="4h Win Rate" value={`${Math.round((h4?.win_rate || 0) * 100)}%`} detail={`${h4?.evaluated || 0} evaluated`} tone={(h4?.win_rate || 0) >= 0.5 ? 'ok' : 'warn'} dark={dark} />
        <Tile icon={Activity} label="4h Avg Return" value={`${((h4?.avg_return || 0) * 100).toFixed(3)}%`} detail={`${h4?.wins || 0} wins / ${h4?.losses || 0} losses`} tone={(h4?.avg_return || 0) >= 0 ? 'ok' : 'bad'} dark={dark} />
        <Tile icon={ShieldCheck} label="Risk Guard" value={guard?.status || '...'} detail={`${guard?.opened_trades_today ?? 0}/${guard?.max_daily_trades ?? 0} trades today`} tone={guard?.status === 'blocked' ? 'bad' : guard?.status === 'watch' ? 'warn' : 'ok'} dark={dark} />
        <Tile icon={AlertTriangle} label="Graph Ready" value={preGraph?.ready_for_graph_rag ? 'Ready' : 'Not Yet'} detail={`${preGraph?.current?.evaluated_4h ?? 0} 4h eval, ${preGraph?.current?.feedback_labels ?? 0} labels`} tone={preGraph?.ready_for_graph_rag ? 'ok' : 'warn'} dark={dark} />
        <Tile icon={Network} label="Trade Graph" value={graph?.status || '...'} detail={`${graph?.nodes ?? 0} nodes / ${graph?.edges ?? 0} edges`} tone={graph?.status === 'OK' ? 'ok' : 'warn'} dark={dark} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_420px]">
        <div className={`rounded-xl border p-5 ${dark ? 'border-white/10 bg-slate-900/70' : 'border-slate-200 bg-white'}`}>
          <h2 className={`mb-4 text-sm font-black uppercase tracking-widest ${dark ? 'text-white' : 'text-slate-900'}`}>Symbol Outcome Record</h2>
          <div className="space-y-2">
            {symbols.length === 0 ? (
              <p className={`text-sm font-bold ${dark ? 'text-slate-500' : 'text-slate-500'}`}>No evaluated records yet.</p>
            ) : symbols.map(([symbol, row]) => (
              <div key={symbol} className={`grid grid-cols-[1fr_90px_90px_110px] items-center gap-3 rounded-lg border p-3 text-xs font-bold ${dark ? 'border-white/5 bg-white/[0.03]' : 'border-slate-100 bg-slate-50'}`}>
                <span className={dark ? 'text-slate-100' : 'text-slate-900'}>{symbol}</span>
                <span className={dark ? 'text-slate-400' : 'text-slate-600'}>{row.evaluated_4h} eval</span>
                <span className={(row.win_rate_4h || 0) >= 0.5 ? 'text-emerald-500' : 'text-amber-500'}>{Math.round((row.win_rate_4h || 0) * 100)}%</span>
                <span className={(row.avg_return_4h || 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'}>{((row.avg_return_4h || 0) * 100).toFixed(3)}%</span>
              </div>
            ))}
          </div>
        </div>

        <div className={`rounded-xl border p-5 ${dark ? 'border-white/10 bg-slate-900/70' : 'border-slate-200 bg-white'}`}>
          <h2 className={`mb-4 text-sm font-black uppercase tracking-widest ${dark ? 'text-white' : 'text-slate-900'}`}>Guard Detail</h2>
          <div className={`rounded-lg border p-4 ${dark ? 'border-white/5 bg-white/[0.03]' : 'border-slate-100 bg-slate-50'}`}>
            <p className={`text-xs font-black uppercase tracking-widest ${dark ? 'text-slate-500' : 'text-slate-400'}`}>Open Trades</p>
            <p className={`mt-1 text-2xl font-black ${dark ? 'text-white' : 'text-slate-950'}`}>{guard?.open_trades ?? 0}</p>
            <p className={`mt-2 text-xs font-bold ${dark ? 'text-slate-400' : 'text-slate-600'}`}>Daily limit {guard?.daily_loss_limit_pct ?? 0}% of ${guard?.balance_basis ?? 0}</p>
          </div>
          <div className="mt-4 space-y-2">
            {(guard?.blockers?.length ? guard.blockers : guard?.warnings?.length ? guard.warnings : ['Guard clear']).map(item => (
              <div key={item} className={`rounded-lg border px-3 py-2 text-xs font-bold ${guard?.blockers?.length ? (dark ? 'border-rose-500/30 bg-rose-500/10 text-rose-300' : 'border-rose-200 bg-rose-50 text-rose-700') : (dark ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700')}`}>
                {item}
              </div>
            ))}
          </div>
        </div>
      </section>

      {!!metrics?.recommendations?.length && (
        <section className={`rounded-xl border p-5 ${dark ? 'border-amber-500/20 bg-amber-500/10' : 'border-amber-200 bg-amber-50'}`}>
          <h2 className={`mb-3 text-sm font-black uppercase tracking-widest ${dark ? 'text-amber-300' : 'text-amber-700'}`}>Recommendations</h2>
          <div className="space-y-2">
            {metrics.recommendations.map(item => <p key={item} className={`text-sm font-bold ${dark ? 'text-amber-100' : 'text-amber-800'}`}>{item}</p>)}
          </div>
        </section>
      )}

      {!!preGraph?.blockers?.length && (
        <section className={`rounded-xl border p-5 ${dark ? 'border-blue-500/20 bg-blue-500/10' : 'border-blue-200 bg-blue-50'}`}>
          <h2 className={`mb-3 text-sm font-black uppercase tracking-widest ${dark ? 'text-blue-300' : 'text-blue-700'}`}>Before Graph RAG</h2>
          <div className="space-y-2">
            {preGraph.blockers.map(item => <p key={item} className={`text-sm font-bold ${dark ? 'text-blue-100' : 'text-blue-800'}`}>{item}</p>)}
          </div>
        </section>
      )}
    </div>
  )
}

export default BestAiControlView
