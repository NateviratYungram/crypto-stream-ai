import { motion, AnimatePresence } from 'framer-motion';
import { Brain, Target, Cpu, ShieldCheck } from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';
import { SignalFeed } from './SignalFeed';
import { PnLTracker } from './PnLTracker';
import { useWebSocket } from '../hooks/useWebSocket';
import { useEffect, useState } from 'react';
import { FinancialTerm } from './Tooltip';
import { useMode } from '../contexts/ModeContext';

interface Signal {
  symbol: string;
  direction: string;
  confidence: number;
  reason: string;
  price: number;
  delta_pct: number;
  vol_surge: number;
}

const REGIME_RULES = (signals: Signal[], theme: 'light' | 'dark') => {
  const buySignals = signals.filter(s => s.direction === 'BUY').length;
  const sellSignals = signals.filter(s => s.direction === 'SELL').length;
  const total = signals.length || 1;
  if (buySignals / total > 0.6) return { 
    label: 'BULLISH', 
    color: theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600', 
    bg: theme === 'dark' ? 'bg-emerald-500/10' : 'bg-emerald-50', 
    border: theme === 'dark' ? 'border-emerald-500/20' : 'border-emerald-200' 
  };
  if (sellSignals / total > 0.6) return { 
    label: 'BEARISH', 
    color: theme === 'dark' ? 'text-rose-400' : 'text-rose-600', 
    bg: theme === 'dark' ? 'bg-rose-500/10' : 'bg-rose-50', 
    border: theme === 'dark' ? 'border-rose-500/20' : 'border-rose-200' 
  };
  return { 
    label: 'SIDEWAYS', 
    color: theme === 'dark' ? 'text-amber-400' : 'text-amber-600', 
    bg: theme === 'dark' ? 'bg-amber-500/10' : 'bg-amber-50', 
    border: theme === 'dark' ? 'border-amber-500/20' : 'border-amber-200' 
  };
};

