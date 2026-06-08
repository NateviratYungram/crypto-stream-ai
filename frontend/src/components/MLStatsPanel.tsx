import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  AlertCircle,
  BarChart2,
  Brain,
  CheckCircle,
  RefreshCw,
  ShieldAlert,
  Target,
  TrendingUp,
} from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { useMode } from '../contexts/ModeContext';

interface MLStats {
  is_training?: boolean;
  paper_trades: { total_labeled: number; wins: number; losses: number; win_rate: number | null };
  model: {
    trained: boolean;
    n_samples?: number;
    train_size?: number;
    test_size?: number;
    accuracy?: number;
    roc_auc?: number;
    trained_at?: string;
    split_method?: string;
    dataset_quality?: {
      symbols?: number;
      timeframes?: string[];
      win_rate_full?: number;
    } | null;
    walk_forward?: {
      summary?: {
        fold_count?: number;
        avg_accuracy?: number;
        avg_roc_auc?: number;
      } | null;
    } | null;
    calibration?: {
      available?: boolean;
      method?: string;
      brier_score?: number;
      ece?: number;
    } | null;
    sufficiency?: {
      ready_for_improvement?: boolean;
      current?: {
        paper_labels?: number;
        training_samples?: number;
        core_symbols_covered?: number;
      };
      targets?: {
        paper_labels?: number;
        training_samples?: number;
        core_symbols?: number;
      };
      progress?: {
        overall?: number;
        paper_labels?: number;
        training_samples?: number;
        core_symbols?: number;
      };
      core_symbols?: {
        covered?: string[];
        missing?: string[];
      };
    } | null;
    auto_retrain?: {
      available?: boolean;
      recommended?: boolean;
      reasons?: string[];
      recent_outcomes?: number;
      recent_win_rate?: number | null;
      outcomes_since_retrain?: number;
      model_age_days?: number | null;
      thresholds?: {
        recent_outcomes?: number;
        decay_win_rate?: number;
        new_outcomes_since_retrain?: number;
        max_model_age_days?: number;
      };
    } | null;
  };
  model_exists: boolean;
  readiness?: {
    passed?: boolean;
    blockers?: { name?: string; detail?: string; ok?: boolean }[];
    thresholds?: {
      min_profit_factor?: number;
      min_walk_forward_auc?: number;
      min_holdout_auc?: number;
    };
    paper?: {
      profit_factor?: number;
      expectancy_usd?: number;
      max_drawdown_usd?: number;
    };
  };
  promotion_history?: {
    available?: boolean;
    count?: number;
    trained_count?: number;
    rejected_count?: number;
    latest?: {
      status?: string;
      trigger_reason?: string;
      roc_auc?: number;
      accuracy?: number;
      walk_forward_auc?: number;
      override_reason?: string;
      blockers?: string[];
      created_at?: string;
    } | null;
  };
  symbol_policy?: {
    summary?: {
      blocked?: number;
      reduced?: number;
      allowed?: number;
    };
    rows?: Array<{
      key: string;
      symbol: string;
      side: string;
      action: 'allow' | 'reduce' | 'block';
      size_multiplier: number;
      trades: number;
      win_rate: number;
      pnl: number;
      reasons?: string[];
    }>;
  };
  focus?: {
    core_symbols?: string[];
    targets?: {
      paper_labels?: number;
      training_samples?: number;
      core_symbols?: number;
    };
  };
}

interface FeatureItem {
  feature: string;
  label: string;
  importance: number;
}

function featureColor(feature: string): string {
  if (['rsi', 'adx', 'macd_hist_norm', 'bb_pct'].includes(feature)) return 'bg-blue-500';
  if (['bullish_align', 'bearish_align', 'price_vs_ema20', 'price_vs_ema50', 'price_vs_ema200', 'ema20_vs_ema50', 'ema20_slope'].includes(feature)) return 'bg-violet-500';
  if (['vol_ratio', 'atr_pct'].includes(feature)) return 'bg-amber-500';
  if (['hour', 'dow', 'session'].includes(feature)) return 'bg-teal-500';
  return 'bg-slate-500';
}

