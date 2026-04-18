import React from 'react';
import {
  Activity,
  MessageSquare,
  ShieldAlert,
  PieChart,
  Newspaper,
  Settings,
  LayoutGrid,
  Search,
  Brain,
  Target,
  SlidersHorizontal,
  Star,
  BookOpen,
  BarChart2,
  DollarSign,
  Bot,
  Bell,
  Zap,
  CalendarDays,
  UserCircle,
  ClipboardList,
  FlaskConical
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useLanguage } from '../../contexts/LanguageContext';

interface AppSidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  wsStatus: string;
  onNavClick?: () => void;
  mode?: 'retail' | 'institutional';
}

export const AppSidebar: React.FC<AppSidebarProps> = ({ activeTab, setActiveTab, wsStatus, onNavClick, mode = 'retail' }) => {
  const isRetail = mode === 'retail';
  const { t } = useLanguage();

  const retailGroups = [
    {
      label: t('sidebar.markets'),
      items: [
        { id: 'Market Trends',    icon: LayoutGrid        },
        { id: 'Sentiment Hub',    icon: Newspaper         },
        { id: 'Screener',         icon: SlidersHorizontal },
        { id: 'Watchlist',        icon: Star              },
        { id: 'Economic Calendar',icon: CalendarDays      },
      ]
    },
    {
      label: t('sidebar.trading_tools'),
      items: [
        { id: 'Strategy Chat',    icon: MessageSquare     },
        { id: 'Paper Trading',    icon: ClipboardList     },
        { id: 'Trading Journal',  icon: BookOpen          },
      ]
    },
    {
      label: t('sidebar.account'),
      items: [
        { id: 'Profile Settings', icon: UserCircle        },
      ]
    }
  ];

  const institutionalGroups = [
    {
      label: t('sidebar.market_intelligence'),
      items: [
        { id: 'Market Trends',        icon: LayoutGrid        },
        { id: 'Sentiment Hub',        icon: Newspaper         },
        { id: 'Intelligence Hub',     icon: Brain             },
        { id: 'Trading Tactics',      icon: Target            },
        { id: 'Screener',             icon: SlidersHorizontal },
      ]
    },
    {
      label: t('sidebar.tracking_signals'),
      items: [
        { id: 'Whale Tracker',        icon: Zap               },
        { id: 'Funding Rates',        icon: DollarSign        },
        { id: 'ETF Flows',            icon: BarChart2         },
        { id: 'Watchlist',            icon: Star              },
      ]
    },
    {
      label: t('sidebar.ai_chat'),
      items: [
        { id: 'Strategy Chat',        icon: MessageSquare     },
        { id: 'AI Persona',           icon: Bot               },
      ]
    },
    {
      label: t('sidebar.risk_portfolio'),
      items: [
        { id: 'Institutional Assets', icon: PieChart          },
        { id: 'Risk Audits',          icon: ShieldAlert       },
        { id: 'Trading Journal',      icon: BookOpen          },
        { id: 'Paper Trading',        icon: ClipboardList     },
        { id: 'Backtester',           icon: FlaskConical      },
        { id: 'Alerts & Reviews',     icon: Bell              },
      ]
    },
    {
      label: t('sidebar.tools_settings'),
      items: [
        { id: 'Economic Calendar',    icon: CalendarDays      },
        { id: 'ML Model',             icon: Activity          },
        { id: 'Profile Settings',     icon: UserCircle        },
      ]
    }
  ];

  const menuGroups = isRetail ? retailGroups : institutionalGroups;

  return (
    <aside className={`w-68 border-r border-white/5 bg-slate-950 flex-col h-full z-40 transition-all duration-300 ${onNavClick ? 'flex' : 'hidden lg:flex'}`}>
      {/* Mode badge */}
      <div className="px-4 pt-4">
        <div className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-[10px] font-black uppercase tracking-widest ${
          isRetail
            ? 'bg-emerald-500/5 border-emerald-500/15 text-emerald-400'
            : 'bg-blue-500/5 border-blue-500/15 text-blue-400'
        }`}>
          <div className={`w-1.5 h-1.5 rounded-full animate-pulse ${isRetail ? 'bg-emerald-400' : 'bg-blue-400'}`} />
          {isRetail ? t('sidebar.retail_mode') : t('sidebar.institutional_mode')}
        </div>
      </div>

      {/* Search Input Container */}
      <div className="p-4 mt-2">
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-hover:text-blue-400 transition-colors" />
          <input
            type="text"
            placeholder={t('sidebar.search')}
            className="w-full bg-slate-900/50 border border-white/5 rounded-xl py-2 pl-9 pr-4 text-xs font-bold text-slate-300 placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-blue-500/30 transition-all"
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-4 py-2 space-y-6 scrollbar-hide">
        {menuGroups.map((group) => (
          <div key={group.label} className="space-y-1">
            <h3 className="px-3 text-[10px] font-black uppercase tracking-[0.2em] text-slate-600 mb-2">{group.label}</h3>
            {group.items.map((item) => (
              <button
                key={item.id}
                onClick={() => { setActiveTab(item.id); onNavClick?.(); }}
                className={`w-full group flex items-center justify-between px-3 py-2.5 rounded-xl transition-all relative ${
                  activeTab === item.id
                    ? 'bg-blue-600/15 border border-blue-500/20 text-blue-400 shadow-[0_0_20px_rgba(37,99,235,0.05)]'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-3">
                  <item.icon className={`w-4 h-4 transition-colors ${activeTab === item.id ? 'text-blue-400' : 'group-hover:text-slate-400'}`} />
                  <span className={`text-[11px] font-black uppercase tracking-widest ${activeTab === item.id ? 'text-blue-400' : ''}`}>
                    {t(`tab.${item.id}` as Parameters<typeof t>[0])}
                  </span>
                </div>
                {activeTab === item.id && (
                  <motion.div layoutId="active-pill" className="w-1 absolute right-2 h-1 bg-blue-500 rounded-full shadow-[0_0_8px_rgba(59,130,246,1)]" />
                )}
              </button>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer / System Status */}
      <div className="p-4 border-t border-white/5 bg-slate-950/80 backdrop-blur-md">
        <div className="flex items-center justify-between mb-3 px-1">
          <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{t('sidebar.connectivity')}</span>
          <div className="flex items-center gap-2">
             <div className={`w-2 h-2 rounded-full ${wsStatus === 'open' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'} shadow-[0_0_8px_currentColor]`} />
             <span className={`text-[10px] font-black uppercase tracking-widest ${wsStatus === 'open' ? 'text-emerald-500' : 'text-rose-500'}`}>
               {wsStatus.toUpperCase()}
             </span>
          </div>
        </div>

        <button className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 text-[10px] font-black text-slate-400 hover:text-slate-200 transition-all uppercase tracking-widest">
          <Settings className="w-3.5 h-3.5" /> {t('sidebar.support_console')}
        </button>
      </div>
    </aside>
  );
};
