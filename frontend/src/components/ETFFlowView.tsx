import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ArrowUpRight, ArrowDownRight, RefreshCcw, BarChart2, Minus } from 'lucide-react';

interface FlowRow {
  symbol:         string;
  price:          number;
  return_5d_pct:  number;
  vol_ratio:      number;
  flow_signal:    string;
  flow_dir:       string;
}

interface FlowData {
  flows:          FlowRow[];
  top_inflows:    FlowRow[];
  top_outflows:   FlowRow[];
  market_theme:   string;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';

const sigColor = (s: string) =>
  s === 'INFLOW'  ? 'text-emerald-400' :
  s === 'OUTFLOW' ? 'text-rose-400'    : 'text-slate-500';

const sigBg = (s: string) =>
  s === 'INFLOW'  ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' :
  s === 'OUTFLOW' ? 'bg-rose-500/10    border-rose-500/20    text-rose-400'    :
                   'bg-slate-800/40    border-white/10       text-slate-500';

export const ETFFlowView = () => {
  const [data,    setData]    = useState<FlowData | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab,     setTab]     = useState<'ALL' | 'INFLOW' | 'OUTFLOW'>('ALL');

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/market/etf-flows', { headers: { 'X-API-Key': API_KEY() } });
      setData(await res.json());
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); const t = setInterval(load, 3600_000); return () => clearInterval(t); }, []);

  const rows = (data?.flows || []).filter(r =>
    tab === 'ALL' || r.flow_signal === tab
  );

  const themeColor =
    data?.market_theme?.includes('RISK ON')  ? 'text-emerald-400' :
    data?.market_theme?.includes('RISK OFF') ? 'text-rose-400'    : 'text-amber-400';

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-pink-400 font-bold text-xs uppercase tracking-[0.2em]">
            <BarChart2 className="w-3.5 h-3.5" />
            Institutional ETF Monitor
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">ETF Flows</h2>
          <p className="text-slate-500 text-sm">Track fund inflows/outflows: SPY · QQQ · GLD · IBIT · TQQQ · SOXL</p>
        </div>
        <button onClick={load} className="flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-pink-500/40 rounded-xl text-slate-300 text-xs font-bold transition-all">
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {/* Market Theme */}
      {data?.market_theme && (
        <div className={`p-4 bg-slate-900/40 border border-white/5 rounded-2xl`}>
          <p className="text-[11px] font-black text-slate-600 uppercase tracking-widest mb-1">Market Theme (5-Day)</p>
          <p className={`font-black text-lg ${themeColor}`}>{data.market_theme}</p>
        </div>
      )}

      {/* Top Cards */}
      <div className="grid grid-cols-2 gap-6">
        {[
          { title: 'Top Inflows',  items: data?.top_inflows  || [], up: true  },
          { title: 'Top Outflows', items: data?.top_outflows || [], up: false },
        ].map(({ title, items, up }) => (
          <div key={title} className="p-5 bg-slate-900/40 border border-white/5 rounded-2xl space-y-3">
            <p className={`text-xs font-black uppercase tracking-widest ${up ? 'text-emerald-400' : 'text-rose-400'}`}>{title}</p>
            {items.length === 0 && !loading && <p className="text-slate-600 text-sm font-bold">No data</p>}
            {items.map(r => (
              <div key={r.symbol} className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {up ? <ArrowUpRight className="w-4 h-4 text-emerald-400" /> : <ArrowDownRight className="w-4 h-4 text-rose-400" />}
                  <span className="font-black text-white text-sm">{r.symbol}</span>
                </div>
                <div className="text-right">
                  <p className={`font-black font-mono text-sm ${r.return_5d_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {r.return_5d_pct >= 0 ? '+' : ''}{r.return_5d_pct.toFixed(2)}%
                  </p>
                  <p className="text-[10px] text-slate-600 font-bold">Vol {r.vol_ratio.toFixed(1)}×</p>
                </div>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2">
        {(['ALL','INFLOW','OUTFLOW'] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
              tab === t
                ? t === 'INFLOW'  ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-400'
                : t === 'OUTFLOW' ? 'bg-rose-600/20    border-rose-500/40    text-rose-400'
                                  : 'bg-pink-600/20   border-pink-500/40    text-pink-400'
                : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
            }`}>{t}</button>
        ))}
      </div>

      {/* Full Table */}
      <div className="bg-slate-900/40 border border-white/5 rounded-[2rem] overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-900/80 border-b border-white/5">
              {['ETF','Price','5d Return','Vol Ratio','Flow Signal'].map(h => (
                <th key={h} className="px-5 py-4 text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading
              ? [1,2,3,4,5].map(i => <tr key={i} className="animate-pulse"><td colSpan={5} className="px-5 py-5"><div className="h-4 bg-slate-800/50 rounded-full" /></td></tr>)
              : rows.map((r, i) => (
                <motion.tr key={r.symbol}
                  initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: i * 0.03 }}
                  className="hover:bg-white/[0.02] transition-colors">
                  <td className="px-5 py-4 font-black text-white">{r.symbol}</td>
                  <td className="px-5 py-4 font-mono text-sm text-slate-300">${r.price.toLocaleString()}</td>
                  <td className="px-5 py-4">
                    <span className={`font-black font-mono text-sm ${r.return_5d_pct >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {r.return_5d_pct >= 0 ? '+' : ''}{r.return_5d_pct.toFixed(2)}%
                    </span>
                  </td>
                  <td className="px-5 py-4 font-mono text-sm">
                    <span className={r.vol_ratio >= 2 ? 'text-amber-400 font-black' : 'text-slate-400'}>{r.vol_ratio.toFixed(1)}×</span>
                  </td>
                  <td className="px-5 py-4">
                    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-xl text-[11px] font-black border ${sigBg(r.flow_signal)}`}>
                      {r.flow_signal === 'INFLOW'  && <ArrowUpRight className="w-3 h-3" />}
                      {r.flow_signal === 'OUTFLOW' && <ArrowDownRight className="w-3 h-3" />}
                      {r.flow_signal === 'NEUTRAL' && <Minus className="w-3 h-3" />}
                      {r.flow_signal}
                    </span>
                  </td>
                </motion.tr>
              ))
            }
          </tbody>
        </table>
      </div>
    </div>
  );
};
