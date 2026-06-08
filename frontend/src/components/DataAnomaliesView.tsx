import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Activity, BarChart3, Clock, RefreshCw, ShieldAlert, Zap } from 'lucide-react'
import { useMode } from '../contexts/ModeContext'

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || 'demo'
const HEADERS = () => ({ 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' })

interface AnomalyEvent {
  symbol: string
  timeframe: string
  event_ts: string
  anomaly_type: string
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  score: number
  metric_value?: number
  baseline_value?: number
  details?: Record<string, unknown>
  detected_at: string
}

interface AnomalySummary {
  total: number
  critical: number
  high: number
  price_spikes: number
  volume_spikes: number
  range_spikes: number
  missing_gaps: number
  last_detected_at?: string
}

interface TopSymbol {
  symbol: string
  count: number
  max_score: number
}

const labelForType = (type: string) => type.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase())

function StatTile({
  icon: Icon,
  label,
  value,
  tone,
  theme,
}: {
  icon: any
  label: string
  value: number | string
  tone: 'red' | 'amber' | 'blue' | 'emerald'
  theme: 'light' | 'dark'
}) {
  const tones = {
    red: theme === 'dark' ? 'text-red-400 bg-red-500/10 border-red-500/20' : 'text-red-600 bg-red-50 border-red-200',
    amber: theme === 'dark' ? 'text-amber-400 bg-amber-500/10 border-amber-500/20' : 'text-amber-600 bg-amber-50 border-amber-200',
    blue: theme === 'dark' ? 'text-blue-400 bg-blue-500/10 border-blue-500/20' : 'text-blue-600 bg-blue-50 border-blue-200',
    emerald: theme === 'dark' ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-emerald-600 bg-emerald-50 border-emerald-200',
  }[tone]
  return (
    <div className={`rounded-xl border p-4 ${tones}`}>
      <div className="flex items-center justify-between">
        <Icon className="w-4 h-4" />
        <span className="text-xl font-black tabular-nums">{value}</span>
      </div>
      <p className="mt-3 text-[10px] font-black uppercase tracking-widest opacity-80">{label}</p>
    </div>
  )
}

function SeverityBadge({ severity, theme }: { severity: AnomalyEvent['severity']; theme: 'light' | 'dark' }) {
  const cls = {
    CRITICAL: theme === 'dark' ? 'bg-red-500/15 text-red-400 border-red-500/30' : 'bg-red-50 text-red-600 border-red-200',
    HIGH: theme === 'dark' ? 'bg-amber-500/15 text-amber-400 border-amber-500/30' : 'bg-amber-50 text-amber-600 border-amber-200',
    MEDIUM: theme === 'dark' ? 'bg-blue-500/15 text-blue-400 border-blue-500/30' : 'bg-blue-50 text-blue-600 border-blue-200',
    LOW: theme === 'dark' ? 'bg-slate-500/15 text-slate-400 border-slate-500/30' : 'bg-slate-50 text-slate-600 border-slate-200',
  }[severity]
  return <span className={`rounded-full border px-2 py-0.5 text-[10px] font-black ${cls}`}>{severity}</span>
}

export function DataAnomaliesView() {
  const { theme } = useMode()
  const [hours, setHours] = useState(72)
  const [summary, setSummary] = useState<AnomalySummary | null>(null)
  const [topSymbols, setTopSymbols] = useState<TopSymbol[]>([])
  const [events, setEvents] = useState<AnomalyEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const dk = theme === 'dark'

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [summaryRes, recentRes] = await Promise.all([
        fetch('/api/anomalies/summary', {
          method: 'POST',
          headers: HEADERS(),
          body: JSON.stringify({ hours }),
        }).then(r => r.json()),
        fetch('/api/anomalies/recent', {
          method: 'POST',
          headers: HEADERS(),
          body: JSON.stringify({ hours, limit: 30 }),
        }).then(r => r.json()),
      ])
      if (summaryRes.status === 'ERROR' || recentRes.status === 'ERROR') {
        throw new Error(summaryRes.error || recentRes.error || 'Unable to load anomalies')
      }
      setSummary(summaryRes.summary)
      setTopSymbols(summaryRes.top_symbols || [])
      setEvents(recentRes.anomalies || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load anomalies')
    } finally {
      setLoading(false)
    }
  }, [hours])

  useEffect(() => {
    load()
    const timer = setInterval(load, 60_000)
    return () => clearInterval(timer)
  }, [load])

  return (
    <div className={`min-h-screen p-6 space-y-6 ${dk ? 'bg-slate-950/40' : 'bg-slate-50'}`}>
      <header className={`flex flex-col gap-4 border-b pb-5 md:flex-row md:items-center md:justify-between ${dk ? 'border-white/5' : 'border-slate-200'}`}>
        <div>
          <div className={`flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] ${dk ? 'text-red-400' : 'text-red-600'}`}>
            <ShieldAlert className="h-3.5 w-3.5" />
            Data Quality Operations
          </div>
          <h1 className={`mt-1 text-2xl font-black uppercase tracking-tight ${dk ? 'text-white' : 'text-slate-950'}`}>
            Data Anomalies
          </h1>
        </div>
        <div className="flex items-center gap-2">
          {[24, 72, 168].map(value => (
            <button
              key={value}
              onClick={() => setHours(value)}
              className={`rounded-lg px-3 py-2 text-xs font-black transition ${
                hours === value
                  ? dk ? 'bg-red-500/20 text-red-300' : 'bg-red-50 text-red-600'
                  : dk ? 'text-slate-500 hover:bg-white/5 hover:text-slate-300' : 'text-slate-500 hover:bg-white hover:text-slate-900'
              }`}
            >
              {value}h
            </button>
          ))}
          <button
            onClick={load}
            className={`rounded-lg p-2 transition ${dk ? 'text-slate-400 hover:bg-white/5 hover:text-white' : 'text-slate-500 hover:bg-white hover:text-slate-900'}`}
            title="Refresh"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {error && (
        <div className={`rounded-xl border p-4 text-sm font-bold ${dk ? 'border-red-500/30 bg-red-500/10 text-red-300' : 'border-red-200 bg-red-50 text-red-700'}`}>
          {error}
        </div>
      )}

      <section className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatTile icon={AlertTriangle} label="Critical" value={summary?.critical ?? 0} tone="red" theme={theme} />
        <StatTile icon={Zap} label="High" value={summary?.high ?? 0} tone="amber" theme={theme} />
        <StatTile icon={Activity} label="Total Events" value={summary?.total ?? 0} tone="blue" theme={theme} />
        <StatTile icon={Clock} label="Missing Gaps" value={summary?.missing_gaps ?? 0} tone="emerald" theme={theme} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[360px_1fr]">
        <div className={`rounded-xl border p-5 ${dk ? 'border-white/10 bg-slate-900/60' : 'border-slate-200 bg-white'}`}>
          <div className="mb-4 flex items-center gap-2">
            <BarChart3 className={dk ? 'h-4 w-4 text-blue-400' : 'h-4 w-4 text-blue-600'} />
            <h2 className={`text-sm font-black uppercase tracking-widest ${dk ? 'text-white' : 'text-slate-900'}`}>Top Symbols</h2>
          </div>
          <div className="space-y-3">
            {topSymbols.map(item => (
              <div key={item.symbol}>
                <div className="mb-1 flex items-center justify-between">
                  <span className={`font-mono text-xs font-black ${dk ? 'text-slate-200' : 'text-slate-800'}`}>{item.symbol}</span>
                  <span className={`text-xs font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>{item.count}</span>
                </div>
                <div className={`h-1.5 overflow-hidden rounded-full ${dk ? 'bg-white/5' : 'bg-slate-100'}`}>
                  <div className="h-full rounded-full bg-red-500" style={{ width: `${Math.min(100, item.count * 4)}%` }} />
                </div>
              </div>
            ))}
            {!topSymbols.length && <p className={`text-xs ${dk ? 'text-slate-500' : 'text-slate-400'}`}>No anomalies in this window.</p>}
          </div>
        </div>

        <div className={`overflow-hidden rounded-xl border ${dk ? 'border-white/10 bg-slate-900/60' : 'border-slate-200 bg-white'}`}>
          <div className={`grid grid-cols-[1fr_100px_110px_90px] gap-4 border-b px-4 py-3 text-[10px] font-black uppercase tracking-widest ${dk ? 'border-white/5 text-slate-500' : 'border-slate-100 text-slate-400'}`}>
            <span>Event</span>
            <span>Severity</span>
            <span>Score</span>
            <span>Time</span>
          </div>
          <div className="max-h-[560px] overflow-y-auto">
            {events.map((event, idx) => (
              <div
                key={`${event.symbol}-${event.event_ts}-${event.anomaly_type}-${idx}`}
                className={`grid grid-cols-[1fr_100px_110px_90px] gap-4 px-4 py-3 text-sm ${dk ? 'border-white/5 hover:bg-white/[0.03]' : 'border-slate-100 hover:bg-slate-50'} ${idx !== events.length - 1 ? 'border-b' : ''}`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`font-mono text-xs font-black ${dk ? 'text-white' : 'text-slate-900'}`}>{event.symbol}</span>
                    <span className={`text-[10px] font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>{event.timeframe}</span>
                  </div>
                  <p className={`mt-1 truncate text-xs ${dk ? 'text-slate-400' : 'text-slate-600'}`}>{labelForType(event.anomaly_type)}</p>
                </div>
                <div className="flex items-center"><SeverityBadge severity={event.severity} theme={theme} /></div>
                <div className={`font-mono text-xs font-black tabular-nums ${dk ? 'text-slate-300' : 'text-slate-700'}`}>
                  {Number(event.score).toFixed(2)}
                </div>
                <div className={`text-[10px] font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>
                  {new Date(event.event_ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </div>
            ))}
            {!events.length && (
              <div className={`p-8 text-center text-xs font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>
                No anomaly events found for this window.
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
