import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, BarChart, RefreshCcw, ArrowUpRight, ArrowDownRight, Target, Clock } from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';
import { LiveChart } from './LiveChart';
import { OrderBookPanel } from './OrderBookPanel';
import { MarketSummary } from './MarketSummary';
import { AnimatedCounter } from './AnimatedCounter';
import { useMode } from '../contexts/ModeContext';
import { useWebSocket } from '../hooks/useWebSocket';

interface MarketItem {
  symbol: string;
  avg_price: number;
  total_volume: number;
  trade_count: number;
  history: { time: number; value: number }[];
  vwap_baseline: number;
  sentiment: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
  delta: number;
  lastTickAt: number;
}

export const TrendsView = () => {
  const [data, setData] = useState<MarketItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(Date.now());
  const { isConnected, lastMessage, latency } = useWebSocket();

  // Clock for latency display
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const getSymbolColor = (symbol: string) => {
    if (symbol.startsWith('BTC')) return '#f59e0b'; // Orange
    if (symbol.startsWith('ETH')) return '#3b82f6'; // Blue
    if (symbol.startsWith('SOL')) return '#8b5cf6'; // Purple
    if (symbol.startsWith('BNB')) return '#eab308'; // Yellow
    return '#10b981'; // Emerald default
  };

  const getSymbolIcon = (symbol: string) => {
    const color = getSymbolColor(symbol);
    return (
      <div className="w-10 h-10 rounded-2xl flex items-center justify-center relative overflow-hidden group-hover:scale-110 transition-transform duration-500" style={{ backgroundColor: `${color}15`, border: `1px solid ${color}30` }}>
        <div className="absolute inset-0 bg-gradient-to-br from-white/10 to-transparent" />
        <span className="text-sm font-black" style={{ color }}>{symbol[0]}</span>
      </div>
    );
  };

  // Generate unique seed-based history to avoid identical charts
  const generateHistory = (price: number, symbol: string) => {
    const seed = symbol.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return Array.from({ length: 30 }, (_, i) => {
      const noise = (Math.sin(i * 0.5 + seed) * 0.002) + (Math.cos(i * 0.2 + seed) * 0.001);
      return {
        time: Date.now() - (30 - i) * 1000,
        value: price * (1 + noise)
      };
    });
  };

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/data/trends');
      const json = await res.json();
      const enriched: MarketItem[] = (json.data || []).map((item: any) => {
        const p = parseFloat(item.avg_price);
        return {
          ...item,
          avg_price: p,
          total_volume: parseFloat(item.total_volume),
          trade_count: parseInt(item.trade_count),
          vwap_baseline: p,
          history: generateHistory(p, item.symbol),
          sentiment: 'NEUTRAL' as const,
          delta: 0,
          lastTickAt: Date.now(),
        }
      });
      setData(enriched);
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, []);

  useEffect(() => {
    if (lastMessage?.type !== 'TICK') return;
    const tick = lastMessage.data;
    setData(prev => prev.map(item => {
      if (item.symbol !== tick.symbol) return item;
      const newPrice = parseFloat(tick.price);
      const delta = ((newPrice - item.vwap_baseline) / item.vwap_baseline) * 100;
      const sentiment: MarketItem['sentiment'] = delta > 0.02 ? 'BULLISH' : delta < -0.02 ? 'BEARISH' : 'NEUTRAL';
      const newHistory = [...item.history, { time: Date.now(), value: newPrice }].slice(-30);
      return {
        ...item,
        avg_price: newPrice,
        sentiment,
        delta,
        total_volume: item.total_volume + parseFloat(tick.quantity),
        trade_count: item.trade_count + 1,
        history: newHistory,
        lastTickAt: Date.now(),
      };
    }));
  }, [lastMessage]);

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950/20 custom-scrollbar overflow-y-auto pb-20">
      {/* Header */}
      <header className="h-20 border-b border-white/5 flex items-center justify-between pl-8 pr-10 bg-slate-950/40 backdrop-blur-3xl z-30 sticky top-0 shrink-0 shadow-2xl">
        <div className="flex items-center gap-5">
          <div className="w-12 h-12 bg-blue-600/10 rounded-2xl flex items-center justify-center border border-blue-500/20 shadow-inner">
            <TrendingUp className="w-6 h-6 text-blue-400" />
          </div>
          <div className="space-y-0.5">
            <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">Market Trends</h1>
            <div className="flex items-center gap-3">
              <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-500 shadow-[0_0_12px_rgba(16,185,129,0.8)] animate-pulse' : 'bg-rose-500'}`} />
              <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest leading-none">
                {isConnected ? 'Institutional Core Active' : 'Offline'}
              </span>
              {latency && (
                <div className="px-1.5 py-0.5 bg-white/5 rounded border border-white/5">
                  <span className="text-[9px] font-mono text-slate-500">{latency}ms</span>
                </div>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="hidden lg:flex items-center gap-2.5 px-4 py-2 bg-slate-900/50 border border-white/10 rounded-2xl">
            <Target className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest">Global Order Monitor</span>
          </div>
          <button
            onClick={fetchData}
            className="group flex items-center gap-2.5 px-6 py-2.5 bg-blue-600 hover:bg-blue-500 border border-blue-400/30 rounded-2xl text-[11px] font-black text-white uppercase tracking-widest transition-all shadow-xl shadow-blue-600/20 hover:shadow-blue-600/40 active:scale-95 overflow-hidden relative"
          >
            <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/10 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-1000" />
            <RefreshCcw className={`w-4 h-4 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`} />
            REFRESH ENGINE
          </button>
        </div>
      </header>

      <div className="p-10 space-y-10 max-w-[1600px] mx-auto w-full">
        <MarketSummary />

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            {[1,2,3,4,5,6].map(i => <div key={i} className="h-96 bg-slate-900/40 animate-pulse rounded-[2.5rem] border border-white/5" />)}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 pb-10">
            {data.map((item) => {
              const secsAgo = Math.floor((now - item.lastTickAt) / 1000);
              const isFresh = secsAgo < 5;
              const assetColor = getSymbolColor(item.symbol);
              return (
                <HoverGlowCard key={item.symbol} className="p-8 rounded-[2.5rem] border-white/10 group relative overflow-hidden flex flex-col gap-6 bg-slate-900/40 backdrop-blur-sm shadow-2xl transition-all duration-500 hover:border-blue-500/30">
                  {/* Symbol dynamic glow */}
                  <div className="absolute -top-24 -right-24 w-60 h-60 blur-[100px] opacity-20 rounded-full transition-all duration-1000 group-hover:opacity-40" style={{ backgroundColor: assetColor }} />

                  {/* Title row */}
                  <div className="flex justify-between items-start relative z-10">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <div className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: assetColor }} />
                        <span className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] font-mono">SPOT · INTERFACE</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <h3 className="text-3xl font-black text-white tracking-tighter font-mono group-hover:text-blue-400 transition-colors uppercase">{item.symbol}</h3>
                        <AnimatePresence mode="wait">
                          {item.sentiment !== 'NEUTRAL' && (
                            <motion.span
                              initial={{ opacity: 0, scale: 0.7, x: -10 }}
                              animate={{ opacity: 1, scale: 1, x: 0 }}
                              exit={{ opacity: 0 }}
                              className={`px-2.5 py-1 rounded-lg text-[9px] font-black tracking-widest uppercase border ${
                                item.sentiment === 'BULLISH'
                                  ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                                  : 'bg-rose-500/20 text-rose-400 border-rose-500/30'
                              }`}
                            >{item.sentiment}</motion.span>
                          )}
                        </AnimatePresence>
                      </div>
                    </div>
                    {getSymbolIcon(item.symbol)}
                  </div>

                  {/* Price Area */}
                  <div className="relative z-10 bg-slate-950/40 p-5 rounded-3xl border border-white/5 group-hover:border-white/10 transition-colors">
                    <div className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] mb-2 flex justify-between items-center">
                      <span>Index Entry Price</span>
                      <div className="flex items-center gap-1.5">
                        <div className={`w-1.5 h-1.5 rounded-full ${isFresh ? 'bg-emerald-500 animate-pulse' : 'bg-slate-700'}`} />
                        <span className="text-[9px] font-mono lowercase">{secsAgo}s</span>
                      </div>
                    </div>
                    <div className="flex items-end justify-between gap-2">
                      <span className={`text-4xl font-mono font-black tracking-tighter tabular-nums transition-colors duration-300 ${
                        item.sentiment === 'BULLISH' ? 'text-emerald-400' : item.sentiment === 'BEARISH' ? 'text-rose-400' : 'text-slate-50'
                      }`}>
                        $<AnimatedCounter value={item.avg_price} decimals={2} />
                      </span>
                      <div className={`px-2.5 py-1.5 border rounded-xl flex items-center gap-1.5 text-[11px] font-black shadow-lg ${
                        item.delta >= 0 ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400 shadow-emerald-500/5' : 'bg-rose-500/10 border-rose-500/20 text-rose-400 shadow-rose-500/5'
                      }`}>
                        {item.delta >= 0 ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
                        {Math.abs(item.delta).toFixed(3)}%
                      </div>
                    </div>
                  </div>

                  {/* Visual Chart */}
                  <div className="h-24 w-full relative">
                    <div className="absolute inset-0 bg-gradient-to-t from-slate-950/20 to-transparent pointer-events-none" />
                    <LiveChart
                      data={item.history}
                      color={item.sentiment === 'BULLISH' ? '#10b981' : item.sentiment === 'BEARISH' ? '#f43f5e' : assetColor}
                    />
                  </div>

                  {/* High Frequency Order Book */}
                  <div className="border-t border-white/5 pt-6 relative z-10">
                    <OrderBookPanel symbol={item.symbol} currentPrice={item.avg_price} history={item.history} />
                  </div>

                  {/* Quantitative Stats */}
                  <div className="grid grid-cols-2 gap-6 border-t border-white/5 pt-6 relative z-10">
                    <div className="space-y-1">
                      <span className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em] flex items-center gap-2">
                        <BarChart className="w-3 h-3" /> Agg. Volume
                      </span>
                      <div className="text-base font-mono font-bold text-slate-200 tabular-nums">
                        {item.total_volume.toLocaleString(undefined, { maximumFractionDigits: 1 })} <span className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">{item.symbol.replace('USDT','')}</span>
                      </div>
                    </div>
                    <div className="text-right space-y-1">
                      <span className="text-[10px] font-black text-slate-600 uppercase tracking-[0.2em]">Strategy Rank</span>
                      <div className="text-base font-mono font-black text-blue-400 tabular-nums">
                        #{Math.floor(item.trade_count / 100).toLocaleString()} <span className="text-[10px] text-slate-500 font-bold">PTS</span>
                      </div>
                    </div>
                  </div>
                </HoverGlowCard>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
