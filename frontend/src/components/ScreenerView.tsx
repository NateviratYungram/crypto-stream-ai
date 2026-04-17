import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, SlidersHorizontal, TrendingUp, TrendingDown, Zap } from 'lucide-react';

interface ScreenerResult {
  symbol:         string;
  price:          number;
  rsi:            number;
  vol_ratio:      number;
  pct_from_52wh:  number;
  return_1w_pct:  number;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';

const UNIVERSES = ['NASDAQ100', 'SP500', 'CRYPTO'];

export const ScreenerView = () => {
  const [universe,     setUniverse]     = useState('NASDAQ100');
  const [rsiMin,       setRsiMin]       = useState('');
  const [rsiMax,       setRsiMax]       = useState('');
  const [volSpike,     setVolSpike]     = useState('');
  const [pct52wh,      setPct52wh]      = useState('');
  const [retMin,       setRetMin]       = useState('');
  const [retMax,       setRetMax]       = useState('');
  const [results,      setResults]      = useState<ScreenerResult[]>([]);
  const [loading,      setLoading]      = useState(false);
  const [ran,          setRan]          = useState(false);
  const [matchCount,   setMatchCount]   = useState(0);

  const run = async () => {
    setLoading(true); setRan(true);
    try {
      const params = new URLSearchParams({ universe });
      if (rsiMin)   params.set('rsi_min',       rsiMin);
      if (rsiMax)   params.set('rsi_max',       rsiMax);
      if (volSpike) params.set('vol_spike',     volSpike);
      if (pct52wh)  params.set('pct_from_52wh', pct52wh);
      if (retMin)   params.set('min_return_1w', retMin);
      if (retMax)   params.set('max_return_1w', retMax);

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
            Custom Filter Engine
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">Screener</h2>
          <p className="text-slate-500 text-sm">สแกน NASDAQ 100 · S&P 500 · Crypto ด้วย filter ที่ตั้งเอง</p>
        </div>
      </header>

      {/* Filter Panel */}
      <div className="p-6 bg-slate-900/40 border border-white/5 rounded-[2rem] space-y-5">
        {/* Universe */}
        <div className="space-y-2">
          <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Universe</p>
          <div className="flex gap-2">
            {UNIVERSES.map(u => (
              <button key={u} onClick={() => setUniverse(u)}
                className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
                  universe === u
                    ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                    : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
                }`}>
                {u}
              </button>
            ))}
          </div>
        </div>

        {/* Filters Grid */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <Field label="RSI Min"       val={rsiMin}   set={setRsiMin}   placeholder="e.g. 20" />
          <Field label="RSI Max"       val={rsiMax}   set={setRsiMax}   placeholder="e.g. 35" />
          <Field label="Vol Spike ×"   val={volSpike} set={setVolSpike} placeholder="e.g. 2.5" />
          <Field label="% from 52w Hi" val={pct52wh}  set={setPct52wh}  placeholder="e.g. 20" />
          <Field label="1w Return Min" val={retMin}   set={setRetMin}   placeholder="e.g. -5" />
          <Field label="1w Return Max" val={retMax}   set={setRetMax}   placeholder="e.g. 5" />
        </div>

        {/* Presets */}
        <div className="flex gap-2 flex-wrap items-center">
          <span className="text-[11px] font-black text-slate-600 uppercase tracking-widest">Presets:</span>
          {[
            { label: 'Oversold Bounce', apply: () => { setRsiMax('35'); setVolSpike('1.5'); setPct52wh('30'); setRsiMin(''); setRetMin(''); setRetMax(''); } },
            { label: 'Breakout Setup',  apply: () => { setVolSpike('3'); setRsiMin('50'); setRsiMax(''); setPct52wh(''); setRetMin('5'); setRetMax(''); } },
            { label: 'Momentum',        apply: () => { setRetMin('10'); setVolSpike('2'); setRsiMin('60'); setRsiMax(''); setPct52wh(''); setRetMax(''); } },
          ].map(p => (
            <button key={p.label} onClick={p.apply}
              className="px-3 py-1.5 text-[11px] font-black uppercase tracking-widest border border-white/10 rounded-xl text-slate-500 hover:text-white hover:border-blue-500/30 transition-all">
              {p.label}
            </button>
          ))}
          <button onClick={() => { setRsiMin(''); setRsiMax(''); setVolSpike(''); setPct52wh(''); setRetMin(''); setRetMax(''); }}
            className="px-3 py-1.5 text-[11px] font-black uppercase tracking-widest border border-rose-500/20 rounded-xl text-rose-500/60 hover:text-rose-400 transition-all ml-auto">
            Clear
          </button>
        </div>

        <button onClick={run} disabled={loading}
          className="w-full flex items-center justify-center gap-3 py-4 bg-blue-600/20 border border-blue-500/30 hover:border-blue-500/60 rounded-2xl text-blue-400 font-black text-sm transition-all disabled:opacity-50">
          <Search className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? `Scanning ${universe}...` : `Scan ${universe}`}
        </button>
      </div>

      {/* Results */}
      {ran && (
        <div className="bg-slate-900/40 border border-white/5 rounded-[2rem] overflow-hidden">
          <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between">
            <p className="text-sm font-black text-slate-300">
              Found <span className="text-blue-400">{matchCount}</span> matches
            </p>
            {results.length > 0 && (
              <p className="text-[11px] text-slate-600 font-bold uppercase tracking-widest">Sorted by Volume Spike</p>
            )}
          </div>
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/5">
                {['Symbol','Price','RSI','Vol ×','% from 52wH','1w Return'].map(h => (
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
                      <p className="text-slate-500 font-bold">ไม่พบ symbol ที่ตรง filter</p>
                      <p className="text-slate-600 text-sm mt-1">ลอง relax เงื่อนไข หรือเปลี่ยน universe</p>
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
