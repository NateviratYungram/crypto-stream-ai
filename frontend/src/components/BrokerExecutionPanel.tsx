import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  DollarSign,
  Gauge,
  Layers,
  Loader2,
  MessageSquare,
  RefreshCw,
  Server,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Wallet,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import { useMode } from '../contexts/ModeContext'

interface Account {
  login?: number
  name?: string
  company?: string
  balance?: number
  equity?: number
  profit?: number
  margin?: number
  margin_free?: number
  margin_level?: number
  leverage?: number
  currency?: string
  server?: string
  trade_allowed?: boolean
  trade_expert?: boolean
}

interface Position {
  ticket: number
  symbol: string
  type: number
  volume: number
  price_open?: number
  sl?: number
  tp?: number
  profit?: number
  comment?: string
}

interface Quote {
  symbol: string
  bid: number
  ask: number
  last?: number
  spread?: number
  time?: number
  digits?: number
  point?: number
  volume_min?: number
  volume_max?: number
  volume_step?: number
  trade_contract_size?: number
}

const XM_SYMBOLS = [
  'BTCUSD',
  'ETHUSD',
  'SOLUSD',
  'XRPUSD',
  'GOLD',
  'SILVER',
  'EURUSD',
  'GBPUSD',
  'USDJPY',
  'USOIL',
  'US100Cash',
  'US500Cash',
  'NVDA#',
  'TSLA#',
  'AAPL#',
  'MSFT#',
]

const LOT_PRESETS = [0.01, 0.05, 0.1, 0.5, 1]
const PENDING_TYPES = ['BUY_LIMIT', 'SELL_LIMIT', 'BUY_STOP', 'SELL_STOP'] as const
const FILLING_POLICIES = ['IOC', 'FOK', 'RETURN'] as const

const fmtMoney = (value?: number, currency = 'USD') =>
  `${currency === 'USD' ? '$' : `${currency} `}${Number(value ?? 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`

const fmtNumber = (value?: number, digits = 2) => Number(value ?? 0).toFixed(digits)

