import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
  Zap, LogOut, TrendingUp, ShieldAlert, MessageSquare,
  LayoutDashboard, Brain
} from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  wsStatus: 'connecting' | 'open' | 'closed';
}

export const Sidebar = ({ activeTab, setActiveTab, wsStatus }: SidebarProps) => {
  const { isRetail } = useMode();
  const [health, setHealth] = useState<{db: string, kafka: string, mcp: string}>({
    db: 'loading', kafka: 'loading', mcp: 'loading'
  });

  const checkHealth = async () => {
    try {
      const res = await fetch('/api/health');
      const data = await res.json();
      setHealth({
        db: data.db,
        kafka: data.kafka_broker === 'localhost:9092' ? 'ok' : 'error',
        mcp: data.mcp
      });
    } catch {
      setHealth({ db: 'error', kafka: 'error', mcp: 'error' });
    }
  };

  useEffect(() => {
    checkHealth();
    const timer = setInterval(checkHealth, 5000);
    return () => clearInterval(timer);
  }, []);

  const menuItems = [
    { id: 'Market Trends',    label: isRetail ? '📈 ราคาตลาด'      : 'Market Trends',    sublabel: isRetail ? 'Live prices'         : '', icon: TrendingUp  },
    { id: 'Intelligence Hub', label: isRetail ? '🧠 สัญญาณ AI'     : 'Intelligence Hub', sublabel: isRetail ? 'AI buy/sell signals'  : '', icon: Brain       },
    { id: 'Whale Tracker',    label: isRetail ? '🐋 วาฬ Tracker'    : 'Whale Tracker',    sublabel: isRetail ? 'Big player trades'    : '', icon: Zap         },
    { id: 'Risk Audits',      label: isRetail ? '🛡️ ความเสี่ยง'    : 'Risk Intel',       sublabel: isRetail ? 'Market risk meter'    : '', icon: ShieldAlert },
    { id: 'Strategy Chat',    label: isRetail ? '💬 ถาม AI'         : 'Strategy Chat',    sublabel: isRetail ? 'Ask anything in Thai' : '', icon: MessageSquare },
  ];

  const handleLogout = () => {
    localStorage.removeItem('crypto_terminal_key');
    window.location.reload();
  };

  return (
    <aside className="w-80 h-screen bg-slate-900/40 backdrop-blur-3xl border-r border-white/5 flex flex-col p-6 gap-8 z-30 relative overflow-hidden">
      {/* Glossy Overlay */}
      <div className="absolute inset-0 bg-gradient-to-b from-blue-500/5 via-transparent to-transparent pointer-events-none" />
      
      <div className="fixed inset-0 terminal-scanline opacity-[0.02] pointer-events-none" />

      {/* Brand Section */}
      <div className="flex items-center gap-4 pb-8 border-b border-white/5 relative z-10">
        <motion.div 
          animate={wsStatus === 'open' ? { scale: [1, 1.05, 1] } : {}}
          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
          className={`w-12 h-12 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-2xl flex items-center justify-center shadow-2xl shadow-blue-500/20 group cursor-pointer transition-transform active:scale-95 ${wsStatus === 'open' ? 'infra-pulse' : ''}`}
        >
          <LayoutDashboard className="w-6 h-6 text-white group-hover:rotate-12 transition-transform" />
        </motion.div>
        <div>
          <h1 className="text-xl font-black text-white tracking-tighter leading-none uppercase">CryptoStream</h1>
          <p className="text-[10px] text-blue-400 font-black uppercase tracking-[0.2em] mt-1.5 opacity-80">Tactical Terminal</p>
        </div>
      </div>

      {/* Main Navigation */}
      <nav className="flex-1 space-y-2 relative z-10">
        <p className="px-4 text-[9px] font-black text-slate-500 uppercase tracking-[0.2em] mb-4">Command Deck</p>
        <div className="space-y-1.5">
          {menuItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center gap-4 px-5 py-4 rounded-2xl transition-all duration-300 group relative ${
                activeTab === item.id 
                  ? 'bg-blue-600/10 text-blue-400 border border-blue-500/20 shadow-lg shadow-blue-900/10' 
                  : 'text-slate-400 hover:text-white hover:bg-white/5 border border-transparent'
              }`}
            >
              {activeTab === item.id && (
                <motion.div 
                  layoutId="activePill"
                  className="absolute left-0 w-1 h-6 bg-blue-500 rounded-r-full"
                />
              )}
              <item.icon className={`w-5 h-5 shrink-0 ${activeTab === item.id ? 'glow-bloom shadow-blue-500/50' : ''}`} />
              <div className="flex flex-col items-start">
                <span className="text-xs font-bold uppercase tracking-widest leading-none">{item.label}</span>
                {item.sublabel && (
                  <span className="text-[9px] text-slate-600 font-bold leading-none mt-1">{item.sublabel}</span>
                )}
              </div>
            </button>
          ))}
        </div>
      </nav>

      {/* Institutional Health Stack */}
      <div className="space-y-6 relative z-10">
        <p className="px-4 text-[9px] font-black text-slate-500 uppercase tracking-[0.2em]">Infrastructure Stack</p>
        <div className="space-y-4 px-2">
          <StatusRow label="Persistence" status={health.db} sub="PostgreSQL Cluster" />
          <StatusRow label="Ingestion" status={health.kafka} sub="Kafka / Flink" />
          <StatusRow label="Intelligence" status={health.mcp} sub="AI MCP Enclave" />
          <StatusRow label="Market Bridge" status={wsStatus === 'open' ? 'ok' : wsStatus === 'connecting' ? 'loading' : 'error'} sub="WebSocket Node" />
        </div>

        <div className="p-4 bg-slate-950/50 rounded-2xl border border-white/5 space-y-3 shadow-inner">
           <div className="flex items-center gap-2 px-1">
             <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
             <span className="text-[9px] font-black text-emerald-500 uppercase tracking-widest leading-none">Security Protocol Active</span>
           </div>
           <p className="text-[8px] text-slate-600 font-bold uppercase tracking-widest leading-none px-1">Session Level: 4-Institutional</p>
        </div>
      </div>

      <div className="pt-4 border-t border-white/5 relative z-10">
         <button onClick={handleLogout} className="w-full flex items-center gap-3 px-3 py-2 text-slate-500 hover:text-rose-400 transition-colors group">
            <LogOut className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
            <span className="text-[10px] font-black uppercase tracking-widest">Terminate Session</span>
         </button>
      </div>
    </aside>
  );
};

const StatusRow = ({ label, status, sub }: { label: string; status: string; sub: string }) => (
  <div className="flex flex-col gap-1 group/row">
    <div className="flex items-center justify-between">
      <span className="text-[10px] font-black text-slate-300 uppercase tracking-wider group-hover/row:text-white transition-colors">{label}</span>
      <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-full border ${
        status === 'ok' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' :
        status === 'loading' ? 'bg-amber-500/10 border-amber-500/20 text-amber-400' :
        'bg-rose-500/10 border-rose-500/20 text-rose-400'
      }`}>
        <div className={`w-1 h-1 rounded-full ${
          status === 'ok' ? 'bg-emerald-400' : status === 'loading' ? 'bg-amber-400 animate-pulse' : 'bg-rose-400 animate-pulse'
        }`} />
        <span className="text-[8px] font-black uppercase tracking-tighter">{status === 'ok' ? 'Online' : status === 'loading' ? 'Sync' : 'Fail'}</span>
      </div>
    </div>
    <span className="text-[8px] text-slate-600 font-bold uppercase tracking-widest">{sub}</span>
  </div>
);
