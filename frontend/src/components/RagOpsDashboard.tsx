import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  BarChart3,
  Brain,
  CheckCircle2,
  Clock3,
  DollarSign,
  FlaskConical,
  RefreshCw,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react'
import { useMode } from '../contexts/ModeContext'

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || 'demo'
const HEADERS = () => ({ 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' })

interface ObservabilitySummary {
  retrieval_count: number
  avg_latency_ms?: number
  p95_latency_ms?: number
  estimated_cost_usd?: number
  total_tokens?: number
}

interface ExperimentArm {
  arm: string
  retrieval_count: number
  avg_latency_ms?: number
  estimated_cost_usd?: number
}

interface QueueItem {
  retrieval_id: string
  query: string
  result_count: number
  citations: string[]
  metadata: Record<string, unknown>
  created_at: string
  feedback_count: number
  negative_feedback_count: number
}

interface FeedbackStats {
  feedback_count: number
  positive_count: number
  negative_count: number
  satisfaction_percent?: number
  by_rating: Array<{ rating: string; count: number }>
  improvement_candidates: Array<{ query: string; feedback_count: number; negative_count: number }>
}

interface ObservabilityPayload {
  status: string
  tenant_id: string
  summary: ObservabilitySummary
  by_experiment: ExperimentArm[]
  feedback_by_arm: Array<{ arm: string; feedback_count: number; positive_count: number; negative_count: number }>
  annotation_queue: QueueItem[]
}

function MetricTile({
  icon: Icon,
  label,
  value,
  detail,
  theme,
}: {
  icon: any
  label: string
  value: string | number
  detail?: string
  theme: 'light' | 'dark'
}) {
  const dk = theme === 'dark'
  return (
    <div className={`rounded-xl border p-4 ${dk ? 'border-white/10 bg-slate-900/70' : 'border-slate-200 bg-white'}`}>
      <div className="flex items-center justify-between">
        <Icon className={dk ? 'h-4 w-4 text-blue-400' : 'h-4 w-4 text-blue-600'} />
        <span className={`text-xl font-black tabular-nums ${dk ? 'text-white' : 'text-slate-950'}`}>{value}</span>
      </div>
      <p className={`mt-3 text-[10px] font-black uppercase tracking-widest ${dk ? 'text-slate-500' : 'text-slate-400'}`}>{label}</p>
      {detail && <p className={`mt-1 text-xs font-bold ${dk ? 'text-slate-400' : 'text-slate-600'}`}>{detail}</p>}
    </div>
  )
}

export function RagOpsDashboard() {
  const { theme } = useMode()
  const dk = theme === 'dark'
  const [tenantId, setTenantId] = useState('public')
  const [obs, setObs] = useState<ObservabilityPayload | null>(null)
  const [feedback, setFeedback] = useState<FeedbackStats | null>(null)
  const [selected, setSelected] = useState<QueueItem | null>(null)
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [obsRes, feedbackRes] = await Promise.all([
        fetch(`/api/rag/observability?tenant_id=${encodeURIComponent(tenantId)}&limit=30`, { headers: HEADERS() }),
        fetch('/api/rag/feedback/stats?limit=20', { headers: HEADERS() }),
      ])
      if (!obsRes.ok || !feedbackRes.ok) throw new Error('Unable to load RAG operations data')
      const nextObs = await obsRes.json()
      const nextFeedback = await feedbackRes.json()
      if (nextObs.status === 'ERROR' || nextFeedback.status === 'ERROR') {
        throw new Error(nextObs.error || nextFeedback.error || 'RAG operations API returned an error')
      }
      setObs(nextObs)
      setFeedback(nextFeedback)
      setSelected(current => current || nextObs.annotation_queue?.[0] || null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load RAG operations data')
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => {
    load()
    const timer = setInterval(load, 45_000)
    return () => clearInterval(timer)
  }, [load])

  const submitFeedback = async (rating: 'up' | 'down' | 'needs_more_context' | 'wrong_source') => {
    if (!selected) return
    setSaving(true)
    try {
      const body = {
        retrieval_id: selected.retrieval_id,
        rating,
        useful: rating === 'up',
        selected_citation: selected.citations?.[0],
        comment: comment || `Annotation dashboard marked ${rating}`,
        metadata: { source: 'rag_ops_dashboard', tenant_id: tenantId },
      }
      const res = await fetch('/api/rag/feedback', {
        method: 'POST',
        headers: HEADERS(),
        body: JSON.stringify(body),
      })
      if (!res.ok) throw new Error('Unable to save annotation')
      setComment('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save annotation')
    } finally {
      setSaving(false)
    }
  }

  const summary = obs?.summary
  const queue = obs?.annotation_queue || []
  const bestArm = useMemo(() => {
    if (!obs?.by_experiment?.length) return 'No traffic yet'
    return [...obs.by_experiment].sort((a, b) => Number(b.retrieval_count) - Number(a.retrieval_count))[0]?.arm || 'Unknown'
  }, [obs])

  return (
    <div className={`min-h-screen p-6 space-y-6 ${dk ? 'bg-slate-950/40' : 'bg-slate-50'}`}>
      <header className={`flex flex-col gap-4 border-b pb-5 md:flex-row md:items-center md:justify-between ${dk ? 'border-white/5' : 'border-slate-200'}`}>
        <div>
          <div className={`flex items-center gap-2 text-[10px] font-black uppercase tracking-[0.2em] ${dk ? 'text-blue-400' : 'text-blue-600'}`}>
            <Brain className="h-3.5 w-3.5" />
            RAG Production Operations
          </div>
          <h1 className={`mt-1 text-2xl font-black uppercase tracking-tight ${dk ? 'text-white' : 'text-slate-950'}`}>
            Annotation & Retrieval Control
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={tenantId}
            onChange={event => setTenantId(event.target.value || 'public')}
            className={`h-10 w-36 rounded-lg border px-3 text-xs font-bold outline-none ${dk ? 'border-white/10 bg-slate-900 text-slate-200' : 'border-slate-200 bg-white text-slate-900'}`}
            aria-label="Tenant ID"
          />
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

      <section className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <MetricTile icon={BarChart3} label="Retrievals" value={summary?.retrieval_count ?? 0} theme={theme} />
        <MetricTile icon={Clock3} label="Avg Latency" value={`${Number(summary?.avg_latency_ms || 0).toFixed(1)} ms`} detail={`p95 ${Number(summary?.p95_latency_ms || 0).toFixed(1)} ms`} theme={theme} />
        <MetricTile icon={DollarSign} label="Est. Cost" value={`$${Number(summary?.estimated_cost_usd || 0).toFixed(6)}`} detail={`${summary?.total_tokens || 0} tokens`} theme={theme} />
        <MetricTile icon={FlaskConical} label="Top Arm" value={bestArm} theme={theme} />
        <MetricTile icon={ShieldCheck} label="Satisfaction" value={`${Number(feedback?.satisfaction_percent || 0).toFixed(1)}%`} detail={`${feedback?.feedback_count || 0} labels`} theme={theme} />
      </section>

      <section className="grid gap-6 xl:grid-cols-[380px_1fr]">
        <div className={`rounded-xl border p-5 ${dk ? 'border-white/10 bg-slate-900/70' : 'border-slate-200 bg-white'}`}>
          <h2 className={`mb-4 text-sm font-black uppercase tracking-widest ${dk ? 'text-white' : 'text-slate-900'}`}>A/B Arms</h2>
          <div className="space-y-3">
            {(obs?.by_experiment || []).map(arm => (
              <div key={arm.arm} className={`rounded-lg border p-3 ${dk ? 'border-white/5 bg-white/[0.03]' : 'border-slate-100 bg-slate-50'}`}>
                <div className="flex items-center justify-between">
                  <span className={`text-xs font-black uppercase tracking-widest ${dk ? 'text-slate-200' : 'text-slate-900'}`}>{arm.arm}</span>
                  <span className={`font-mono text-xs font-bold ${dk ? 'text-blue-300' : 'text-blue-600'}`}>{arm.retrieval_count}</span>
                </div>
                <p className={`mt-1 text-xs ${dk ? 'text-slate-500' : 'text-slate-500'}`}>
                  avg {Number(arm.avg_latency_ms || 0).toFixed(1)} ms · ${Number(arm.estimated_cost_usd || 0).toFixed(6)}
                </p>
              </div>
            ))}
            {!obs?.by_experiment?.length && <p className={`text-xs ${dk ? 'text-slate-500' : 'text-slate-400'}`}>No experiment traffic yet.</p>}
          </div>

          <h2 className={`mb-4 mt-6 text-sm font-black uppercase tracking-widest ${dk ? 'text-white' : 'text-slate-900'}`}>Weak Queries</h2>
          <div className="space-y-2">
            {(feedback?.improvement_candidates || []).slice(0, 5).map(item => (
              <div key={item.query} className={`rounded-lg border p-3 ${dk ? 'border-amber-500/20 bg-amber-500/5' : 'border-amber-200 bg-amber-50'}`}>
                <p className={`line-clamp-2 text-xs font-bold ${dk ? 'text-amber-100' : 'text-amber-800'}`}>{item.query}</p>
                <p className={`mt-1 text-[10px] font-black uppercase tracking-widest ${dk ? 'text-amber-400' : 'text-amber-600'}`}>
                  {item.negative_count} negative / {item.feedback_count} total
                </p>
              </div>
            ))}
            {!feedback?.improvement_candidates?.length && <p className={`text-xs ${dk ? 'text-slate-500' : 'text-slate-400'}`}>No negative feedback yet.</p>}
          </div>
        </div>

        <div className={`overflow-hidden rounded-xl border ${dk ? 'border-white/10 bg-slate-900/70' : 'border-slate-200 bg-white'}`}>
          <div className={`grid grid-cols-[1fr_120px_100px] gap-4 border-b px-4 py-3 text-[10px] font-black uppercase tracking-widest ${dk ? 'border-white/5 text-slate-500' : 'border-slate-100 text-slate-400'}`}>
            <span>Annotation Queue</span>
            <span>Arm</span>
            <span>Feedback</span>
          </div>
          <div className="grid xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="max-h-[620px] overflow-y-auto">
              {queue.map(item => {
                const active = selected?.retrieval_id === item.retrieval_id
                const arm = String(item.metadata?.experiment_arm || 'unknown')
                return (
                  <button
                    key={item.retrieval_id}
                    onClick={() => setSelected(item)}
                    className={`grid w-full grid-cols-[1fr_120px_100px] gap-4 border-b px-4 py-3 text-left transition ${active ? dk ? 'bg-blue-500/10' : 'bg-blue-50' : dk ? 'border-white/5 hover:bg-white/[0.03]' : 'border-slate-100 hover:bg-slate-50'}`}
                  >
                    <div className="min-w-0">
                      <p className={`truncate text-xs font-black ${dk ? 'text-white' : 'text-slate-900'}`}>{item.query}</p>
                      <p className={`mt-1 truncate text-[10px] font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>{item.retrieval_id}</p>
                    </div>
                    <span className={`text-xs font-bold ${dk ? 'text-blue-300' : 'text-blue-600'}`}>{arm}</span>
                    <span className={`text-xs font-black ${item.negative_feedback_count ? 'text-red-500' : dk ? 'text-slate-400' : 'text-slate-500'}`}>
                      {item.feedback_count}
                    </span>
                  </button>
                )
              })}
              {!queue.length && <div className={`p-8 text-center text-xs font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>No retrievals recorded yet.</div>}
            </div>

            <aside className={`border-l p-5 ${dk ? 'border-white/5 bg-slate-950/40' : 'border-slate-100 bg-slate-50'}`}>
              {selected ? (
                <div className="space-y-4">
                  <div>
                    <p className={`text-[10px] font-black uppercase tracking-widest ${dk ? 'text-slate-500' : 'text-slate-400'}`}>Selected Query</p>
                    <h3 className={`mt-1 text-sm font-black ${dk ? 'text-white' : 'text-slate-950'}`}>{selected.query}</h3>
                  </div>
                  <div className="space-y-2">
                    {(selected.citations || []).slice(0, 5).map(citation => (
                      <div key={citation} className={`rounded-lg border p-2 text-xs font-bold ${dk ? 'border-white/5 bg-white/[0.03] text-slate-300' : 'border-slate-200 bg-white text-slate-700'}`}>
                        {citation}
                      </div>
                    ))}
                  </div>
                  <textarea
                    value={comment}
                    onChange={event => setComment(event.target.value)}
                    placeholder="Reviewer note"
                    className={`min-h-24 w-full rounded-lg border p-3 text-xs font-bold outline-none ${dk ? 'border-white/10 bg-slate-900 text-slate-200 placeholder:text-slate-600' : 'border-slate-200 bg-white text-slate-900 placeholder:text-slate-400'}`}
                  />
                  <div className="grid grid-cols-2 gap-2">
                    <button onClick={() => submitFeedback('up')} disabled={saving} className="flex items-center justify-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-xs font-black uppercase tracking-widest text-white disabled:opacity-50">
                      <ThumbsUp className="h-3.5 w-3.5" /> Good
                    </button>
                    <button onClick={() => submitFeedback('down')} disabled={saving} className="flex items-center justify-center gap-2 rounded-lg bg-red-600 px-3 py-2 text-xs font-black uppercase tracking-widest text-white disabled:opacity-50">
                      <ThumbsDown className="h-3.5 w-3.5" /> Bad
                    </button>
                    <button onClick={() => submitFeedback('needs_more_context')} disabled={saving} className={`rounded-lg border px-3 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50 ${dk ? 'border-white/10 text-slate-300' : 'border-slate-200 text-slate-700'}`}>
                      More Context
                    </button>
                    <button onClick={() => submitFeedback('wrong_source')} disabled={saving} className={`rounded-lg border px-3 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50 ${dk ? 'border-white/10 text-slate-300' : 'border-slate-200 text-slate-700'}`}>
                      Wrong Source
                    </button>
                  </div>
                  <div className={`flex items-center gap-2 rounded-lg border p-3 text-xs font-bold ${dk ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}>
                    <CheckCircle2 className="h-4 w-4" />
                    Labels are saved to the RAG feedback store.
                  </div>
                </div>
              ) : (
                <p className={`text-xs font-bold ${dk ? 'text-slate-500' : 'text-slate-400'}`}>Select a retrieval to annotate.</p>
              )}
            </aside>
          </div>
        </div>
      </section>
    </div>
  )
}