function featureGroupLabel(feature: string): string {
  if (['rsi', 'adx', 'macd_hist_norm', 'bb_pct'].includes(feature)) return 'Oscillator';
  if (['bullish_align', 'bearish_align', 'price_vs_ema20', 'price_vs_ema50', 'price_vs_ema200', 'ema20_vs_ema50', 'ema20_slope'].includes(feature)) return 'Trend';
  if (['vol_ratio', 'atr_pct'].includes(feature)) return 'Volume/Vol';
  if (['hour', 'dow', 'session'].includes(feature)) return 'Time';
  return 'Other';
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function fmt(value: number, digits = 0): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPct(value: number | null | undefined, digits = 1): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
  return `${value.toFixed(digits)}%`;
}

function statTone(theme: 'light' | 'dark', tone: 'blue' | 'violet' | 'emerald' | 'amber' | 'rose' | 'slate') {
  const darkMap = {
    blue: 'border-blue-500/20 from-blue-600/10 to-transparent text-blue-400',
    violet: 'border-violet-500/20 from-violet-600/10 to-transparent text-violet-400',
    emerald: 'border-emerald-500/20 from-emerald-600/10 to-transparent text-emerald-400',
    amber: 'border-amber-500/20 from-amber-600/10 to-transparent text-amber-400',
    rose: 'border-rose-500/20 from-rose-600/10 to-transparent text-rose-400',
    slate: 'border-white/5 from-slate-700/20 to-transparent text-slate-200',
  };
  const lightMap = {
    blue: 'border-blue-200 from-blue-50 to-transparent text-blue-600',
    violet: 'border-violet-200 from-violet-50 to-transparent text-violet-600',
    emerald: 'border-emerald-200 from-emerald-50 to-transparent text-emerald-600',
    amber: 'border-amber-200 from-amber-50 to-transparent text-amber-600',
    rose: 'border-rose-200 from-rose-50 to-transparent text-rose-600',
    slate: 'border-slate-200 from-slate-100 to-transparent text-slate-800',
  };
  return theme === 'dark' ? darkMap[tone] : lightMap[tone];
}

