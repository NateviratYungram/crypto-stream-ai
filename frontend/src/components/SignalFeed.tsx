import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus, Eye, Zap } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { useWebSocket } from '../hooks/useWebSocket';

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

const getDirectionConfig = (dir: string, theme: 'light' | 'dark') => {
  const isDark = theme === 'dark';
  const configs: any = {
    BUY: {
      icon: TrendingUp,
      label: 'LONG',
      bg: isDark ? 'bg-emerald-500/10' : 'bg-emerald-50',
      border: isDark ? 'border-emerald-500/30' : 'border-emerald-200',
      text: isDark ? 'text-emerald-400' : 'text-emerald-600',
    },
    SELL: {
      icon: TrendingDown,
      label: 'SHORT',
      bg: isDark ? 'bg-rose-500/10' : 'bg-rose-50',
      border: isDark ? 'border-rose-500/30' : 'border-rose-200',
      text: isDark ? 'text-rose-400' : 'text-rose-600',
    },
    HOLD: {
      icon: Minus,
      label: 'HOLD',
      bg: isDark ? 'bg-amber-500/10' : 'bg-amber-50',
      border: isDark ? 'border-amber-500/30' : 'border-amber-200',
      text: isDark ? 'text-amber-400' : 'text-amber-600',
    },
    WATCH: {
      icon: Eye,
      label: 'WATCH',
      bg: isDark ? 'bg-blue-500/10' : 'bg-blue-50',
      border: isDark ? 'border-blue-500/30' : 'border-blue-200',
      text: isDark ? 'text-blue-400' : 'text-blue-600',
    },
  };
  return configs[dir] || configs.HOLD;
};

export const SignalFeed = ({
  bootstrapSignals = [],
  skipInitialFetch = false,
}: {
  bootstrapSignals?: Signal[]
  skipInitialFetch?: boolean
}) => {
  const { theme } = useMode();
  const { lastMessage } = useWebSocket();
  const [signals, setSignals] = useState<Signal[]>(bootstrapSignals);
  const [loading, setLoading] = useState(bootstrapSignals.length === 0);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());

  // One-shot HTTP fetch on mount (fast first load before WS warms up)
  useEffect(() => {
    if (bootstrapSignals.length > 0) {
      setSignals(bootstrapSignals);
      setLastRefresh(new Date());
      setLoading(false);
      return;
    }
    if (skipInitialFetch) {
      setLoading(false);
      return;
    }
    fetch('/api/signals')
      .then(r => r.json())
      .then(json => {
        if (json.signals?.length > 0) setSignals(json.signals);
      })
      .catch(err => console.error('Signal initial fetch error:', err))
      .finally(() => setLoading(false));
  }, [bootstrapSignals, skipInitialFetch]);

  // Real-time WebSocket updates — fires every ~15s from signal_broadcaster_task
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'SIGNALS') return;
    const incoming: Signal[] = lastMessage.data?.signals ?? [];
    if (incoming.length > 0) {
      setSignals(incoming);
      setLastRefresh(new Date());
      setLoading(false);
    }
  }, [lastMessage]);

  return (
    <div className="flex flex-col h-full space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          <h3 className={`text-[11px] font-black uppercase tracking-[0.3em] transition-colors ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>Neural Signal Stream</h3>
        </div>
        <div className={`px-3 py-1 rounded-full border text-[9px] font-black uppercase tracking-widest ${
          theme === 'dark' ? 'bg-white/5 border-white/5 text-slate-500' : 'bg-slate-50 border-slate-200 text-slate-400'
        }`}>
          {lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto custom-scrollbar pr-2">
        {loading ? (
          [1, 2, 3, 4].map(i => (
            <div key={i} className={`h-24 animate-pulse rounded-[1.5rem] border ${
              theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-slate-50 border-slate-200'
            }`} />
          ))
        ) : signals.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
            <div className={`w-12 h-12 rounded-2xl flex items-center justify-center border ${
              theme === 'dark' ? 'bg-white/5 border-white/5' : 'bg-slate-50 border-slate-200'
            }`}>
              <Minus className="w-6 h-6 text-slate-700" />
            </div>
            <div className="space-y-1">
              <p className="text-[10px] text-slate-500 font-black uppercase tracking-widest">Awaiting Volatility</p>
              <p className="text-[9px] text-slate-700 font-bold uppercase tracking-widest">Model scan in progress...</p>
            </div>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {signals.map((signal, i) => {
              const cfg = getDirectionConfig(signal.direction, theme);
              const Icon = cfg.icon;
              return (
                <motion.div
                  key={signal.symbol + signal.timestamp}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={`p-4 rounded-[1.4rem] border backdrop-blur-2xl transition-all duration-500 group relative overflow-hidden ${
                    theme === 'dark' 
                      ? 'bg-slate-900/40 border-white/5 hover:border-white/10' 
                      : 'bg-white border-slate-200 shadow-sm hover:shadow-md'
                  }`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className={`p-1.5 rounded-lg border transition-all duration-500 ${cfg.bg} ${cfg.border}`}>
                        <Icon className={`w-3.5 h-3.5 ${cfg.text}`} />
                      </div>
                      <div className="space-y-0">
                        <span className={`text-sm font-black tracking-tighter italic uppercase ${
                          theme === 'dark' ? 'text-white' : 'text-slate-950'
                        }`}>{signal.symbol}</span>
                        <div className={`flex items-center gap-1 text-[7px] font-black uppercase tracking-widest ${cfg.text}`}>
                          <div className={`w-1 h-1 rounded-full bg-current ${signal.direction !== 'HOLD' ? 'animate-pulse' : ''}`} />
                          {cfg.label}
                        </div>
                      </div>
                    </div>
                    
                    <div className="text-right space-y-0.5">
                      <p className={`text-base font-black font-mono leading-none ${cfg.text}`}>
                        {signal.confidence}%
                      </p>
                      <p className="text-[7px] font-black text-slate-600 uppercase tracking-widest">Conf</p>
                    </div>
                  </div>

                  <p className={`text-[9px] leading-relaxed font-bold mb-3 line-clamp-2 italic ${
                    theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
                  }`}>
                    "{signal.reason}"
                  </p>

                  <div className={`flex items-center justify-between pt-3 border-t ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                    <div className="flex items-center gap-3">
                      <span className={`text-[9px] font-black font-mono ${theme === 'dark' ? 'text-slate-200' : 'text-slate-900'}`}>
                        ${signal.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </span>
                      <span className={`text-[9px] font-black font-mono ${ (signal.delta_pct ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500' }`}>
                        {(signal.delta_pct ?? 0) >= 0 ? '+' : ''}{(signal.delta_pct ?? 0).toFixed(3)}%
                      </span>
                    </div>
                    <div className={`px-1.5 py-0.5 rounded-lg text-[7px] font-black uppercase tracking-widest ${
                      theme === 'dark' ? 'bg-white/5 text-slate-500' : 'bg-slate-50 text-slate-400'
                    }`}>
                      ×{(signal.vol_surge ?? 1.0).toFixed(2)}
                    </div>
                  </div>

                  {/* Confidence Bar Underlay */}
                  <div className="absolute bottom-0 left-0 w-full h-[2px] bg-white/5 overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${signal.confidence}%` }}
                      className={`h-full ${
                        signal.direction === 'BUY' ? 'bg-emerald-500' :
                        signal.direction === 'SELL' ? 'bg-rose-500' :
                        signal.direction === 'HOLD' ? 'bg-amber-500' : 'bg-blue-500'
                      }`}
                    />
                  </div>
                </motion.div>
              );
            })}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
};
