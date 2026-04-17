import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FlaskConical, Play, TrendingUp, TrendingDown, Percent,
  BarChart2, ShieldAlert, Trophy, Target, Clock, AlertCircle
} from 'lucide-react'

interface BacktestResult {
  status: string
  error?: string
  symbol?: string
  initial_balance: number
  final_balance: number
  net_profit: number
  net_return_pct: number
  cagr_pct: number
  years_tested: number
  total_trades: number
  win_rate_pct: number
  profit_factor: number
  expectancy_pct: number
  avg_win_pct: number
  avg_loss_pct: number
  max_drawdown_pct: number
  sharpe_ratio: number
  wins: number
  losses: number
  exits_sl: number
  exits_tp: number
  exits_time: number
  best_trade_pct: number
  worst_trade_pct: number
  regime_breakdown: Record<string, number>
  asset_class?: string
}

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']
const UNIVERSES  = ['CRYPTO', 'STOCK', 'MACRO']

function StatCard({
  label, value, sub, color = 'slate', icon: Icon
}: {
  label: string; value: string; sub?: string
  color?: 'green' | 'red' | 'blue' | 'amber' | 'slate'; icon: React.FC<any>
}) {
  const colors = {
    green: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
    red:   'text-rose-400   bg-rose-500/10    border-rose-500/20',
    blue:  'text-blue-400   bg-blue-500/10    border-blue-500/20',
    amber: 'text-amber-400  bg-amber-500/10   border-amber-500/20',
    slate: 'text-slate-300  bg-white/5        border-white/10',
  }
  return (
    <div className={`rounded-xl border p-4 ${colors[color]} flex flex-col gap-1`}>
      <div className="flex items-center gap-2 mb-1">
        <Icon className="w-4 h-4 opacity-70" />
        <span className="text-[10px] font-black uppercase tracking-widest opacity-60">{label}</span>
      </div>
      <span className="text-2xl font-black tabular-nums leading-none">{value}</span>
      {sub && <span className="text-[10px] opacity-50 font-bold">{sub}</span>}
    </div>
  )
}

