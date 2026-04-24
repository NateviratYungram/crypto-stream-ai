import { useState, Suspense, lazy, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Waves, Landmark, Briefcase } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { TabSkeleton } from './TabSkeleton';

const WhaleTrackerView = lazy(() => import('./WhaleTrackerView').then(m => ({ default: m.WhaleTrackerView })));
const ETFFlowView = lazy(() => import('./ETFFlowView').then(m => ({ default: m.ETFFlowView })));
const PortfolioCenter = lazy(() => import('./PortfolioCenter').then(m => ({ default: m.PortfolioCenter })));

type SubTab = 'WHALES' | 'ETF' | 'INSTITUTIONAL';
const MONEY_FLOW_SUBTAB_KEY = 'crypto_money_flow_subtab';

export const MoneyFlow = ({ tickerPrices }: { tickerPrices: any }) => {
  const { theme } = useMode();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>(() => {
    const stored = sessionStorage.getItem(MONEY_FLOW_SUBTAB_KEY);
    return stored === 'ETF' || stored === 'INSTITUTIONAL' ? stored : 'WHALES';
  });
  const [visitedSubTabs, setVisitedSubTabs] = useState<SubTab[]>(() => {
    const stored = sessionStorage.getItem(MONEY_FLOW_SUBTAB_KEY);
    return stored === 'ETF' || stored === 'INSTITUTIONAL' ? ['WHALES', stored] : ['WHALES'];
  });

  const tabs: { id: SubTab; label: string; icon: any }[] = [
    { id: 'WHALES',        label: 'Whale Tracker', icon: Waves },
    { id: 'ETF',           label: 'ETF Flows',     icon: Landmark },
    { id: 'INSTITUTIONAL', label: 'Inst. Assets',  icon: Briefcase },
  ];

  const dk = theme === 'dark';

  useEffect(() => {
    sessionStorage.setItem(MONEY_FLOW_SUBTAB_KEY, activeSubTab);
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
                    ? (dk ? 'bg-amber-500/20 text-amber-400' : 'bg-amber-50 text-amber-600') 
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
            {(['WHALES', 'ETF', 'INSTITUTIONAL'] as const).map((tabId) => {
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
                  {tabId === 'WHALES' && <WhaleTrackerView />}
                  {tabId === 'ETF' && <ETFFlowView />}
                  {tabId === 'INSTITUTIONAL' && <PortfolioCenter tickerPrices={tickerPrices} />}
                </motion.div>
              );
            })}
          </div>
        </Suspense>
      </div>
    </div>
  );
};
