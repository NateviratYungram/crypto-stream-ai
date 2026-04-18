import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Brain, RefreshCw, AlertCircle, CheckCircle, Activity, BarChart2, Cpu, TrendingUp } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';

interface MLStats {
  paper_trades: { total_labeled: number; wins: number; losses: number; win_rate: number | null };
  model: { trained: boolean; n_samples?: number; accuracy?: number; roc_auc?: number; trained_at?: string };
  model_exists: boolean;
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

export default function MLStatsPanel() {
  const { t } = useLanguage();
  const [stats,       setStats]       = useState<MLStats | null>(null);
  const [features,    setFeatures]    = useState<FeatureItem[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [retraining,  setRetraining]  = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const [tab,         setTab]         = useState<'overview' | 'features'>('overview');

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

  const [retrainElapsed, setRetrainElapsed] = useState(0);

  const triggerRetrain = async () => {
    setRetraining(true);
    setRetrainElapsed(0);
    try {
      const res = await fetch('/api/ml/retrain', { method: 'POST' });
      if (!res.ok) { setRetraining(false); return; }
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
        const timedOut = Date.now() - startedAt > 480_000;
        if (newTrainedAt !== prevTrainedAt || timedOut) {
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
        if (Date.now() - startedAt > 480_000) { clearInterval(poll); clearInterval(ticker); setRetraining(false); }
      }
    }, 5_000);
  };

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 5 * 60 * 1000);
    return () => clearInterval(iv);
  }, []);

  const m       = stats?.model;
  const p       = stats?.paper_trades;
  const winRate = p?.win_rate != null ? Math.round(p.win_rate * 100) : null;
  const auc     = m?.roc_auc ?? 0;
  const maxImp  = features[0]?.importance ?? 1;

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">

      {/* Header */}
      <header className="flex items-center justify-between border-b border-white/5 pb-6">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-blue-400 font-bold text-xs uppercase tracking-[0.2em]">
            <Cpu className="w-3.5 h-3.5" />
            {t('ml.badge')}
          </div>
          <h1 className="text-3xl font-black text-white tracking-tighter uppercase italic">{t('ml.title')}</h1>
          <p className="text-slate-500 text-sm">{t('ml.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Status badge */}
          {m?.trained
            ? <div className="flex items-center gap-2 px-4 py-2 rounded-2xl bg-emerald-500/10 border border-emerald-500/20">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-black text-emerald-400 uppercase tracking-widest">{t('ml.trained')}</span>
              </div>
            : <div className="flex items-center gap-2 px-4 py-2 rounded-2xl bg-amber-500/10 border border-amber-500/20">
                <AlertCircle className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-black text-amber-400 uppercase tracking-widest">{t('ml.not_trained')}</span>
              </div>
          }
          <button onClick={fetchAll} className="p-2.5 rounded-xl border border-white/10 hover:bg-white/5 text-slate-400 hover:text-white transition-all">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </header>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <Activity className="w-6 h-6 text-blue-400 animate-pulse" />
        </div>
      ) : (
        <>
          {/* Stat cards row */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: t('ml.training_samples'), value: m?.trained ? (m.n_samples?.toLocaleString() ?? '—') : '—', color: 'text-blue-400', border: 'border-blue-500/20', bg: 'from-blue-600/10 to-transparent' },
              { label: t('ml.accuracy'),         value: m?.trained && m.accuracy ? `${(m.accuracy * 100).toFixed(1)}%` : '—', color: 'text-violet-400', border: 'border-violet-500/20', bg: 'from-violet-600/10 to-transparent' },
              { label: t('ml.roc_auc'),          value: m?.trained ? (m.roc_auc?.toFixed(3) ?? '—') : '—', color: auc >= 0.75 ? 'text-emerald-400' : auc >= 0.65 ? 'text-amber-400' : 'text-slate-400', border: auc >= 0.75 ? 'border-emerald-500/20' : 'border-amber-500/20', bg: 'from-slate-800/40 to-transparent' },
              { label: t('ml.paper_win_rate'),   value: winRate != null ? `${winRate}%` : '—', color: winRate != null && winRate >= 55 ? 'text-emerald-400' : winRate != null && winRate >= 45 ? 'text-amber-400' : 'text-slate-400', border: 'border-white/10', bg: 'from-slate-800/40 to-transparent' },
            ].map(card => (
              <div key={card.label} className={`p-5 rounded-2xl border ${card.border} bg-gradient-to-br ${card.bg} bg-slate-900/40`}>
                <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest mb-2">{card.label}</p>
                <p className={`text-2xl font-black tabular-nums ${card.color}`}>{card.value}</p>
              </div>
            ))}
          </div>

          {/* Main 2-col layout */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

            {/* Left: Model quality + paper trade stats */}
            <div className="space-y-4">
              {/* AUC quality bar */}
              {m?.trained && (
                <div className="p-6 rounded-2xl border border-white/5 bg-slate-900/40 space-y-4">
                  <div className="flex items-center gap-2">
                    <Brain className="w-4 h-4 text-blue-400" />
                    <h3 className="text-xs font-black text-white uppercase tracking-widest">{t('ml.model_quality')}</h3>
                    <span className={`ml-auto text-xs font-black uppercase tracking-widest ${auc >= 0.75 ? 'text-emerald-400' : auc >= 0.65 ? 'text-amber-400' : 'text-red-400'}`}>
                      {auc >= 0.75 ? t('ml.quality_good') : auc >= 0.65 ? t('ml.quality_fair') : t('ml.quality_learning')}
                    </span>
                  </div>
                  <div className="space-y-1">
                    <div className="w-full h-3 bg-slate-950 rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${Math.min((auc - 0.5) / 0.5 * 100, 100)}%` }}
                        transition={{ duration: 1, ease: 'easeOut' }}
                        className={`h-full rounded-full ${auc >= 0.75 ? 'bg-gradient-to-r from-emerald-600 to-emerald-400' : auc >= 0.65 ? 'bg-gradient-to-r from-amber-600 to-amber-400' : 'bg-gradient-to-r from-red-700 to-red-500'}`}
                      />
                    </div>
                    <div className="flex justify-between">
                      <span className="text-[10px] text-slate-600">{t('ml.auc_random')}</span>
                      <span className="text-[10px] text-slate-600">{t('ml.auc_perfect')}</span>
                    </div>
                  </div>
                  {m.trained_at && (
                    <p className="text-[10px] text-slate-600">{t('ml.last_trained')} {new Date(m.trained_at).toLocaleString()}</p>
                  )}
                </div>
              )}

              {/* Paper trade results */}
              <div className="p-6 rounded-2xl border border-white/5 bg-slate-900/40 space-y-4">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-blue-400" />
                  <h3 className="text-xs font-black text-white uppercase tracking-widest">{t('ml.paper_results')}</h3>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  {[
                    { label: t('ml.total'),  value: p?.total_labeled ?? 0, color: 'text-slate-200' },
                    { label: t('ml.wins'),   value: p?.wins    ?? 0,       color: 'text-emerald-400' },
                    { label: t('ml.losses'), value: p?.losses  ?? 0,       color: 'text-red-400' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="rounded-xl bg-white/5 p-3 text-center">
                      <div className={`text-xl font-black tabular-nums ${color}`}>{value}</div>
                      <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-1">{label}</div>
                    </div>
                  ))}
                </div>
                {winRate !== null ? (
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="text-slate-500 font-bold uppercase tracking-widest">{t('ml.win_rate')}</span>
                      <span className={`font-black tabular-nums ${winRate >= 55 ? 'text-emerald-400' : winRate >= 45 ? 'text-amber-400' : 'text-red-400'}`}>{winRate}%</span>
                    </div>
                    <div className="w-full h-2 bg-slate-950 rounded-full overflow-hidden">
                      <motion.div initial={{ width: 0 }} animate={{ width: `${winRate}%` }} transition={{ duration: 0.8 }}
                        className={`h-full rounded-full ${winRate >= 55 ? 'bg-emerald-500' : winRate >= 45 ? 'bg-amber-500' : 'bg-red-500'}`} />
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-slate-500 text-center py-2">
                    {t('ml.no_trades')}
                  </p>
                )}
              </div>

              {/* Retrain button */}
              <button onClick={triggerRetrain} disabled={retraining}
                className="w-full flex items-center justify-center gap-2 px-4 py-4 rounded-2xl border border-blue-500/20 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 text-xs font-black uppercase tracking-widest transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]">
                {retraining
                  ? <><RefreshCw className="w-4 h-4 animate-spin" />{t('ml.training')} {retrainElapsed > 0 ? `${retrainElapsed}s` : 'starting'}</>
                  : <><Brain className="w-4 h-4" />{t('ml.retrain')}</>
                }
              </button>
              {lastRefresh && (
                <p className="text-[10px] text-slate-600 text-center">{t('ml.updated')} {lastRefresh.toLocaleTimeString()}</p>
              )}
            </div>

            {/* Right: Feature importance */}
            <div className="p-6 rounded-2xl border border-white/5 bg-slate-900/40 space-y-4">
              <div className="flex items-center gap-2">
                <BarChart2 className="w-4 h-4 text-blue-400" />
                <h3 className="text-xs font-black text-white uppercase tracking-widest">{t('ml.feature_importance')}</h3>
                {features.length > 0 && (
                  <span className="ml-auto text-[10px] text-slate-600 font-mono">{features.length} {t('ml.features')}</span>
                )}
              </div>

              {/* Legend */}
              <div className="flex flex-wrap gap-3">
                {[
                  { label: t('ml.osc'),    color: 'bg-blue-500' },
                  { label: t('ml.trend'),  color: 'bg-violet-500' },
                  { label: t('ml.volume'), color: 'bg-amber-500' },
                  { label: t('ml.time'),   color: 'bg-teal-500' },
                ].map(({ label, color }) => (
                  <div key={label} className="flex items-center gap-1.5">
                    <div className={`w-2 h-2 rounded-full ${color} opacity-80`} />
                    <span className="text-[10px] text-slate-500 uppercase tracking-widest">{label}</span>
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
                <div className="space-y-3 overflow-y-auto max-h-96 custom-scrollbar pr-1">
                  {features.slice(0, 15).map((f, i) => {
                    const pct    = (f.importance / maxImp) * 100;
                    const impPct = (f.importance * 100).toFixed(2);
                    const col    = featureColor(f.feature);
                    return (
                      <motion.div key={f.feature}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.04 }}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-black text-slate-600 tabular-nums w-5">{i + 1}</span>
                            <span className="text-xs font-bold text-slate-300">{f.label}</span>
                            <span className={`text-[9px] px-1.5 py-0.5 rounded-full text-white opacity-70 ${col}`}>
                              {featureGroupLabel(f.feature)}
                            </span>
                          </div>
                          <span className="text-[10px] font-black text-slate-400 tabular-nums font-mono">{impPct}%</span>
                        </div>
                        <div className="w-full h-1.5 bg-slate-950 rounded-full overflow-hidden">
                          <motion.div
                            initial={{ width: 0 }}
                            animate={{ width: `${pct}%` }}
                            transition={{ duration: 0.6, delay: i * 0.04, ease: 'easeOut' }}
                            className={`h-full rounded-full ${col}`}
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
