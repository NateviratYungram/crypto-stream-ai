import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Brain, RefreshCw, AlertCircle, CheckCircle, Activity, BarChart2 } from 'lucide-react';

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

// Colour per feature group
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
  const [stats,      setStats]      = useState<MLStats | null>(null);
  const [features,   setFeatures]   = useState<FeatureItem[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [retraining, setRetraining] = useState(false);
  const [lastRefresh,setLastRefresh]= useState<Date | null>(null);
  const [tab,        setTab]        = useState<'overview' | 'features'>('overview');

  const fetchAll = async () => {
    try {
      const [sRes, fRes] = await Promise.all([
        fetch('/api/ml/stats'),
        fetch('/api/ml/feature-importance'),
      ]);
      const sData = await sRes.json();
      const fData = await fRes.json();
      setStats(sData);
      if (fData.available && fData.features) setFeatures(fData.features);
      setLastRefresh(new Date());
    } catch (e) {
      console.error('ML fetch failed', e);
    } finally {
      setLoading(false);
    }
  };

  const triggerRetrain = async () => {
    setRetraining(true);
    await fetch('/api/ml/retrain', { method: 'POST' });
    setTimeout(() => { fetchAll(); setRetraining(false); }, 70_000);
  };

  useEffect(() => {
    fetchAll();
    const iv = setInterval(fetchAll, 5 * 60 * 1000);
    return () => clearInterval(iv);
  }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-40">
      <Activity className="w-5 h-5 text-blue-400 animate-pulse" />
    </div>
  );

  const m = stats?.model;
  const p = stats?.paper_trades;
  const winRate  = p?.win_rate != null ? Math.round(p.win_rate * 100) : null;
  const auc      = m?.roc_auc ?? 0;
  const maxImp   = features[0]?.importance ?? 1;

  return (
    <div className="space-y-4 p-1">
      {/* Header + tabs */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-blue-400" />
          <span className="text-xs font-black text-slate-200 uppercase tracking-widest">ML Signal Model</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setTab('overview')}
            className={`px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest transition-colors ${tab === 'overview' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-500 hover:text-slate-300'}`}>
            Overview
          </button>
          <button onClick={() => setTab('features')}
            className={`px-2.5 py-1 rounded-lg text-[10px] font-black uppercase tracking-widest transition-colors ${tab === 'features' ? 'bg-blue-500/20 text-blue-400' : 'text-slate-500 hover:text-slate-300'}`}>
            Features
          </button>
          <button onClick={fetchAll} className="p-1.5 rounded-lg hover:bg-white/5 text-slate-500 hover:text-slate-300 transition-colors ml-1">
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* ── OVERVIEW TAB ── */}
      {tab === 'overview' && (
        <>
          {/* Model status card */}
          <div className="rounded-2xl border border-white/5 bg-slate-900/40 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Model Status</span>
              {m?.trained
                ? <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20"><CheckCircle className="w-3 h-3 text-emerald-400" /><span className="text-[9px] font-black text-emerald-400 uppercase tracking-widest">Trained</span></div>
                : <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-500/10 border border-amber-500/20"><AlertCircle className="w-3 h-3 text-amber-400" /><span className="text-[9px] font-black text-amber-400 uppercase tracking-widest">Not Trained</span></div>
              }
            </div>

            {m?.trained && (
              <>
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { label: 'Samples',  value: m.n_samples?.toLocaleString() ?? '—' },
                    { label: 'Accuracy', value: m.accuracy ? `${(m.accuracy * 100).toFixed(1)}%` : '—' },
                    { label: 'ROC AUC',  value: m.roc_auc?.toFixed(3) ?? '—' },
                  ].map(({ label, value }) => (
                    <div key={label} className="rounded-xl bg-white/5 p-2.5 text-center">
                      <div className="text-sm font-black text-slate-200 tabular-nums">{value}</div>
                      <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-0.5">{label}</div>
                    </div>
                  ))}
                </div>

                {/* AUC quality bar */}
                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-[9px] text-slate-500 uppercase tracking-widest">Model Quality</span>
                    <span className={`text-[9px] font-black uppercase tracking-widest ${auc >= 0.75 ? 'text-emerald-400' : auc >= 0.65 ? 'text-amber-400' : 'text-red-400'}`}>
                      {auc >= 0.75 ? 'Good' : auc >= 0.65 ? 'Fair' : 'Learning...'}
                    </span>
                  </div>
                  <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${Math.min((auc - 0.5) / 0.5 * 100, 100)}%` }} transition={{ duration: 0.8, ease: 'easeOut' }}
                      className={`h-full rounded-full ${auc >= 0.75 ? 'bg-emerald-500' : auc >= 0.65 ? 'bg-amber-500' : 'bg-red-500'}`} />
                  </div>
                  <div className="flex justify-between mt-0.5">
                    <span className="text-[8px] text-slate-600">Random (0.5)</span>
                    <span className="text-[8px] text-slate-600">Perfect (1.0)</span>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Paper trade win rate */}
          <div className="rounded-2xl border border-white/5 bg-slate-900/40 p-4 space-y-3">
            <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Live Paper Trade Results</span>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'Total',  value: p?.total_labeled ?? 0, color: 'text-slate-200' },
                { label: 'Wins',   value: p?.wins ?? 0,          color: 'text-emerald-400' },
                { label: 'Losses', value: p?.losses ?? 0,        color: 'text-red-400' },
              ].map(({ label, value, color }) => (
                <div key={label} className="rounded-xl bg-white/5 p-2.5 text-center">
                  <div className={`text-sm font-black tabular-nums ${color}`}>{value}</div>
                  <div className="text-[9px] text-slate-500 uppercase tracking-widest mt-0.5">{label}</div>
                </div>
              ))}
            </div>
            {winRate !== null ? (
              <div>
                <div className="flex justify-between mb-1">
                  <span className="text-[9px] text-slate-500 uppercase tracking-widest">Win Rate</span>
                  <span className={`text-[9px] font-black tabular-nums ${winRate >= 55 ? 'text-emerald-400' : winRate >= 45 ? 'text-amber-400' : 'text-red-400'}`}>{winRate}%</span>
                </div>
                <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                  <motion.div initial={{ width: 0 }} animate={{ width: `${winRate}%` }} transition={{ duration: 0.8 }}
                    className={`h-full rounded-full ${winRate >= 55 ? 'bg-emerald-500' : winRate >= 45 ? 'bg-amber-500' : 'bg-red-500'}`} />
                </div>
              </div>
            ) : (
              <p className="text-[10px] text-slate-500 text-center py-1">
                ยังไม่มี paper trade ที่ปิดแล้ว — เปิดออเดอร์เพื่อเริ่มเก็บข้อมูล
              </p>
            )}
          </div>
        </>
      )}

      {/* ── FEATURES TAB ── */}
      {tab === 'features' && (
        <div className="rounded-2xl border border-white/5 bg-slate-900/40 p-4 space-y-1">
          <div className="flex items-center gap-2 mb-3">
            <BarChart2 className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Feature Importance</span>
            {features.length > 0 && (
              <span className="ml-auto text-[9px] text-slate-600 font-mono">{features.length} features</span>
            )}
          </div>

          {/* Legend */}
          <div className="flex flex-wrap gap-2 mb-3">
            {[
              { label: 'Oscillator', color: 'bg-blue-500' },
              { label: 'Trend / EMA', color: 'bg-violet-500' },
              { label: 'Volume / Vol', color: 'bg-amber-500' },
              { label: 'Time', color: 'bg-teal-500' },
            ].map(({ label, color }) => (
              <div key={label} className="flex items-center gap-1">
                <div className={`w-2 h-2 rounded-full ${color} opacity-80`} />
                <span className="text-[8px] text-slate-500 uppercase tracking-widest">{label}</span>
              </div>
            ))}
          </div>

          {features.length === 0 ? (
            <p className="text-[10px] text-slate-500 text-center py-4">Train model ก่อนเพื่อดู feature importance</p>
          ) : (
            <div className="space-y-2">
              {features.slice(0, 15).map((f, i) => {
                const pct = (f.importance / maxImp) * 100;
                const impPct = (f.importance * 100).toFixed(2);
                return (
                  <motion.div key={f.feature}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: i * 0.04 }}
                    className="group"
                  >
                    <div className="flex items-center justify-between mb-0.5">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[8px] font-black text-slate-600 tabular-nums w-4">{i + 1}</span>
                        <span className="text-[10px] font-bold text-slate-300">{f.label}</span>
                        <span className={`text-[8px] px-1.5 py-0.5 rounded-full opacity-60 text-white ${featureColor(f.feature)}`}>
                          {featureGroupLabel(f.feature)}
                        </span>
                      </div>
                      <span className="text-[9px] font-black text-slate-400 tabular-nums font-mono">{impPct}%</span>
                    </div>
                    <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                      <motion.div
                        initial={{ width: 0 }}
                        animate={{ width: `${pct}%` }}
                        transition={{ duration: 0.6, delay: i * 0.04, ease: 'easeOut' }}
                        className={`h-full rounded-full ${featureColor(f.feature)}`}
                      />
                    </div>
                  </motion.div>
                );
              })}
            </div>
          )}

          {features.length > 0 && (
            <p className="text-[9px] text-slate-600 text-center pt-3">
              แสดง top 15 จาก {features.length} features · GradientBoosting impurity-based importance
            </p>
          )}
        </div>
      )}

      {/* Retrain button */}
      <button onClick={triggerRetrain} disabled={retraining}
        className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-2xl border border-blue-500/20 bg-blue-500/10 hover:bg-blue-500/20 text-blue-400 text-xs font-black uppercase tracking-widest transition-all disabled:opacity-50 disabled:cursor-not-allowed active:scale-95">
        {retraining
          ? <><RefreshCw className="w-3.5 h-3.5 animate-spin" />Retraining... (~60s)</>
          : <><Brain className="w-3.5 h-3.5" />Retrain Model ตอนนี้</>
        }
      </button>

      {lastRefresh && (
        <p className="text-[9px] text-slate-600 text-center">Updated {lastRefresh.toLocaleTimeString()}</p>
      )}
    </div>
  );
}
