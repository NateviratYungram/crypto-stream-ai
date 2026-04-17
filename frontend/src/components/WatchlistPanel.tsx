import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Plus, Trash2, TrendingUp, TrendingDown, Star, RefreshCcw } from 'lucide-react';

interface WatchItem {
  id:         number;
  symbol:     string;
  note?:      string;
  added_at?:  string;
  price?:     number | null;
  change_pct?: number | null;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';
const hdrs    = () => ({ 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' });

interface WatchlistPanelProps {
  onAnalyze?: (symbol: string) => void;
}

export const WatchlistPanel = ({ onAnalyze }: WatchlistPanelProps) => {
  const [items,   setItems]   = useState<WatchItem[]>([]);
  const [input,   setInput]   = useState('');
  const [note,    setNote]    = useState('');
  const [loading, setLoading] = useState(true);
  const [adding,  setAdding]  = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/watchlist', { headers: hdrs() });
      const d   = await res.json();
      setItems(d.watchlist || []);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); const t = setInterval(load, 60_000); return () => clearInterval(t); }, []);

  const add = async () => {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    setAdding(true);
    try {
      await fetch('/api/watchlist', {
        method: 'POST', headers: hdrs(),
        body: JSON.stringify({ symbol: sym, note })
      });
      setInput(''); setNote('');
      await load();
    } finally { setAdding(false); }
  };

  const remove = async (symbol: string) => {
    await fetch(`/api/watchlist/${symbol}`, { method: 'DELETE', headers: hdrs() });
    setItems(p => p.filter(i => i.symbol !== symbol));
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-yellow-500 font-bold text-xs uppercase tracking-[0.2em]">
            <Star className="w-3.5 h-3.5 fill-yellow-500" />
            My Watchlist
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">Watchlist</h2>
          <p className="text-slate-500 text-sm">Pin symbols — live price updates every 60s</p>
        </div>
        <button onClick={load} className="flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-yellow-500/40 rounded-xl text-slate-300 text-xs font-bold transition-all">
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {/* Add Symbol */}
      <div className="flex gap-3">
        <input
          value={input}
          onChange={e => setInput(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === 'Enter' && add()}
          placeholder="BTC, NVDA, GOLD, EURUSD..."
          className="flex-1 px-4 py-3 bg-slate-900/60 border border-white/10 rounded-2xl text-white text-sm font-bold placeholder:text-slate-600 focus:outline-none focus:border-yellow-500/40 transition-all"
        />
        <input
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="Note (optional)"
          className="w-48 px-4 py-3 bg-slate-900/60 border border-white/10 rounded-2xl text-white text-sm placeholder:text-slate-600 focus:outline-none focus:border-yellow-500/40 transition-all"
        />
        <button
          onClick={add}
          disabled={adding || !input.trim()}
          className="px-5 py-3 bg-yellow-500/10 border border-yellow-500/30 hover:border-yellow-500/60 rounded-2xl text-yellow-400 font-black text-sm transition-all disabled:opacity-40 flex items-center gap-2"
        >
          <Plus className="w-4 h-4" />
          Add
        </button>
      </div>

      {/* Watchlist Grid */}
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {[1,2,3,4].map(i => <div key={i} className="h-28 bg-slate-900/40 border border-white/5 rounded-2xl animate-pulse" />)}
        </div>
      ) : items.length === 0 ? (
        <div className="p-24 text-center space-y-3">
          <Star className="w-12 h-12 text-slate-700 mx-auto" />
          <p className="text-slate-500 font-bold">Watchlist ว่างอยู่</p>
          <p className="text-slate-600 text-sm">พิมพ์ symbol แล้วกด Add หรือ Enter</p>
        </div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          <AnimatePresence>
            {items.map((item, i) => {
              const up = (item.change_pct ?? 0) >= 0;
              return (
                <motion.div key={item.symbol}
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  transition={{ delay: i * 0.04 }}
                  className="relative group p-5 bg-slate-900/40 border border-white/5 hover:border-yellow-500/20 rounded-2xl transition-all cursor-pointer"
                  onClick={() => onAnalyze?.(item.symbol)}
                >
                  {/* Remove button */}
                  <button
                    onClick={e => { e.stopPropagation(); remove(item.symbol); }}
                    className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 p-1 text-slate-600 hover:text-rose-400 transition-all"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>

                  <div className="space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-black text-white text-base tracking-tight">{item.symbol}</span>
                      {item.change_pct != null && (
                        <span className={`flex items-center gap-1 text-[11px] font-black ${up ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {up ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                          {up ? '+' : ''}{item.change_pct.toFixed(2)}%
                        </span>
                      )}
                    </div>

                    <p className={`font-black font-mono text-xl ${up ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {item.price != null
                        ? `$${item.price.toLocaleString(undefined, { maximumFractionDigits: 4 })}`
                        : <span className="text-slate-600 text-base">Loading...</span>
                      }
                    </p>

                    {item.note && (
                      <p className="text-[11px] text-slate-600 font-bold truncate">{item.note}</p>
                    )}

                    <p className="text-[10px] text-slate-700 font-bold uppercase tracking-widest">
                      Tap to analyze →
                    </p>
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