export function BacktesterView() {
  const [symbol,    setSymbol]    = useState('BTC')
  const [timeframe, setTimeframe] = useState('15m')
  const [limit,     setLimit]     = useState(500)
  const [riskPct,   setRiskPct]   = useState(2.0)
  const [leverage,  setLeverage]  = useState(1.0)
  const [assetClass,setAssetClass]= useState('CRYPTO')
  const [loading,   setLoading]   = useState(false)
  const [result,    setResult]    = useState<BacktestResult | null>(null)
  const [error,     setError]     = useState('')

  const run = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const params = new URLSearchParams({
        symbol, timeframe,
        limit:      String(limit),
        risk_pct:   String(riskPct),
        leverage:   String(leverage),
        asset_class: assetClass,
      })
      const res = await fetch(`/api/backtest?${params}`, {
        headers: { 'X-API-Key': 'demo' }
      })
      const data: BacktestResult = await res.json()
      if (data.error) { setError(data.error); return }
      if (data.status === 'no_trades') { setError('No trades generated — try a longer limit or different timeframe.'); return }
      setResult(data)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const profitable = result ? result.net_profit >= 0 : true

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[#060b14]/50 p-4 md:p-6 gap-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-violet-500/15 border border-violet-500/20 flex items-center justify-center">
          <FlaskConical className="w-5 h-5 text-violet-400" />
        </div>
        <div>
          <h1 className="text-sm font-black text-white uppercase tracking-widest">Strategy Backtester</h1>
          <p className="text-[10px] text-slate-500 font-bold">Historical signal simulation — crypto & macro</p>
        </div>
      </div>

      {/* Disclaimer Banner */}
      <div className="flex items-start gap-3 p-4 bg-amber-500/5 border border-amber-500/20 rounded-2xl">
        <AlertCircle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
        <div>
          <p className="text-xs font-black text-amber-400 uppercase tracking-widest mb-1">Past Performance Disclaimer</p>
          <p className="text-sm text-slate-400">ผลลัพธ์จากการ backtest เป็นข้อมูลในอดีตเท่านั้น — <span className="text-amber-300 font-bold">ไม่ใช่การรับประกันผลลัพธ์ในอนาคต</span> ใช้เพื่อศึกษาและทดสอบกลยุทธ์เท่านั้น ไม่ใช่คำแนะนำการลงทุน</p>
        </div>
      </div>

      {/* Config Panel */}
      <div className="bg-slate-900/60 border border-white/5 rounded-2xl p-5 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {/* Symbol */}
        <div className="flex flex-col gap-1.5 col-span-2 md:col-span-1">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Symbol</label>
          <input
            value={symbol}
            onChange={e => setSymbol(e.target.value.toUpperCase())}
            className="bg-slate-800 border border-white/10 rounded-xl px-3 py-2 text-sm font-black text-white focus:outline-none focus:ring-1 focus:ring-violet-500/50 uppercase"
            placeholder="BTC"
          />
        </div>

        {/* Asset Class */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Universe</label>
          <select
            value={assetClass}
            onChange={e => setAssetClass(e.target.value)}
            className="bg-slate-800 border border-white/10 rounded-xl px-3 py-2 text-xs font-black text-white focus:outline-none focus:ring-1 focus:ring-violet-500/50"
          >
            {UNIVERSES.map(u => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>

        {/* Timeframe */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Timeframe</label>
          <select
            value={timeframe}
            onChange={e => setTimeframe(e.target.value)}
            className="bg-slate-800 border border-white/10 rounded-xl px-3 py-2 text-xs font-black text-white focus:outline-none focus:ring-1 focus:ring-violet-500/50"
          >
            {TIMEFRAMES.map(tf => <option key={tf} value={tf}>{tf}</option>)}
          </select>
        </div>

        {/* Candles */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Candles <span className="text-violet-400">{limit}</span>
          </label>
          <input type="range" min={100} max={1000} step={50} value={limit}
            onChange={e => setLimit(Number(e.target.value))}
            className="accent-violet-500 mt-2"
          />
        </div>

        {/* Risk */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Risk/Trade <span className="text-violet-400">{riskPct}%</span>
          </label>
          <input type="range" min={0.5} max={5} step={0.5} value={riskPct}
            onChange={e => setRiskPct(Number(e.target.value))}
            className="accent-violet-500 mt-2"
          />
        </div>

        {/* Leverage */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Leverage <span className="text-violet-400">{leverage}x</span>
          </label>
          <input type="range" min={1} max={10} step={0.5} value={leverage}
            onChange={e => setLeverage(Number(e.target.value))}
            className="accent-violet-500 mt-2"
          />
        </div>
      </div>

      {/* Run Button */}
      <button
        onClick={run}
        disabled={loading}
        className="self-start flex items-center gap-2.5 px-6 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-black text-xs uppercase tracking-widest transition-all active:scale-95 shadow-lg shadow-violet-500/20"
      >
        {loading
          ? <><span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> Running…</>
          : <><Play className="w-4 h-4" /> Run Backtest</>
        }
      </button>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs font-bold">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      {/* Results */}
      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex flex-col gap-6"
          >
            {/* Summary Banner */}
            <div className={`rounded-2xl border p-5 flex flex-wrap gap-4 items-center justify-between ${profitable ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-rose-500/5 border-rose-500/20'}`}>
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">
                  {result.symbol ?? symbol} · {timeframe} · {result.years_tested}y tested
                </p>
                <p className={`text-3xl font-black tabular-nums ${profitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {profitable ? '+' : ''}{result.net_return_pct}%
                </p>
                <p className="text-xs font-bold text-slate-400">
                  ${result.initial_balance.toLocaleString()} → ${result.final_balance.toLocaleString()} &nbsp;|&nbsp;
                  Net P&L: {profitable ? '+' : ''}${result.net_profit.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                </p>
              </div>
              <div className={`text-4xl font-black ${profitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                {profitable ? '▲' : '▼'}
              </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <StatCard icon={Trophy}     label="Win Rate"       value={`${result.win_rate_pct}%`}       sub={`${result.wins}W / ${result.losses}L`}                     color={result.win_rate_pct >= 50 ? 'green' : 'red'} />
              <StatCard icon={BarChart2}  label="Profit Factor"  value={String(result.profit_factor)}     sub="gross win / gross loss"                                    color={result.profit_factor >= 1.5 ? 'green' : result.profit_factor >= 1 ? 'amber' : 'red'} />
              <StatCard icon={TrendingUp} label="Sharpe Ratio"   value={String(result.sharpe_ratio)}      sub="risk-adjusted return"                                      color={result.sharpe_ratio >= 1 ? 'green' : result.sharpe_ratio >= 0 ? 'amber' : 'red'} />
              <StatCard icon={Percent}    label="CAGR"           value={`${result.cagr_pct}%`}            sub="annual compounded return"                                  color={result.cagr_pct >= 0 ? 'green' : 'red'} />
              <StatCard icon={ShieldAlert}label="Max Drawdown"   value={`-${result.max_drawdown_pct}%`}  sub="peak-to-trough loss"                                       color={result.max_drawdown_pct <= 10 ? 'green' : result.max_drawdown_pct <= 25 ? 'amber' : 'red'} />
              <StatCard icon={Target}     label="Expectancy"     value={`${result.expectancy_pct}%`}      sub="avg expected return/trade"                                 color={result.expectancy_pct >= 0 ? 'green' : 'red'} />
              <StatCard icon={TrendingUp} label="Avg Win"        value={`+${result.avg_win_pct}%`}        sub="avg profit per winning trade"                              color="green" />
              <StatCard icon={TrendingDown}label="Avg Loss"      value={`-${Math.abs(result.avg_loss_pct)}%`} sub="avg loss per losing trade"                            color="red" />
            </div>

            {/* Exit Breakdown + Best/Worst */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Exit reasons */}
              <div className="bg-slate-900/60 border border-white/5 rounded-2xl p-5">
                <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-4 flex items-center gap-2">
                  <Clock className="w-3.5 h-3.5" /> Exit Breakdown
                </h3>
                <div className="space-y-3">
                  {[
                    { label: 'Stop Loss',   count: result.exits_sl,   color: 'bg-rose-500'   },
                    { label: 'Take Profit', count: result.exits_tp,   color: 'bg-emerald-500'},
                    { label: 'Time Exit',   count: result.exits_time, color: 'bg-amber-500'  },
                  ].map(({ label, count, color }) => {
                    const pct = result.total_trades > 0 ? (count / result.total_trades) * 100 : 0
                    return (
                      <div key={label}>
                        <div className="flex justify-between text-[10px] font-black uppercase tracking-widest text-slate-400 mb-1">
                          <span>{label}</span><span>{count} ({pct.toFixed(0)}%)</span>
                        </div>
                        <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
                          <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Best / worst + regime */}
              <div className="bg-slate-900/60 border border-white/5 rounded-2xl p-5">
                <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-4">Trade Extremes & Regime</h3>
                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3">
                    <p className="text-[9px] font-black uppercase tracking-widest text-emerald-400/60">Best Trade</p>
                    <p className="text-xl font-black text-emerald-400">+{result.best_trade_pct}%</p>
                  </div>
                  <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-3">
                    <p className="text-[9px] font-black uppercase tracking-widest text-rose-400/60">Worst Trade</p>
                    <p className="text-xl font-black text-rose-400">{result.worst_trade_pct}%</p>
                  </div>
                </div>
                {Object.keys(result.regime_breakdown ?? {}).length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[9px] font-black uppercase tracking-widest text-slate-600 mb-2">Market Regime</p>
                    {Object.entries(result.regime_breakdown).map(([regime, count]) => (
                      <div key={regime} className="flex justify-between text-[10px] font-bold text-slate-400">
                        <span>{regime}</span>
                        <span className="text-slate-300 font-black">{count} trades</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {!result && !loading && !error && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 text-slate-600 py-16">
          <FlaskConical className="w-12 h-12 opacity-20" />
          <p className="text-sm font-black uppercase tracking-widest">Configure params and run backtest</p>
        </div>
      )}
    </div>
  )
}
