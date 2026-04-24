import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { RefreshCcw, TrendingUp, TrendingDown, Zap, AlertTriangle, HelpCircle } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

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
  const { theme } = useMode();

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
    <div className={`flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950' : 'bg-slate-50'
    }`}>
      {/* Header */}
      <header className={`flex justify-between items-center border-b pb-8 transition-colors duration-500 ${
        theme === 'dark' ? 'border-white/5' : 'border-slate-200'
      }`}>
        <div className="space-y-1">
          <div className={`font-bold text-xs uppercase tracking-[0.2em] flex items-center gap-2 ${
            theme === 'dark' ? 'text-amber-500' : 'text-amber-600'
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full animate-pulse ${theme === 'dark' ? 'bg-amber-500' : 'bg-amber-600'}`} />
            Perp Funding Monitor
          </div>
          <h2 className={`text-3xl font-extrabold tracking-tight ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Funding Rates</h2>
          <p className="text-slate-500 text-sm">
            อัตราค่าธรรมเนียม Futures รายชั่วโมง — อัพเดท {lastUpdated}
          </p>
        </div>
        <button onClick={fetch} className={`flex items-center gap-2 px-4 py-2 border rounded-xl text-xs font-bold transition-all ${
          theme === 'dark' ? 'bg-slate-900 border-white/10 hover:border-amber-500/40 text-slate-300' : 'bg-white border-slate-200 hover:border-amber-500/40 text-slate-600 shadow-sm'
        }`}>
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {/* Extremes Alert Banner */}
      {extremes.length > 0 && (
        <div className={`flex items-start gap-3 p-4 border rounded-2xl transition-colors duration-500 ${
          theme === 'dark' ? 'bg-amber-500/5 border-amber-500/20' : 'bg-amber-50 border-amber-200'
        }`}>
          <AlertTriangle className={`w-4 h-4 mt-0.5 shrink-0 ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`} />
          <div>
            <p className={`text-xs font-black uppercase tracking-widest mb-1 ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`}>Extreme Funding Detected</p>
            <p className={`text-sm ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>
              {extremes.map(r => `${r.symbol} (${r.rate_pct > 0 ? '+' : ''}${r.rate_pct.toFixed(3)}%)`).join(' · ')} — พิจารณา Contrarian Trade
            </p>
          </div>
        </div>
      )}

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Avg Funding (8h)',    value: rates.length ? `${(rates.reduce((s,r) => s+r.rate_pct,0)/rates.length).toFixed(4)}%` : '—', color: theme === 'dark' ? 'text-slate-300' : 'text-slate-700' },
          { label: 'Extreme (>0.2%)',     value: `${extremes.filter(r=>r.rate_pct>0).length} Long / ${extremes.filter(r=>r.rate_pct<0).length} Short`, color: theme === 'dark' ? 'text-amber-400' : 'text-amber-600' },
          { label: 'Contrarian Signals',  value: `${rates.filter(r=>r.signal!=='HOLD').length}`, color: theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600' },
        ].map((s,i) => (
          <div key={i} className={`p-4 border rounded-2xl transition-all duration-500 ${
            theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
          }`}>
            <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest mb-1">{s.label}</p>
            <p className={`text-base font-black font-mono ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className={`backdrop-blur-xl border rounded-[2rem] overflow-hidden shadow-2xl transition-all duration-500 ${
        theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-slate-200/40'
      }`}>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className={`border-b transition-colors duration-500 ${theme === 'dark' ? 'bg-slate-900/80 border-white/5' : 'bg-slate-50/80 border-slate-200'}`}>
              {['Symbol','Rate (8h)','Annualized','Mark Price','Sentiment','Signal'].map(h => (
                <th key={h} className="px-5 py-4 text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className={`divide-y transition-colors duration-500 ${theme === 'dark' ? 'divide-white/5' : 'divide-slate-100'}`}>
            {loading
              ? [1,2,3,4,5,6].map(i => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={6} className="px-5 py-5"><div className={`h-4 rounded-full w-full ${theme === 'dark' ? 'bg-slate-800/50' : 'bg-slate-200/50'}`} /></td>
                  </tr>
                ))
              : rates.map((r, i) => {
                  const isHigh = Math.abs(r.rate_pct) > 0.2;
                  const isPos  = r.rate_pct > 0;
                  return (
                    <motion.tr key={r.symbol}
                      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.03 }}
                      className={`transition-colors ${
                        theme === 'dark' 
                          ? `hover:bg-white/[0.02] ${isHigh ? 'bg-amber-500/[0.02]' : ''}` 
                          : `hover:bg-slate-50 ${isHigh ? 'bg-amber-50' : ''}`
                      }`}
                    >
                      <td className={`px-5 py-4 font-black ${theme === 'dark' ? 'text-slate-100' : 'text-slate-900'}`}>{r.symbol}</td>
                      <td className="px-5 py-4">
                        <span className={`font-black font-mono text-sm ${isHigh ? (isPos ? (theme === 'dark' ? 'text-rose-400' : 'text-rose-600') : (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600')) : 'text-slate-500'}`}>
                          {isPos ? '+' : ''}{r.rate_pct.toFixed(4)}%
                        </span>
                      </td>
                      <td className="px-5 py-4 font-mono text-sm text-slate-500">
                        {isPos ? '+' : ''}{r.annual_pct.toFixed(1)}% APR
                      </td>
                      <td className={`px-5 py-4 font-mono text-sm ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>
                        ${r.mark_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                      </td>
                      <td className="px-5 py-4">
                        <span className={`text-[11px] font-black uppercase tracking-widest ${
                          r.sentiment.includes('EXTREME') ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600')
                          : r.sentiment.includes('BULLISH') ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600')
                          : r.sentiment.includes('BEARISH') ? (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
                          : 'text-slate-500'
                        }`}>{r.sentiment}</span>
                      </td>
                      <td className="px-5 py-4">
                        {r.signal !== 'HOLD' ? (
                          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-xl text-[11px] font-black border ${
                            r.signal === 'CONTRARIAN SHORT'
                              ? (theme === 'dark' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-rose-50 border-rose-200 text-rose-600')
                              : (theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-600')
                          }`}>
                            {r.signal === 'CONTRARIAN SHORT' ? <TrendingDown className="w-3 h-3" /> : <TrendingUp className="w-3 h-3" />}
                            {r.signal}
                          </span>
                        ) : (
                          <span className="text-slate-500 text-[11px] font-black">HOLD</span>
                        )}
                      </td>
                    </motion.tr>
                  );
                })
            }
          </tbody>
        </table>
        {!loading && rates.length === 0 && (
          <div className="p-20 text-center"><Zap className="w-8 h-8 text-slate-500 mx-auto mb-3" /><p className="text-slate-500 font-bold">No data — Binance API unavailable</p></div>
        )}
      </div>
    </div>
  );
};
