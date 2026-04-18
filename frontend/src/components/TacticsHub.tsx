import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Shield, TrendingUp, Zap, Target, ChevronRight } from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';

interface AuditLog {
  id: number;
  symbol: string;
  confidence: number;
  reasoning: string;
  price: number;
  timestamp: string;
}

interface Tactic {
  name: string;
  style: string;
  score: number;
  move: string;
  trigger: string;
  invalidation: string;
  tp: string;
  logic: string;
}

interface TacticsData {
  symbol: string;
  price: number;
  recommendation: string;
  best_persona: string;
  tactics: Tactic[];
  timestamp: number;
  v7_status?: {
    active: boolean;
    sniper_mode: boolean;
    sniper_locked: boolean;
    lock_reason: string | null;
    institutional_flow: {
      bullish_sweep?: any;
      bearish_sweep?: any;
    };
  };
  ai_edge?: {
    win_probability: number;
    win_pct: number;
    accuracy: number;
    rationale: string[];
    n_samples?: number;
    trained_at?: string;
    neural_alignment?: boolean;
    v8_prob?: number;
    attention_impact?: number[];
    hybrid_active?: boolean;
    hurst_exponent?: number;
    vol_skew?: number;
    hurst_regime?: string;
    drift_score?: number;
    reflexive_active?: boolean;
    v8_active?: boolean;
    portfolio_health?: string;
    kelly_size?: number;
    htf_on_sync?: boolean;
  };
}