export const BrokerExecutionPanel = () => {
  const { theme } = useMode()
  const dk = theme === 'dark'

  const [account, setAccount] = useState<Account | null>(null)
  const [positions, setPositions] = useState<Position[]>([])
  const [connected, setConnected] = useState(false)
  const [connectionSource, setConnectionSource] = useState<'direct' | 'cache_live' | 'cache_fallback' | 'offline'>('offline')
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastSync, setLastSync] = useState<Date | null>(null)
  const [quote, setQuote] = useState<Quote | null>(null)
  const [quoteLoading, setQuoteLoading] = useState(false)
  const [quoteError, setQuoteError] = useState<string | null>(null)
  const [lastQuoteSync, setLastQuoteSync] = useState<Date | null>(null)
  const [form, setForm] = useState({
    symbol: 'GOLD',
    orderKind: 'MARKET' as 'MARKET' | 'PENDING',
    side: 'BUY' as 'BUY' | 'SELL',
    pendingType: 'BUY_LIMIT' as typeof PENDING_TYPES[number],
    volume: 0.01,
    price: 0,
    sl: 0,
    tp: 0,
    fillingPolicy: 'IOC' as typeof FILLING_POLICIES[number],
    deviation: 20,
    comment: 'Manual MT5 order',
  })
  const [executing, setExecuting] = useState(false)
  const [closingTicket, setClosingTicket] = useState<number | null>(null)
  const [toast, setToast] = useState<{ type: 'ok' | 'err'; msg: string } | null>(null)
  const [confirm, setConfirm] = useState(false)

  const showToast = (type: 'ok' | 'err', msg: string) => {
    setToast({ type, msg })
    setTimeout(() => setToast(null), 4500)
  }

  const fetchAccount = useCallback(async () => {
    setRefreshing(true)
    try {
      const r = await fetch('/api/mt5/account')
      const d = await r.json()
      const nextConnected = Boolean(d.connected)
      setConnected(nextConnected)
      setConnectionSource(nextConnected ? (d.source ?? 'direct') : 'offline')
      setAccount(d.account ?? null)
      setPositions(Array.isArray(d.positions) ? d.positions : [])
      setLastSync(new Date())
      if (!nextConnected && (d.error || d.warning)) showToast('err', d.error || d.warning)
    } catch {
      setConnected(false)
      setConnectionSource('offline')
      showToast('err', 'Unable to reach MT5 account API')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  const fetchQuote = useCallback(async (symbol: string) => {
    setQuoteLoading(true)
    try {
      const r = await fetch(`/api/mt5/quote?symbol=${encodeURIComponent(symbol)}`)
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || d.error || 'Quote unavailable')
      setQuote(d)
      setQuoteError(null)
      setLastQuoteSync(new Date())
      if (form.orderKind === 'PENDING' && !form.price) {
        setForm((f) => ({ ...f, price: Number(d.bid || d.ask || 0) }))
      }
    } catch (e: any) {
      setQuoteError(e.message || 'Quote unavailable')
    } finally {
      setQuoteLoading(false)
    }
  }, [form.orderKind, form.price])

  useEffect(() => {
    fetchAccount()
    const timer = setInterval(fetchAccount, 12000)
    return () => clearInterval(timer)
  }, [fetchAccount])

  useEffect(() => {
    fetchQuote(form.symbol)
    const timer = setInterval(() => fetchQuote(form.symbol), 2000)
    return () => clearInterval(timer)
  }, [fetchQuote, form.symbol])

  const totalPnl = useMemo(() => positions.reduce((sum, pos) => sum + Number(pos.profit ?? 0), 0), [positions])
  const marginLevel = Number(account?.margin_level ?? 0)
  const marginState = marginLevel === 0 ? 'Idle' : marginLevel < 150 ? 'Pressure' : marginLevel < 300 ? 'Watch' : 'Healthy'
  const canSubmit = connected && form.volume > 0 && !executing
  const activeOrderType = form.orderKind === 'MARKET' ? form.side : form.pendingType
  const priceDigits = quote?.digits ?? (form.symbol.includes('JPY') ? 3 : 2)
  const executionPrice = form.orderKind === 'MARKET'
    ? form.side === 'BUY' ? quote?.ask : quote?.bid
    : form.price
  const estimatedNotional = Number(executionPrice ?? 0) * Number(form.volume || 0) * Number(quote?.trade_contract_size || 1)

  const executeTrade = async () => {
    setExecuting(true)
    setConfirm(false)
    try {
      const r = await fetch('/api/mt5/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: form.symbol,
          side: form.orderKind === 'MARKET' ? form.side : form.pendingType,
          volume: form.volume,
          price: form.orderKind === 'PENDING' ? form.price : undefined,
          sl: form.sl || 0,
          tp: form.tp || 0,
          order_kind: form.orderKind,
          filling_policy: form.fillingPolicy,
          deviation: form.deviation,
          comment: form.comment,
        }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || d.message || 'Trade failed')
      const orderId = d.order_id ?? d.order ?? d.ticket ?? d.deal ?? 'accepted'
      showToast('ok', `Order ${orderId}: ${activeOrderType} ${form.volume} ${form.symbol}`)
      fetchAccount()
    } catch (e: any) {
      showToast('err', e.message || 'Trade failed')
    } finally {
      setExecuting(false)
    }
  }

  const closePosition = async (ticket: number) => {
    setClosingTicket(ticket)
    try {
      const r = await fetch('/api/mt5/close', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticket }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || d.message || 'Close failed')
      showToast('ok', `Position ${ticket} closed`)
      fetchAccount()
    } catch (e: any) {
      showToast('err', e.message || 'Close failed')
    } finally {
      setClosingTicket(null)
    }
  }

  const page = `flex-1 overflow-y-auto p-6 lg:p-8 scrollbar-hide ${dk ? 'bg-slate-950' : 'bg-slate-50'}`
  const panel = `border rounded-lg p-5 transition-all ${dk ? 'bg-slate-900/55 border-white/10' : 'bg-white border-slate-200 shadow-sm'}`
  const input = `w-full border rounded-lg px-3 py-2.5 text-sm font-semibold transition-all focus:outline-none focus:ring-2 ${
    dk
      ? 'bg-slate-950/60 border-white/10 text-white focus:ring-blue-500/30'
      : 'bg-white border-slate-200 text-slate-900 focus:ring-blue-500/10 focus:border-blue-400'
  }`
  const muted = dk ? 'text-slate-500' : 'text-slate-400'
  const strong = dk ? 'text-white' : 'text-slate-900'

  const MetricCard = ({
    label,
    value,
    icon: Icon,
    tone,
    sub,
  }: {
    label: string
    value: string
    icon: any
    tone: 'blue' | 'emerald' | 'rose' | 'amber' | 'slate'
    sub?: string
  }) => {
    const tones = {
      blue: dk ? 'bg-blue-500/10 text-blue-400' : 'bg-blue-50 text-blue-600',
      emerald: dk ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-50 text-emerald-600',
      rose: dk ? 'bg-rose-500/10 text-rose-400' : 'bg-rose-50 text-rose-600',
      amber: dk ? 'bg-amber-500/10 text-amber-400' : 'bg-amber-50 text-amber-600',
      slate: dk ? 'bg-slate-800 text-slate-400' : 'bg-slate-100 text-slate-500',
    }
    return (
      <div className={panel}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>{label}</p>
            <p className={`mt-2 text-xl font-black ${strong}`}>{value}</p>
            {sub && <p className={`mt-1 text-[11px] font-bold ${muted}`}>{sub}</p>}
          </div>
          <div className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tones[tone]}`}>
            <Icon className="h-4 w-4" />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={page}>
      {toast && (
        <div
          className={`fixed right-6 top-6 z-50 flex max-w-sm items-center gap-3 rounded-lg border px-4 py-3 text-sm font-bold shadow-2xl ${
            toast.type === 'ok'
              ? dk
                ? 'bg-emerald-950 border-emerald-500/30 text-emerald-300'
                : 'bg-emerald-50 border-emerald-200 text-emerald-700'
              : dk
                ? 'bg-rose-950 border-rose-500/30 text-rose-300'
                : 'bg-rose-50 border-rose-200 text-rose-700'
          }`}
        >
          {toast.type === 'ok' ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
          <span>{toast.msg}</span>
        </div>
      )}

      <header className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-black uppercase tracking-[0.22em] text-blue-500">
            <Activity className="h-4 w-4" />
            Live Trading
          </div>
          <h1 className={`text-3xl font-black tracking-tight ${strong}`}>MT5 Execution</h1>
          <p className={`mt-1 text-sm font-medium ${muted}`}>Account, quote ladder, detailed order ticket, and live positions.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div
            className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-black ${
              connected
                ? dk
                  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                  : 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : dk
                  ? 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                  : 'bg-rose-50 border-rose-200 text-rose-700'
            }`}
          >
            {connected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
            {connected ? (connectionSource === 'cache_live' ? 'MT5 Cached Live' : 'MT5 Connected') : 'MT5 Offline'}
          </div>
          <div className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-bold ${dk ? 'border-white/10 text-slate-400' : 'border-slate-200 text-slate-500'}`}>
            <Clock className="h-3.5 w-3.5" />
            {lastSync ? lastSync.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'No sync'}
          </div>
          <button
            onClick={() => {
              fetchAccount()
              fetchQuote(form.symbol)
            }}
            disabled={refreshing}
            className={`flex h-9 w-9 items-center justify-center rounded-lg border transition-all ${
              dk ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-900'
            } disabled:opacity-50`}
            title="Refresh account"
          >
            <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      <section className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className={`h-28 animate-pulse rounded-lg border ${dk ? 'bg-slate-900 border-white/10' : 'bg-white border-slate-200'}`} />
          ))
        ) : account ? (
          <>
            <MetricCard label="Balance" value={fmtMoney(account.balance, account.currency)} icon={Wallet} tone="blue" sub={account.server || 'Broker server'} />
            <MetricCard
              label="Equity"
              value={fmtMoney(account.equity, account.currency)}
              icon={DollarSign}
              tone={Number(account.equity ?? 0) >= Number(account.balance ?? 0) ? 'emerald' : 'rose'}
              sub={`Floating ${fmtMoney(account.profit, account.currency)}`}
            />
            <MetricCard label="Free Margin" value={fmtMoney(account.margin_free, account.currency)} icon={ShieldCheck} tone="slate" sub={`Used ${fmtMoney(account.margin, account.currency)}`} />
            <MetricCard label="Margin Level" value={marginLevel ? `${fmtNumber(marginLevel, 1)}%` : 'Idle'} icon={Gauge} tone={marginState === 'Pressure' ? 'rose' : marginState === 'Watch' ? 'amber' : 'emerald'} sub={marginState} />
          </>
        ) : (
          <div className={`${panel} col-span-2 lg:col-span-4 flex items-center gap-3`}>
            <WifiOff className={`h-6 w-6 ${muted}`} />
            <div>
              <p className={`text-sm font-black ${strong}`}>MT5 account is unavailable</p>
              <p className={`text-xs font-medium ${muted}`}>Open MetaTrader 5 and confirm the terminal is logged in.</p>
            </div>
          </div>
        )}
      </section>

      <main className="grid grid-cols-1 gap-6 xl:grid-cols-12">
        <section className={`${panel} xl:col-span-5`}>
          <div className="mb-5 flex items-start justify-between gap-3">
            <div>
              <h2 className={`text-base font-black ${strong}`}>New Order</h2>
              <p className={`mt-1 text-xs font-medium ${muted}`}>Structured MT5 order ticket with realtime pricing.</p>
            </div>
            <span className={`rounded-lg px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${activeOrderType.includes('BUY') ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
              {activeOrderType.replace('_', ' ')}
            </span>
          </div>

          <div className="space-y-4">
            <div className={`rounded-lg border p-3 ${dk ? 'bg-slate-950/40 border-white/10' : 'bg-slate-50 border-slate-200'}`}>
              <div className="mb-2 flex items-center justify-between">
                <span className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Realtime Quote</span>
                <span className={`text-[10px] font-bold ${muted}`}>
                  {lastQuoteSync ? lastQuoteSync.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : 'waiting'}
                </span>
              </div>
              {quote ? (
                <div className="grid grid-cols-3 gap-2">
                  <div className={`rounded-lg px-3 py-2 ${dk ? 'bg-slate-900 border border-white/5' : 'bg-white border border-slate-200'}`}>
                    <p className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Bid</p>
                    <p className="mt-1 font-mono text-sm font-black text-rose-400">{quote.bid.toFixed(priceDigits)}</p>
                  </div>
                  <div className={`rounded-lg px-3 py-2 ${dk ? 'bg-slate-900 border border-white/5' : 'bg-white border border-slate-200'}`}>
                    <p className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Ask</p>
                    <p className="mt-1 font-mono text-sm font-black text-emerald-400">{quote.ask.toFixed(priceDigits)}</p>
                  </div>
                  <div className={`rounded-lg px-3 py-2 ${dk ? 'bg-slate-900 border border-white/5' : 'bg-white border border-slate-200'}`}>
                    <p className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Spread</p>
                    <p className={`mt-1 font-mono text-sm font-black ${strong}`}>{Number(quote.spread ?? 0).toFixed(priceDigits)}</p>
                  </div>
                </div>
              ) : (
                <div className={`text-xs font-bold ${quoteError ? 'text-rose-400' : muted}`}>
                  {quoteLoading ? 'Loading quote...' : (quoteError ?? 'No quote yet')}
                </div>
              )}
            </div>

            <div>
              <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Symbol</label>
              <select value={form.symbol} onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value, price: 0 }))} className={`${input} mt-1.5 appearance-none`}>
                {XM_SYMBOLS.map((symbol) => (
                  <option key={symbol} value={symbol} className={dk ? 'bg-slate-950' : 'bg-white'}>
                    {symbol}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Type</label>
              <div className="mt-1.5 grid grid-cols-2 gap-2">
                {(['MARKET', 'PENDING'] as const).map((kind) => (
                  <button
                    key={kind}
                    onClick={() => {
                      setForm((f) => ({ ...f, orderKind: kind, price: kind === 'MARKET' ? 0 : Number(quote?.bid || quote?.ask || 0) }))
                      setConfirm(false)
                    }}
                    className={`rounded-lg border py-3 text-xs font-black transition-all ${
                      form.orderKind === kind
                        ? dk ? 'bg-blue-500/15 border-blue-500/30 text-blue-300' : 'bg-blue-600 border-blue-600 text-white'
                        : dk ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-900'
                    }`}
                  >
                    {kind === 'MARKET' ? 'Market Execution' : 'Pending Order'}
                  </button>
                ))}
              </div>
            </div>

            {form.orderKind === 'MARKET' ? (
              <div className="grid grid-cols-2 gap-2">
                {(['BUY', 'SELL'] as const).map((side) => {
                  const active = form.side === side
                  return (
                    <button
                      key={side}
                      onClick={() => {
                        setForm((f) => ({ ...f, side }))
                        setConfirm(false)
                      }}
                      className={`flex items-center justify-center gap-2 rounded-lg border py-3 text-sm font-black transition-all ${
                        active
                          ? side === 'BUY'
                            ? 'bg-emerald-500 border-emerald-500 text-white shadow-lg shadow-emerald-500/20'
                            : 'bg-rose-500 border-rose-500 text-white shadow-lg shadow-rose-500/20'
                          : dk
                            ? 'border-white/10 text-slate-400 hover:text-white'
                            : 'border-slate-200 text-slate-500 hover:text-slate-900'
                      }`}
                    >
                      {side === 'BUY' ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                      {side}
                    </button>
                  )
                })}
              </div>
            ) : (
              <div>
                <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Pending Type</label>
                <div className="mt-1.5 grid grid-cols-2 gap-2">
                  {PENDING_TYPES.map((pendingType) => {
                    const active = form.pendingType === pendingType
                    const isBuyType = pendingType.startsWith('BUY')
                    return (
                      <button
                        key={pendingType}
                        onClick={() => {
                          setForm((f) => ({ ...f, pendingType }))
                          setConfirm(false)
                        }}
                        className={`rounded-lg border px-2 py-3 text-[11px] font-black transition-all ${
                          active
                            ? isBuyType ? 'bg-emerald-500 border-emerald-500 text-white' : 'bg-rose-500 border-rose-500 text-white'
                            : dk ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-900'
                        }`}
                      >
                        {pendingType.replace('_', ' ')}
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {form.orderKind === 'PENDING' && (
              <div>
                <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Entry Price</label>
                <input
                  type="number"
                  step={quote?.point || 0.01}
                  value={form.price || ''}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, price: Number(e.target.value) || 0 }))
                    setConfirm(false)
                  }}
                  placeholder="Required for pending orders"
                  className={`${input} mt-1.5 font-mono`}
                />
              </div>
            )}

            <div>
              <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Volume</label>
              <input
                type="number"
                step={quote?.volume_step || 0.01}
                min={quote?.volume_min || 0.01}
                max={quote?.volume_max || 100}
                value={form.volume}
                onChange={(e) => {
                  setForm((f) => ({ ...f, volume: Number(e.target.value) || 0.01 }))
                  setConfirm(false)
                }}
                className={`${input} mt-1.5`}
              />
              <div className="mt-2 grid grid-cols-5 gap-1.5">
                {LOT_PRESETS.map((volume) => (
                  <button
                    key={volume}
                    onClick={() => {
                      setForm((f) => ({ ...f, volume }))
                      setConfirm(false)
                    }}
                    className={`rounded-lg border py-1.5 text-[10px] font-black transition-all ${
                      form.volume === volume
                        ? dk
                          ? 'bg-blue-500/15 border-blue-500/30 text-blue-300'
                          : 'bg-blue-600 border-blue-600 text-white'
                        : dk
                          ? 'border-white/10 text-slate-500 hover:text-slate-300'
                          : 'border-slate-200 text-slate-500 hover:text-slate-900'
                    }`}
                  >
                    {volume}
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Stop Loss</label>
                <input
                  type="number"
                  step={quote?.point || 0.01}
                  value={form.sl || ''}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, sl: Number(e.target.value) || 0 }))
                    setConfirm(false)
                  }}
                  placeholder="Optional"
                  className={`${input} mt-1.5 font-mono`}
                />
              </div>
              <div>
                <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Take Profit</label>
                <input
                  type="number"
                  step={quote?.point || 0.01}
                  value={form.tp || ''}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, tp: Number(e.target.value) || 0 }))
                    setConfirm(false)
                  }}
                  placeholder="Optional"
                  className={`${input} mt-1.5 font-mono`}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Filling Policy</label>
                <select
                  value={form.fillingPolicy}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, fillingPolicy: e.target.value as typeof FILLING_POLICIES[number] }))
                    setConfirm(false)
                  }}
                  className={`${input} mt-1.5 appearance-none`}
                >
                  {FILLING_POLICIES.map((policy) => (
                    <option key={policy} value={policy} className={dk ? 'bg-slate-950' : 'bg-white'}>
                      {policy}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Deviation</label>
                <input
                  type="number"
                  min="0"
                  max="500"
                  step="1"
                  value={form.deviation}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, deviation: Number(e.target.value) || 0 }))
                    setConfirm(false)
                  }}
                  className={`${input} mt-1.5`}
                />
              </div>
            </div>

            <div>
              <label className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Comment</label>
              <div className="relative mt-1.5">
                <MessageSquare className={`pointer-events-none absolute left-3 top-3.5 h-4 w-4 ${muted}`} />
                <input
                  type="text"
                  maxLength={31}
                  value={form.comment}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, comment: e.target.value }))
                    setConfirm(false)
                  }}
                  placeholder="Reason or tag for this order"
                  className={`${input} pl-10`}
                />
              </div>
            </div>

            <div className={`rounded-lg border p-3 ${dk ? 'bg-slate-950/40 border-white/10' : 'bg-slate-50 border-slate-200'}`}>
              <div className="mb-2 flex items-center justify-between">
                <span className={`text-[10px] font-black uppercase tracking-widest ${muted}`}>Ticket Preview</span>
                <span className={`text-xs font-black ${activeOrderType.includes('BUY') ? 'text-emerald-400' : 'text-rose-400'}`}>{activeOrderType.replace('_', ' ')}</span>
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs font-bold">
                <span className={muted}>Symbol</span>
                <span className={`text-right ${strong}`}>{form.symbol}</span>
                <span className={muted}>Type</span>
                <span className={`text-right ${strong}`}>{form.orderKind}</span>
                <span className={muted}>Lots</span>
                <span className={`text-right ${strong}`}>{form.volume}</span>
                <span className={muted}>Entry</span>
                <span className={`text-right font-mono ${strong}`}>{executionPrice ? Number(executionPrice).toFixed(priceDigits) : '-'}</span>
                <span className={muted}>SL / TP</span>
                <span className={`text-right ${strong}`}>{form.sl || '-'} / {form.tp || '-'}</span>
                <span className={muted}>Fill / Dev</span>
                <span className={`text-right ${strong}`}>{form.fillingPolicy} / {form.deviation}</span>
                <span className={muted}>Notional</span>
                <span className={`text-right ${strong}`}>{estimatedNotional ? fmtMoney(estimatedNotional, account?.currency) : '-'}</span>
              </div>
            </div>

            <div className={`flex items-start gap-2 rounded-lg border p-3 text-xs font-bold ${dk ? 'bg-amber-500/5 border-amber-500/15 text-amber-300' : 'bg-amber-50 border-amber-100 text-amber-700'}`}>
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>This sends a live MT5 order. Review quote, type, price, volume, SL/TP, filling policy and comment before confirmation.</span>
            </div>

            {!confirm ? (
              <button
                onClick={() => setConfirm(true)}
                disabled={!canSubmit}
                className={`flex w-full items-center justify-center gap-2 rounded-lg py-3.5 text-sm font-black text-white transition-all disabled:cursor-not-allowed disabled:opacity-40 ${
                  activeOrderType.includes('BUY') ? 'bg-emerald-500 hover:bg-emerald-400 shadow-lg shadow-emerald-500/20' : 'bg-rose-500 hover:bg-rose-400 shadow-lg shadow-rose-500/20'
                }`}
              >
                {activeOrderType.includes('BUY') ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                Place {activeOrderType.replace('_', ' ')} Order
              </button>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={() => setConfirm(false)}
                  className={`rounded-lg border py-3 text-xs font-black transition-all ${dk ? 'border-white/10 text-slate-400 hover:text-white' : 'border-slate-200 text-slate-500 hover:text-slate-900'}`}
                >
                  Cancel
                </button>
                <button
                  onClick={executeTrade}
                  disabled={executing}
                  className={`flex items-center justify-center gap-2 rounded-lg py-3 text-xs font-black text-white transition-all disabled:opacity-50 ${activeOrderType.includes('BUY') ? 'bg-emerald-500 hover:bg-emerald-400' : 'bg-rose-500 hover:bg-rose-400'}`}
                >
                  {executing ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
                  Confirm Live Order
                </button>
              </div>
            )}
          </div>
        </section>

        <section className={`${panel} xl:col-span-7`}>
          <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className={`text-base font-black ${strong}`}>Open Positions</h2>
              <p className={`mt-1 text-xs font-medium ${muted}`}>{positions.length} live position{positions.length === 1 ? '' : 's'}</p>
            </div>
            <div
              className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-black ${
                totalPnl >= 0
                  ? dk
                    ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                    : 'bg-emerald-50 border-emerald-100 text-emerald-700'
                  : dk
                    ? 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                    : 'bg-rose-50 border-rose-100 text-rose-700'
              }`}
            >
              <Layers className="h-3.5 w-3.5" />
              Total P&L {totalPnl >= 0 ? '+' : ''}{fmtNumber(totalPnl, 2)}
            </div>
          </div>

          {positions.length === 0 ? (
            <div className={`flex h-64 flex-col items-center justify-center rounded-lg border border-dashed ${dk ? 'border-white/10 text-slate-600' : 'border-slate-200 text-slate-400'}`}>
              <Layers className="mb-3 h-9 w-9" />
              <p className="text-sm font-black">No open positions</p>
              <p className="mt-1 text-xs font-medium">New fills will appear here after the next MT5 sync.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-left">
                <thead>
                  <tr className={`border-b ${dk ? 'border-white/10' : 'border-slate-200'}`}>
                    {['Side', 'Symbol', 'Volume', 'Open', 'SL', 'TP', 'P&L', 'Comment', ''].map((header) => (
                      <th key={header} className={`px-3 py-3 text-[10px] font-black uppercase tracking-widest ${muted}`}>
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className={dk ? 'divide-y divide-white/5' : 'divide-y divide-slate-100'}>
                  {positions.map((pos) => {
                    const isBuy = pos.type === 0
                    const pnl = Number(pos.profit ?? 0)
                    return (
                      <tr key={pos.ticket} className={dk ? 'hover:bg-white/[0.02]' : 'hover:bg-slate-50'}>
                        <td className="px-3 py-3">
                          <span className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-black ${isBuy ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                            {isBuy ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />}
                            {isBuy ? 'BUY' : 'SELL'}
                          </span>
                        </td>
                        <td className={`px-3 py-3 text-sm font-black ${strong}`}>
                          {pos.symbol}
                          <div className={`text-[10px] font-bold ${muted}`}>#{pos.ticket}</div>
                        </td>
                        <td className={`px-3 py-3 font-mono text-sm ${strong}`}>{pos.volume}</td>
                        <td className={`px-3 py-3 font-mono text-xs ${dk ? 'text-slate-300' : 'text-slate-700'}`}>{fmtNumber(pos.price_open, 5)}</td>
                        <td className={`px-3 py-3 font-mono text-xs ${muted}`}>{pos.sl ? fmtNumber(pos.sl, 5) : '-'}</td>
                        <td className={`px-3 py-3 font-mono text-xs ${muted}`}>{pos.tp ? fmtNumber(pos.tp, 5) : '-'}</td>
                        <td className={`px-3 py-3 font-mono text-sm font-black ${pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {pnl >= 0 ? '+' : ''}{fmtNumber(pnl, 2)}
                        </td>
                        <td className={`max-w-[180px] truncate px-3 py-3 text-xs font-medium ${muted}`} title={pos.comment || ''}>
                          {pos.comment || '-'}
                        </td>
                        <td className="px-3 py-3 text-right">
                          <button
                            onClick={() => closePosition(pos.ticket)}
                            disabled={closingTicket === pos.ticket}
                            className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border transition-all ${
                              dk ? 'border-rose-500/25 text-rose-400 hover:bg-rose-500/10' : 'border-rose-200 text-rose-500 hover:bg-rose-50'
                            } disabled:opacity-50`}
                            title="Close position"
                          >
                            {closingTicket === pos.ticket ? <Loader2 className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className={`${panel} xl:col-span-12`}>
          <div className="grid gap-4 md:grid-cols-4">
            <div className="flex items-center gap-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${dk ? 'bg-slate-950 text-blue-400' : 'bg-blue-50 text-blue-600'}`}>
                <Server className="h-4 w-4" />
              </div>
              <div>
                <p className={`text-xs font-black ${strong}`}>Server</p>
                <p className={`text-xs font-bold ${muted}`}>{account?.server || 'Waiting for MT5'}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${dk ? 'bg-slate-950 text-emerald-400' : 'bg-emerald-50 text-emerald-600'}`}>
                <ShieldCheck className="h-4 w-4" />
              </div>
              <div>
                <p className={`text-xs font-black ${strong}`}>Leverage</p>
                <p className={`text-xs font-bold ${muted}`}>{account?.leverage ? `1:${account.leverage}` : 'Unavailable'}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${dk ? 'bg-slate-950 text-amber-400' : 'bg-amber-50 text-amber-600'}`}>
                <AlertTriangle className="h-4 w-4" />
              </div>
              <div>
                <p className={`text-xs font-black ${strong}`}>Trading Rights</p>
                <p className={`text-xs font-bold ${muted}`}>{account?.trade_allowed ? 'Trading enabled' : 'Trading blocked'}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${dk ? 'bg-slate-950 text-purple-400' : 'bg-purple-50 text-purple-600'}`}>
                <Activity className="h-4 w-4" />
              </div>
              <div>
                <p className={`text-xs font-black ${strong}`}>Execution Mode</p>
                <p className={`text-xs font-bold ${muted}`}>Market and pending orders via MT5 bridge</p>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}
