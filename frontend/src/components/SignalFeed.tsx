import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus, Eye, Zap } from 'lucide-react';

interface Signal {
  symbol: string;
  direction: 'BUY' | 'SELL' | 'HOLD' | 'WATCH';
  confidence: number;
  reason: string;
  price: number;
  delta_pct: number;
  vol_surge: number;
  timestamp: string;
}

const directionConfig = {
  BUY:   { color: 'emerald', icon: TrendingUp,   label: 'LONG',  bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400' },
  SELL:  { color: 'rose',    icon: TrendingDown,  label: 'SHORT', bg: 'bg-rose-500/10',    border: 'border-rose-500/30',    text: 'text-rose-400'    },
  HOLD:  { color: 'amber',   icon: Minus,         label: 'HOLD',  bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-400'   },
  WATCH: { color: 'blue',    icon: Eye,           label: 'WATCH', bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    text: 'text-blue-400'    },
};

export const SignalFeed = () => {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  const fetchSignals = async () => {
    try {
      const res = await fetch('/api/signals');
      const json = await res.json();
      setSignals(json.signals || []);
      setLastRefresh(new Date());
    } catch (err) {
      console.error('Signal fetch error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSignals();
    // Poll every 30 seconds
    const interval = setInterval(fetchSignals, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Zap className="w-4 h-4 text-yellow-400 glow-bloom" />
          <h3 className="text-[11px] font-black text-white uppercase tracking-widest">AI Signal Feed</h3>
        </div>
        <span className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">
          {lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </span>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto custom-scrollbar pr-1">
        {loading ? (
          [1,2,3].map(i => (
            <div key={i} className="h-20 bg-slate-900/40 animate-pulse rounded-2xl border border-white/5" />
          ))
        ) : signals.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-center">
            <p className="text-[10px] text-slate-600 font-bold uppercase tracking-widest">No signals generated</p>
            <p className="text-[9px] text-slate-700 mt-1">Insufficient data in last 10 minutes</p>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {signals.map((signal, i) => {
              const cfg = directionConfig[signal.direction];
              const Icon = cfg.icon;
              return (
                <motion.div
                  key={signal.symbol + signal.timestamp}
                  initial={{ opacity: 0, x: -12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={`p-4 rounded-2xl border ${cfg.bg} ${cfg.border} relative overflow-hidden group cursor-default`}
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <div className={`p-1.5 rounded-lg ${cfg.bg} border ${cfg.border}`}>
                        <Icon className={`w-3.5 h-3.5 ${cfg.text}`} />
                      </div>
                      <div>
                        <span className="text-sm font-black text-white tracking-tight">{signal.symbol}</span>
                        <span className={`ml-2 text-[9px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded ${cfg.bg} ${cfg.text} border ${cfg.border}`}>
                          {cfg.label}
                        </span>
                      </div>
                    </div>
                    {/* Confidence bar */}
                    <div className="text-right">
                      <span className={`text-sm font-black font-mono ${cfg.text}`}>{signal.confidence}%</span>
                      <div className="w-16 h-1 bg-slate-800 rounded-full mt-1 overflow-hidden">
                        <motion.div
                          initial={{ width: 0 }}
                          animate={{ width: `${signal.confidence}%` }}
                          transition={{ duration: 0.8 }}
                          className={`h-full rounded-full ${
                            signal.direction === 'BUY' ? 'bg-emerald-500' :
                            signal.direction === 'SELL' ? 'bg-rose-500' :
                            signal.direction === 'HOLD' ? 'bg-amber-500' : 'bg-blue-500'
                          }`}
                        />
                      </div>
                    </div>
                  </div>

                  <p className="text-[10px] text-slate-400 leading-relaxed font-medium line-clamp-2">{signal.reason}</p>

                  <div className="flex items-center gap-4 mt-2">
                    <span className="text-[9px] font-mono text-slate-500">
                      ${signal.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                    </span>
                    <span className={`text-[9px] font-bold font-mono ${signal.delta_pct >= 0 ? 'text-emerald-500' : 'text-rose-500'}`}>
                      {signal.delta_pct >= 0 ? '+' : ''}{signal.delta_pct.toFixed(3)}%
                    </span>
                    <span className="text-[9px] text-slate-600 font-bold">Vol ×{signal.vol_surge}</span>
                  </div>

                  {/* Shine effect on hover */}
                  <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.02] to-transparent opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none" />
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
};
