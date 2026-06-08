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
  FlaskConical,
  DatabaseZap,
  LogOut
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useLanguage } from '../../contexts/LanguageContext';
import { useMode } from '../../contexts/ModeContext';

interface AppSidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  wsStatus: string;
  onNavClick?: () => void;
  onLogout?: () => void;
}

export const AppSidebar: React.FC<AppSidebarProps> = ({ activeTab, setActiveTab, wsStatus, onNavClick, onLogout }) => {
  const { t } = useLanguage();
  const { theme } = useMode();

  const mainGroups = [
    {
      label: 'Trading & Discovery',
      items: [
        { id: 'Alpha Terminal',      icon: SlidersHorizontal },
        { id: 'Market Intelligence', icon: LayoutGrid        },
        { id: 'Money Flow',          icon: Zap               },
      ]
    },
    {
      label: 'Analysis & Strategy',
      items: [
        { id: 'Strategy Chat',       icon: MessageSquare     },
        { id: 'Risk & Alerts',       icon: ShieldAlert       },
        { id: 'Strategy Lab',        icon: FlaskConical      },
        { id: 'RAG Ops',             icon: DatabaseZap       },
      ]
    }
  ];

  const menuGroups = mainGroups;

  return (
    <aside className={`w-72 min-w-[288px] shrink-0 border-r transition-all duration-500 flex-col h-full z-40 relative overflow-hidden ${
      theme === 'dark' 
        ? 'bg-slate-950 border-white/5 shadow-[20px_0_40px_rgba(0,0,0,0.4)]' 
        : 'bg-white border-slate-200 shadow-[10px_0_30px_rgba(0,0,0,0.02)]'
    } ${onNavClick ? 'flex' : 'hidden lg:flex'}`}>
      {/* Decorative gradient for light mode sidebar */}
      {theme === 'light' && (
        <div className="absolute inset-0 pointer-events-none opacity-40">
          <div className="absolute top-0 left-0 w-full h-64 bg-gradient-to-b from-blue-50/50 to-transparent" />
          <div className="absolute bottom-0 left-0 w-full h-64 bg-gradient-to-t from-indigo-50/30 to-transparent" />
        </div>
      )}

      {/* Workspace badge */}
      <div className="px-4 pt-6 relative z-10">
        <div className={`flex items-center gap-2 px-3 py-2.5 rounded-2xl border text-[10px] font-black uppercase tracking-[0.15em] transition-all duration-500 shadow-sm ${
          theme === 'dark' ? 'bg-emerald-500/5 border-emerald-500/15 text-emerald-400 shadow-emerald-500/5' : 'bg-emerald-50/80 border-emerald-200/60 text-emerald-600 shadow-emerald-500/10'
        }`}>
          <div className="w-2 h-2 rounded-full animate-pulse shadow-[0_0_8px_currentColor] bg-emerald-400" />
          Live Workspace
        </div>
      </div>

      {/* Search Input Container */}
      <div className="p-4 mt-2 relative z-10">
        <div className="relative group">
          <Search className={`absolute left-3.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 transition-all duration-500 group-focus-within:scale-110 ${
            theme === 'dark' ? 'text-slate-500 group-hover:text-blue-400' : 'text-slate-400 group-hover:text-blue-500'
          }`} />
          <input
            type="text"
            placeholder={t('sidebar.search')}
            className={`w-full border rounded-2xl py-2.5 pl-10 pr-4 text-[11px] font-bold transition-all duration-500 focus:outline-none focus:ring-2 shadow-sm ${
              theme === 'dark' 
                ? 'bg-slate-900/50 border-white/5 text-slate-300 placeholder:text-slate-600 focus:ring-blue-500/20 focus:bg-slate-900' 
                : 'bg-slate-50/50 border-slate-200/60 text-slate-700 placeholder:text-slate-400 focus:ring-blue-500/10 focus:bg-white focus:border-blue-500/30'
            }`}
          />
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto px-4 py-2 space-y-8 scrollbar-hide relative z-10">
        {menuGroups.map((group) => (
          <div key={group.label} className="space-y-2">
            <h3 className={`px-3 text-[9px] font-black uppercase tracking-[0.25em] transition-colors duration-500 mb-3 opacity-60 ${
              theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
            }`}>{group.label}</h3>
            <div className="space-y-1">
              {group.items.map((item) => (
                <button
                  key={item.id}
                  onClick={() => { setActiveTab(item.id); onNavClick?.(); }}
                  className={`w-full group flex items-center justify-between px-3.5 py-2.5 rounded-2xl transition-all duration-500 relative border ${
                    activeTab === item.id
                      ? (theme === 'dark' 
                          ? 'bg-blue-600/15 border-blue-500/20 text-blue-400 shadow-[0_0_20px_rgba(37,99,235,0.1)]' 
                          : 'bg-blue-600 border-blue-600 text-white shadow-xl shadow-blue-500/30 scale-[1.02]')
                      : (theme === 'dark' 
                          ? 'text-slate-500 hover:text-slate-300 hover:bg-white/5 border-transparent' 
                          : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 border-transparent hover:shadow-sm')
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <item.icon className={`w-4 h-4 transition-all duration-500 group-hover:scale-110 ${
                      activeTab === item.id 
                        ? (theme === 'dark' ? 'text-blue-400' : 'text-white') 
                        : (theme === 'dark' ? 'group-hover:text-slate-400' : 'group-hover:text-blue-600')
                    }`} />
                    <span className={`text-[11px] font-black uppercase tracking-widest transition-colors duration-500 ${
                      activeTab === item.id ? (theme === 'dark' ? 'text-blue-400' : 'text-white') : ''
                    }`}>
                      {item.id}
                    </span>
                  </div>
                  {activeTab === item.id && (
                    <motion.div 
                      layoutId="active-pill" 
                      className={`w-1.5 h-1.5 rounded-full ${
                        theme === 'dark' ? 'bg-blue-500 shadow-[0_0_8px_rgba(59,130,246,1)]' : 'bg-white shadow-[0_0_8px_white]'
                      }`} 
                    />
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer / System Status */}
      <div className={`p-5 border-t transition-all duration-500 relative z-10 ${
        theme === 'dark' ? 'border-white/5 bg-slate-900/80' : 'border-slate-200/60 bg-white shadow-[0_-10px_30px_rgba(0,0,0,0.02)]'
      }`}>
        <div className="flex items-center justify-between mb-4 px-1">
          <span className={`text-[10px] font-black uppercase tracking-widest transition-colors duration-500 opacity-60 ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}>{t('sidebar.connectivity')}</span>
          <div className="flex items-center gap-2.5">
             <div className={`w-2 h-2 rounded-full shadow-[0_0_10px_currentColor] ${
               wsStatus === 'open' ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'
             }`} />
             <span className={`text-[10px] font-black uppercase tracking-widest ${
               wsStatus === 'open' ? 'text-emerald-500' : 'text-rose-500'
             }`}>
               {wsStatus.toUpperCase()}
             </span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <button
            onClick={() => { setActiveTab('Settings'); onNavClick?.(); }}
            className={`w-full group flex items-center justify-center gap-2.5 px-4 py-3 rounded-2xl border text-[10px] font-black transition-all duration-500 uppercase tracking-widest shadow-sm active:scale-95 ${
            theme === 'dark' 
              ? 'bg-white/5 hover:bg-white/10 border-white/5 text-slate-400 hover:text-slate-200' 
              : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-900 shadow-sm shadow-slate-200/50 hover:shadow-md'
          }`}>
            <Settings className="w-3.5 h-3.5 group-hover:rotate-90 transition-transform duration-500" /> 
            {t('sidebar.support_console')}
          </button>
          
          <button 
            onClick={onLogout}
            className={`w-full group flex items-center justify-center gap-2.5 px-4 py-3 rounded-2xl border text-[10px] font-black transition-all duration-500 uppercase tracking-widest shadow-sm active:scale-95 ${
              theme === 'dark' 
                ? 'bg-rose-500/5 hover:bg-rose-500/10 border-rose-500/10 text-rose-400 hover:text-rose-300' 
                : 'bg-rose-100 hover:bg-rose-200 border-rose-200 text-rose-700'
            }`}
          >
            <LogOut className="w-3.5 h-3.5 group-hover:-translate-x-1 transition-transform" /> 
            {t('navbar.signout')}
          </button>

        </div>
      </div>
    </aside>
  );
};
