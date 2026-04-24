import { useState, Suspense, lazy, useEffect } from 'react';
import { motion } from 'framer-motion';
import { BookOpen, Repeat, Laptop } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { TabSkeleton } from './TabSkeleton';

const TradingJournalView = lazy(() => import('./TradingJournalView').then(m => ({ default: m.TradingJournalView })));
const BacktesterView = lazy(() => import('./BacktesterView').then(m => ({ default: m.BacktesterView })));
const PaperTradingDashboard = lazy(() => import('./PaperTradingDashboard').then(m => ({ default: m.PaperTradingDashboard })));

type SubTab = 'JOURNAL' | 'BACKTESTER' | 'PAPER';
const STRATEGY_LAB_SUBTAB_KEY = 'crypto_strategy_lab_subtab';

export const StrategyLab = () => {
  const { theme } = useMode();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>(() => {
    const stored = sessionStorage.getItem(STRATEGY_LAB_SUBTAB_KEY);
    return stored === 'BACKTESTER' || stored === 'PAPER' ? stored : 'JOURNAL';
  });
  const [visitedSubTabs, setVisitedSubTabs] = useState<SubTab[]>(() => {
    const stored = sessionStorage.getItem(STRATEGY_LAB_SUBTAB_KEY);
    return stored === 'BACKTESTER' || stored === 'PAPER' ? ['JOURNAL', stored] : ['JOURNAL'];
  });

  const tabs: { id: SubTab; label: string; icon: any }[] = [
    { id: 'JOURNAL',    label: 'Journal',    icon: BookOpen },
    { id: 'BACKTESTER', label: 'Backtester', icon: Repeat },
    { id: 'PAPER',      label: 'Paper Trade', icon: Laptop },
  ];

  const dk = theme === 'dark';

  useEffect(() => {
    sessionStorage.setItem(STRATEGY_LAB_SUBTAB_KEY, activeSubTab);
    if (!visitedSubTabs.includes(activeSubTab)) {
      setVisitedSubTabs(prev => [...prev, activeSubTab]);
    }
  }, [activeSubTab, visitedSubTabs]);

  return (
    <div className="flex flex-col min-h-screen">
      <div className={`sticky top-0 z-20 border-b backdrop-blur-xl ${
        dk ? 'bg-slate-950/80 border-white/5' : 'bg-white/80 border-slate-200'
      }`}>
        <div className="flex items-center px-8 h-16 gap-6">
          {tabs.map((tab) => {
            const Icon = tab.icon;
            const active = activeSubTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveSubTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl transition-all ${
                  active 
                    ? (dk ? 'bg-indigo-500/20 text-indigo-400' : 'bg-indigo-50 text-indigo-600') 
                    : (dk ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-600')
                }`}
              >
                <Icon className="w-4 h-4" />
                <span className="text-xs font-black uppercase tracking-widest">{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex-1">
        <Suspense fallback={<TabSkeleton variant="full" />}>
          <div className="relative w-full h-full">
            {(['JOURNAL', 'BACKTESTER', 'PAPER'] as const).map((tabId) => {
              if (!visitedSubTabs.includes(tabId)) return null;
              const isActive = activeSubTab === tabId;
              return (
                <motion.div
                  key={tabId}
                  initial={false}
                  animate={{ opacity: isActive ? 1 : 0, x: isActive ? 0 : 8 }}
                  transition={{ duration: 0.18 }}
                  className={`w-full h-full ${
                    isActive
                      ? 'relative z-10 pointer-events-auto'
                      : 'absolute inset-0 -z-10 pointer-events-none overflow-hidden'
                  }`}
                >
                  {tabId === 'JOURNAL' && <TradingJournalView />}
                  {tabId === 'BACKTESTER' && <BacktesterView />}
                  {tabId === 'PAPER' && <PaperTradingDashboard />}
                </motion.div>
              );
            })}
          </div>
        </Suspense>
      </div>
    </div>
  );
};
