import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Clock, ArrowUpRight, ArrowDownRight, RefreshCcw, Zap, Filter, Download } from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMode } from '../contexts/ModeContext';

interface WhaleEntry {
  symbol: string;
  price: string;
  quantity: string;
  timestamp: string;
  is_buyer_maker: boolean;
}

type WhaleTier = 'krill' | 'dolphin' | 'whale' | 'mega';

// Compute USD value. Assuming BTC=~65k, ETH=~3.5k, SOL=~150 for rough unit scaling if price not passed.
const computeUSD = (qty: number, price: number) => qty * price;

const getTier = (usdValue: number): WhaleTier => {
  if (usdValue >= 3000000) return 'mega';    // > $3M
  if (usdValue >= 500000) return 'whale';    // > $500k
  if (usdValue >= 100000) return 'dolphin';  // > $100k
  return 'krill';                            // < $100k
};

const tierConfig: Record<WhaleTier, { label: string; minBtc: string; color: string; glow: string }> = {
  krill:   { label: 'KRILL',      minBtc: '< $100k',  color: 'text-slate-400',   glow: '' },
  dolphin: { label: 'DOLPHIN',    minBtc: '> $100k',  color: 'text-blue-400',    glow: 'shadow-[0_0_8px_rgba(59,130,246,0.25)]' },
  whale:   { label: 'WHALE',      minBtc: '> $500k',  color: 'text-emerald-400', glow: 'shadow-[0_0_12px_rgba(16,185,129,0.3)]' },
  mega:    { label: 'MEGA-WHALE', minBtc: '> $3M',    color: 'text-yellow-400',  glow: 'shadow-[0_0_20px_rgba(251,191,36,0.4)]' },
};