function StatCard({
  label,
  value,
  sub,
  tone,
  theme,
}: {
  label: string;
  value: string;
  sub: string;
  tone: 'blue' | 'violet' | 'emerald' | 'amber' | 'rose' | 'slate';
  theme: 'light' | 'dark';
}) {
  const toneClass = statTone(theme, tone);
  return (
    <div
      className={`rounded-2xl border bg-gradient-to-br p-5 transition-all duration-500 ${toneClass} ${
        theme === 'dark' ? 'bg-slate-900/40' : 'bg-white shadow-sm shadow-slate-200/50'
      }`}
    >
      <p className={`text-[11px] font-black uppercase tracking-widest ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>
        {label}
      </p>
      <p className="mt-2 text-2xl font-black tabular-nums">{value}</p>
      <p className={`mt-1 text-[11px] ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>{sub}</p>
    </div>
  );
}

export default function MLStatsPanel() {
  const { t } = useLanguage();
  const { theme } = useMode();
  const [stats, setStats] = useState<MLStats | null>(null);
  const [features, setFeatures] = useState<FeatureItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [retraining, setRetraining] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [retrainElapsed, setRetrainElapsed] = useState(0);

  const fetchAll = async () => {
    try {
      const [sRes, fRes] = await Promise.all([
        fetch('/api/ml/stats'),
        fetch('/api/ml/feature-importance'),
      ]);
      if (!sRes.ok) throw new Error(`/api/ml/stats ${sRes.status}`);
      const sData = await sRes.json();
      setStats(sData);
      if (fRes.ok) {
        const fData = await fRes.json();
        if (fData.available && fData.features) setFeatures(fData.features);
      }
      setLastRefresh(new Date());
    } catch (e) {
      console.error('[MLStatsPanel] fetch failed:', e);
    } finally {
      setLoading(false);
    }
  };

  const triggerRetrain = async () => {
    setRetraining(true);
    setRetrainElapsed(0);
    try {
      const res = await fetch('/api/ml/retrain', { method: 'POST' });
      if (!res.ok) {
        setRetraining(false);
        return;
      }
    } catch {
      setRetraining(false);
      return;
    }
    const startedAt = Date.now();
    const prevTrainedAt = stats?.model?.trained_at ?? '';

    const ticker = setInterval(() => {
      setRetrainElapsed(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);

    const poll = setInterval(async () => {
      try {
        const res = await fetch('/api/ml/stats');
        if (!res.ok) return;
        const data = await res.json();
        const newTrainedAt = data?.model?.trained_at ?? '';
        const isTraining = data?.is_training ?? false;
        const timedOut = Date.now() - startedAt > 480_000;
        const timeElapsed = Date.now() - startedAt;

        if (newTrainedAt !== prevTrainedAt || timedOut || (timeElapsed > 3000 && !isTraining)) {
          clearInterval(poll);
          clearInterval(ticker);
          setStats(data);
          setRetraining(false);
          setRetrainElapsed(0);
          setLastRefresh(new Date());
          if (newTrainedAt !== prevTrainedAt) {
            const fRes = await fetch('/api/ml/feature-importance');
            const fData = await fRes.json();
            if (fData.available && fData.features) setFeatures(fData.features);
          }
        }
      } catch {
        if (Date.now() - startedAt > 480_000) {
          clearInterval(poll);
          clearInterval(ticker);
          setRetraining(false);
        }
      }
    }, 5000);
  };

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 5 * 60 * 1000);
    return () => clearInterval(iv);
  }, []);

  const model = stats?.model;
  const paper = stats?.paper_trades;
  const auc = num(model?.roc_auc);
  const accuracy = num(model?.accuracy);
  const samples = num(model?.n_samples);
  const trainSize = num(model?.train_size);
  const testSize = num(model?.test_size);
  const datasetQuality = model?.dataset_quality;
  const walkForward = model?.walk_forward?.summary;
  const sufficiency = model?.sufficiency;
  const sufficiencyTargets = sufficiency?.targets ?? stats?.focus?.targets;
  const covered = sufficiency?.core_symbols?.covered ?? [];
  const missing = sufficiency?.core_symbols?.missing ?? [];
  const overallProgress = num(sufficiency?.progress?.overall) * 100;
  const winRate = paper?.win_rate != null ? Math.round(paper.win_rate * 100) : null;
  const autoRetrain = model?.auto_retrain;
  const readiness = stats?.readiness;
  const blockers = readiness?.blockers ?? [];
  const promotionSummary = stats?.promotion_history;
  const latestPromotion = promotionSummary?.latest;
  const symbolPolicy = stats?.symbol_policy;
  const policyRows = symbolPolicy?.rows ?? [];
  const blockedRows = policyRows.filter((row) => row.action === 'block');
  const reducedRows = policyRows.filter((row) => row.action === 'reduce');
  const maxImp = features[0]?.importance ?? 1;
  const recentWinRatePct =
    typeof autoRetrain?.recent_win_rate === 'number' ? autoRetrain.recent_win_rate * 100 : null;
  const aucTone: 'emerald' | 'amber' | 'rose' = auc >= 0.7 ? 'emerald' : auc >= 0.62 ? 'amber' : 'rose';

  return (
    <div
      className={`flex-1 overflow-y-auto p-8 space-y-6 custom-scrollbar transition-colors duration-500 ${
        theme === 'dark' ? 'bg-slate-950/20' : 'bg-slate-50'
      }`}
    >
      <header
        className={`flex items-center justify-between border-b pb-6 transition-colors duration-500 ${
          theme === 'dark' ? 'border-white/5' : 'border-slate-200'
        }`}
      >
        <div className="space-y-1">
          <div
            className={`flex items-center gap-2 text-xs font-bold uppercase tracking-[0.2em] transition-colors duration-500 ${
              theme === 'dark' ? 'text-blue-400' : 'text-blue-600'
            }`}
          >
            <Brain className="w-3.5 h-3.5" />
            {t('ml.badge')}
          </div>
          <h1
            className={`text-3xl font-black tracking-tighter uppercase italic transition-colors duration-500 ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}
          >
            {t('ml.title')}
          </h1>
          <p className={`text-sm transition-colors duration-500 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-600'}`}>
            {t('ml.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {model?.trained ? (
            <div
              className={`flex items-center gap-2 rounded-2xl border px-4 py-2 transition-all ${
                theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-emerald-50 border-emerald-200'
              }`}
            >
              <CheckCircle className="w-4 h-4 text-emerald-400" />
              <span className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'}`}>
                {t('ml.trained')}
              </span>
            </div>
          ) : (
            <div
              className={`flex items-center gap-2 rounded-2xl border px-4 py-2 transition-all ${
                theme === 'dark' ? 'bg-amber-500/10 border-amber-500/20' : 'bg-amber-50 border-amber-200'
              }`}
            >
              <AlertCircle className="w-4 h-4 text-amber-400" />
              <span className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`}>
                {t('ml.not_trained')}
              </span>
            </div>
          )}
          <button
            onClick={fetchAll}
            className={`rounded-xl border p-2.5 transition-all ${
              theme === 'dark'
                ? 'border-white/10 bg-slate-900/40 text-slate-400 hover:bg-white/5 hover:text-white'
                : 'border-blue-200 bg-blue-50 text-blue-600 shadow-sm hover:bg-blue-100'
            }`}
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <Activity className="w-6 h-6 text-blue-400 animate-pulse" />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label={t('ml.training_samples')} value={model?.trained ? fmt(samples) : '--'} sub={`${fmt(trainSize)} train / ${fmt(testSize)} test`} tone="blue" theme={theme} />
            <StatCard label={t('ml.accuracy')} value={model?.trained ? fmtPct(accuracy * 100) : '--'} sub={model?.split_method || 'n/a'} tone="violet" theme={theme} />
            <StatCard label={t('ml.roc_auc')} value={model?.trained ? auc.toFixed(3) : '--'} sub={walkForward?.avg_roc_auc ? `WF ${walkForward.avg_roc_auc.toFixed(3)}` : 'walk-forward pending'} tone={aucTone} theme={theme} />
            <StatCard label="Data Progress" value={fmtPct(overallProgress, 0)} sub={sufficiency?.ready_for_improvement ? 'minimum target reached' : 'still collecting'} tone={sufficiency?.ready_for_improvement ? 'emerald' : 'amber'} theme={theme} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-[1.2fr_0.8fr] gap-6">
            <div className="space-y-4">
              <div
                className={`rounded-2xl border p-6 space-y-4 transition-all duration-500 ${
                  theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-sm'
                }`}
              >
                <div className="flex items-center gap-2">
                  <Target className="w-4 h-4 text-blue-400" />
                  <h3 className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    Data Sufficiency Mode
                  </h3>
                  <span
                    className={`ml-auto rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${
                      sufficiency?.ready_for_improvement
                        ? theme === 'dark'
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                          : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : theme === 'dark'
                          ? 'bg-amber-500/10 text-amber-300 border-amber-500/20'
                          : 'bg-amber-50 text-amber-700 border-amber-200'
                    }`}
                  >
                    {sufficiency?.ready_for_improvement ? 'Ready' : 'Collecting'}
                  </span>
                </div>

                <div className={`w-full h-3 rounded-full overflow-hidden ${theme === 'dark' ? 'bg-slate-950' : 'bg-slate-200'}`}>
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${Math.max(0, Math.min(overallProgress, 100))}%` }}
                    transition={{ duration: 0.8, ease: 'easeOut' }}
                    className={`h-full rounded-full ${
                      overallProgress >= 100
                        ? 'bg-gradient-to-r from-emerald-500 to-emerald-400'
                        : overallProgress >= 66
                          ? 'bg-gradient-to-r from-amber-500 to-amber-400'
                          : 'bg-gradient-to-r from-rose-500 to-amber-400'
                    }`}
                  />
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <StatCard label="Paper Labels" value={`${fmt(num(sufficiency?.current?.paper_labels))} / ${fmt(num(sufficiencyTargets?.paper_labels))}`} sub="closed labeled trades" tone={num(sufficiency?.progress?.paper_labels) >= 1 ? 'emerald' : 'amber'} theme={theme} />
                  <StatCard label="Train Samples" value={`${fmt(num(sufficiency?.current?.training_samples))} / ${fmt(num(sufficiencyTargets?.training_samples))}`} sub="usable filtered rows" tone={num(sufficiency?.progress?.training_samples) >= 1 ? 'emerald' : 'amber'} theme={theme} />
                  <StatCard label="Core Symbols" value={`${fmt(num(sufficiency?.current?.core_symbols_covered))} / ${fmt(num(sufficiencyTargets?.core_symbols))}`} sub="focus universe coverage" tone={num(sufficiency?.progress?.core_symbols) >= 1 ? 'emerald' : 'amber'} theme={theme} />
                  <StatCard label="Universe" value={fmt(num(datasetQuality?.symbols))} sub={(datasetQuality?.timeframes ?? []).join(', ') || 'n/a'} tone="slate" theme={theme} />
                </div>

                <div className={`text-xs font-bold space-y-1 ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>
                  <p>
                    <span className={theme === 'dark' ? 'text-slate-200' : 'text-slate-900'}>Focus:</span>{' '}
                    {(stats?.focus?.core_symbols ?? []).join(', ') || 'none'}
                  </p>
                  <p>
                    <span className={theme === 'dark' ? 'text-slate-200' : 'text-slate-900'}>Covered:</span>{' '}
                    {covered.join(', ') || 'none'}
                  </p>
                  <p>
                    <span className={theme === 'dark' ? 'text-slate-200' : 'text-slate-900'}>Missing:</span>{' '}
                    {missing.join(', ') || 'none'}
                  </p>
                </div>
              </div>

              <div
                className={`rounded-2xl border p-6 space-y-4 transition-all duration-500 ${
                  theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-sm'
                }`}
              >
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-4 h-4 text-blue-400" />
                  <h3 className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    Live Readiness
                  </h3>
                  <span
                    className={`ml-auto rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${
                      readiness?.passed
                        ? theme === 'dark'
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                          : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                        : theme === 'dark'
                          ? 'bg-rose-500/10 text-rose-300 border-rose-500/20'
                          : 'bg-rose-50 text-rose-700 border-rose-200'
                    }`}
                  >
                    {readiness?.passed ? 'Ready' : 'Blocked'}
                  </span>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <StatCard label="PF" value={readiness?.paper?.profit_factor != null ? readiness.paper.profit_factor.toFixed(2) : '--'} sub={`need ${(readiness?.thresholds?.min_profit_factor ?? 0).toFixed(2)}`} tone={num(readiness?.paper?.profit_factor) >= num(readiness?.thresholds?.min_profit_factor) ? 'emerald' : 'rose'} theme={theme} />
                  <StatCard label="Holdout AUC" value={auc ? auc.toFixed(3) : '--'} sub={`need ${(readiness?.thresholds?.min_holdout_auc ?? 0).toFixed(3)}`} tone={auc >= num(readiness?.thresholds?.min_holdout_auc) ? 'emerald' : 'rose'} theme={theme} />
                  <StatCard label="WF AUC" value={walkForward?.avg_roc_auc ? walkForward.avg_roc_auc.toFixed(3) : '--'} sub={`need ${(readiness?.thresholds?.min_walk_forward_auc ?? 0).toFixed(3)}`} tone={num(walkForward?.avg_roc_auc) >= num(readiness?.thresholds?.min_walk_forward_auc) ? 'emerald' : 'rose'} theme={theme} />
                </div>

                <div className={`rounded-xl border p-4 text-sm space-y-2 ${theme === 'dark' ? 'bg-white/5 border-white/10 text-slate-300' : 'bg-slate-50 border-slate-200 text-slate-700'}`}>
                  {blockers.length ? blockers.map((blocker) => (
                    <div key={`${blocker.name}-${blocker.detail}`} className="flex items-start gap-2">
                      <AlertCircle className="mt-0.5 h-4 w-4 text-rose-400" />
                      <div>
                        <p className="font-black uppercase tracking-widest text-[10px]">{blocker.name || 'blocker'}</p>
                        <p className="text-xs">{blocker.detail || 'details unavailable'}</p>
                      </div>
                    </div>
                  )) : (
                    <p>All model-quality checks are clear.</p>
                  )}
                </div>
              </div>

              <div
                className={`rounded-2xl border p-6 space-y-4 transition-all duration-500 ${
                  theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-sm'
                }`}
              >
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-4 h-4 text-blue-400" />
                  <h3 className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    Auto Retrain Monitor
                  </h3>
                  <span
                    className={`ml-auto rounded-full border px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${
                      autoRetrain?.recommended
                        ? theme === 'dark'
                          ? 'bg-rose-500/10 text-rose-300 border-rose-500/20'
                          : 'bg-rose-50 text-rose-700 border-rose-200'
                        : theme === 'dark'
                          ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
                          : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                    }`}
                  >
                    {autoRetrain?.recommended ? 'Retrain Soon' : 'Healthy'}
                  </span>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <StatCard label="Recent Win Rate" value={fmtPct(recentWinRatePct)} sub={`need ${fmtPct(num(autoRetrain?.thresholds?.decay_win_rate) * 100, 0)}+`} tone={recentWinRatePct == null ? 'slate' : recentWinRatePct >= num(autoRetrain?.thresholds?.decay_win_rate) * 100 ? 'emerald' : 'rose'} theme={theme} />
                  <StatCard label="Recent Outcomes" value={fmt(num(autoRetrain?.recent_outcomes))} sub={`check after ${fmt(num(autoRetrain?.thresholds?.recent_outcomes))}`} tone="slate" theme={theme} />
                  <StatCard label="New Labels" value={fmt(num(autoRetrain?.outcomes_since_retrain))} sub={`trigger at ${fmt(num(autoRetrain?.thresholds?.new_outcomes_since_retrain))}`} tone={num(autoRetrain?.outcomes_since_retrain) >= num(autoRetrain?.thresholds?.new_outcomes_since_retrain) ? 'amber' : 'slate'} theme={theme} />
                  <StatCard label="Model Age" value={autoRetrain?.model_age_days != null ? `${autoRetrain.model_age_days.toFixed(1)}d` : '--'} sub={`refresh by ${fmt(num(autoRetrain?.thresholds?.max_model_age_days), 0)}d`} tone={num(autoRetrain?.model_age_days) >= num(autoRetrain?.thresholds?.max_model_age_days) ? 'amber' : 'slate'} theme={theme} />
                </div>

                <div className={`rounded-xl border p-4 text-sm ${theme === 'dark' ? 'bg-white/5 border-white/10 text-slate-300' : 'bg-slate-50 border-slate-200 text-slate-700'}`}>
                  {autoRetrain?.recommended ? (
                    <p>
                      Retrain recommendation: {(autoRetrain.reasons ?? []).join(', ') || 'monitor triggered'}.
                    </p>
                  ) : (
                    <p>Current model looks stable enough to keep collecting more labels before the next forced retrain.</p>
                  )}
                </div>
              </div>

              <div
                className={`rounded-2xl border p-6 space-y-4 transition-all duration-500 ${
                  theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-sm'
                }`}
              >
                <div className="flex items-center gap-2">
                  <RefreshCw className="w-4 h-4 text-blue-400" />
                  <h3 className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    Promotion History
                  </h3>
                </div>

                <div className="grid grid-cols-3 gap-3">
                  <StatCard label="Promoted" value={fmt(num(promotionSummary?.trained_count))} sub="saved challengers" tone="emerald" theme={theme} />
                  <StatCard label="Rejected" value={fmt(num(promotionSummary?.rejected_count))} sub="blocked challengers" tone="amber" theme={theme} />
                  <StatCard label="Attempts" value={fmt(num(promotionSummary?.count))} sub="recent history" tone="slate" theme={theme} />
                </div>

                <div className={`rounded-xl border p-4 space-y-2 ${theme === 'dark' ? 'bg-white/5 border-white/10 text-slate-300' : 'bg-slate-50 border-slate-200 text-slate-700'}`}>
                  <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">Latest Challenger</p>
                  <p className={`text-sm font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    {(latestPromotion?.status || 'unknown').toUpperCase()} {latestPromotion?.trigger_reason ? `• ${latestPromotion.trigger_reason}` : ''}
                  </p>
                  <p className="text-xs">
                    AUC {latestPromotion?.roc_auc != null ? latestPromotion.roc_auc.toFixed(3) : '--'} • ACC {latestPromotion?.accuracy != null ? `${(latestPromotion.accuracy * 100).toFixed(1)}%` : '--'} • WF {latestPromotion?.walk_forward_auc != null ? latestPromotion.walk_forward_auc.toFixed(3) : '--'}
                  </p>
                  {latestPromotion?.override_reason && (
                    <p className="text-xs text-blue-400">{latestPromotion.override_reason}</p>
                  )}
                  {!!latestPromotion?.blockers?.length && (
                    <p className="text-xs text-rose-400">{latestPromotion.blockers.join(', ')}</p>
                  )}
                </div>
              </div>

              <div
                className={`rounded-2xl border p-6 space-y-4 transition-all duration-500 ${
                  theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-sm'
                }`}
              >
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-blue-400" />
                  <h3 className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    {t('ml.paper_results')}
                  </h3>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { label: t('ml.total'), value: paper?.total_labeled ?? 0, tone: 'slate' as const },
                    { label: t('ml.wins'), value: paper?.wins ?? 0, tone: 'emerald' as const },
                    { label: t('ml.losses'), value: paper?.losses ?? 0, tone: 'rose' as const },
                  ].map((item) => (
                    <div key={item.label} className={`rounded-xl p-3 text-center ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-50'}`}>
                      <div className={`${statTone(theme, item.tone).split(' ').pop()} text-xl font-black tabular-nums`}>
                        {item.value}
                      </div>
                      <div className="mt-1 text-[9px] uppercase tracking-widest text-slate-500">{item.label}</div>
                    </div>
                  ))}
                </div>
                {winRate !== null ? (
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="font-bold uppercase tracking-widest text-slate-500">{t('ml.win_rate')}</span>
                      <span className={`font-black tabular-nums ${winRate >= 55 ? 'text-emerald-400' : winRate >= 45 ? 'text-amber-400' : 'text-red-400'}`}>
                        {winRate}%
                      </span>
                    </div>
                    <div className={`w-full h-2 rounded-full overflow-hidden ${theme === 'dark' ? 'bg-slate-950' : 'bg-slate-200'}`}>
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${winRate}%` }}
                        transition={{ duration: 0.8 }}
                        className={`h-full rounded-full ${winRate >= 55 ? 'bg-emerald-500' : winRate >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                      />
                    </div>
                  </div>
                ) : (
                  <p className="py-2 text-center text-xs text-slate-500">{t('ml.no_trades')}</p>
                )}

                <button
                  onClick={triggerRetrain}
                  disabled={retraining}
                  className={`w-full flex items-center justify-center gap-2 rounded-2xl border px-4 py-4 text-xs font-black uppercase tracking-widest transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98] ${
                    theme === 'dark'
                      ? 'border-blue-500/20 bg-blue-500/10 text-blue-400 hover:bg-blue-500/20'
                      : 'bg-blue-600 border-blue-700 text-white shadow-lg shadow-blue-500/20 hover:bg-blue-700'
                  }`}
                >
                  {retraining ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      {t('ml.training')} {retrainElapsed > 0 ? `${retrainElapsed}s` : 'starting'}
                    </>
                  ) : (
                    <>
                      <Brain className="w-4 h-4" />
                      {t('ml.retrain')}
                    </>
                  )}
                </button>

                {lastRefresh && (
                  <p className="text-[10px] text-slate-600 text-center">
                    {t('ml.updated')} {lastRefresh.toLocaleTimeString()}
                  </p>
                )}
              </div>
            </div>

            <div
              className={`rounded-2xl border p-6 space-y-4 transition-all duration-500 ${
                theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-sm'
              }`}
            >
              <div className="flex items-center gap-2">
                <BarChart2 className="w-4 h-4 text-blue-400" />
                <h3 className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                  {t('ml.feature_importance')}
                </h3>
                {features.length > 0 && (
                  <span className="ml-auto text-[10px] font-mono text-slate-600">{features.length} {t('ml.features')}</span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <StatCard label="WF AUC" value={walkForward?.avg_roc_auc ? walkForward.avg_roc_auc.toFixed(3) : '--'} sub={`${fmt(num(walkForward?.fold_count))} folds`} tone={num(walkForward?.avg_roc_auc) >= 0.65 ? 'emerald' : 'amber'} theme={theme} />
                <StatCard label="Calibration" value={model?.calibration?.available ? 'On' : 'Off'} sub={model?.calibration?.method || 'n/a'} tone={model?.calibration?.available ? 'emerald' : 'amber'} theme={theme} />
                <StatCard label="ECE" value={model?.calibration?.ece != null ? model.calibration.ece.toFixed(3) : '--'} sub="lower is better" tone={num(model?.calibration?.ece) <= 0.08 ? 'emerald' : 'amber'} theme={theme} />
                <StatCard label="Brier" value={model?.calibration?.brier_score != null ? model.calibration.brier_score.toFixed(3) : '--'} sub="lower is better" tone={num(model?.calibration?.brier_score) <= 0.2 ? 'emerald' : 'amber'} theme={theme} />
              </div>

              <div className="grid grid-cols-3 gap-3">
                <StatCard label="Blocked Sides" value={fmt(blockedRows.length)} sub="hard stop" tone={blockedRows.length ? 'rose' : 'emerald'} theme={theme} />
                <StatCard label="Reduced Sides" value={fmt(reducedRows.length)} sub="risk trimmed" tone={reducedRows.length ? 'amber' : 'emerald'} theme={theme} />
                <StatCard label="Allowed Sides" value={fmt(num(symbolPolicy?.summary?.allowed))} sub="normal flow" tone="slate" theme={theme} />
              </div>

              <div className={`rounded-xl border p-4 space-y-3 ${theme === 'dark' ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'}`}>
                <p className="text-[10px] font-black uppercase tracking-widest text-slate-500">Policy Highlights</p>
                {[...blockedRows, ...reducedRows].slice(0, 6).map((row) => (
                  <div key={row.key} className="flex items-center justify-between gap-3">
                    <div>
                      <p className={`text-sm font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{row.symbol} {row.side}</p>
                      <p className="text-[10px] font-bold text-slate-500">
                        {row.trades} trades • {row.win_rate.toFixed(1)}% • {row.pnl >= 0 ? '+' : ''}${row.pnl.toFixed(2)}
                      </p>
                    </div>
                    <div className={`rounded-full px-2.5 py-1 text-[10px] font-black uppercase tracking-widest ${
                      row.action === 'block'
                        ? theme === 'dark' ? 'bg-rose-500/10 text-rose-300' : 'bg-rose-50 text-rose-700'
                        : theme === 'dark' ? 'bg-amber-500/10 text-amber-300' : 'bg-amber-50 text-amber-700'
                    }`}>
                      {row.action === 'block' ? 'block' : `x${row.size_multiplier.toFixed(2)}`}
                    </div>
                  </div>
                ))}
                {blockedRows.length === 0 && reducedRows.length === 0 && (
                  <p className="text-xs text-slate-500">No symbol-side policy pressure right now.</p>
                )}
              </div>

              <div className="flex flex-wrap gap-3">
                {[
                  { label: t('ml.osc'), color: 'bg-blue-500' },
                  { label: t('ml.trend'), color: 'bg-violet-500' },
                  { label: t('ml.volume'), color: 'bg-amber-500' },
                  { label: t('ml.time'), color: 'bg-teal-500' },
                ].map(({ label, color }) => (
                  <div key={label} className="flex items-center gap-1.5">
                    <div className={`w-2 h-2 rounded-full ${color} opacity-80`} />
                    <span className="text-[10px] uppercase tracking-widest text-slate-500">{label}</span>
                  </div>
                ))}
              </div>

              {features.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Brain className="w-10 h-10 text-slate-700 mb-3" />
                  <p className="text-sm text-slate-500 font-bold">{t('ml.train_first')}</p>
                  <p className="text-xs text-slate-600 mt-1">{t('ml.click_retrain')}</p>
                </div>
              ) : (
                <div className="space-y-3 overflow-y-auto max-h-[34rem] custom-scrollbar pr-1">
                  {features.slice(0, 15).map((feature, index) => {
                    const pct = (feature.importance / maxImp) * 100;
                    const impPct = (feature.importance * 100).toFixed(2);
                    const color = featureColor(feature.feature);
                    return (
                      <motion.div
                        key={feature.feature}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.04 }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="w-5 text-[10px] font-black tabular-nums text-slate-600">{index + 1}</span>
                            <span className={`text-xs font-bold ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>
                              {feature.label}
                            </span>
                            <span className={`rounded-full px-1.5 py-0.5 text-[9px] text-white opacity-70 ${color}`}>
                              {featureGroupLabel(feature.feature)}
                            </span>
                          </div>
                          <span className="text-[10px] font-black tabular-nums font-mono text-slate-400">{impPct}%</span>
                        </div>
                        <div className={`w-full h-1.5 rounded-full overflow-hidden ${theme === 'dark' ? 'bg-slate-950' : 'bg-slate-200'}`}>
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{ width: `${pct}%` }}
                            transition={{ duration: 0.6, delay: index * 0.04, ease: 'easeOut' }}
                            className={`h-full rounded-full ${color}`}
                          />
                        </div>
                      </motion.div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