export const IntelligenceHub = () => {
  const [signals, setSignals] = useState<Signal[]>(() => {
    try {
      const raw = sessionStorage.getItem('intelligence_signals_cache_v1');
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed?.signals) ? parsed.signals : [];
    } catch {
      return [];
    }
  });
  const [dbOk, setDbOk] = useState<boolean | null>(() => {
    try {
      const raw = sessionStorage.getItem('intelligence_signals_cache_v1');
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return typeof parsed?.dbOk === 'boolean' ? parsed.dbOk : null;
    } catch {
      return null;
    }
  });
  const [dqOk, setDqOk] = useState<boolean | null>(() => {
    try {
      const raw = sessionStorage.getItem('intelligence_signals_cache_v1');
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return typeof parsed?.dqOk === 'boolean' ? parsed.dqOk : null;
    } catch {
      return null;
    }
  });
  const { status, lastMessage } = useWebSocket();
  const { isRetail, theme } = useMode();

  // One-shot HTTP fetch on mount (fast first load before WS sends data)
  useEffect(() => {
    fetch('/api/signals')
      .then(r => r.json())
      .then(json => { if (json.signals?.length > 0) setSignals(json.signals); })
      .catch(() => {});
  }, []);

  // Real-time WebSocket signal updates — replaces the 30s polling loop
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'SIGNALS') return;
    const { signals: incoming, db_ok, dq_ok } = lastMessage.data ?? {};
    if (incoming?.length > 0) setSignals(incoming);
    if (db_ok !== undefined) setDbOk(db_ok);
    if (dq_ok !== undefined) setDqOk(dq_ok);
  }, [lastMessage]);

  useEffect(() => {
    try {
      sessionStorage.setItem('intelligence_signals_cache_v1', JSON.stringify({ signals, dbOk, dqOk }));
    } catch {
      // ignore cache write issues
    }
  }, [signals, dbOk, dqOk]);

  const gaugeAssets = signals.length > 0
    ? signals.slice(0, 8).map(s => {
        // Risk-adjusted quality score
        const quality = Math.min(100, Math.round(s.confidence * (s.vol_surge > 1 ? Math.min(s.vol_surge, 1.5) : 0.8)));
        return {
          symbol: s.symbol,
          confidence: s.confidence,
          quality,
          status: s.direction === 'BUY' ? 'Whale Accumulation' : s.direction === 'SELL' ? 'Distribution Phase' : 'Consolidation',
          direction: s.direction,
          delta: s.delta_pct,
        };
      })
    : [
        { symbol: 'BTCUSDT', confidence: 0, quality: 0, status: 'Awaiting signal...', direction: 'HOLD', delta: 0 },
        { symbol: 'ETHUSDT', confidence: 0, quality: 0, status: 'Awaiting signal...', direction: 'HOLD', delta: 0 },
        { symbol: 'SOLUSDT', confidence: 0, quality: 0, status: 'Awaiting signal...', direction: 'HOLD', delta: 0 },
      ];

  const regime = REGIME_RULES(signals, theme);

  return (
    <div className={`flex-1 p-6 overflow-y-auto space-y-6 custom-scrollbar relative transition-all duration-700 ${
      theme === 'dark' ? 'bg-slate-950/20' : 'bg-slate-50'
    }`}>
      {/* Header */}
      <header className={`flex justify-between items-center border-b pb-6 relative z-10 transition-colors duration-500 ${
        theme === 'dark' ? 'border-white/5' : 'border-slate-200'
      }`}>
        <div className="space-y-1">
          <div className={`font-bold text-[10px] uppercase tracking-[0.2em] flex items-center gap-2 ${
            theme === 'dark' ? 'text-blue-400' : 'text-blue-600'
          }`}>
            <Brain className="w-3 h-3 glow-bloom" />
            Predictive Intelligence Engine
          </div>
            <h1 className={`text-2xl font-black tracking-tighter uppercase italic flex items-center gap-3 transition-colors duration-500 ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>
              Intelligence Hub
              <span className={`text-[8px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded-md not-italic animate-pulse ${
                theme === 'dark' ? 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/20' : 'text-emerald-600 bg-emerald-50 border border-emerald-200 shadow-sm'
              }`}>
                LIVE
              </span>
            </h1>
          <p className={`text-xs font-medium transition-colors duration-500 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-600'}`}>
            {isRetail ? 'ระบบ AI วิเคราะห์ความน่าจะเป็นและทิศทางตลาดระดับสากล' : 'Institutional-grade signals derived from real-time market_metrics + whale flow data.'}
          </p>
        </div>
        {/* Market Regime Indicator */}
        <div className={`flex items-center gap-2.5 px-4 py-2 rounded-xl border transition-all duration-500 ${regime.bg} ${regime.border}`}>
          <Cpu className={`w-3.5 h-3.5 ${regime.color}`} />
          <div>
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">
              <FinancialTerm term="Regime">Market Regime</FinancialTerm>
            </p>
            <p className={`text-xs font-black ${regime.color} uppercase tracking-tight`}><FinancialTerm term={regime.label}>{regime.label}</FinancialTerm></p>
          </div>
        </div>
      </header>

      {/* AI Confidence Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6 relative z-10">
        {gaugeAssets.map((asset, i) => {
          const dirColor = asset.direction === 'BUY' ? '#10b981' : asset.direction === 'SELL' ? '#f43f5e' : '#3b82f6';
          return (
            <HoverGlowCard key={i} className={`p-4 rounded-[1.5rem] border relative overflow-hidden group transition-all duration-500 ${
              theme === 'dark' ? 'border-white/10 bg-slate-900/60' : 'border-slate-200 bg-white shadow-xl shadow-slate-200/20'
            }`}>
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className={`text-lg font-black font-mono ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{asset.symbol}</h3>
                  <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-0.5">{asset.status}</p>
                </div>
                <div className="flex flex-col items-end">
                   <div className={`p-1.5 rounded-lg border mb-1 ${
                     theme === 'dark' ? 'bg-blue-600/10 border-blue-500/20' : 'bg-blue-50 border-blue-200'
                   }`}>
                     <Target className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
                   </div>
                   {!isRetail && (
                     <span className="text-[10px] font-black text-slate-500 tracking-widest uppercase">Q-Score: {asset.quality}</span>
                   )}
                </div>
              </div>

              <div className="space-y-4">
                <div className="space-y-1.5">
                  <div className="flex justify-between text-[10px] font-bold uppercase tracking-tighter">
                    <span className="text-slate-500">
                      <FinancialTerm term="Confidence">AI Confidence</FinancialTerm>
                    </span>
                    <span className={`font-mono transition-colors duration-500 ${theme === 'dark' ? 'text-white' : 'text-slate-900 font-black'}`}>{asset.confidence}%</span>
                  </div>

                  <div className={`h-1.5 w-full rounded-full overflow-hidden transition-colors duration-500 ${theme === 'dark' ? 'bg-slate-950' : 'bg-slate-100'}`}>
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${asset.confidence}%` }}
                      transition={{ duration: 1, delay: i * 0.2 }}
                      className="h-full rounded-full"
                      style={{ background: `linear-gradient(90deg, ${dirColor}88, ${dirColor})`, boxShadow: theme === 'dark' ? `0 0 8px ${dirColor}66` : 'none' }}
                    />
                  </div>
                </div>

                <div className={`grid grid-cols-2 gap-3 pt-3 border-t ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                  <div>
                    <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Signal</p>
                    <p className={`text-xs font-black mt-0.5 ${
                      asset.direction === 'BUY' ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') :
                      asset.direction === 'SELL' ? (theme === 'dark' ? 'text-rose-400' : 'text-rose-600') : (theme === 'dark' ? 'text-amber-400' : 'text-amber-600')
                    }`}>{asset.direction}</p>
                  </div>
                  <div>
                    <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">Delta</p>
                    <p className={`text-xs font-black font-mono mt-0.5 ${
                      asset.delta >= 0 
                        ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') 
                        : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
                    }`}>
                      {asset.delta >= 0 ? '+' : ''}{asset.delta.toFixed(3)}%
                    </p>
                  </div>
                </div>
              </div>
              <div className="absolute -bottom-4 -right-4 w-24 h-24 blur-3xl rounded-full group-hover:opacity-100 opacity-50 transition-opacity"
                style={{ background: `${dirColor}20` }} />
            </HoverGlowCard>
          );
        })}
      </div>

      {/* Bottom 2-column layout: SignalFeed + PnLTracker + Correlation */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 relative z-10">
        {/* Signal Feed — takes 2/3 */}
        <HoverGlowCard className={`lg:col-span-2 p-6 rounded-[1.5rem] border min-h-[480px] transition-all duration-500 ${
          theme === 'dark' ? 'border-white/10 bg-slate-900/60' : 'border-slate-200 bg-white shadow-xl shadow-slate-200/40'
        }`}>
          <SignalFeed bootstrapSignals={signals} skipInitialFetch />
        </HoverGlowCard>

        {/* PnL Tracker — takes 1/3 */}
        <div className="space-y-4">
          <HoverGlowCard className={`p-4 rounded-[1.5rem] border transition-all duration-500 ${
            theme === 'dark' ? 'border-white/10 bg-slate-900/60' : 'border-slate-200 bg-white shadow-xl shadow-slate-200/40'
          }`}>
            <PnLTracker bootstrapSignals={signals} skipInitialFetch />
          </HoverGlowCard>

          {/* Infrastructure status widget */}
          <HoverGlowCard className={`p-4 rounded-[1.5rem] border transition-all duration-500 ${
            theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'border-slate-200 bg-white shadow-xl shadow-slate-200/40'
          }`}>
            <div className="flex items-center gap-2 mb-3">
              <ShieldCheck className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'}`} />
              <h3 className={`text-[10px] font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Pipeline Status</h3>
            </div>
            <div className="space-y-3">
              {[
                { label: 'WebSocket', ok: status === 'open' },
                { label: 'Signal Engine', ok: signals.length > 0 },
                // These now reflect REAL system health from the backend broadcast
                { label: 'DB Metrics', ok: dbOk === true, pending: dbOk === null },
                { label: 'DQ Guard', ok: dqOk === true, pending: dqOk === null },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">{item.label}</span>
                  <div className={`flex items-center gap-1.5 ${
                    item.pending
                      ? 'text-slate-500'
                      : item.ok
                        ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600')
                        : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
                  }`}>
                    <div className={`w-1.5 h-1.5 rounded-full ${
                      item.pending
                        ? 'bg-slate-500 animate-pulse'
                        : item.ok
                          ? (theme === 'dark' ? 'bg-emerald-500 status-breath' : 'bg-emerald-600')
                          : (theme === 'dark' ? 'bg-rose-500 animate-pulse' : 'bg-rose-600')
                    }`} />
                    <span className="text-[11px] font-black uppercase tracking-widest">
                      {item.pending ? 'CHECKING...' : item.ok ? 'OK' : 'FAIL'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </HoverGlowCard>
        </div>
      </div>
    </div>
  );
};