export const WhaleTrackerView = () => {
  const [whales, setWhales] = useState<WhaleEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterTier, setFilterTier] = useState<WhaleTier | 'all'>('all');
  const [filterDirection, setFilterDirection] = useState<'all' | 'buy' | 'sell'>('all');
  const { isConnected, lastMessage, latency } = useWebSocket();
  const { isRetail } = useMode();

  const fetchWhales = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/data/whales');
      const json = await res.json();
      setWhales(json.data || []);
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchWhales(); }, []);

  useEffect(() => {
    if (lastMessage?.type === 'WHALE_ALERT') {
      const newWhale = lastMessage.data;
      setWhales(prev => [newWhale, ...prev].slice(0, 50));
    }
  }, [lastMessage]);

  const filtered = whales.filter(w => {
    const usdVal = computeUSD(parseFloat(w.quantity), parseFloat(w.price));
    const tier = getTier(usdVal);
    const tierOk = filterTier === 'all' || tier === filterTier;
    const dirOk = filterDirection === 'all'
      || (filterDirection === 'buy' && !w.is_buyer_maker)
      || (filterDirection === 'sell' && w.is_buyer_maker);
    return tierOk && dirOk;
  });

  // Aggregate stats using USD to normalize across assets
  const totalBuyUSD = whales.filter(w => !w.is_buyer_maker).reduce((s, w) => s + computeUSD(parseFloat(w.quantity), parseFloat(w.price)), 0);
  const totalSellUSD = whales.filter(w => w.is_buyer_maker).reduce((s, w) => s + computeUSD(parseFloat(w.quantity), parseFloat(w.price)), 0);
  const largestTrade = whales.reduce((max, w) => computeUSD(parseFloat(w.quantity), parseFloat(w.price)) > computeUSD(parseFloat(max?.quantity || '0'), parseFloat(max?.price || '0')) ? w : max, whales[0]);
  
  const totalVolUSD = totalBuyUSD + totalSellUSD;
  const flowImbalance = totalVolUSD > 0 ? ((totalBuyUSD - totalSellUSD) / totalVolUSD) * 100 : 0;
  
  const exportCSV = () => {
    const header = "Time,Symbol,Side,Price,Quantity,USD_Value,Tier\n";
    const rows = filtered.map(w => {
      const time = new Date(parseInt(w.timestamp)).toISOString();
      const side = w.is_buyer_maker ? "SELL" : "BUY";
      const usdVal = computeUSD(parseFloat(w.quantity), parseFloat(w.price));
      const tier = getTier(usdVal);
      return `${time},${w.symbol},${side},${w.price},${w.quantity},${usdVal.toFixed(2)},${tier}`;
    }).join("\n");
    
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `whale_flow_${Date.now()}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-emerald-500 font-bold text-[10px] uppercase tracking-[0.2em]">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] status-breath" />
            Whale Watch {latency && <span className="text-slate-600 ml-2">{latency}ms</span>}
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">Institutional Flow</h2>
          <p className="text-slate-500 text-sm font-medium">Monitoring classified transaction clusters in real-time execution.</p>
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-[10px] font-bold tracking-widest uppercase transition-all ${
            isConnected ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
            {isConnected ? 'Live' : 'Syncing'}
          </div>
          
          {!isRetail && (
            <button onClick={exportCSV} className="group flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-blue-500/50 rounded-xl text-slate-300 transition-all font-bold text-xs">
              <Download className="w-3.5 h-3.5 group-hover:-translate-y-0.5 transition-transform" />
              CSV
            </button>
          )}

          <button onClick={fetchWhales} className="group flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-emerald-500/50 rounded-xl text-slate-300 transition-all font-bold text-xs">
            <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`} />
            Sync
          </button>
        </div>
      </header>

      {/* Aggregate Stats */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Buy Pressure (USD)', value: `$${(totalBuyUSD / 1000000).toFixed(2)}M`, color: 'text-emerald-400' },
          { label: 'Sell Pressure (USD)', value: `$${(totalSellUSD / 1000000).toFixed(2)}M`, color: 'text-rose-400' },
          { label: 'Flow Imbalance', value: `${flowImbalance > 0 ? '+' : ''}${flowImbalance.toFixed(1)}%`, color: flowImbalance > 0 ? 'text-emerald-400' : 'text-rose-400' },
          { label: 'Largest Trade', value: largestTrade ? `$${(computeUSD(parseFloat(largestTrade.quantity), parseFloat(largestTrade.price)) / 1000000).toFixed(2)}M` : '—', color: 'text-yellow-400' },
        ].map((stat, i) => (
          <div key={i} className="p-4 bg-slate-900/40 border border-white/5 rounded-2xl">
            <p className="text-[9px] font-black text-slate-600 uppercase tracking-widest mb-1">{stat.label}</p>
            <p className={`text-base font-black font-mono ${stat.color}`}>{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter className="w-3.5 h-3.5 text-slate-500" />
        <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Tier:</span>
        {(['all', 'krill', 'dolphin', 'whale', 'mega'] as const).map(t => (
          <button
            key={t}
            onClick={() => setFilterTier(t)}
            className={`px-3 py-1 rounded-xl text-[9px] font-black uppercase tracking-widest border transition-all ${
              filterTier === t
                ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            {t === 'all' ? 'ALL' : tierConfig[t].label}
          </button>
        ))}
        <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest ml-4">Side:</span>
        {(['all', 'buy', 'sell'] as const).map(d => (
          <button
            key={d}
            onClick={() => setFilterDirection(d)}
            className={`px-3 py-1 rounded-xl text-[9px] font-black uppercase tracking-widest border transition-all ${
              filterDirection === d
                ? d === 'buy' ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-400'
                  : d === 'sell' ? 'bg-rose-600/20 border-rose-500/40 text-rose-400'
                  : 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
            }`}
          >
            {d.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-slate-900/40 backdrop-blur-xl border border-white/5 rounded-[2rem] overflow-hidden shadow-2xl relative">
        <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-500/5 blur-[100px] pointer-events-none" />
        <table className="w-full text-left border-collapse relative z-10">
          <thead>
            <tr className="bg-slate-900/80 border-b border-white/5">
              <th className="px-6 py-5 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Time</th>
              <th className="px-6 py-5 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Tier</th>
              <th className="px-6 py-5 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Asset</th>
              <th className="px-6 py-5 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em]">Direction</th>
              <th className="px-6 py-5 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] text-right">Size (BTC)</th>
              <th className="px-6 py-5 text-[10px] font-bold text-slate-500 uppercase tracking-[0.2em] text-right">Exec Price</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            <AnimatePresence mode="popLayout">
              {loading ? (
                [1,2,3,4,5].map(i => (
                  <tr key={i} className="animate-pulse">
                    <td colSpan={6} className="px-6 py-6"><div className="h-4 bg-slate-800/50 rounded-full w-full" /></td>
                  </tr>
                ))
              ) : filtered.map((whale, i) => {
                const qty = parseFloat(whale.quantity);
                const tier = getTier(qty);
                const cfg = tierConfig[tier];
                return (
                  <motion.tr
                    key={i}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.02 }}
                    className={`hover:bg-white/[0.02] transition-colors ${tier === 'mega' ? 'bg-yellow-500/[0.02]' : ''}`}
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2 text-slate-500 font-mono text-[11px] font-bold">
                        <Clock className="w-3 h-3 opacity-50" />
                        {new Date(parseInt(whale.timestamp)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`text-[9px] font-black uppercase tracking-widest ${cfg.color}`}>{cfg.label}</span>
                    </td>
                    <td className="px-6 py-4">
                      <span className="font-black text-slate-100 tracking-tight">{whale.symbol}</span>
                    </td>
                    <td className="px-6 py-4">
                      <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-xl text-[10px] font-black tracking-wider border ${
                        whale.is_buyer_maker
                          ? 'bg-rose-500/5 text-rose-400 border-rose-500/20'
                          : 'bg-emerald-500/5 text-emerald-400 border-emerald-500/20'
                      }`}>
                        {whale.is_buyer_maker ? <ArrowDownRight className="w-3 h-3" /> : <ArrowUpRight className="w-3 h-3" />}
                        {whale.is_buyer_maker ? 'SELL' : 'BUY'}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className={`text-base font-black font-mono ${cfg.color} ${cfg.glow}`}>{qty.toFixed(4)}</span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <span className="text-sm text-slate-400 font-black font-mono">${parseFloat(whale.price).toLocaleString()}</span>
                    </td>
                  </motion.tr>
                );
              })}
            </AnimatePresence>
          </tbody>
        </table>
        {!loading && filtered.length === 0 && (
          <div className="p-24 text-center space-y-4">
            <div className="w-16 h-16 bg-slate-800/40 rounded-full flex items-center justify-center mx-auto border border-white/5">
              <Zap className="w-8 h-8 text-slate-600" />
            </div>
            <p className="text-slate-400 font-bold text-base">No whales match current filters</p>
            <p className="text-slate-600 text-sm">Try changing tier or direction filter</p>
          </div>
        )}
      </div>
    </div>
  );
};
