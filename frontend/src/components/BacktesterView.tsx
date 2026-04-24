import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  FlaskConical,
  Play,
  TrendingUp,
  TrendingDown,
  Percent,
  BarChart2,
  ShieldAlert,
  Trophy,
  Target,
  Clock,
  AlertCircle,
} from 'lucide-react'
import { useMode } from '../contexts/ModeContext'

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

interface MlStatsResponse {
  is_training: boolean
  model_exists: boolean
  focus?: {
    core_symbols?: string[]
    targets?: {
      paper_labels?: number
      training_samples?: number
      core_symbols?: number
    }
  }
  model: {
    trained?: boolean
    n_samples?: number | null
    train_size?: number | null
    test_size?: number | null
    split_method?: string | null
    accuracy?: number | null
    roc_auc?: number | null
    win_rate_train?: number | null
    win_rate_test?: number | null
    trained_at?: string | null
    outcomes_at_retrain?: number | null
    dataset_quality?: {
      symbols?: number
      timeframes?: string[]
      win_rate_full?: number
    } | null
    dataset_report?: Array<{
      symbol: string
      timeframe: string
      samples: number
      wins: number
      losses: number
      win_rate: number
    }> | null
    slice_pruning?: {
      available?: boolean
      pruned_count?: number
      pruned?: Array<{
        symbol: string
        timeframe: string
        samples: number
        wins: number
        losses: number
        win_rate: number
        reason?: string
      }>
    } | null
    calibration?: {
      available?: boolean
      method?: string
      brier_score?: number
      ece?: number
    } | null
    sufficiency?: {
      ready_for_improvement?: boolean
      progress?: {
        paper_labels?: number
        training_samples?: number
        core_symbols?: number
        overall?: number
      }
      current?: {
        paper_labels?: number
        training_samples?: number
        core_symbols_covered?: number
      }
      targets?: {
        paper_labels?: number
        training_samples?: number
        core_symbols?: number
      }
      core_symbols?: {
        covered?: string[]
        missing?: string[]
      }
    } | null
    walk_forward?: {
      available?: boolean
      summary?: {
        fold_count?: number
        avg_accuracy?: number
        avg_roc_auc?: number
        min_roc_auc?: number
        max_roc_auc?: number
      } | null
      folds?: Array<{
        train_size: number
        test_size: number
        accuracy: number
        roc_auc: number
        win_rate_test: number
      }>
    } | null
  }
  paper_trades: {
    total_labeled?: number
    wins?: number
    losses?: number
    win_rate?: number
  }
}

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d']
const UNIVERSES = ['CRYPTO', 'STOCK', 'MACRO']

const num = (value: unknown, fallback = 0) => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

const fmt = (value: unknown, digits = 0) =>
  num(value).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })

const fmtPct = (value: unknown, digits = 2) => `${fmt(value, digits)}%`

const hasUsableBacktestResult = (value: BacktestResult) => {
  const totalTrades = num(value.total_trades)
  const initialBalance = num(value.initial_balance)
  const finalBalance = num(value.final_balance)

  return totalTrades > 0 && initialBalance > 0 && finalBalance > 0
}

