import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ShieldCheck, AlertCircle, Terminal, Clock, RefreshCcw, Activity, ShieldQuestion, Zap } from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';
import { useWebSocket } from '../hooks/useWebSocket';

export const RiskAuditsView = () => {
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { wsStatus, lastMessage } = useWebSocket();

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/data/audits');
      const json = await res.json();
      setLogs(json.data || []);
    } catch (error) {
      console.error('Fetch error:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  // Real-time DQ Alert Handling
  useEffect(() => {
    if (lastMessage?.type === 'DQ_ALERT') {
      const newLog = {
        type: 'DQ_ERROR',
        detail: `DQ Violation: ${lastMessage.data.error_reason} | ${lastMessage.data.symbol}`,
        time: new Date().toISOString()
      };
      setLogs(prev => [newLog, ...prev.slice(0, 19)]); // Keep latest 20
    }
  }, [lastMessage]);

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-10 custom-scrollbar">
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-indigo-500 font-bold text-[10px] uppercase tracking-[0.2em]">
             <div className={`w-1.5 h-1.5 rounded-full shadow-[0_0_8px_rgba(99,102,241,0.5)] ${
                wsStatus === 'connected' ? 'bg-indigo-500 status-breath' : 'bg-slate-700'
             }`} />
             Integrity Guard {wsStatus === 'connected' && '• LIVE'}
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight flex items-center gap-3">
             Risk Intel Terminal
          </h2>
          <p className="text-slate-500 text-sm font-medium">Monitoring DQ isolation gates and autonomous AI query permissions.</p>
        </div>
        <div className="flex items-center gap-4">
          {wsStatus === 'connected' && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
              <Zap className="w-3 h-3 text-emerald-400 fill-emerald-400" />
              <span className="text-[10px] text-emerald-400 font-black uppercase tracking-tighter">DLQ MONITOR ACTIVE</span>
            </div>
          )}
          <button 
            onClick={fetchLogs} 
            className="group flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-indigo-500/50 rounded-xl text-slate-300 transition-all font-bold text-xs"
          >
            <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`} />
            Refresh Trail
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4">
        {loading ? (
            [1,2,3,4].map(i => <div key={i} className="h-28 bg-slate-900/40 animate-pulse rounded-3xl border border-white/5" />)
        ) : (
          <AnimatePresence initial={false}>
            {logs.map((log, i) => (
              <motion.div
                key={log.time + i}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.4 }}
              >
                <HoverGlowCard className="p-6 flex items-start gap-6 rounded-[1.5rem]">
                  <div className={`mt-1 p-3 rounded-2xl shrink-0 border ${
                    log.type === 'DQ_ERROR' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20 shadow-[0_0_15px_rgba(244,63,94,0.1)]' : 'bg-blue-500/10 text-blue-400 border-blue-500/20'
                  }`}>
                    {log.type === 'DQ_ERROR' ? <ShieldQuestion className="w-5 h-5" /> : <Terminal className="w-5 h-5" />}
                  </div>
                  
                  <div className="flex-1 space-y-3">
                    <div className="flex justify-between items-center">
                      <div className="flex items-center gap-3">
                         <span className={`text-[10px] font-black uppercase tracking-[0.15em] px-2 py-0.5 rounded ${
                            log.type === 'DQ_ERROR' ? 'bg-rose-500/10 text-rose-400' : 'bg-blue-500/10 text-blue-400'
                         }`}>
                            {log.type === 'DQ_ERROR' ? 'DQ VIOLATION' : 'AI TRACE'}
                         </span>
                         <div className="h-1 w-1 rounded-full bg-slate-700" />
                         <span className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Node: Delta-01</span>
                      </div>
                      <div className="flex items-center gap-2 text-[10px] text-slate-500 font-mono font-bold">
                        <Clock className="w-3.5 h-3.5 opacity-50" />
                        {new Date(log.time).toLocaleString()}
                      </div>
                    </div>
                    
                    <div className="bg-black/20 p-4 rounded-xl border border-white/[0.03] font-mono">
                       <p className="text-sm font-bold text-slate-300 leading-relaxed">
                          <span className="text-slate-600 mr-2">$</span>
                          {log.detail}
                       </p>
                    </div>

                    <div className="flex items-center gap-6 text-[10px] font-bold">
                      <span className="flex items-center gap-1.5 text-emerald-500/80">
                        <ShieldCheck className="w-3.5 h-3.5" />
                        VERIFIED ENCLAVE
                      </span>
                      <span className="text-slate-600 uppercase">ACTION: {log.type === 'DQ_ERROR' ? 'ISOLATED_IN_DLQ' : 'LOGGED_IN_AUDIT'}</span>
                    </div>
                  </div>
                </HoverGlowCard>
              </motion.div>
            ))}
          </AnimatePresence>
        )}

        {!loading && logs.length === 0 && (
          <div className="bg-emerald-500/[0.02] border border-emerald-500/10 p-20 rounded-[3rem] text-center space-y-4">
            <div className="w-20 h-20 bg-emerald-500/10 rounded-full flex items-center justify-center mx-auto border border-emerald-500/20">
               <ShieldCheck className="w-10 h-10 text-emerald-400" />
            </div>
            <div className="space-y-1">
               <h3 className="text-emerald-400 font-black text-xl tracking-tight">Perimeter Secure</h3>
               <p className="text-slate-500 text-sm font-medium">No recent risk anomalies or data quality violations detected across the pipeline.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
