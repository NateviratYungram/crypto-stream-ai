import React from 'react';
import { AppSidebar } from './AppSidebar';
import { AppNavbar } from './AppNavbar';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, MessageSquare, Zap, SlidersHorizontal, Star } from 'lucide-react';

// 5-tab mobile bottom nav (most-used tabs)
const MOBILE_TABS = [
  { id: 'Market Trends', icon: TrendingUp,       label: 'Markets' },
  { id: 'Watchlist',     icon: Star,              label: 'Watch'   },
  { id: 'Screener',      icon: SlidersHorizontal, label: 'Scan'    },
  { id: 'Whale Tracker', icon: Zap,               label: 'Whales'  },
  { id: 'Strategy Chat', icon: MessageSquare,     label: 'Chat'    },
];

interface MainLayoutProps {
  children: React.ReactNode;
  activeTab: string;
  setActiveTab: (tab: string) => void;
  wsStatus: string;
  mode: 'institutional' | 'retail';
  setMode: (mode: 'institutional' | 'retail') => void;
  onOpenCommand: () => void;
  tickerPrices: Record<string, { price: number; delta: number }>;
  onLogout: () => void;
}

export const MainLayout: React.FC<MainLayoutProps> = ({
  children,
  activeTab,
  setActiveTab,
  wsStatus,
  mode,
  setMode,
  onOpenCommand,
  tickerPrices,
  onLogout
}) => {
  const TICKER_SYMBOLS = ['BTC', 'ETH', 'SOL', 'NVDA', 'TSLA', 'GOLD', 'NASDAQ', 'SP500'];

  return (
    <div className="h-screen w-screen bg-slate-950 text-slate-200 flex flex-col overflow-hidden font-inter selection:bg-blue-500/30 selection:text-white relative">
      {/* Background Glows */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-blue-600/10 blur-[120px] rounded-full" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-indigo-600/10 blur-[120px] rounded-full" />
      </div>

      <AppNavbar 
        mode={mode} 
        setMode={setMode} 
        onOpenCommand={onOpenCommand} 
        isAuthorized={true} 
        onLogout={onLogout}
      />

      <div className="flex-1 flex overflow-hidden relative z-10">
        <AppSidebar 
          activeTab={activeTab} 
          setActiveTab={setActiveTab} 
          wsStatus={wsStatus} 
        />

        <main className="flex-1 flex flex-col relative overflow-hidden bg-[#060b14]/50">
          {/* Ticker Tape */}
          <div className="h-10 border-b border-white/5 bg-slate-950/20 backdrop-blur-sm flex items-center overflow-hidden shrink-0">
            <motion.div
              animate={{ x: [0, -1000] }}
              transition={{ duration: 40, repeat: Infinity, ease: 'linear' }}
              className="flex items-center gap-16 whitespace-nowrap px-8"
            >
              {[1, 2, 3].map(group => (
                <div key={group} className="flex items-center gap-16">
                  {TICKER_SYMBOLS.map(sym => {
                    const tick = tickerPrices[sym];
                    const up = (tick?.delta ?? 0) >= 0;
                    return (
                      <div key={sym} className="flex items-center gap-2.5">
                        <span className="text-[10px] font-black text-slate-500 font-mono tracking-widest">{sym.replace('USDT', '')}</span>
                        <span className="text-xs font-black text-slate-100 font-mono tabular-nums tracking-tighter">
                          {tick ? `$${tick.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '---'}
                        </span>
                        {tick && (
                          <span className={`text-[10px] font-black ${up ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {up ? '▲' : '▼'} {Math.abs(tick.delta).toFixed(3)}%
                          </span>
                        )}
                      </div>
                    );
                  })}
                  <div className="flex items-center gap-2 px-3 py-1 bg-blue-500/5 rounded-full border border-blue-500/10">
                    <div className="w-1 h-1 bg-blue-500 rounded-full animate-ping" />
                    <span className="text-[9px] font-black text-blue-400/80 uppercase tracking-widest font-mono">
                      Institutional Quant Feed Active
                    </span>
                  </div>
                </div>
              ))}
            </motion.div>
          </div>

          <div className="flex-1 relative overflow-hidden flex flex-col">
            <AnimatePresence mode="wait">
              <motion.div
                key={activeTab}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
                className="flex-1 flex flex-col h-full w-full pb-16 lg:pb-0"
              >
                {children}
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
      </div>

      {/* ─── Mobile Bottom Nav ───────────────────────────────── */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-[990] bg-slate-950/95 backdrop-blur-2xl border-t border-white/5 flex items-center justify-around px-2 h-16 safe-pb">
        {MOBILE_TABS.map(({ id, icon: Icon, label }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              aria-label={label}
              aria-current={active ? 'page' : undefined}
              className={`flex flex-col items-center justify-center gap-1 flex-1 py-2 rounded-xl transition-all duration-200 ${
                active ? 'text-blue-400' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {active && (
                <motion.div
                  layoutId="mobileActivePill"
                  className="absolute w-10 h-10 bg-blue-500/10 rounded-xl -z-10"
                />
              )}
              <Icon className={`w-5 h-5 ${active ? 'drop-shadow-[0_0_6px_rgba(96,165,250,0.7)]' : ''}`} aria-hidden="true" />
              <span className={`text-[10px] font-black uppercase tracking-widest leading-none ${active ? 'text-blue-400' : 'text-slate-600'}`}>
                {label}
              </span>
            </button>
          );
        })}
      </nav>
    </div>
  );
};
