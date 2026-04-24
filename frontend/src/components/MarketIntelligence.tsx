import { useState, Suspense, lazy, useEffect } from 'react';
import { motion } from 'framer-motion';
import { BarChart3, MessageSquare, Lightbulb, Calendar, Target } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { TabSkeleton } from './TabSkeleton';

const loadTrendsView = () => import('./TrendsView').then(m => ({ default: m.TrendsView }));
const loadNewsSentimentHub = () => import('./NewsSentimentHub').then(m => ({ default: m.NewsSentimentHub }));
const loadIntelligenceHub = () => import('./IntelligenceHub').then(m => ({ default: m.IntelligenceHub }));
const loadEconomicCalendar = () => import('./EconomicCalendarView').then(m => ({ default: m.EconomicCalendarView }));
const loadTacticsHub = () => import('./TacticsHub').then(m => ({ default: m.TacticsHub }));

const TrendsView = lazy(loadTrendsView);
const NewsSentimentHub = lazy(loadNewsSentimentHub);
const IntelligenceHub = lazy(loadIntelligenceHub);
const EconomicCalendar = lazy(loadEconomicCalendar);
const TacticsHub = lazy(loadTacticsHub);

type SubTab = 'TRENDS' | 'SENTIMENT' | 'TACTICS' | 'MACRO' | 'CALENDAR';
const MARKET_INTEL_SUBTAB_KEY = 'crypto_market_intel_subtab';

export const MarketIntelligence = () => {
  const { theme } = useMode();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>(() => {
    const stored = sessionStorage.getItem(MARKET_INTEL_SUBTAB_KEY);
    return stored === 'SENTIMENT' || stored === 'TACTICS' || stored === 'MACRO' || stored === 'CALENDAR' ? stored : 'TRENDS';
  });
  const [visitedSubTabs, setVisitedSubTabs] = useState<SubTab[]>(() => {
    const stored = sessionStorage.getItem(MARKET_INTEL_SUBTAB_KEY);
    return stored === 'SENTIMENT' || stored === 'TACTICS' || stored === 'MACRO' || stored === 'CALENDAR'
      ? ['TRENDS', stored]
      : ['TRENDS'];
  });

  const tabs: { id: SubTab; label: string; icon: any }[] = [
    { id: 'TRENDS',    label: 'Trends',    icon: BarChart3 },
    { id: 'SENTIMENT', label: 'Sentiment', icon: MessageSquare },
    { id: 'TACTICS',   label: 'Tactics',   icon: Target },
    { id: 'MACRO',     label: 'Macro Hub',  icon: Lightbulb },
    { id: 'CALENDAR',  label: 'Calendar',   icon: Calendar },
  ];

  const dk = theme === 'dark';

  useEffect(() => {
    sessionStorage.setItem(MARKET_INTEL_SUBTAB_KEY, activeSubTab);
    if (!visitedSubTabs.includes(activeSubTab)) {
      setVisitedSubTabs(prev => [...prev, activeSubTab]);
    }
  }, [activeSubTab, visitedSubTabs]);

  useEffect(() => {
    const preload = () => {
      void loadTacticsHub();
      void loadIntelligenceHub();
      void loadEconomicCalendar();
    };

    if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
      const idleId = window.requestIdleCallback(preload, { timeout: 1200 });
      return () => window.cancelIdleCallback(idleId);
    }

    const timer = window.setTimeout(preload, 250);
    return () => window.clearTimeout(timer);
  }, []);

  const prefetchTab = (tabId: SubTab) => {
    if (tabId === 'TACTICS') void loadTacticsHub();
    if (tabId === 'MACRO') void loadIntelligenceHub();
    if (tabId === 'CALENDAR') void loadEconomicCalendar();
    if (tabId === 'SENTIMENT') void loadNewsSentimentHub();
    if (tabId === 'TRENDS') void loadTrendsView();
  };

  return (
    <div className="flex flex-col min-h-screen">
      <div className={`sticky top-0 z-50 border-b backdrop-blur-xl ${
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
                onMouseEnter={() => prefetchTab(tab.id)}
                onFocus={() => prefetchTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl transition-all ${
                  active 
                    ? (dk ? 'bg-blue-500/20 text-blue-400' : 'bg-blue-50 text-blue-600') 
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
            {(['TRENDS', 'SENTIMENT', 'TACTICS', 'MACRO', 'CALENDAR'] as const).map((tabId) => {
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
                  {tabId === 'TRENDS' && <TrendsView />}
                  {tabId === 'SENTIMENT' && <NewsSentimentHub />}
                  {tabId === 'TACTICS' && <TacticsHub />}
                  {tabId === 'MACRO' && <IntelligenceHub />}
                  {tabId === 'CALENDAR' && <EconomicCalendar />}
                </motion.div>
              );
            })}
          </div>
        </Suspense>
      </div>
    </div>
  );
};
