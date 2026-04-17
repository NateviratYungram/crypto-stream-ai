import React from 'react';
import {
  Activity,
  MessageSquare,
  Radar,
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
  ClipboardList
} from 'lucide-react';
import { motion } from 'framer-motion';

interface AppSidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  wsStatus: string;
}

export const AppSidebar: React.FC<AppSidebarProps> = ({ activeTab, setActiveTab, wsStatus }) => {
  const menuGroups = [
    {
      label: 'Market Intelligence',
      items: [
        { id: 'Market Trends',        label: 'Tactical Dashboard',  icon: LayoutGrid        },
        { id: 'Sentiment Hub',        label: 'News Sentiment',       icon: Newspaper         },
        { id: 'Intelligence Hub',     label: 'Quant Intelligence',   icon: Brain             },
        { id: 'Trading Tactics',      label: 'Trading Tactics',      icon: Target            },
        { id: 'Screener',             label: 'Market Screener',      icon: SlidersHorizontal },
      ]
    },
    {
      label: 'Tracking & Signals',
      items: [
        { id: 'Whale Tracker',        label: 'Whale Radar',          icon: Zap               },
        { id: 'Funding Rates',        label: 'Funding Rates',        icon: DollarSign        },
        { id: 'ETF Flows',            label: 'ETF Flows',            icon: BarChart2         },
        { id: 'Watchlist',            label: 'Watchlist',            icon: Star              },
      ]
    },
    {
      label: 'AI & Chat',
      items: [
        { id: 'Strategy Chat',        label: 'AI Strategy Chat',     icon: MessageSquare     },
        { id: 'AI Persona',           label: 'AI Persona',           icon: Bot               },
      ]
    },
    {
      label: 'Risk & Portfolio',
      items: [
        { id: 'Institutional Assets', label: 'Portfolio Analytics',  icon: PieChart          },
        { id: 'Risk Audits',          label: 'Compliance Audit',     icon: ShieldAlert       },
        { id: 'Trading Journal',      label: 'Trading Journal',      icon: BookOpen          },
        { id: 'Paper Trading',        label: 'Paper Trading',        icon: ClipboardList     },
        { id: 'Alerts & Reviews',     label: 'Alerts & Reviews',     icon: Bell              },
      ]
    },
    {
      label: 'Tools & Settings',
      items: [
        { id: 'Economic Calendar',    label: 'Economic Calendar',    icon: CalendarDays      },
        { id: 'Profile Settings',     label: 'Profile & Account',    icon: UserCircle        },
      ]
    }
  ];

  return (
    <aside className="w-68 border-r border-white/5 bg-slate-950 flex flex-col h-full z-40 transition-all duration-300 hidden lg:flex">
      {/* Search Input Container */}
      <div className="p-4 mt-2">
        <div className="relative group">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 group-hover:text-blue-400 transition-colors" />
          <input
            type="text"
            placeholder="Search panels..."
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
                onClick={() => setActiveTab(item.id)}
                className={`w-full group flex items-center justify-between px-3 py-2.5 rounded-xl transition-all relative ${
                  activeTab === item.id
                    ? 'bg-blue-600/15 border border-blue-500/20 text-blue-400 shadow-[0_0_20px_rgba(37,99,235,0.05)]'
                    : 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border border-transparent'
                }`}
              >
                <div className="flex items-center gap-3">
                  <item.icon className={`w-4 h-4 transition-colors ${activeTab === item.id ? 'text-blue-400' : 'group-hover:text-slate-400'}`} />
                  <span className={`text-[11px] font-black uppercase tracking-widest ${activeTab === item.id ? 'text-blue-400' : ''}`}>
                    {item.label}
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
          <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Connectivity</span>
          <div className="flex items-center gap-2">
             <div className={`w-2 h-2 rounded-full ${wsStatus === 'open' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'} shadow-[0_0_8px_currentColor]`} />
             <span className={`text-[10px] font-black uppercase tracking-widest ${wsStatus === 'open' ? 'text-emerald-500' : 'text-rose-500'}`}>
               {wsStatus.toUpperCase()}
             </span>
          </div>
        </div>

        <button className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-xl bg-white/5 hover:bg-white/10 border border-white/5 text-[10px] font-black text-slate-400 hover:text-slate-200 transition-all uppercase tracking-widest">
          <Settings className="w-3.5 h-3.5" /> Support Console
        </button>
      </div>
    </aside>
  );
};
