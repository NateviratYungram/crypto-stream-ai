import { useState, Suspense, lazy, useEffect } from 'react';
import { motion } from 'framer-motion';
import { ShieldAlert, Bell, Percent } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { TabSkeleton } from './TabSkeleton';

const RiskAuditsView = lazy(() => import('./RiskAuditsView').then(m => ({ default: m.RiskAuditsView })));
const AlertsReviewsView = lazy(() => import('./AlertsReviewsView').then(m => ({ default: m.AlertsReviewsView })));
const FundingRatesView = lazy(() => import('./FundingRatesView').then(m => ({ default: m.FundingRatesView })));

type SubTab = 'RISK' | 'ALERTS' | 'FUNDING';
const RISK_ALERTS_SUBTAB_KEY = 'crypto_risk_alerts_subtab';

export const RiskAlerts = () => {
  const { theme } = useMode();
  const [activeSubTab, setActiveSubTab] = useState<SubTab>(() => {
    const stored = sessionStorage.getItem(RISK_ALERTS_SUBTAB_KEY);
    return stored === 'ALERTS' || stored === 'FUNDING' ? stored : 'RISK';
  });
  const [visitedSubTabs, setVisitedSubTabs] = useState<SubTab[]>(() => {
    const stored = sessionStorage.getItem(RISK_ALERTS_SUBTAB_KEY);
    return stored === 'ALERTS' || stored === 'FUNDING' ? ['RISK', stored] : ['RISK'];
  });

  const tabs: { id: SubTab; label: string; icon: any }[] = [
    { id: 'RISK',    label: 'Risk Audits', icon: ShieldAlert },
    { id: 'ALERTS',  label: 'Alerts Hub',  icon: Bell },
    { id: 'FUNDING', label: 'Funding',     icon: Percent },
  ];

  const dk = theme === 'dark';

  useEffect(() => {
    sessionStorage.setItem(RISK_ALERTS_SUBTAB_KEY, activeSubTab);
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
                    ? (dk ? 'bg-rose-500/20 text-rose-400' : 'bg-rose-50 text-rose-600') 
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
            {(['RISK', 'ALERTS', 'FUNDING'] as const).map((tabId) => {
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
                  {tabId === 'RISK' && <RiskAuditsView />}
                  {tabId === 'ALERTS' && <AlertsReviewsView />}
                  {tabId === 'FUNDING' && <FundingRatesView />}
                </motion.div>
              );
            })}
          </div>
        </Suspense>
      </div>
    </div>
  );
};
