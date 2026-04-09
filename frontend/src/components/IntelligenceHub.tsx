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

const REGIME_RULES = (signals: Signal[]) => {
  const buySignals = signals.filter(s => s.direction === 'BUY').length;
  const sellSignals = signals.filter(s => s.direction === 'SELL').length;
  const total = signals.length || 1;
  if (buySignals / total > 0.6) return { label: 'BULLISH', color: 'text-emerald-400', bg: 'bg-emerald-500/10', border: 'border-emerald-500/20' };
  if (sellSignals / total > 0.6) return { label: 'BEARISH', color: 'text-rose-400', bg: 'bg-rose-500/10', border: 'border-rose-500/20' };
  return { label: 'SIDEWAYS', color: 'text-amber-400', bg: 'bg-amber-500/10', border: 'border-amber-500/20' };
};

export const IntelligenceHub = () => {
  const [signals, setSignals] = useState<Signal[]>([]);
  const { status } = useWebSocket();
  const { isRetail } = useMode();

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/signals');
        const json = await res.json();
        setSignals(json.signals || []);
      } catch (_) {}
    };
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, []);

  const gaugeAssets = signals.length > 0
    ? signals.slice(0, 3).map(s => {
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

  const regime = REGIME_RULES(signals);

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-8 custom-scrollbar relative">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8 relative z-10">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-blue-400 font-bold text-[10px] uppercase tracking-[0.2em]">
            <Brain className="w-3.5 h-3.5 glow-bloom" />
            Predictive Intelligence Engine
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">Strategy Intelligence Hub</h2>
          <p className="text-slate-500 text-sm font-medium">
            {isRetail ? 'ระบบ AI วิเคราะห์ความน่าจะเป็นและทิศทางตลาด (ไม่ใช่คำแนะนำทางการเงิน)' : 'AI signals derived from live market_metrics + whale flow data.'}
          </p>
        </div>
        {/* Market Regime Indicator */}
        <div className={`flex items-center gap-3 px-5 py-3 rounded-2xl border ${regime.bg} ${regime.border}`}>
          <Cpu className={`w-4 h-4 ${regime.color}`} />
          <div>
            <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">
              <FinancialTerm term="Regime">Market Regime</FinancialTerm>
            </p>
            <p className={`text-sm font-black ${regime.color} uppercase tracking-tight`}><FinancialTerm term={regime.label}>{regime.label}</FinancialTerm></p>
          </div>
        </div>
      </header>

      {/* AI Confidence Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 relative z-10">
        {gaugeAssets.map((asset, i) => {
          const dirColor = asset.direction === 'BUY' ? '#10b981' : asset.direction === 'SELL' ? '#f43f5e' : '#3b82f6';
          return (
            <HoverGlowCard key={i} className="p-6 rounded-[2rem] border border-white/5 bg-slate-900/40 relative overflow-hidden group">
              <div className="flex justify-between items-start mb-6">
                <div>
                  <h3 className="text-xl font-black text-white font-mono">{asset.symbol}</h3>
                  <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest mt-1">{asset.status}</p>
                </div>
                <div className="flex flex-col items-end">
                   <div className="p-2 bg-blue-600/10 rounded-xl border border-blue-500/20 mb-1">
                     <Target className="w-4 h-4 text-blue-400" />
                   </div>
                   {!isRetail && (
                     <span className="text-[8px] font-black text-slate-500 tracking-widest uppercase">Q-Score: {asset.quality}</span>
                   )}
                </div>
              </div>

              <div className="space-y-4">
                <div className="space-y-2">
                  <div className="flex justify-between text-[11px] font-bold uppercase tracking-tighter">
                    <span className="text-slate-500">
                      <FinancialTerm term="Confidence">AI Confidence</FinancialTerm>
                    </span>
                    <span className="text-white font-mono">{asset.confidence}%</span>
                  </div>
                  <div className="h-2 w-full bg-slate-950 rounded-full overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${asset.confidence}%` }}
                      transition={{ duration: 1, delay: i * 0.2 }}
                      className="h-full rounded-full"
                      style={{ background: `linear-gradient(90deg, ${dirColor}88, ${dirColor})`, boxShadow: `0 0 8px ${dirColor}66` }}
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-white/5">
                  <div>
                    <p className="text-[9px] text-slate-500 font-bold uppercase tracking-widest">Signal</p>
                    <p className={`text-sm font-black mt-1 ${
                      asset.direction === 'BUY' ? 'text-emerald-400' :
                      asset.direction === 'SELL' ? 'text-rose-400' : 'text-amber-400'
                    }`}>{asset.direction}</p>
                  </div>
                  <div>
                    <p className="text-[9px] text-slate-500 font-bold uppercase tracking-widest">Delta</p>
                    <p className={`text-sm font-black font-mono mt-1 ${asset.delta >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
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
        <HoverGlowCard className="lg:col-span-2 p-8 rounded-[2.5rem] border border-white/5 bg-slate-900/40 min-h-[480px]">
          <SignalFeed />
        </HoverGlowCard>

        {/* PnL Tracker — takes 1/3 */}
        <div className="space-y-4">
          <HoverGlowCard className="p-6 rounded-[2.5rem] border border-white/5 bg-slate-900/40">
            <PnLTracker />
          </HoverGlowCard>

          {/* Infrastructure status widget */}
          <HoverGlowCard className="p-6 rounded-[2.5rem] border border-white/5 bg-slate-900/40">
            <div className="flex items-center gap-2 mb-4">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              <h3 className="text-[11px] font-black text-white uppercase tracking-widest">Pipeline Status</h3>
            </div>
            <div className="space-y-3">
              {[
                { label: 'WebSocket', ok: status === 'open' },
                { label: 'Signal Engine', ok: signals.length > 0 },
                { label: 'DB Metrics', ok: true },
                { label: 'DQ Guard', ok: true },
              ].map((item, i) => (
                <div key={i} className="flex items-center justify-between">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{item.label}</span>
                  <div className={`flex items-center gap-1.5 ${item.ok ? 'text-emerald-400' : 'text-rose-400'}`}>
                    <div className={`w-1.5 h-1.5 rounded-full ${item.ok ? 'bg-emerald-500 status-breath' : 'bg-rose-500 animate-pulse'}`} />
                    <span className="text-[9px] font-black uppercase tracking-widest">{item.ok ? 'OK' : 'FAIL'}</span>
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