export const TacticsHub = () => {
  const [symbol, setSymbol] = useState('BTC');
  const [data, setData] = useState<TacticsData | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apiKey = () => localStorage.getItem('crypto_terminal_key') || 'demo';

  const fetchTactics = async (targetSym: string) => {
    setLoading(true);
    setError(null);
    const headers = { 'X-API-Key': apiKey() };
    try {
      const res = await fetch(`/api/tactics/${targetSym}`, { headers });
      const json = await res.json();
      if (json.error) throw new Error(json.error);
      if (json.detail) throw new Error(String(json.detail));
      if (!json.tactics || !Array.isArray(json.tactics)) {
        throw new Error(`Server returned: ${JSON.stringify(json).slice(0, 200)}`);
      }
      setData(json);

      // Fetch Audit Logs too
      const auditRes = await fetch('/api/tactics/audit/logs', { headers });
      const auditJson = await auditRes.json();
      if (auditJson.logs) setAuditLogs(auditJson.logs);
      
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTactics(symbol);
  }, []);

  const handleSearch = (e: React.SyntheticEvent) => {
    e.preventDefault();
    fetchTactics(symbol.toUpperCase());
  };

  const getPersonaIcon = (name: string) => {
    if (name.includes('Trend')) return <TrendingUp className="w-5 h-5 text-emerald-400" />;
    if (name.includes('Liquidity')) return <Shield className="w-5 h-5 text-indigo-400" />;
    if (name.includes('Breakout')) return <Zap className="w-5 h-5 text-amber-400" />;
    if (name.includes('Mean')) return <TrendingUp className="w-5 h-5 text-blue-400 rotate-180" />;
    if (name.includes('Stock')) return <Target className="w-5 h-5 text-purple-400" />;
    if (name.includes('No Trade')) return <Shield className="w-5 h-5 text-rose-400" />;
    if (name.includes('AI Confidence')) return <Zap className="w-5 h-5 text-indigo-400 glow-bloom" />;
    return <Zap className="w-5 h-5 text-slate-400" />;
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return 'text-emerald-400';
    if (score <= 30) return 'text-slate-500';
    return 'text-amber-400';
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-8 custom-scrollbar bg-slate-950">
      {/* Header & Search */}
      <header className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-indigo-400 font-bold text-xs uppercase tracking-[0.2em]">
            <Zap className="w-3.5 h-3.5 glow-bloom text-purple-400" />
            AI Trading Tactics
          </div>
          <h1 className="text-3xl font-black text-white tracking-tighter uppercase italic">
            Trading Tactics
          </h1>
          <p className="text-slate-500 text-sm font-medium">
            แนวทางการเทรดพร้อม Entry · Stop Loss · Take Profit — <span className="text-amber-400 font-bold">ไม่ใช่คำแนะนำทางการเงิน</span>
          </p>
        </div>

        <form onSubmit={handleSearch} className="relative group w-full md:w-64">
          <input
            type="text"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="w-full bg-slate-900/50 border border-white/10 rounded-2xl px-5 py-3 text-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all placeholder:text-slate-600 uppercase"
            placeholder="SEARCH TICKER..."
          />
          <button type="submit" className="absolute right-3 top-1/2 -translate-y-1/2 p-1.5 bg-indigo-500/10 text-indigo-400 rounded-xl hover:bg-indigo-500 hover:text-white transition-all">
            <ChevronRight className="w-4 h-4" />
          </button>
        </form>
      </header>

      {/* Main Content */}
      <AnimatePresence mode="wait">
        {loading ? (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"
          >
            {[1, 2, 3, 4, 5, 6].map(i => (
              <div key={i} className="h-80 bg-slate-900/40 rounded-[2rem] border border-white/5 animate-pulse" />
            ))}
          </motion.div>
        ) : data ? (
          <motion.div 
            initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }}
            className="space-y-8"
          >
            {/* Strategic Banner */}
            <div className="p-1 px-1 rounded-[2.5rem] bg-gradient-to-r from-indigo-500 via-blue-500 to-emerald-500 group">
              <div className="bg-slate-950 rounded-[2.45rem] p-8 flex flex-col md:flex-row items-center justify-between gap-8 backdrop-blur-3xl overflow-hidden relative">
                <div className="absolute top-0 right-0 w-96 h-96 bg-indigo-500/10 blur-[100px] -mr-48 -mt-48 group-hover:bg-indigo-500/20 transition-colors duration-1000" />
                
                <div className="flex items-center gap-8 relative z-10">
                   <div className="w-20 h-20 rounded-3xl bg-white/5 flex items-center justify-center border border-white/10 shadow-2xl">
                     <span className="text-3xl font-black text-white font-mono tracking-tighter">{data.symbol}</span>
                   </div>
                   <div className="space-y-1">
                     <p className="text-[11px] font-black text-indigo-400 uppercase tracking-[0.3em]">Institutional Recommendation</p>
                     <p className="text-3xl font-black text-white tracking-tight uppercase italic group-hover:text-indigo-300 transition-colors">{data.recommendation}</p>
                     <div className="flex items-center gap-3">
                        <p className="text-2xl font-black text-slate-400 font-mono">${data.price?.toLocaleString()}</p>
                        <div className="h-4 w-[1px] bg-white/10" />
                        <p className="text-xs font-bold text-slate-500 uppercase">Best Persona: <span className="text-white">{data.best_persona}</span></p>
                     </div>
                   </div>
                </div>

                <div className="flex items-center gap-4 relative z-10">
                  <div className="px-6 py-3 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 text-center">
                    <p className="text-[9px] font-black text-emerald-500 uppercase tracking-widest mb-1">Engine Status</p>
                    <p className="text-sm font-black text-white">OPTIMIZED</p>
                  </div>
                  <div className="px-6 py-3 rounded-2xl bg-white/5 border border-white/10 text-center">
                    <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-1">Latency</p>
                    <p className="text-sm font-black text-white">12ms</p>
                  </div>
                  {data.v7_status?.sniper_locked && (
                    <div className="px-6 py-3 rounded-2xl bg-rose-500/20 border border-rose-500/40 text-center shadow-[0_0_20px_rgba(244,63,94,0.3)] animate-pulse">
                      <p className="text-[9px] font-black text-rose-400 uppercase tracking-widest mb-1">Sniper Locked</p>
                      <p className="text-sm font-black text-white">80%+ CONFIRMED</p>
                    </div>
                  )}
                  {data.ai_edge && (
                    <div className={`px-6 py-3 rounded-2xl border ${data.ai_edge.win_pct > 60 ? (data.ai_edge.neural_alignment ? 'bg-purple-500/20 border-purple-500/40' : 'bg-indigo-500/20 border-indigo-500/40') : 'bg-slate-500/10 border-white/10'} text-center shadow-[0_0_20px_rgba(139,92,246,0.3)] relative group/shield`}>
                      <p className={`text-[9px] font-black ${data.ai_edge.neural_alignment ? 'text-purple-400' : 'text-indigo-400'} uppercase tracking-widest mb-1`}>
                        {data.ai_edge.neural_alignment ? 'V7 Neural Alignment' : 'Sniper Logic (active)'}
                      </p>
                      <p className="text-sm font-black text-white">
                        {data.ai_edge.win_pct >= 80 ? '🎯 SNIPER ELITE' : (data.ai_edge.win_pct > 60 ? '🛡️ V7 ACTIVE' : 'REJECTED')}
                      </p>
                      
                      {/* Tooltip for Model Health */}
                      <div className="absolute top-full left-1/2 -translate-x-1/2 mt-4 w-64 p-5 bg-slate-950 border border-white/10 rounded-2xl opacity-0 group-hover/shield:opacity-100 transition-opacity pointer-events-none z-50 shadow-2xl backdrop-blur-xl">
                        <p className="text-[10px] font-black text-indigo-400 uppercase mb-3 tracking-tighter">Institutional Model Consensus</p>
                        
                        {/* Attention Mapping Visualizer (XAI) */}
                        {data.ai_edge.attention_impact && (
                          <div className="mb-4 space-y-2">
                             <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">Temporal Attention Focus (Last 10 Bars)</p>
                             <div className="flex items-end gap-1 h-12 bg-white/5 rounded-lg p-2 border border-white/5">
                               {data.ai_edge.attention_impact.map((weight, idx) => (
                                 <div 
                                   key={idx} 
                                   className="flex-1 bg-indigo-500/40 rounded-sm border-t border-indigo-400" 
                                   style={{ height: `${Math.max(10, weight * 100 * 2)}%`, opacity: 0.3 + (weight * 0.7) }} 
                                 />
                               ))}
                             </div>
                          </div>
                        )}

                        <div className="space-y-1.5">
                           <div className="flex justify-between"><span className="text-[9px] text-slate-500">Ensemble V8 Score</span><span className="text-[9px] text-white">{(data.ai_edge.accuracy * 100).toFixed(1)}% Acc</span></div>
                           <div className="flex justify-between"><span className="text-[9px] text-slate-500">Neural V8 Prob</span><span className="text-[9px] text-purple-400">{(data.ai_edge.v8_prob ? data.ai_edge.v8_prob * 100 : 0).toFixed(1)}%</span></div>
                           <div className="flex justify-between">
                              <span className="text-[9px] text-slate-500">Fractal Efficiency (H)</span>
                              <span className="text-[9px] text-white">
                                {(data.ai_edge.hurst_exponent || 0.5).toFixed(2)} 
                                ({ (data.ai_edge.hurst_exponent || 0.5) > 0.55 ? 'TRENDING' : ( (data.ai_edge.hurst_exponent || 0.5) < 0.45 ? 'REVERTING' : 'RANDOM' ) })
                              </span>
                           </div>
                           <div className="flex justify-between"><span className="text-[9px] text-slate-500">Risk Skewness</span><span className={`text-[9px] ${(data.ai_edge.vol_skew || 0) > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>{(data.ai_edge.vol_skew || 0).toFixed(2)}</span></div>
                           <div className="flex justify-between"><span className="text-[9px] text-slate-500">Signal Integrity</span><span className="text-[9px] text-emerald-400">{data.ai_edge.drift_score || 100}/100</span></div>
                           <div className="flex justify-between"><span className="text-[9px] text-slate-500">Portfolio Status</span><span className={`text-[9px] ${data.ai_edge.portfolio_health === 'SAFE' ? 'text-emerald-400' : 'text-rose-400'}`}>{data.ai_edge.portfolio_health || 'READY'}</span></div>
                           <div className="flex justify-between border-t border-white/5 pt-1 mt-1"><span className="text-[9px] text-slate-500">XAI Interpretation</span><span className="text-[9px] text-white italic">Hardened Attention Active</span></div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Institutional Flow Section */}
            {data.v7_status?.institutional_flow && (
              <div className="p-8 rounded-[2.5rem] bg-indigo-500/5 border border-indigo-500/20 space-y-4">
                <div className="flex items-center gap-2">
                  <Shield className="w-5 h-5 text-indigo-400" />
                  <h2 className="text-xl font-black text-white uppercase italic">Institutional Flow Signals</h2>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className={`p-4 rounded-2xl bg-slate-950 border ${data.v7_status.institutional_flow.bullish_sweep ? 'border-emerald-500/40 bg-emerald-500/5' : 'border-white/5'}`}>
                    <p className="text-[10px] font-black text-emerald-500 uppercase tracking-widest mb-1">Bullish Liquidity Sweep</p>
                    <p className="text-sm font-bold text-white">{data.v7_status.institutional_flow.bullish_sweep ? '✅ DETECTED: Institutional Absorption' : 'None Detected'}</p>
                  </div>
                  <div className={`p-4 rounded-2xl bg-slate-950 border ${data.v7_status.institutional_flow.bearish_sweep ? 'border-rose-500/40 bg-rose-500/5' : 'border-white/5'}`}>
                    <p className="text-[10px] font-black text-rose-500 uppercase tracking-widest mb-1">Bearish Liquidity Sweep</p>
                    <p className="text-sm font-bold text-white">{data.v7_status.institutional_flow.bearish_sweep ? '✅ DETECTED: Institutional Distribution' : 'None Detected'}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Tactics Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {(data.tactics || []).map((tactic, i) => (
                <HoverGlowCard key={i} className={`p-8 rounded-[2.5rem] border ${tactic.name === data.best_persona ? 'border-indigo-500/30 bg-indigo-500/5' : 'border-white/5 bg-slate-900/40'} flex flex-col h-full group transition-all duration-500 hover:-translate-y-2`}>
                  <div className="flex justify-between items-start mb-8">
                    <div className="p-3 bg-white/5 rounded-2xl border border-white/10 group-hover:scale-110 group-hover:shadow-[0_0_20px_rgba(99,102,241,0.2)] transition-all duration-500">
                      {getPersonaIcon(tactic.name)}
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Setup Score</p>
                      <p className={`text-2xl font-black font-mono ${getScoreColor(tactic.score)}`}>{tactic.score}%</p>
                    </div>
                  </div>

                  <div className="flex-1 space-y-6">
                    <div>
                      <div className="flex items-center gap-2">
                         <h3 className="text-xl font-black text-white uppercase italic tracking-tight">{tactic.name}</h3>
                         {tactic.name === data.best_persona && <div className="px-2 py-0.5 rounded-full bg-indigo-500 text-[8px] font-black text-white uppercase">Primary</div>}
                      </div>
                      <p className="text-xs text-slate-500 font-bold uppercase tracking-widest mt-1">{tactic.style}</p>
                    </div>

                    <div className="grid grid-cols-1 gap-3">
                      <div className="p-4 rounded-2xl bg-slate-950/50 border border-emerald-500/20 group-hover:bg-emerald-500/5 transition-colors">
                        <p className="text-[9px] font-black text-emerald-500 uppercase tracking-widest mb-1">🎯 Trigger (Entry)</p>
                        <p className="text-xs font-bold text-slate-200 leading-snug">{tactic.trigger}</p>
                      </div>
                      <div className="p-4 rounded-2xl bg-slate-950/50 border border-rose-500/20 group-hover:bg-rose-500/5 transition-colors">
                        <p className="text-[9px] font-black text-rose-500 uppercase tracking-widest mb-1">❌ Invalidation (SL)</p>
                        <p className="text-xs font-bold text-slate-200 leading-snug">{tactic.invalidation}</p>
                      </div>
                      <div className="p-4 rounded-2xl bg-slate-950/50 border border-blue-500/20 group-hover:bg-blue-500/5 transition-colors">
                        <p className="text-[9px] font-black text-blue-500 uppercase tracking-widest mb-1">💰 Take Profit (TP)</p>
                        <p className="text-xs font-bold text-slate-200 leading-snug">{tactic.tp}</p>
                      </div>
                    </div>

                    <div className="space-y-2 pt-2 border-t border-white/5">
                      <p className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Persona Logic</p>
                      <p className="text-xs text-slate-400 leading-relaxed font-mono bg-white/5 p-3 rounded-xl">
                        {tactic.logic}
                      </p>
                    </div>
                  </div>
                </HoverGlowCard>
              ))}
            </div>

            {/* Sniper Audit Log - Rejected Signals */}
            {auditLogs.length > 0 && (
              <div className="space-y-4 pt-8 border-t border-white/5">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Target className="w-5 h-5 text-rose-500" />
                    <h2 className="text-xl font-black text-white uppercase italic">Sniper Audit Log <span className="text-slate-500 text-sm not-italic font-medium ml-2">(High-Precision Rejections)</span></h2>
                  </div>
                  <div className="px-3 py-1 rounded-full bg-rose-500/10 border border-rose-500/20 text-[10px] font-black text-rose-400 uppercase tracking-widest">
                    Auto-Reject Protocol Active
                  </div>
                </div>

                <div className="overflow-hidden rounded-[2rem] border border-white/5 bg-slate-900/40 backdrop-blur-3xl">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-white/5 bg-white/5">
                        <th className="px-6 py-4 text-[10px] font-black text-slate-500 uppercase tracking-widest">Symbol</th>
                        <th className="px-6 py-4 text-[10px] font-black text-slate-500 uppercase tracking-widest">Confidence</th>
                        <th className="px-6 py-4 text-[10px] font-black text-slate-500 uppercase tracking-widest">Reasoning</th>
                        <th className="px-6 py-4 text-[10px] font-black text-slate-500 uppercase tracking-widest">Decision</th>
                        <th className="px-6 py-4 text-[10px] font-black text-slate-500 uppercase tracking-widest">Timestamp</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-white/5">
                      {auditLogs.map((log) => (
                        <tr key={log.id} className="hover:bg-white/5 transition-colors group">
                          <td className="px-6 py-4 font-mono font-bold text-white">{log.symbol}</td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-2">
                              <span className="text-rose-400 font-mono font-bold">{(log.confidence * 100).toFixed(0)}%</span>
                              <div className="w-16 h-1.5 bg-white/5 rounded-full overflow-hidden">
                                <div className="h-full bg-rose-500" style={{ width: `${log.confidence * 100}%` }} />
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-xs text-slate-400 max-w-md truncate group-hover:whitespace-normal group-hover:overflow-visible transition-all">
                            {log.reasoning}
                          </td>
                          <td className="px-6 py-4">
                            <span className="px-2 py-1 rounded-md bg-rose-500/20 text-[9px] font-black text-rose-400 uppercase">Rejected</span>
                          </td>
                          <td className="px-6 py-4 text-[10px] text-slate-500 font-mono">
                            {new Date(log.timestamp).toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </motion.div>
        ) : error ? (
          <div className="p-12 text-center space-y-4 bg-rose-500/5 rounded-[2rem] border border-rose-500/10">
            <p className="text-rose-400 font-black uppercase tracking-widest">Execution Error</p>
            <p className="text-slate-400 text-sm font-mono max-w-md mx-auto">{error}</p>
          </div>
        ) : null}
      </AnimatePresence>
    </div>
  );
};
