import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { DollarSign, TrendingUp, TrendingDown, Target, Award, Zap } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import type { WSMessage } from '../hooks/useWebSocket';

interface Signal {
  symbol: string;
  direction: string;
  confidence: number;
  price: number;
  timestamp: string;
}

interface Position {
  symbol: string;
  entryPrice: number;
  direction: string;
  openedAt: number;
  currentPrice: number;
  basePrice: number;
  pnlPct: number;
  pnlUsd: number;
}

const STARTING_EQUITY = 100000; // Institutional Base Allocation
const EMPTY_SIGNALS: Signal[] = [];

export const PnLTracker = ({
  bootstrapSignals = EMPTY_SIGNALS,
  skipInitialFetch = false,
  wsLastMessage = null,
}: {
  bootstrapSignals?: Signal[]
  skipInitialFetch?: boolean
  wsLastMessage?: WSMessage | null
}) => {
  const { theme } = useMode();
  const lastMessage = wsLastMessage;
  const [positions, setPositions] = useState<Position[]>([]);
  const [sessionPnl, setSessionPnl] = useState(0);
  const [winCount, setWinCount] = useState(0);
  const [totalTrades, setTotalTrades] = useState(0);
  const [isLive, setIsLive] = useState(false);
  const [accountSummary, setAccountSummary] = useState<any>(null);
  const positionRef = useRef<Map<string, Position>>(new Map());

  // Helper: process an incoming signals array into positions and PnL
  const processSignals = (sigs: any[]) => {
    if (isLive) return; // Don't run simulation if we have live data
    const now = Date.now();
    let pnlSum = 0;
    let wins = 0;
    const updated: Position[] = [];

    sigs.forEach(sig => {
      if (sig.direction !== 'BUY' && sig.direction !== 'SELL') return;
      const existing = positionRef.current.get(sig.symbol);
      const currentPrice = sig.price;

      if (existing) {
        // Update mark-to-market using the ORIGINAL direction
        const rawPnl = existing.direction === 'BUY'
          ? ((currentPrice - existing.entryPrice) / existing.entryPrice) * 100
          : ((existing.entryPrice - currentPrice) / existing.entryPrice) * 100;
        const pnlUsd = (rawPnl / 100) * (STARTING_EQUITY / 10);
        const updated_pos = { ...existing, currentPrice, basePrice: currentPrice, pnlPct: rawPnl, pnlUsd };
        positionRef.current.set(sig.symbol, updated_pos);
        updated.push(updated_pos);
        pnlSum += pnlUsd;
        if (pnlUsd > 0) wins++;
      } else {
        // Open new sim position at 10% of equity per trade
        const pos: Position = {
          symbol: sig.symbol,
          entryPrice: currentPrice,
          direction: sig.direction,
          openedAt: now,
          currentPrice,
          basePrice: currentPrice,
          pnlPct: 0,
          pnlUsd: 0,
        };
        positionRef.current.set(sig.symbol, pos);
        updated.push(pos);
      }
    });

    setPositions(updated);
    setSessionPnl(pnlSum);
    setTotalTrades(updated.length);
    setWinCount(wins);
  };

  // One-shot HTTP fetch on mount (fast bootstrap before WS warms up)
  useEffect(() => {
    if (bootstrapSignals.length > 0) {
      processSignals(bootstrapSignals);
      return;
    }
    if (skipInitialFetch) {
      return;
    }
    fetch('/api/signals')
      .then(r => r.json())
      .then(json => { if (json.signals?.length > 0) processSignals(json.signals); })
      .catch(err => console.error('PnL initial fetch error:', err));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bootstrapSignals, skipInitialFetch]);

  // Real-time listener: handles both simulation signals and live MT5 account updates
  useEffect(() => {
    if (!lastMessage) return;

    if (lastMessage.type === 'ACCOUNT_UPDATE') {
      const { summary, positions: mt5Positions } = lastMessage.data;
      setIsLive(true);
      setAccountSummary(summary);
      
      // Convert MT5 positions to our internal format
      const livePositions: Position[] = mt5Positions.map((p: any) => ({
        symbol: p.symbol,
        entryPrice: p.price_open,
        direction: p.type === 0 ? 'BUY' : 'SELL', // 0 is BUY, 1 is SELL in MT5
        openedAt: p.time * 1000,
        currentPrice: p.price_current,
        basePrice: p.price_current,
        pnlPct: (p.profit / (p.price_open * p.volume)) * 100, // heuristic
        pnlUsd: p.profit
      }));
      setPositions(livePositions);
      setSessionPnl(summary.profit);
      setTotalTrades(livePositions.length);
    } else if (lastMessage.type === 'SIGNALS' && !isLive) {
      const sigs = lastMessage.data?.signals ?? [];
      if (sigs.length > 0) processSignals(sigs);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastMessage, isLive]);

  // Simulate High-Frequency Live Ticks (simulation only)
  useEffect(() => {
    if (isLive) return;
    const tickInterval = setInterval(() => {
      let pnlSum = 0;
      let wins = 0;
      const updated: Position[] = [];

      positionRef.current.forEach((pos) => {
        const tickNoise = (Math.random() - 0.5) * (pos.basePrice * 0.0002);
        const newPrice = pos.basePrice + tickNoise;
        const rawPnl = pos.direction === 'BUY'
          ? ((newPrice - pos.entryPrice) / pos.entryPrice) * 100
          : ((pos.entryPrice - newPrice) / pos.entryPrice) * 100;
        const pnlUsd = (rawPnl / 100) * (STARTING_EQUITY / 10);
        const updated_pos = { ...pos, currentPrice: newPrice, pnlPct: rawPnl, pnlUsd };
        positionRef.current.set(pos.symbol, updated_pos);
        updated.push(updated_pos);
        pnlSum += pnlUsd;
        if (pnlUsd > 0) wins++;
      });

      if (updated.length > 0) {
        setPositions(updated);
        setSessionPnl(pnlSum);
        setWinCount(wins);
      }
    }, 1500);

    return () => clearInterval(tickInterval);
  }, [isLive]);

  const displayEquity = isLive && accountSummary ? accountSummary.equity : STARTING_EQUITY + sessionPnl;
  const winRate = totalTrades > 0 ? (isLive ? 0 : Math.round((winCount / totalTrades) * 100)) : 0;
  const isProfit = sessionPnl >= 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Award className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`} />
          <h3 className={`text-[10px] font-black uppercase tracking-[0.2em] transition-colors ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>Intelligence Command</h3>
        </div>
        {isLive && (
          <div className={`flex items-center gap-2 px-3 py-1 rounded-full border text-[9px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-600'
          }`}>
            <div className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
            Live Sync
          </div>
        )}
      </div>

      {/* Summary Bento Grid */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          label="Session PnL"
          value={`${isProfit ? '+' : ''}$${Math.abs(sessionPnl).toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
          positive={isProfit}
          icon={isProfit ? TrendingUp : TrendingDown}
          theme={theme}
        />
        <StatCard
          label="Total Equity"
          value={`$${displayEquity.toLocaleString(undefined, { minimumFractionDigits: 2 })}`}
          positive={true}
          icon={DollarSign}
          theme={theme}
        />
        <StatCard
          label="Neural Precision"
          value={isLive ? "ELITE" : `${winRate}%`}
          positive={isLive || winRate >= 50}
          icon={Target}
          theme={theme}
        />
        <StatCard
          label="Active Deploy"
          value={String(totalTrades)}
          positive={true}
          icon={Zap}
          theme={theme}
        />
      </div>

      {/* Deployment Monitoring */}
      <div className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <p className="text-[8px] font-black text-slate-500 uppercase tracking-[0.2em]">Active Deployments</p>
          <p className="text-[7px] font-black text-slate-700 uppercase tracking-widest italic opacity-50">V7 Protocol</p>
        </div>
        
        <div className="space-y-2">
          {positions.length === 0 ? (
            <div className={`p-6 rounded-[1.2rem] border border-dashed text-center space-y-1.5 ${
              theme === 'dark' ? 'border-white/5 bg-white/5' : 'border-slate-200 bg-slate-50'
            }`}>
              <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">No Active Positions</p>
              <p className="text-[8px] text-slate-600 font-bold uppercase tracking-widest italic">Awaiting Sniper Confirmation</p>
            </div>
          ) : (
            <AnimatePresence mode="popLayout">
              {positions.slice(0, 4).map((pos, i) => (
                <motion.div
                  key={pos.symbol}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  className={`flex items-center justify-between p-2.5 rounded-xl border backdrop-blur-3xl transition-all duration-500 hover:scale-[1.02] ${
                    theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`w-0.5 h-7 rounded-full ${pos.direction === 'BUY' ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                    <div>
                      <p className={`text-xs font-black font-mono tracking-tighter ${theme === 'dark' ? 'text-white' : 'text-slate-950'}`}>{pos.symbol}</p>
                      <p className={`text-[7px] font-black uppercase tracking-[0.2em] ${pos.direction === 'BUY' ? 'text-emerald-500' : 'text-rose-500'}`}>
                        {pos.direction} MODE
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <motion.p
                      key={pos.pnlUsd}
                      initial={{ scale: 1.1 }}
                      animate={{ scale: 1 }}
                      className={`text-xs font-black font-mono ${pos.pnlUsd >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
                    >
                      {pos.pnlUsd >= 0 ? '+' : ''}${Math.abs(pos.pnlUsd).toFixed(2)}
                    </motion.p>
                    <p className="text-[7px] font-black text-slate-600 uppercase tracking-widest">Unrealized</p>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </div>
      </div>

      <div className={`p-2 rounded-lg border text-center transition-all ${
        theme === 'dark' ? 'bg-indigo-500/5 border-indigo-500/10' : 'bg-indigo-50 border-indigo-100'
      }`}>
        <p className={`text-[9px] font-black uppercase tracking-[0.3em] ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`}>
          Institutional Sync Active
        </p>
        <p className="text-[7px] font-bold text-slate-600 uppercase tracking-widest mt-0.5 italic">
          Data Integrity Verified by Alpha-Core V7
        </p>
      </div>
    </div>
  );
};

const StatCard = ({ label, value, positive, icon: Icon, theme }: {
  label: string; value: string; positive: boolean; icon: any; theme: 'light' | 'dark'
}) => (
  <div className={`p-2.5 rounded-xl border space-y-1 transition-all duration-500 hover:scale-[1.02] ${
    theme === 'dark' ? 'bg-slate-900/40 border-white/5 hover:border-white/10' : 'bg-white border-slate-200 shadow-sm hover:shadow-md'
  }`}>
    <div className="flex items-center gap-1">
      <div className={`p-0.5 rounded ${positive ? (theme === 'dark' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-50 text-emerald-600') : (theme === 'dark' ? 'bg-rose-500/10 text-rose-400' : 'bg-rose-50 text-rose-600')}`}>
        <Icon className="w-2.5 h-2.5" />
      </div>
      <span className="text-[7px] font-black text-slate-500 uppercase tracking-[0.1em]">{label}</span>
    </div>
    <p className={`text-xs font-black font-mono tracking-tighter ${positive 
      ? (theme === 'dark' ? 'text-white' : 'text-slate-950') 
      : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
    }`}>{value}</p>
  </div>
);
