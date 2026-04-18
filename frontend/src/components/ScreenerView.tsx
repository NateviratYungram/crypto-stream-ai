import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, SlidersHorizontal, TrendingUp, TrendingDown, Zap } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';

interface ScreenerResult {
  symbol:         string;
  price:          number;
  rsi:            number;
  vol_ratio:      number;
  pct_from_52wh:  number;
  return_1w_pct:  number;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';

const UNIVERSES = ['NASDAQ100', 'SP500', 'CRYPTO', 'SMALL_CAP', 'CUSTOM'];

export const ScreenerView = () => {
  const { t } = useLanguage();
  const [universe,      setUniverse]      = useState('NASDAQ100');
  const [rsiMin,        setRsiMin]        = useState('');
  const [rsiMax,        setRsiMax]        = useState('');
  const [volSpike,      setVolSpike]      = useState('');
  const [pct52wh,       setPct52wh]       = useState('');
  const [retMin,        setRetMin]        = useState('');
  const [retMax,        setRetMax]        = useState('');
  const [customTickers, setCustomTickers] = useState('');
  const [results,       setResults]       = useState<ScreenerResult[]>([]);
  const [loading,       setLoading]       = useState(false);
  const [ran,           setRan]           = useState(false);
  const [matchCount,    setMatchCount]    = useState(0);

  const run = async (overrides?: { rsiMin?: string; rsiMax?: string; volSpike?: string; pct52wh?: string; retMin?: string; retMax?: string; universe?: string }) => {
    const _uni      = overrides?.universe  ?? universe;
    const _rsiMin   = overrides?.rsiMin    ?? rsiMin;
    const _rsiMax   = overrides?.rsiMax    ?? rsiMax;
    const _volSpike = overrides?.volSpike  ?? volSpike;
    const _pct52wh  = overrides?.pct52wh   ?? pct52wh;
    const _retMin   = overrides?.retMin    ?? retMin;
    const _retMax   = overrides?.retMax    ?? retMax;

    setLoading(true); setRan(true);
    try {
      const params = new URLSearchParams({ universe: _uni });
      if (_rsiMin)      params.set('rsi_min',        _rsiMin);
      if (_rsiMax)      params.set('rsi_max',        _rsiMax);
      if (_volSpike)    params.set('vol_spike',      _volSpike);
      if (_pct52wh)     params.set('pct_from_52wh',  _pct52wh);
      if (_retMin)      params.set('min_return_1w',  _retMin);
      if (_retMax)      params.set('max_return_1w',  _retMax);
      if (_uni === 'CUSTOM' && customTickers) params.set('custom_tickers', customTickers);

      const res = await fetch(`/api/screener?${params}`, { headers: { 'X-API-Key': API_KEY() } });
      const d   = await res.json();
      setResults(d.results || []);
      setMatchCount(d.match_count ?? 0);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  const Field = ({ label, val, set, placeholder }: { label: string; val: string; set: (v:string)=>void; placeholder: string }) => (
    <div className="space-y-1.5">
      <label className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{label}</label>
      <input
        value={val} onChange={e => set(e.target.value)} placeholder={placeholder}
        className="w-full px-3 py-2.5 bg-slate-900/60 border border-white/10 rounded-xl text-white text-sm font-mono placeholder:text-slate-700 focus:outline-none focus:border-blue-500/40 transition-all"
      />
    </div>
  );

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-blue-500 font-bold text-xs uppercase tracking-[0.2em]">
            <SlidersHorizontal className="w-3.5 h-3.5" />
            {t('screener.badge')}
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">{t('screener.title')}</h2>
          <p className="text-slate-500 text-sm">{t('screener.subtitle')}</p>
        </div>
      </header>

      {/* Disclaimer */}
      <div className="flex items-center gap-2 px-4 py-2.5 bg-slate-900/40 border border-white/5 rounded-xl">
        <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
        <p className="text-xs text-slate-500">{t('screener.disclaimer')}</p>
      </div>

      {/* Filter Panel */}
      <div className="p-6 bg-slate-900/40 border border-white/5 rounded-[2rem] space-y-5">
        {/* Universe */}
        <div className="space-y-2">
          <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{t('screener.universe')}</p>
          <div className="flex gap-2 flex-wrap">
            {UNIVERSES.map(u => (
              <button key={u} onClick={() => setUniverse(u)}
                className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
                  universe === u
                    ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                    : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
                }`}>
                {u === 'SMALL_CAP' ? t('screener.small_cap') : u}
              </button>
            ))}
          </div>
          {universe === 'CUSTOM' && (
            <div className="space-y-1.5 mt-2">
              <label className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{t('screener.custom_tickers')}</label>
              <input
                value={customTickers}
                onChange={e => setCustomTickers(e.target.value)}
                placeholder="e.g. EOSE, RKLB, IONQ, ASTS"
                className="w-full px-3 py-2.5 bg-slate-900/60 border border-blue-500/20 rounded-xl text-white text-sm font-mono placeholder:text-slate-700 focus:outline-none focus:border-blue-500/40 transition-all"
              />
            </div>
          )}
        </div>

        {/* Filters Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <Field label={t('screener.rsi_min')}   val={rsiMin}   set={setRsiMin}   placeholder="e.g. 20" />
          <Field label={t('screener.rsi_max')}   val={rsiMax}   set={setRsiMax}   placeholder="e.g. 35" />
          <Field label={t('screener.vol_spike')} val={volSpike} set={setVolSpike} placeholder="e.g. 2.5" />
          <Field label={t('screener.pct_52w')}   val={pct52wh}  set={setPct52wh}  placeholder="e.g. 20" />
          <Field label={t('screener.ret_min')}   val={retMin}   set={setRetMin}   placeholder="e.g. -5" />
          <Field label={t('screener.ret_max')}   val={retMax}   set={setRetMax}   placeholder="e.g. 5" />
        </div>

        {/* Presets */}
        <div className="flex gap-2 flex-wrap items-center">
          <span className="text-[11px] font-black text-slate-600 uppercase tracking-widest">{t('screener.presets')}</span>
          {[
            { label: t('screener.preset_oversold'), filters: { rsiMax: '45', volSpike: '1.2', pct52wh: '40', rsiMin: '', retMin: '', retMax: '' } },
            { label: t('screener.preset_breakout'), filters: { volSpike: '2', rsiMin: '50', rsiMax: '', pct52wh: '', retMin: '3', retMax: '' } },
            { label: t('screener.preset_momentum'), filters: { retMin: '5', volSpike: '1.5', rsiMin: '55', rsiMax: '', pct52wh: '', retMax: '' } },
          ].map(p => (
            <button key={p.label} onClick={() => {
              setRsiMin(p.filters.rsiMin); setRsiMax(p.filters.rsiMax);
              setVolSpike(p.filters.volSpike); setPct52wh(p.filters.pct52wh);
              setRetMin(p.filters.retMin); setRetMax(p.filters.retMax);
              run(p.filters);
            }}
              className="px-3 py-1.5 text-[11px] font-black uppercase tracking-widest border border-white/10 rounded-xl text-slate-500 hover:text-white hover:border-blue-500/30 transition-all">
              {p.label}
            </button>
          ))}
          <button onClick={() => { setRsiMin(''); setRsiMax(''); setVolSpike(''); setPct52wh(''); setRetMin(''); setRetMax(''); }}
            className="px-3 py-1.5 text-[11px] font-black uppercase tracking-widest border border-rose-500/20 rounded-xl text-rose-500/60 hover:text-rose-400 transition-all ml-auto">
            {t('screener.clear')}
          </button>
        </div>

        <button onClick={() => run()} disabled={loading}
          className="w-full flex items-center justify-center gap-3 py-4 bg-blue-600/20 border border-blue-500/30 hover:border-blue-500/60 rounded-2xl text-blue-400 font-black text-sm transition-all disabled:opacity-50">
          <Search className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? `${t('screener.scanning')} ${universe}...` : `${t('screener.scan')} ${universe}`}
        </button>
      </div>

      {/* Results */}
      {ran && (
        <div className="bg-slate-900/40 border border-white/5 rounded-[2rem] overflow-hidden">
          <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
            <p className="text-sm font-black text-slate-300">
              {t('screener.found')} <span className="text-blue-400">{matchCount}</span> {t('screener.matches')}
            </p>
            {results.length > 0 && (
              <p className="text-[11px] text-slate-600 font-bold uppercase tracking-widest">{t('screener.sorted_by')}</p>
            )}
          </div>
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/5">
                {[t('screener.symbol'),t('screener.price'),t('screener.rsi_col'),t('screener.vol_col'),t('screener.pct_col'),t('screener.ret_col')].map(h => (
                  <th key={h} className="px-5 py-4 text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              <AnimatePresence>
                {loading
                  ? [1,2,3].map(i => <tr key={i} className="animate-pulse"><td colSpan={6} className="px-5 py-5"><div className="h-4 bg-slate-800/50 rounded-full" /></td></tr>)
                  : results.length === 0
                  ? (
                    <tr><td colSpan={6} className="px-5 py-20 text-center">
                      <Zap className="w-8 h-8 text-slate-600 mx-auto mb-3" />
                      <p className="text-slate-500 font-bold">{t('screener.no_results')}</p>
                      <p className="text-slate-600 text-sm mt-1">{t('screener.relax')}</p>
                    </td></tr>
                  )
                  : results.map((r, i) => {
                    const retUp = r.return_1w_pct >= 0;
                    const rsiColor = r.rsi < 30 ? 'text-emerald-400' : r.rsi > 70 ? 'text-rose-400' : 'text-slate-300';
                    return (
                      <motion.tr key={r.symbol}
                        initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: i * 0.04 }}
                        className="hover:bg-white/[0.02] transition-colors">
                        <td className="px-5 py-4 font-black text-white">{r.symbol}</td>
                        <td className="px-5 py-4 font-mono text-sm text-slate-300">${r.price.toLocaleString()}</td>
                        <td className="px-5 py-4 font-mono text-sm">
                          <span className={`font-black ${rsiColor}`}>{r.rsi.toFixed(1)}</span>
                        </td>
                        <td className="px-5 py-4 font-mono text-sm">
                          <span className={`font-black ${r.vol_ratio >= 3 ? 'text-amber-400' : r.vol_ratio >= 2 ? 'text-blue-400' : 'text-slate-400'}`}>
                            {r.vol_ratio.toFixed(1)}×
                          </span>
                        </td>
                        <td className="px-5 py-4 font-mono text-sm text-slate-400">{r.pct_from_52wh.toFixed(1)}%</td>
                        <td className="px-5 py-4">
                          <span className={`flex items-center gap-1 font-black font-mono text-sm ${retUp ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {retUp ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                            {retUp ? '+' : ''}{r.return_1w_pct.toFixed(2)}%
                          </span>
                        </td>
                      </motion.tr>
                    );
                  })
                }
              </AnimatePresence>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