function StatCard({
  label,
  value,
  sub,
  color = 'slate',
  icon: Icon,
  theme,
}: {
  label: string
  value: string
  sub?: string
  color?: 'green' | 'red' | 'blue' | 'amber' | 'slate'
  icon: React.FC<any>
  theme: 'light' | 'dark'
}) {
  const dk = theme === 'dark'
  const colors = dk
    ? {
        green: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
        red: 'text-rose-400 bg-rose-500/10 border-rose-500/20',
        blue: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
        amber: 'text-amber-400 bg-amber-500/10 border-amber-500/20',
        slate: 'text-slate-300 bg-white/5 border-white/10',
      }
    : {
        green: 'text-emerald-700 bg-emerald-50 border-emerald-200 shadow-sm',
        red: 'text-rose-700 bg-rose-50 border-rose-200 shadow-sm',
        blue: 'text-blue-700 bg-blue-50 border-blue-200 shadow-sm',
        amber: 'text-amber-700 bg-amber-50 border-amber-200 shadow-sm',
        slate: 'text-slate-700 bg-white border-slate-200 shadow-sm',
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
  const { theme } = useMode()
  const dk = theme === 'dark'
  const [symbol, setSymbol] = useState('BTC')
  const [timeframe, setTimeframe] = useState('15m')
  const [limit, setLimit] = useState(500)
  const [riskPct, setRiskPct] = useState(2.0)
  const [leverage, setLeverage] = useState(1.0)
  const [assetClass, setAssetClass] = useState('CRYPTO')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [error, setError] = useState('')
  const [mlStats, setMlStats] = useState<MlStatsResponse | null>(null)
  const [mlLoading, setMlLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    const loadMlStats = async () => {
      setMlLoading(true)
      try {
        const res = await fetch('/api/ml/stats', {
          headers: { 'X-API-Key': 'demo' },
        })
        const data: MlStatsResponse = await res.json()
        if (!cancelled) {
          setMlStats(data)
        }
      } catch {
        if (!cancelled) {
          setMlStats(null)
        }
      } finally {
        if (!cancelled) {
          setMlLoading(false)
        }
      }
    }

    loadMlStats()
    return () => {
      cancelled = true
    }
  }, [])

  const run = async () => {
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const params = new URLSearchParams({
        symbol,
        timeframe,
        limit: String(limit),
        risk_pct: String(riskPct),
        leverage: String(leverage),
        asset_class: assetClass,
      })
      const res = await fetch(`/api/backtest?${params}`, {
        headers: { 'X-API-Key': 'demo' },
      })
      const data: BacktestResult = await res.json()
      if (data.error) {
        setError(data.error)
        return
      }
      if (data.status === 'no_trades') {
        setError('No trades generated - try a longer limit or different timeframe.')
        return
      }
      if (!hasUsableBacktestResult(data)) {
        setError('No usable backtest result returned by the backend. Try a longer limit, another timeframe, or check the API response.')
        return
      }
      setResult(data)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  const profitable = result ? result.net_profit >= 0 : true
  const testedYears = num(result?.years_tested, 0)
  const testedYearsLabel = testedYears > 0 ? testedYears.toFixed(2) : '<0.01'
  const initialBalance = num(result?.initial_balance)
  const finalBalance = num(result?.final_balance)
  const netProfit = num(result?.net_profit)
  const netReturnPct = num(result?.net_return_pct, 0)
  const winRatePct = num(result?.win_rate_pct)
  const profitFactor = num(result?.profit_factor)
  const sharpeRatio = num(result?.sharpe_ratio)
  const cagrPct = num(result?.cagr_pct)
  const maxDrawdownPct = num(result?.max_drawdown_pct)
  const expectancyPct = num(result?.expectancy_pct)
  const avgWinPct = num(result?.avg_win_pct)
  const avgLossPct = num(result?.avg_loss_pct)
  const wins = num(result?.wins)
  const losses = num(result?.losses)
  const totalTrades = num(result?.total_trades)
  const exitsSl = num(result?.exits_sl)
  const exitsTp = num(result?.exits_tp)
  const exitsTime = num(result?.exits_time)
  const bestTradePct = num(result?.best_trade_pct)
  const worstTradePct = num(result?.worst_trade_pct)
  const auc = num(mlStats?.model?.roc_auc)
  const accuracy = num(mlStats?.model?.accuracy)
  const trainSize = num(mlStats?.model?.train_size)
  const testSize = num(mlStats?.model?.test_size)
  const trainingSamples = num(mlStats?.model?.n_samples)
  const paperLabels = num(mlStats?.paper_trades?.total_labeled)
  const paperWinRate = num(mlStats?.paper_trades?.win_rate)
  const splitMethod = mlStats?.model?.split_method || 'legacy'
  const trainedAt = mlStats?.model?.trained_at
  const weakAuc = mlStats?.model?.roc_auc != null && auc < 0.6
  const lowPaperLabels = paperLabels < 100
  const datasetSymbols = num(mlStats?.model?.dataset_quality?.symbols)
  const datasetTimeframes = mlStats?.model?.dataset_quality?.timeframes ?? []
  const datasetWinRate = num(mlStats?.model?.dataset_quality?.win_rate_full)
  const walkForwardSummary = mlStats?.model?.walk_forward?.summary
  const walkForwardAuc = num(walkForwardSummary?.avg_roc_auc)
  const walkForwardAcc = num(walkForwardSummary?.avg_accuracy)
  const walkForwardFolds = num(walkForwardSummary?.fold_count)
  const datasetReport = (mlStats?.model?.dataset_report ?? []).slice(0, 6)
  const prunedSlices = num(mlStats?.model?.slice_pruning?.pruned_count)
  const calibrationEce = num(mlStats?.model?.calibration?.ece)
  const calibrationBrier = num(mlStats?.model?.calibration?.brier_score)
  const sufficiency = mlStats?.model?.sufficiency
  const sufficiencyOverall = num(sufficiency?.progress?.overall)
  const sufficiencyReady = Boolean(sufficiency?.ready_for_improvement)
  const sufficiencyTargets = sufficiency?.targets ?? mlStats?.focus?.targets
  const coreCovered = sufficiency?.core_symbols?.covered ?? []
  const coreMissing = sufficiency?.core_symbols?.missing ?? []

  return (
    <div
      className={`flex flex-col h-full overflow-y-auto p-4 md:p-6 gap-6 transition-colors duration-500 ${
        dk ? 'bg-[#060b14]/50' : 'bg-slate-50'
      }`}
    >
      <div className="flex items-center gap-3">
        <div
          className={`w-9 h-9 rounded-xl border flex items-center justify-center ${
            dk ? 'bg-violet-500/15 border-violet-500/20' : 'bg-violet-50 border-violet-200'
          }`}
        >
          <FlaskConical className={`w-5 h-5 ${dk ? 'text-violet-400' : 'text-violet-600'}`} />
        </div>
        <div>
          <h1 className={`text-sm font-black uppercase tracking-widest ${dk ? 'text-white' : 'text-slate-900'}`}>
            Strategy Backtester
          </h1>
          <p className={`text-[10px] font-bold ${dk ? 'text-slate-500' : 'text-slate-500'}`}>
            Historical signal simulation - crypto and macro
          </p>
        </div>
      </div>

      <div
        className={`flex items-start gap-3 p-4 border rounded-2xl ${
          dk ? 'bg-amber-500/5 border-amber-500/20' : 'bg-amber-50 border-amber-200'
        }`}
      >
        <AlertCircle className={`w-4 h-4 mt-0.5 shrink-0 ${dk ? 'text-amber-400' : 'text-amber-600'}`} />
        <div>
          <p className={`text-xs font-black uppercase tracking-widest mb-1 ${dk ? 'text-amber-400' : 'text-amber-700'}`}>
            Past Performance Disclaimer
          </p>
          <p className={`text-sm ${dk ? 'text-slate-400' : 'text-slate-600'}`}>
            ผลลัพธ์จากการ backtest เป็นข้อมูลในอดีตเท่านั้น{' '}
            <span className={`font-bold ${dk ? 'text-amber-300' : 'text-amber-700'}`}>
              ไม่ใช่การรับประกันผลลัพธ์ในอนาคต
            </span>{' '}
            ใช้เพื่อศึกษาและทดสอบกลยุทธ์เท่านั้น ไม่ใช่คำแนะนำการลงทุน
          </p>
        </div>
      </div>

      <div
        className={`rounded-2xl border p-5 transition-colors duration-500 ${
          dk ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
        }`}
      >
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <div>
            <p className={`text-xs font-black uppercase tracking-widest ${dk ? 'text-white' : 'text-slate-900'}`}>
              ML Health
            </p>
            <p className={`text-[11px] font-bold ${dk ? 'text-slate-500' : 'text-slate-500'}`}>
              Training quality, sample size, and live label coverage
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {mlStats?.is_training && (
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${dk ? 'bg-blue-500/10 text-blue-300 border border-blue-500/20' : 'bg-blue-50 text-blue-700 border border-blue-200'}`}>
                Training
              </span>
            )}
            {weakAuc && (
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${dk ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}>
                Weak AUC
              </span>
            )}
            {lowPaperLabels && (
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${dk ? 'bg-rose-500/10 text-rose-300 border border-rose-500/20' : 'bg-rose-50 text-rose-700 border border-rose-200'}`}>
                Few Live Labels
              </span>
            )}
          </div>
        </div>

        {mlLoading ? (
          <div className={`text-sm font-bold ${dk ? 'text-slate-500' : 'text-slate-500'}`}>Loading ML stats...</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <StatCard icon={BarChart2} label="Samples" value={fmt(trainingSamples)} sub={`${fmt(trainSize)} train / ${fmt(testSize)} test`} color={trainingSamples >= 10000 ? 'green' : trainingSamples >= 1000 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={TrendingUp} label="ROC AUC" value={auc ? auc.toFixed(3) : '0.000'} sub="ranking quality" color={auc >= 0.65 ? 'green' : auc >= 0.55 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Target} label="Accuracy" value={fmtPct(accuracy * 100, 1)} sub="holdout accuracy" color={accuracy >= 0.65 ? 'green' : accuracy >= 0.55 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={ShieldAlert} label="Paper Labels" value={fmt(paperLabels)} sub={`win rate ${fmtPct(paperWinRate * 100, 1)}`} color={paperLabels >= 100 ? 'green' : paperLabels >= 20 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Clock} label="Split" value={splitMethod === 'time_ordered_holdout_75_25' ? 'Time 75/25' : 'Legacy'} sub="evaluation method" color={splitMethod === 'time_ordered_holdout_75_25' ? 'green' : 'amber'} theme={theme} />
              <StatCard icon={Percent} label="Train/Test Win" value={`${fmtPct(num(mlStats?.model?.win_rate_train) * 100, 1)} / ${fmtPct(num(mlStats?.model?.win_rate_test) * 100, 1)}`} sub="class balance drift" color="slate" theme={theme} />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
              <StatCard icon={BarChart2} label="Dataset Symbols" value={fmt(datasetSymbols)} sub={datasetTimeframes.join(', ') || 'n/a'} color={datasetSymbols >= 10 ? 'green' : datasetSymbols >= 5 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={TrendingUp} label="WF AUC" value={walkForwardAuc ? walkForwardAuc.toFixed(3) : '0.000'} sub={`${fmt(walkForwardFolds)} folds`} color={walkForwardAuc >= 0.65 ? 'green' : walkForwardAuc >= 0.55 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Target} label="WF Accuracy" value={fmtPct(walkForwardAcc * 100, 1)} sub="expanding window" color={walkForwardAcc >= 0.65 ? 'green' : walkForwardAcc >= 0.55 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Percent} label="Dataset Win Rate" value={fmtPct(datasetWinRate * 100, 1)} sub="full labeled set" color="slate" theme={theme} />
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-4">
              <StatCard icon={ShieldAlert} label="Pruned Slices" value={fmt(prunedSlices)} sub="weak slices removed" color={prunedSlices > 0 ? 'amber' : 'green'} theme={theme} />
              <StatCard icon={Target} label="Calibration ECE" value={calibrationEce ? calibrationEce.toFixed(3) : '0.000'} sub="lower is better" color={calibrationEce <= 0.08 ? 'green' : calibrationEce <= 0.15 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={BarChart2} label="Brier Score" value={calibrationBrier ? calibrationBrier.toFixed(3) : '0.000'} sub="lower is better" color={calibrationBrier <= 0.2 ? 'green' : calibrationBrier <= 0.3 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Clock} label="Calibration" value={mlStats?.model?.calibration?.available ? 'Enabled' : 'Off'} sub={mlStats?.model?.calibration?.method || 'n/a'} color={mlStats?.model?.calibration?.available ? 'green' : 'amber'} theme={theme} />
            </div>

            <div className={`mt-4 rounded-xl border p-4 ${dk ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'}`}>
              <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
                <p className={`text-[10px] font-black uppercase tracking-widest ${dk ? 'text-slate-300' : 'text-slate-800'}`}>
                  Data Sufficiency Mode
                </p>
                <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${
                  sufficiencyReady
                    ? dk ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20' : 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                    : dk ? 'bg-amber-500/10 text-amber-300 border border-amber-500/20' : 'bg-amber-50 text-amber-700 border border-amber-200'
                }`}>
                  {sufficiencyReady ? 'Ready' : 'Collecting'}
                </span>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <StatCard icon={Percent} label="Overall Progress" value={fmtPct(sufficiencyOverall * 100, 0)} sub="toward minimum sufficient data" color={sufficiencyOverall >= 1 ? 'green' : sufficiencyOverall >= 0.66 ? 'amber' : 'red'} theme={theme} />
                <StatCard icon={ShieldAlert} label="Paper Labels" value={`${fmt(num(sufficiency?.current?.paper_labels))} / ${fmt(num(sufficiencyTargets?.paper_labels))}`} sub="closed labeled trades" color={num(sufficiency?.progress?.paper_labels) >= 1 ? 'green' : 'amber'} theme={theme} />
                <StatCard icon={BarChart2} label="Train Samples" value={`${fmt(num(sufficiency?.current?.training_samples))} / ${fmt(num(sufficiencyTargets?.training_samples))}`} sub="usable filtered rows" color={num(sufficiency?.progress?.training_samples) >= 1 ? 'green' : 'amber'} theme={theme} />
                <StatCard icon={Target} label="Core Symbols" value={`${fmt(num(sufficiency?.current?.core_symbols_covered))} / ${fmt(num(sufficiencyTargets?.core_symbols))}`} sub="focus universe coverage" color={num(sufficiency?.progress?.core_symbols) >= 1 ? 'green' : 'amber'} theme={theme} />
              </div>
              <div className={`mt-3 text-xs font-bold ${dk ? 'text-slate-400' : 'text-slate-600'}`}>
                <span className={dk ? 'text-slate-300' : 'text-slate-800'}>Covered:</span> {coreCovered.join(', ') || 'none'}
                {' · '}
                <span className={dk ? 'text-slate-300' : 'text-slate-800'}>Missing:</span> {coreMissing.join(', ') || 'none'}
              </div>
            </div>

            {datasetReport.length > 0 && (
              <div className={`mt-4 rounded-xl border p-4 ${dk ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'}`}>
                <p className={`text-[10px] font-black uppercase tracking-widest mb-3 ${dk ? 'text-slate-300' : 'text-slate-800'}`}>
                  Best Dataset Coverage
                </p>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {datasetReport.map((row) => (
                    <div key={`${row.symbol}-${row.timeframe}`} className={`rounded-xl border p-3 ${dk ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200'}`}>
                      <div className="flex items-center justify-between gap-2">
                        <span className={`text-xs font-black ${dk ? 'text-white' : 'text-slate-900'}`}>{row.symbol}</span>
                        <span className={`text-[10px] font-black uppercase tracking-widest ${dk ? 'text-violet-300' : 'text-violet-700'}`}>{row.timeframe}</span>
                      </div>
                      <div className={`mt-2 text-[11px] font-bold ${dk ? 'text-slate-400' : 'text-slate-600'}`}>
                        {fmt(row.samples)} samples · {fmtPct(row.win_rate * 100, 1)} win rate
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className={`mt-4 rounded-xl border p-4 text-xs font-bold ${dk ? 'bg-white/5 border-white/10 text-slate-400' : 'bg-slate-50 border-slate-200 text-slate-600'}`}>
              <span className={dk ? 'text-slate-300' : 'text-slate-800'}>Last trained:</span> {trainedAt ? new Date(trainedAt).toLocaleString() : 'unknown'}
              {' · '}
              <span className={dk ? 'text-slate-300' : 'text-slate-800'}>Why this matters:</span> plenty of samples helps, but low AUC or too few paper-trade labels means the model can still be fragile in real market conditions.
            </div>
          </>
        )}
      </div>

      <div
        className={`rounded-2xl p-5 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 border transition-colors duration-500 ${
          dk ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
        }`}
      >
        <div className="flex flex-col gap-1.5 col-span-2 md:col-span-1">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Symbol</label>
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            className={`rounded-xl px-3 py-2 text-sm font-black focus:outline-none focus:ring-1 focus:ring-violet-500/50 uppercase transition-colors ${
              dk ? 'bg-slate-800 border border-white/10 text-white' : 'bg-slate-50 border border-slate-200 text-slate-900'
            }`}
            placeholder="BTC"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Universe</label>
          <select
            value={assetClass}
            onChange={(e) => setAssetClass(e.target.value)}
            className={`rounded-xl px-3 py-2 text-xs font-black focus:outline-none focus:ring-1 focus:ring-violet-500/50 transition-colors ${
              dk ? 'bg-slate-800 border border-white/10 text-white' : 'bg-slate-50 border border-slate-200 text-slate-900'
            }`}
          >
            {UNIVERSES.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">Timeframe</label>
          <select
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value)}
            className={`rounded-xl px-3 py-2 text-xs font-black focus:outline-none focus:ring-1 focus:ring-violet-500/50 transition-colors ${
              dk ? 'bg-slate-800 border border-white/10 text-white' : 'bg-slate-50 border border-slate-200 text-slate-900'
            }`}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Candles <span className={dk ? 'text-violet-400' : 'text-violet-600'}>{limit}</span>
          </label>
          <input
            type="range"
            min={100}
            max={1000}
            step={50}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="accent-violet-500 mt-2"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Risk/Trade <span className={dk ? 'text-violet-400' : 'text-violet-600'}>{riskPct}%</span>
          </label>
          <input
            type="range"
            min={0.5}
            max={5}
            step={0.5}
            value={riskPct}
            onChange={(e) => setRiskPct(Number(e.target.value))}
            className="accent-violet-500 mt-2"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <label className="text-[10px] font-black uppercase tracking-widest text-slate-500">
            Leverage <span className={dk ? 'text-violet-400' : 'text-violet-600'}>{leverage}x</span>
          </label>
          <input
            type="range"
            min={1}
            max={10}
            step={0.5}
            value={leverage}
            onChange={(e) => setLeverage(Number(e.target.value))}
            className="accent-violet-500 mt-2"
          />
        </div>
      </div>

      <button
        onClick={run}
        disabled={loading}
        className="self-start flex items-center gap-2.5 px-6 py-3 rounded-xl bg-violet-600 hover:bg-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-black text-xs uppercase tracking-widest transition-all active:scale-95 shadow-lg shadow-violet-500/20"
      >
        {loading ? (
          <>
            <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Running...
          </>
        ) : (
          <>
            <Play className="w-4 h-4" /> Run Backtest
          </>
        )}
      </button>

      {error && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 text-xs font-bold">
          <AlertCircle className="w-4 h-4 shrink-0" />
          {error}
        </div>
      )}

      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex flex-col gap-6"
          >
            <div
              className={`rounded-2xl border p-5 flex flex-wrap gap-4 items-center justify-between ${
                profitable
                  ? dk
                    ? 'bg-emerald-500/5 border-emerald-500/20'
                    : 'bg-emerald-50 border-emerald-200'
                  : dk
                    ? 'bg-rose-500/5 border-rose-500/20'
                    : 'bg-rose-50 border-rose-200'
              }`}
            >
              <div>
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">
                  {result.symbol ?? symbol} · {timeframe} · {testedYearsLabel}y tested
                </p>
                <p className={`text-3xl font-black tabular-nums ${profitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {profitable ? '+' : ''}
                  {netReturnPct}%
                </p>
                <p className={`text-xs font-bold ${dk ? 'text-slate-400' : 'text-slate-600'}`}>
                  ${fmt(initialBalance)} {'->'} ${fmt(finalBalance)} &nbsp;|&nbsp;
                  Net P&amp;L: {profitable ? '+' : ''}
                  ${fmt(netProfit)}
                </p>
              </div>
              <div className={`text-4xl font-black ${profitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                {profitable ? '▲' : '▼'}
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              <StatCard icon={Trophy} label="Win Rate" value={`${winRatePct}%`} sub={`${wins}W / ${losses}L`} color={winRatePct >= 50 ? 'green' : 'red'} theme={theme} />
              <StatCard icon={BarChart2} label="Profit Factor" value={String(profitFactor)} sub="gross win / gross loss" color={profitFactor >= 1.5 ? 'green' : profitFactor >= 1 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={TrendingUp} label="Sharpe Ratio" value={String(sharpeRatio)} sub="risk-adjusted return" color={sharpeRatio >= 1 ? 'green' : sharpeRatio >= 0 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Percent} label="CAGR" value={`${cagrPct}%`} sub="annual compounded return" color={cagrPct >= 0 ? 'green' : 'red'} theme={theme} />
              <StatCard icon={ShieldAlert} label="Max Drawdown" value={`-${maxDrawdownPct}%`} sub="peak-to-trough loss" color={maxDrawdownPct <= 10 ? 'green' : maxDrawdownPct <= 25 ? 'amber' : 'red'} theme={theme} />
              <StatCard icon={Target} label="Expectancy" value={`${expectancyPct}%`} sub="avg expected return/trade" color={expectancyPct >= 0 ? 'green' : 'red'} theme={theme} />
              <StatCard icon={TrendingUp} label="Avg Win" value={`+${avgWinPct}%`} sub="avg profit per winning trade" color="green" theme={theme} />
              <StatCard icon={TrendingDown} label="Avg Loss" value={`-${Math.abs(avgLossPct)}%`} sub="avg loss per losing trade" color="red" theme={theme} />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div
                className={`rounded-2xl p-5 border transition-colors duration-500 ${
                  dk ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
                }`}
              >
                <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-4 flex items-center gap-2">
                  <Clock className="w-3.5 h-3.5" /> Exit Breakdown
                </h3>
                <div className="space-y-3">
                  {[
                    { label: 'Stop Loss', count: exitsSl, color: 'bg-rose-500' },
                    { label: 'Take Profit', count: exitsTp, color: 'bg-emerald-500' },
                    { label: 'Time Exit', count: exitsTime, color: 'bg-amber-500' },
                  ].map(({ label, count, color }) => {
                    const pct = totalTrades > 0 ? (count / totalTrades) * 100 : 0
                    return (
                      <div key={label}>
                        <div className={`flex justify-between text-[10px] font-black uppercase tracking-widest mb-1 ${dk ? 'text-slate-400' : 'text-slate-600'}`}>
                          <span>{label}</span>
                          <span>
                            {count} ({pct.toFixed(0)}%)
                          </span>
                        </div>
                        <div className={`h-1.5 rounded-full overflow-hidden ${dk ? 'bg-white/5' : 'bg-slate-100'}`}>
                          <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>

              <div
                className={`rounded-2xl p-5 border transition-colors duration-500 ${
                  dk ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
                }`}
              >
                <h3 className="text-[10px] font-black uppercase tracking-widest text-slate-500 mb-4">
                  Trade Extremes & Regime
                </h3>
                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className={`rounded-xl p-3 border ${dk ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-emerald-50 border-emerald-200'}`}>
                    <p className={`text-[9px] font-black uppercase tracking-widest ${dk ? 'text-emerald-400/60' : 'text-emerald-700/70'}`}>Best Trade</p>
                    <p className={dk ? 'text-xl font-black text-emerald-400' : 'text-xl font-black text-emerald-700'}>
                      +{bestTradePct}%
                    </p>
                  </div>
                  <div className={`rounded-xl p-3 border ${dk ? 'bg-rose-500/10 border-rose-500/20' : 'bg-rose-50 border-rose-200'}`}>
                    <p className={`text-[9px] font-black uppercase tracking-widest ${dk ? 'text-rose-400/60' : 'text-rose-700/70'}`}>Worst Trade</p>
                    <p className={dk ? 'text-xl font-black text-rose-400' : 'text-xl font-black text-rose-700'}>
                      {worstTradePct}%
                    </p>
                  </div>
                </div>
                {Object.keys(result.regime_breakdown ?? {}).length > 0 && (
                  <div className="space-y-1.5">
                    <p className="text-[9px] font-black uppercase tracking-widest text-slate-500 mb-2">Market Regime</p>
                    {Object.entries(result.regime_breakdown).map(([regime, count]) => (
                      <div key={regime} className={`flex justify-between text-[10px] font-bold ${dk ? 'text-slate-400' : 'text-slate-600'}`}>
                        <span>{regime}</span>
                        <span className={`font-black ${dk ? 'text-slate-300' : 'text-slate-800'}`}>{count} trades</span>
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
        <div className={`flex-1 flex flex-col items-center justify-center gap-3 py-16 ${dk ? 'text-slate-600' : 'text-slate-400'}`}>
          <FlaskConical className="w-12 h-12 opacity-20" />
          <p className={`text-sm font-black uppercase tracking-widest ${dk ? 'text-slate-600' : 'text-slate-500'}`}>
            Configure params and run backtest
          </p>
        </div>
      )}
    </div>
  )
}
