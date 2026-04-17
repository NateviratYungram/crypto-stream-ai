import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Wallet, Landmark, TrendingUp, ArrowUpRight, ArrowDownRight, Search, PlusCircle, RefreshCcw, DollarSign, PieChart as PieIcon } from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';
import { AnimatedCounter } from './AnimatedCounter';

const DEMO_ASSETS = [
  { symbol: 'BTC', balance: 0.45, price: 71850.22, allocation: 45, type: 'CRYPTO' },
  { symbol: 'ETH', balance: 5.2, price: 3452.12, allocation: 25, type: 'CRYPTO' },
  { symbol: 'SOL', balance: 42.5, price: 142.34, allocation: 15, type: 'CRYPTO' },
  { symbol: 'USDT', balance: 12500, price: 1.0, allocation: 15, type: 'STABLE' },
];

interface PortfolioCenterProps {
  tickerPrices?: Record<string, { price: number; delta: number }>;
}

export const PortfolioCenter = ({ tickerPrices = {} }: PortfolioCenterProps) => {
  const [address, setAddress] = useState('');
  const [loading, setLoading] = useState(false);
  
  // Real-time macro state derived from props
  const goldPrice = tickerPrices['GOLD']?.price || 2350.45;
  const goldDelta = tickerPrices['GOLD']?.delta || 1.25;
  const nasdaqPrice = tickerPrices['NASDAQ']?.price || 18230.12;
  const nasdaqDelta = tickerPrices['NASDAQ']?.delta || 0.45;
  const sp500Price = tickerPrices['SP500']?.price || 5120.40;
  const sp500Delta = tickerPrices['SP500']?.delta || -0.15;

  const MACRO_BENCHMARKS = [
    { symbol: 'GOLD', price: goldPrice, change24h: goldDelta, name: 'Gold Spot' },
    { symbol: 'NASDAQ', price: nasdaqPrice, change24h: nasdaqDelta, name: 'Nasdaq 100' },
    { symbol: 'SP500', price: sp500Price, change24h: sp500Delta, name: 'S&P 500 Index' },
  ];

  const [portfolio, setPortfolio] = useState(DEMO_ASSETS);
  const [isWatching, setIsWatching] = useState(false);

  const totalValue = portfolio.reduce((sum, asset) => sum + (asset.balance * asset.price), 0);
  const pnl24h = 1240.50; // Mock data
  const pnlPct = (pnl24h / totalValue) * 100;

  const handleWatchAddress = (e: React.FormEvent) => {
    e.preventDefault();
    if (!address) return;
    setLoading(true);
    // Simulate API fetch delay
    setTimeout(() => {
      setIsWatching(true);
      setLoading(false);
    }, 1500);
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950/20 custom-scrollbar overflow-y-auto pb-20">
      <header className="h-20 border-b border-white/5 flex items-center justify-between pl-8 pr-10 bg-slate-950/40 backdrop-blur-3xl z-30 sticky top-0 shrink-0 shadow-2xl">
        <div className="flex items-center gap-5">
          <div className="w-12 h-12 bg-indigo-600/10 rounded-2xl flex items-center justify-center border border-indigo-500/20 shadow-inner">
            <Landmark className="w-6 h-6 text-indigo-400" />
          </div>
          <div className="space-y-0.5">
            <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">Institutional Assets</h1>
            <div className="flex items-center gap-3">
              <div className="px-2 py-0.5 rounded text-[11px] font-black uppercase tracking-widest text-amber-500 bg-amber-500/10 border border-amber-500/20">
                Demo Mode
              </div>
              <span className="text-xs font-bold text-slate-400 uppercase tracking-wide">
                Using Synthetic Analytics Data
              </span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <form onSubmit={handleWatchAddress} className="relative group hidden md:block">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-focus-within:text-indigo-400 transition-colors" />
            <input
              type="text"
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="Watch public address (ETH/SOL)..."
              className="bg-slate-900/50 border border-white/10 rounded-2xl px-12 py-2.5 text-xs text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 transition-all w-80 font-mono"
            />
            <button type="submit" disabled={loading} className="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 hover:bg-white/5 rounded-xl transition-colors">
              {loading ? <RefreshCcw className="w-3.5 h-3.5 text-indigo-400 animate-spin" /> : <PlusCircle className="w-3.5 h-3.5 text-slate-500" />}
            </button>
          </form>
        </div>
      </header>

      <div className="p-10 space-y-10 max-w-[1400px] mx-auto w-full">
        {/* Main Stats Banner */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <HoverGlowCard className="lg:col-span-2 p-10 rounded-[2.5rem] bg-indigo-600/5 border-indigo-500/20 relative overflow-hidden group">
            <div className="absolute top-0 right-0 p-10 opacity-10 group-hover:opacity-20 transition-opacity">
              <Wallet className="w-32 h-32 text-indigo-500" />
            </div>
            <div className="relative z-10 space-y-6">
              <div className="flex items-center gap-2">
                <span className="text-xs font-black text-indigo-400 uppercase tracking-[0.3em]">Total Portfolio Value</span>
              </div>
              <div className="flex items-baseline gap-4">
                <span className="text-6xl font-black text-white tracking-tighter tabular-nums font-mono">
                  $<AnimatedCounter value={totalValue} decimals={2} />
                </span>
                <div className="px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-xl flex items-center gap-1.5 text-emerald-400 font-bold text-xs uppercase tracking-widest">
                  <TrendingUp className="w-3.5 h-3.5" />
                  Live Feed
                </div>
              </div>
              <div className="flex items-center gap-10">
                <div className="space-y-1">
                  <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">24h Net PnL</p>
                  <p className="text-xl font-bold text-emerald-400 font-mono">
                    +${pnl24h.toLocaleString()} <span className="text-xs">({pnlPct.toFixed(2)}%)</span>
                  </p>
                </div>
                <div className="w-px h-10 bg-white/5" />
                <div className="space-y-1">
                  <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Asset Diversity</p>
                  <div className="flex gap-1.5">
                    {[1,2,3,4].map(i => <div key={i} className={`h-1.5 w-6 rounded-full ${i <= 3 ? 'bg-indigo-500' : 'bg-slate-700'}`} />)}
                  </div>
                </div>
              </div>
            </div>
          </HoverGlowCard>

          <HoverGlowCard className="p-8 rounded-[2.5rem] bg-slate-900/40 border-white/5 flex flex-col justify-between">
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <PieIcon className="w-4 h-4 text-indigo-400" />
                  <span className="text-xs font-black text-slate-400 uppercase tracking-widest leading-none">Allocation</span>
                </div>
              </div>
              <div className="space-y-4">
                {portfolio.map(asset => (
                  <div key={asset.symbol} className="space-y-1.5">
                    <div className="flex justify-between text-xs font-black uppercase tracking-widest">
                      <span className="text-slate-200">{asset.symbol}</span>
                      <span className="text-slate-500">{asset.allocation}%</span>
                    </div>
                    <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                      <motion.div 
                        initial={{ width: 0 }}
                        animate={{ width: `${asset.allocation}%` }}
                        className="h-full bg-indigo-500 shadow-[0_0_8px_rgba(99,102,241,0.4)]"
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </HoverGlowCard>
        </div>

        {/* Macro Benchmarks */}
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-black text-white uppercase tracking-[0.2em] flex items-center gap-3">
              <TrendingUp className="w-4 h-4 text-amber-500" />
              Global Macro Benchmarks
            </h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {MACRO_BENCHMARKS.map((bench) => (
              <HoverGlowCard key={bench.symbol} className="p-6 rounded-3xl bg-slate-900/40 border-white/5 group">
                <div className="flex justify-between items-start mb-4">
                  <div>
                    <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1">{bench.name}</p>
                    <h3 className="text-xl font-black text-white tracking-tighter">{bench.symbol}</h3>
                  </div>
                  <div className={`px-2 py-1 rounded-lg text-[10px] font-bold ${bench.change24h > 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                    {bench.change24h > 0 ? '+' : ''}{bench.change24h}%
                  </div>
                </div>
                <div className="text-2xl font-mono font-bold text-slate-100 mb-4">
                  ${bench.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </div>
                <div className="h-1 w-full bg-white/5 rounded-full overflow-hidden">
                  <motion.div 
                    initial={{ width: 0 }}
                    animate={{ width: '100%' }}
                    transition={{ duration: 1 }}
                    className={`h-full ${bench.change24h > 0 ? 'bg-emerald-500' : 'bg-rose-500'} opacity-30`} 
                  />
                </div>
              </HoverGlowCard>
            ))}
          </div>
        </div>

        {/* Assets Table */}
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-black text-white uppercase tracking-[0.2em] flex items-center gap-3">
              <Landmark className="w-4 h-4 text-slate-500" />
              Holding Distribution
            </h2>
            <div className="flex items-center gap-3">
              <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest italic">Updated every 60s</span>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4">
            {portfolio.map((asset) => (
              <motion.div
                key={asset.symbol}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="group flex items-center justify-between p-6 bg-slate-900/40 border border-white/5 rounded-3xl hover:border-indigo-500/30 transition-all hover:bg-slate-900/60"
              >
                <div className="flex items-center gap-6">
                  <div className="w-12 h-12 bg-white/5 rounded-2xl flex items-center justify-center border border-white/10 group-hover:scale-110 transition-transform">
                    <span className="text-sm font-black text-slate-100">{asset.symbol[0]}</span>
                  </div>
                  <div className="space-y-1">
                    <h3 className="text-lg font-black text-white tracking-tighter uppercase">{asset.symbol}</h3>
                    <p className="text-xs font-mono text-slate-500 font-bold uppercase tracking-widest">SPOT · QUANT ACCOUNT</p>
                  </div>
                </div>

                <div className="hidden md:block space-y-1 text-right">
                  <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Holding</p>
                  <p className="text-base font-mono font-bold text-slate-100">
                    {asset.balance.toLocaleString()} {asset.symbol}
                  </p>
                </div>

                <div className="hidden md:block space-y-1 text-right">
                  <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Market Price</p>
                  <p className="text-base font-mono font-bold text-slate-100">
                    ${asset.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  </p>
                </div>

                <div className="space-y-1 text-right bg-indigo-500/5 px-6 py-2 rounded-2xl border border-indigo-500/10 min-w-[180px]">
                  <p className="text-[11px] font-black text-indigo-400 uppercase tracking-widest">Equiv. Value</p>
                  <p className="text-lg font-mono font-black text-white">
                    ${(asset.balance * asset.price).toLocaleString(undefined, { maximumFractionDigits: 2 })}
                  </p>
                </div>

                <div className="pl-4 group-hover:translate-x-1 transition-transform">
                  <ArrowUpRight className="w-5 h-5 text-slate-700 group-hover:text-indigo-400 transition-colors" />
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
