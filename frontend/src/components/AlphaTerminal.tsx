import { useState, Suspense, lazy, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Search, Star, CreditCard, ChevronRight } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { TabSkeleton } from './TabSkeleton';

// Lazy load sub-components for performance
const ScreenerView = lazy(() => import('./ScreenerView').then(m => ({ default: m.ScreenerView })));
const WatchlistPanel = lazy(() => import('./WatchlistPanel').then(m => ({ default: m.WatchlistPanel })));
const BrokerExecutionPanel = lazy(() => import('./BrokerExecutionPanel').then(m => ({ default: m.BrokerExecutionPanel })));

type SubTab = 'SCREENER' | 'WATCHLIST' | 'BROKER';
const ALPHA_TERMINAL_SUBTAB_KEY = 'crypto_alpha_terminal_subtab';

export const AlphaTerminal = ({ onAnalyze }: { onAnalyze?: (sym: string) => void }) => {
  const { theme } = useMode();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>(() => {
    const stored = sessionStorage.getItem(ALPHA_TERMINAL_SUBTAB_KEY);
    return stored === 'WATCHLIST' || stored === 'BROKER' ? stored : 'SCREENER';
  });
  const [visitedSubTabs, setVisitedSubTabs] = useState<SubTab[]>(() => {
    const stored = sessionStorage.getItem(ALPHA_TERMINAL_SUBTAB_KEY);
    return stored === 'WATCHLIST' || stored === 'BROKER' ? ['SCREENER', stored] : ['SCREENER'];
  });

  const tabs: { id: SubTab; label: string; icon: any; desc: string }[] = [
    { id: 'SCREENER',  label: 'Discovery', icon: Search,     desc: 'Scan 5,000+ Assets' },
    { id: 'WATCHLIST', label: 'Surveillance', icon: Star,       desc: 'Track Priority Targets' },
    { id: 'BROKER',    label: 'Execution', icon: CreditCard, desc: 'Live Order Entry' },
  ];

  const dk = theme === 'dark';

  const selectSubTab = (nextSubTab: SubTab) => {
    setActiveSubTab(nextSubTab);
    sessionStorage.setItem(ALPHA_TERMINAL_SUBTAB_KEY, nextSubTab);
  };

  useEffect(() => {
    if (!visitedSubTabs.includes(activeSubTab)) {
      setVisitedSubTabs(prev => [...prev, activeSubTab]);
    }
  }, [activeSubTab, visitedSubTabs]);

  return (
    <div className={`flex flex-col min-h-screen transition-colors duration-500 ${
      dk ? 'bg-slate-950 text-white' : 'bg-slate-50 text-slate-900'
    }`}>
      {/* Sub-tab Navigation */}
      <div className={`sticky top-0 z-30 border-b backdrop-blur-xl transition-all duration-500 ${
        dk ? 'bg-slate-950/80 border-white/5' : 'bg-white/80 border-slate-200'
      }`}>
        <div className="flex items-center px-6 lg:px-10 h-20 gap-8 overflow-x-auto scrollbar-hide">
          <div className="flex items-center gap-3 shrink-0 pr-6 border-r border-slate-800/20">
            <div className="w-10 h-10 rounded-xl bg-blue-600 flex items-center justify-center shadow-lg shadow-blue-600/20">
              <span className="font-black italic text-white">A</span>
            </div>
            <div>
              <h1 className="text-sm font-black tracking-tighter uppercase italic">Alpha Terminal</h1>
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Unified Action Hub</p>
            </div>
          </div>

          <div className="flex items-center gap-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const active = activeSubTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => selectSubTab(tab.id)}
                  className={`group relative flex items-center gap-3 px-6 py-3 rounded-2xl transition-all duration-300 ${
                    active 
                      ? (dk ? 'bg-white/5' : 'bg-blue-50 shadow-sm shadow-blue-100') 
                      : 'hover:bg-white/5'
                  }`}
                >
                  <div className={`w-8 h-8 rounded-xl flex items-center justify-center transition-all ${
                    active 
                      ? 'bg-blue-600 text-white' 
                      : (dk ? 'bg-slate-900 text-slate-500 group-hover:text-slate-300' : 'bg-slate-100 text-slate-400 group-hover:text-slate-600')
                  }`}>
                    <Icon className="w-4 h-4" />
                  </div>
                  <div className="text-left">
                    <p className={`text-xs font-black uppercase tracking-widest leading-none ${
                      active ? (dk ? 'text-white' : 'text-blue-600') : (dk ? 'text-slate-500' : 'text-slate-400')
                    }`}>{tab.label}</p>
                    <p className="text-[9px] font-bold text-slate-600 mt-1">{tab.desc}</p>
                  </div>
                  {active && (
                    <motion.div 
                      layoutId="activeSubTab"
                      className="absolute -bottom-[21px] left-0 right-0 h-[3px] bg-blue-600 rounded-full"
                    />
                  )}
                </button>
              );
            })}
          </div>


        </div>
      </div>

      {/* Main Action Area */}
      <div className="flex-1 relative">
        <Suspense fallback={<TabSkeleton variant="full" />}>
          <div className="relative w-full h-full">
            {(['SCREENER', 'WATCHLIST', 'BROKER'] as const).map((tabId) => {
              if (!visitedSubTabs.includes(tabId)) return null;
              const isActive = activeSubTab === tabId;
              return (
                <motion.div
                  key={tabId}
                  initial={false}
                  animate={{ opacity: isActive ? 1 : 0, y: isActive ? 0 : 8 }}
                  transition={{ duration: 0.18 }}
                  className={`w-full h-full ${
                    isActive
                      ? 'relative z-10 pointer-events-auto'
                      : 'absolute inset-0 -z-10 pointer-events-none overflow-hidden'
                  }`}
                >
                  {tabId === 'SCREENER' && <ScreenerView />}
                  {tabId === 'WATCHLIST' && <WatchlistPanel onAnalyze={onAnalyze} />}
                  {tabId === 'BROKER' && <BrokerExecutionPanel />}
                </motion.div>
              );
            })}
          </div>
        </Suspense>
      </div>

      {/* Interactive Quick-Bar (Bottom Floating) */}
      <div className="fixed bottom-8 right-8 z-50 flex items-center gap-2">
        <button 
          onClick={() => selectSubTab('BROKER')}
          className="flex items-center gap-3 px-6 py-4 bg-emerald-500 text-white rounded-2xl font-black shadow-2xl shadow-emerald-500/30 hover:scale-105 active:scale-95 transition-all group"
        >
          <CreditCard className="w-5 h-5" />
          <span className="uppercase tracking-widest text-sm">Fast Execution</span>
          <ChevronRight className="w-4 h-4 opacity-0 group-hover:opacity-100 transition-all translate-x-[-10px] group-hover:translate-x-0" />
        </button>
      </div>
    </div>
  );
};
