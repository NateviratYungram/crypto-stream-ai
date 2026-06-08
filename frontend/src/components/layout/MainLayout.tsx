import React, { useState } from 'react';
import { AppSidebar } from './AppSidebar';
import { AppNavbar } from './AppNavbar';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, MessageSquare, Zap, SlidersHorizontal } from 'lucide-react';
import { useMode } from '../../contexts/ModeContext';

const MOBILE_TAB_IDS = [
  { id: 'Alpha Terminal',      icon: SlidersHorizontal, label: 'Alpha' },
  { id: 'Market Intelligence', icon: TrendingUp,        label: 'Intel' },
  { id: 'Strategy Chat',       icon: MessageSquare,     label: 'Chat' },
  { id: 'Money Flow',          icon: Zap,               label: 'Flows' },
];

interface MainLayoutProps {
  children: React.ReactNode;
  activeTab: string;
  setActiveTab: (tab: string) => void;
  wsStatus: string;
  onOpenCommand: () => void;
  tickerPrices: Record<string, { price: number; delta: number }>;
  onLogout: () => void;
}

export const MainLayout: React.FC<MainLayoutProps> = ({
  children,
  activeTab,
  setActiveTab,
  wsStatus,
  onOpenCommand,
  tickerPrices,
  onLogout
}) => {
  const TICKER_SYMBOLS = ['BTC', 'ETH', 'SOL', 'NVDA', 'TSLA', 'GOLD', 'NASDAQ', 'SP500'];
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { theme } = useMode();

  return (
    <div className={`h-screen w-screen flex flex-col overflow-hidden font-inter selection:bg-amber-500/30 selection:text-white relative transition-colors duration-700 ${
      theme === 'dark' ? 'bg-[#020617] text-slate-200' : 'bg-slate-50 text-slate-900'
    }`}>
      {/* Background Intelligence Glows */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className={`absolute top-[-20%] left-[-10%] w-[60%] h-[60%] blur-[160px] rounded-full transition-all duration-1000 ${
          theme === 'dark' ? 'bg-indigo-600/5' : 'bg-blue-400/5'
        }`} />
        <div className={`absolute bottom-[-20%] right-[-10%] w-[60%] h-[60%] blur-[160px] rounded-full transition-all duration-1000 ${
          theme === 'dark' ? 'bg-amber-600/5' : 'bg-indigo-400/5'
        }`} />
      </div>

      <AppNavbar
        onOpenCommand={onOpenCommand}
        isAuthorized={true}
        onLogout={onLogout}
        onMobileMenuClick={() => setMobileNavOpen(true)}
        onNavigate={setActiveTab}
      />

      <div className="flex-1 flex overflow-hidden relative z-10">
        {/* Desktop sidebar */}
        <AppSidebar
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          wsStatus={wsStatus}
          onLogout={onLogout}
        />

        {/* Mobile drawer overlay */}
        <AnimatePresence>
          {mobileNavOpen && (
            <>
              <motion.div
                key="overlay"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
                className="lg:hidden fixed inset-0 z-[980] bg-black/80 backdrop-blur-md"
                onClick={() => setMobileNavOpen(false)}
              />
              <motion.div
                key="drawer"
                initial={{ x: '-100%' }}
                animate={{ x: 0 }}
                exit={{ x: '-100%' }}
                transition={{ type: 'spring', damping: 25, stiffness: 200 }}
                className="lg:hidden fixed top-0 left-0 h-full w-80 z-[990] flex flex-col"
              >
                <AppSidebar
                  activeTab={activeTab}
                  setActiveTab={setActiveTab}
                  wsStatus={wsStatus}
                  onNavClick={() => setMobileNavOpen(false)}
                  onLogout={onLogout}
                />
              </motion.div>
            </>
          )}
        </AnimatePresence>

        <main className={`flex-1 flex flex-col relative overflow-hidden transition-all duration-700 ${
          theme === 'dark' ? 'bg-[#020617]/50' : 'bg-slate-100/30'
        }`}>
          {/* Institutional Ticker Tape */}
          <div className={`h-11 border-b backdrop-blur-3xl flex items-center overflow-hidden shrink-0 transition-all duration-700 ${
            theme === 'dark' ? 'border-white/5 bg-[#020617]/40' : 'border-slate-200/60 bg-white shadow-sm shadow-slate-200/10'
          }`}>
            <motion.div
              animate={{ x: [0, -2000] }}
              transition={{ duration: 60, repeat: Infinity, ease: 'linear' }}
              className="flex items-center gap-24 whitespace-nowrap px-12"
            >
              {[1, 2, 3, 4].map(group => (
                <div key={group} className="flex items-center gap-24">
                  {TICKER_SYMBOLS.map(sym => {
                    const tick = tickerPrices[sym];
                    const up = (tick?.delta ?? 0) >= 0;
                    return (
                      <div key={sym} className="flex items-center gap-4 group cursor-default">
                        <span className={`text-[10px] font-black font-mono tracking-[0.2em] transition-colors duration-500 uppercase ${
                          theme === 'dark' ? 'text-slate-600 group-hover:text-slate-400' : 'text-slate-400 group-hover:text-slate-600'
                        }`}>{sym.replace('USDT', '')}</span>
                        <div className="flex flex-col">
                          <span className={`text-[11px] font-black font-mono tabular-nums tracking-tighter transition-colors duration-500 leading-none ${
                            theme === 'dark' ? 'text-white' : 'text-slate-950'
                          }`}>
                            {tick ? `$${tick.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : '---'}
                          </span>
                          {tick && (
                            <span className={`text-[8px] font-black tracking-widest mt-0.5 ${up ? 'text-emerald-500' : 'text-rose-500'}`}>
                              {up ? '+' : ''}{tick.delta.toFixed(3)}%
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  <div className={`flex items-center gap-3 px-4 py-1.5 rounded-xl border transition-all duration-700 ${
                    theme === 'dark' ? 'bg-white/5 border-white/5' : 'bg-slate-50 border-slate-200'
                  }`}>
                    <div className="flex gap-1">
                      <div className="w-1 h-1 bg-amber-500 rounded-full animate-pulse" />
                      <div className="w-1 h-1 bg-amber-500/40 rounded-full animate-pulse delay-75" />
                    </div>
                    <span className={`text-[9px] font-black uppercase tracking-[0.2em] font-mono transition-colors duration-500 ${
                      theme === 'dark' ? 'text-amber-400/80' : 'text-amber-600'
                    }`}>
                      LIVE MARKET SYNC
                    </span>
                  </div>
                </div>
              ))}
            </motion.div>
          </div>

          <div className={`flex-1 relative custom-scrollbar flex flex-col pb-16 lg:pb-0 h-full ${activeTab === 'Strategy Chat' ? 'overflow-hidden' : 'overflow-y-auto'}`}>
            {children}
          </div>
        </main>
      </div>

      {/* ─── Mobile Bottom Nav ───────────────────────────────── */}
      <nav className={`lg:hidden fixed bottom-0 inset-x-0 z-[990] backdrop-blur-2xl border-t flex items-center justify-around px-2 h-16 safe-pb transition-all duration-500 ${
        theme === 'dark' ? 'bg-slate-950/95 border-white/5' : 'bg-white/95 border-slate-200 shadow-[0_-4px_20px_rgba(0,0,0,0.03)]'
      }`}>
        {MOBILE_TAB_IDS.map(({ id, icon: Icon, label }) => {
          const active = activeTab === id;
          return (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              aria-label={label}
              aria-current={active ? 'page' : undefined}
              className={`flex flex-col items-center justify-center gap-1 flex-1 py-2 rounded-xl transition-all duration-200 relative ${
                active 
                  ? (theme === 'dark' ? 'text-blue-400' : 'text-blue-600') 
                  : (theme === 'dark' ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700')
              }`}
            >
              {active && (
                <motion.div
                  layoutId="mobileActivePill"
                  className={`absolute w-10 h-10 rounded-xl -z-10 ${
                    theme === 'dark' ? 'bg-blue-500/10' : 'bg-blue-50'
                  }`}
                />
              )}
              <Icon className={`w-5 h-5 transition-all duration-300 ${active ? (theme === 'dark' ? 'drop-shadow-[0_0_8px_rgba(96,165,250,0.7)]' : 'drop-shadow-[0_0_4px_rgba(37,99,235,0.2)]') : ''}`} aria-hidden="true" />
              <span className={`text-[10px] font-black uppercase tracking-widest leading-none transition-colors duration-300 ${
                active ? (theme === 'dark' ? 'text-blue-400' : 'text-blue-600') : (theme === 'dark' ? 'text-slate-600' : 'text-slate-400')
              }`}>
                {label}
              </span>
            </button>
          );
        })}
      </nav>
    </div>
  );
};
