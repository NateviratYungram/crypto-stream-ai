import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { RefreshCcw, TrendingUp, TrendingDown, Zap, AlertTriangle, HelpCircle } from 'lucide-react';

interface FundingRow {
  symbol:     string;
  rate_pct:   number;
  annual_pct: number;
  mark_price: number;
  sentiment:  string;
  signal:     string;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';

export const FundingRatesView = () => {
  const [rates,   setRates]   = useState<FundingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState('');

  const fetch = async () => {
    setLoading(true);
    try {
      const res = await window.fetch('/api/market/funding-rates', {
        headers: { 'X-API-Key': API_KEY() }
      });
      const d = await res.json();
      setRates(d.rates || []);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { fetch(); const t = setInterval(fetch, 300_000); return () => clearInterval(t); }, []);

  const extremes = rates.filter(r => Math.abs(r.rate_pct) > 0.2);

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-amber-500 font-bold text-xs uppercase tracking-[0.2em]">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            Perp Funding Monitor
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">Funding Rates</h2>
          <p className="text-slate-500 text-sm">
            อัตราค่าธรรมเนียม Futures รายชั่วโมง — อัพเดท {lastUpdated}
          </p>
        </div>
        <button onClick={fetch} className="flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-amber-500/40 rounded-xl text-slate-300 text-xs font-bold transition-all">
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {/* Extremes Alert Banner */}
      {extremes.length > 0 && (
        <div className="flex items-start gap-3 p-4 bg-amber-500/5 border border-amber-500/20 rounded-2xl">
          <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-xs font-black text-amber-400 uppercase tracking-widest mb-1">Extreme Funding Detected</p>
            <p className="text-sm text-slate-300">
              {extremes.map(r => `${r.symbol} (${r.rate_pct > 0 ? '+' : ''}${r.rate_pct.toFixed(3)}%)`).join(' · ')} — พิจารณา Contrarian Trade
            </p>
          </div>
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Avg Funding (8h)',    value: rates.length ? `${(rates.reduce((s,r) => s+r.rate_pct,0)/rates.length).toFixed(4)}%` : '—', color: 'text-slate-300' },
          { label: 'Extreme (>0.2%)',     value: `${extremes.filter(r=>r.rate_pct>0).length} Long / ${extremes.filter(r=>r.rate_pct<0).length} Short`, color: 'text-amber-400' },
          { label: 'Contrarian Signals',  value: `${rates.filter(r=>r.signal!=='HOLD').length}`, color: 'text-emerald-400' },
        ].map((s,i) => (
          <div key={i} className="p-4 bg-slate-900/40 border border-white/5 rounded-2xl">
            <p className="text-[11px] font-black text-slate-600 uppercase tracking-widest mb-1">{s.label}</p>
            <p className={`text-base font-black font-mono ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="bg-slate-900/40 backdrop-blur-xl border border-white/5 rounded-[2rem] overflow-hidden shadow-2xl">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-900/80 border-b border-white/5">
              {['Symbol','Rate (8h)','Annualized','Mark Price','Sentiment','Signal'].map(h => (
                <th key={h} className="px-5 py-4 text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading
              ? [1,2,3,4,5,6].map(i => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={6} className="px-5 py-5"><div className="h-4 bg-slate-800/50 rounded-full w-full" /></td>
                  </tr>
                ))
              : rates.map((r, i) => {
                  const isHigh = Math.abs(r.rate_pct) > 0.2;
                  const isPos  = r.rate_pct > 0;
                  return (
                    <motion.tr key={r.symbol}
                      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.03 }}
                      className={`hover:bg-white/[0.02] transition-colors ${isHigh ? 'bg-amber-500/[0.02]' : ''}`}
                    >
                      <td className="px-5 py-4 font-black text-slate-100">{r.symbol}</td>
                      <td className="px-5 py-4">
                        <span className={`font-black font-mono text-sm ${isHigh ? (isPos ? 'text-rose-400' : 'text-emerald-400') : 'text-slate-400'}`}>
                          {isPos ? '+' : ''}{r.rate_pct.toFixed(4)}%
                        </span>
                      </td>
                      <td className="px-5 py-4 font-mono text-sm text-slate-400">
                        {isPos ? '+' : ''}{r.annual_pct.toFixed(1)}% APR
                      </td>
                      <td className="px-5 py-4 font-mono text-sm text-slate-300">
                        ${r.mark_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-5 py-4">
                        <span className={`text-[11px] font-black uppercase tracking-widest ${
                          r.sentiment.includes('EXTREME') ? 'text-amber-400'
                          : r.sentiment.includes('BULLISH') ? 'text-emerald-400'
                          : r.sentiment.includes('BEARISH') ? 'text-rose-400'
                          : 'text-slate-500'
                        }`}>{r.sentiment}</span>
                      </td>
                      <td className="px-5 py-4">
                        {r.signal !== 'HOLD' ? (
                          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-[11px] font-black border ${
                            r.signal === 'CONTRARIAN SHORT'
                              ? 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                              : 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                          }`}>
                            {r.signal === 'CONTRARIAN SHORT' ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
                            {r.signal}
                          </span>
                        ) : (
                          <span className="text-slate-600 text-[11px] font-black">HOLD</span>
                        )}
                      </td>
                    </motion.tr>
                  );
                })
            }
          </tbody>
        </table>
        {!loading && rates.length === 0 && (
          <div className="p-20 text-center"><Zap className="w-8 h-8 text-slate-600 mx-auto mb-3" /><p className="text-slate-500 font-bold">No data — Binance API unavailable</p></div>
        )}
      </div>
    </div>
  );
};
