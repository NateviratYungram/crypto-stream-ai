import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Trash2, TrendingUp, TrendingDown, Star, RefreshCcw } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

interface WatchItem {
  id:         number;
  symbol:     string;
  note?:      string;
  added_at?:  string;
  price?:     number | null;
  change_pct?: number | null;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || 'demo';
const hdrs    = () => ({ 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' });

interface WatchlistPanelProps {
  onAnalyze?: (symbol: string) => void;
}

export const WatchlistPanel: React.FC<WatchlistPanelProps> = ({ onAnalyze }) => {
  const [items,   setItems]   = useState<WatchItem[]>([]);
  const [input,   setInput]   = useState('');
  const [note,    setNote]    = useState('');
  const [loading, setLoading] = useState(false);
  const [adding,  setAdding]  = useState(false);
  const { theme } = useMode();


  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/watchlist', { headers: hdrs() });
      if (!res.ok) throw new Error(`Status ${res.status}`);
      const d   = await res.json();
      setItems(d.watchlist || []);
    } catch (err: any) {
      console.error("Watchlist load failed:", err);
    }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, []);

  const add = async () => {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    try {
      const res = await fetch('/api/watchlist', {
        method: 'POST', headers: hdrs(),
        body: JSON.stringify({ symbol: sym, note })
      });
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({ detail: 'Unknown error' }));
        alert(`Failed to add: ${errorData.detail || res.statusText}`);
        return;
      }
      setInput(''); setNote('');
      await load();
    } catch (err: any) {
      alert(`Network error: ${err.message}`);
    } finally { setAdding(false); }
  };

  const remove = async (symbol: string) => {
    try {
      const res = await fetch(`/api/watchlist/${symbol}`, { method: 'DELETE', headers: hdrs() });
      if (!res.ok) throw new Error(`Failed to delete: ${res.status}`);
      setItems(p => p.filter(i => i.symbol !== symbol));
      alert(`Removed ${symbol} from watchlist`); 
    } catch (err: any) {
      alert(err.message);
    }
  };

  return (
    <div className={`flex-1 p-5 md:p-8 overflow-y-auto space-y-6 custom-scrollbar transition-all duration-700 ${
      theme === 'dark' ? 'bg-[#020617]' : 'bg-slate-50'
    }`}>
      {/* Institutional Header */}
      <header className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-8 relative z-20">
        <div className="space-y-1">
          <motion.div 
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className={`flex items-center gap-2 font-black text-[9px] uppercase tracking-[0.3em] ${
              theme === 'dark' ? 'text-amber-400' : 'text-amber-600'
            }`}
          >
            <Star className="w-3 h-3 fill-current" />
            Asset Surveillance
          </motion.div>
          <h1 className={`text-3xl md:text-4xl font-black tracking-tighter uppercase italic leading-none ${
            theme === 'dark' ? 'text-white' : 'text-slate-950'
          }`}>
            Priority <span className={theme === 'dark' ? 'text-amber-500' : 'text-amber-600'}>Watchlist</span>
          </h1>
        </div>

        <button 
          onClick={load} 
          className={`group flex items-center gap-2 px-5 py-2.5 rounded-xl border font-black text-[9px] uppercase tracking-widest transition-all ${
            theme === 'dark' 
              ? 'bg-white/5 border-white/5 text-slate-400 hover:bg-white/10 hover:text-white' 
              : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-100 shadow-sm'
          }`}
        >
          <RefreshCcw className={`w-3.5 h-3.5 transition-transform duration-700 group-hover:rotate-180 ${loading ? 'animate-spin' : ''}`} />
          Synchronize Data
        </button>
      </header>

      {/* Deployment Control */}
      <div className={`p-1 rounded-[2rem] bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-yellow-500/20 ${
        theme === 'dark' ? '' : 'from-amber-100 via-orange-100 to-yellow-100'
      }`}>
        <div className={`flex flex-col md:flex-row gap-3 p-5 rounded-[1.95rem] ${
          theme === 'dark' ? 'bg-slate-900/80' : 'bg-white shadow-sm'
        }`}>
          <div className="flex-1 relative group">
            <input
              value={input}
              onChange={e => setInput(e.target.value.toUpperCase())}
              onKeyDown={e => e.key === 'Enter' && add()}
              placeholder="BTC, ETH, GOLD..."
              className={`relative w-full px-5 py-3 border rounded-xl font-mono text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/50 transition-all uppercase ${
                theme === 'dark' 
                  ? 'bg-slate-950 border-white/10 text-white placeholder:text-slate-700' 
                  : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400'
              }`}
            />
          </div>
          <input
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="Add Tactical Note..."
            className={`w-full md:w-56 px-5 py-3 border rounded-xl text-xs font-bold transition-all focus:outline-none ${
              theme === 'dark' 
                ? 'bg-slate-950 border-white/10 text-white placeholder:text-slate-700 focus:ring-2 focus:ring-amber-500/50' 
                : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400'
            }`}
          />
          <button
            onClick={add}
            disabled={adding || !input.trim()}
            className={`px-8 py-3 rounded-xl font-black text-[10px] uppercase tracking-[0.2em] transition-all disabled:opacity-40 flex items-center justify-center gap-2 ${
              theme === 'dark' 
                ? 'bg-amber-500 text-slate-950 hover:bg-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.2)]' 
                : 'bg-amber-600 text-white shadow-lg shadow-amber-600/20 hover:bg-amber-700'
            }`}
          >
            {adding ? <RefreshCcw className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            Deploy Target
          </button>
        </div>
      </div>

      {/* Asset Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {[1,2,3,4,5,6,7,8].map(i => (
            <div key={i} className={`h-48 rounded-[2.5rem] border animate-pulse ${
              theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-slate-200/50 border-slate-200'
            }`} />
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-32 text-center space-y-6">
          <div className={`w-20 h-20 rounded-[2rem] flex items-center justify-center border ${
            theme === 'dark' ? 'bg-white/5 border-white/5' : 'bg-slate-100 border-slate-200'
          }`}>
            <Star className={`w-10 h-10 ${theme === 'dark' ? 'text-slate-700' : 'text-slate-300'}`} />
          </div>
          <div className="space-y-2">
            <h3 className={`text-xl font-black uppercase italic ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Zero Surveillance Assets</h3>
            <p className="text-slate-500 text-sm max-w-xs">Initialize your primary trading dashboard by deploying asset tickers above.</p>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          <AnimatePresence mode="popLayout">
            {items.map((item, i) => {
              const up = (item.change_pct ?? 0) >= 0;
              return (
                <motion.div 
                  key={item.symbol}
                  initial={{ opacity: 0, y: 15 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ delay: i * 0.05 }}
                  className={`group relative p-5 rounded-[1.8rem] border backdrop-blur-3xl transition-all duration-500 cursor-pointer overflow-hidden ${
                    theme === 'dark' 
                      ? 'bg-slate-900/40 border-white/5 hover:border-amber-500/30 hover:bg-slate-900/60' 
                      : 'bg-white border-slate-200 hover:border-amber-400 shadow-md shadow-slate-200/40'
                  }`}
                  onClick={() => onAnalyze?.(item.symbol)}
                >
                  {/* Remove button */}
                  <button
                    onClick={e => { e.stopPropagation(); remove(item.symbol); }}
                    className="absolute bottom-4 right-4 p-2 text-rose-500 bg-rose-500/10 hover:bg-rose-500/20 rounded-xl transition-all z-30 shadow-sm"
                    title="Remove from surveillance"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>

                  <div className="space-y-4 relative z-10">
                    <div className="flex items-center justify-between">
                      <div className="space-y-0.5">
                        <span className={`text-xl font-black tracking-tighter italic uppercase ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                          {item.symbol}
                        </span>
                        <div className={`flex items-center gap-1 text-[8px] font-black uppercase tracking-widest ${up ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`}>
                          {up ? <TrendingUp className="w-2.5 h-2.5" /> : <TrendingDown className="w-2.5 h-2.5" />}
                          {up ? 'BULLISH' : 'BEARISH'}
                        </div>
                      </div>
                      <div className="text-right">
                        <p className={`text-xs font-black font-mono ${up ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`}>
                          {up ? '+' : ''}{item.change_pct?.toFixed(2)}%
                        </p>
                      </div>
                    </div>

                    <div className="space-y-0.5">
                      <p className="text-[8px] font-black text-slate-500 uppercase tracking-[0.2em]">Live Valuation</p>
                      <p className={`text-2xl font-black font-mono tracking-tighter ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                        {item.price != null
                          ? `$${item.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
                          : <span className="text-slate-700">---</span>
                        }
                      </p>
                    </div>

                    <div className={`pt-4 border-t ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                      {item.note ? (
                        <p className="text-[9px] text-slate-500 font-bold italic line-clamp-1">"{item.note}"</p>
                      ) : (
                        <p className="text-[8px] text-slate-700 font-black uppercase tracking-[0.2em]">Alpha Capture Ready</p>
                      )}
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      )}
    </div>
  );
};
