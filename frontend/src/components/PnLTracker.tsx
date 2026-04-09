import { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import { DollarSign, TrendingUp, TrendingDown, Target, Award } from 'lucide-react';

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
  pnlPct: number;
  pnlUsd: number;
}

const STARTING_EQUITY = 100000; // $100k sim

export const PnLTracker = () => {
  const [positions, setPositions] = useState<Position[]>([]);
  const [sessionPnl, setSessionPnl] = useState(0);
  const [winCount, setWinCount] = useState(0);
  const [totalTrades, setTotalTrades] = useState(0);
  const positionRef = useRef<Map<string, Position>>(new Map());

  // Subscribe to signal feed and open/close sim positions
  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/signals');
        const json = await res.json();
        const sigs: Signal[] = json.signals || [];

        const now = Date.now();
        let pnlSum = 0;
        let wins = 0;
        const updated: Position[] = [];

        sigs.forEach(sig => {
          if (sig.direction !== 'BUY' && sig.direction !== 'SELL') return;
          const existing = positionRef.current.get(sig.symbol);

          const currentPrice = sig.price;

          if (existing) {
            // Update mark-to-market
            const rawPnl = sig.direction === 'BUY'
              ? ((currentPrice - existing.entryPrice) / existing.entryPrice) * 100
              : ((existing.entryPrice - currentPrice) / existing.entryPrice) * 100;
            const pnlUsd = (rawPnl / 100) * (STARTING_EQUITY / 10);
            const updated_pos = { ...existing, currentPrice, pnlPct: rawPnl, pnlUsd };
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
      } catch (e) {
        console.error('PnL fetch error:', e);
      }
    };

    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  const equity = STARTING_EQUITY + sessionPnl;
  const winRate = totalTrades > 0 ? Math.round((winCount / totalTrades) * 100) : 0;
  const isProfit = sessionPnl >= 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Award className="w-4 h-4 text-amber-400" />
        <h3 className="text-[11px] font-black text-white uppercase tracking-widest">Session PnL (Simulation)</h3>
      </div>

      {/* Summary Row */}
      <div className="grid grid-cols-2 gap-3">
        <StatCard
          label="Session PnL"
          value={`${isProfit ? '+' : ''}$${Math.abs(sessionPnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          positive={isProfit}
          icon={isProfit ? TrendingUp : TrendingDown}
        />
        <StatCard
          label="Equity"
          value={`$${equity.toLocaleString(undefined, { maximumFractionDigits: 0 })}`}
          positive={true}
          icon={DollarSign}
        />
        <StatCard
          label="Win Rate"
          value={`${winRate}%`}
          positive={winRate >= 50}
          icon={Target}
        />
        <StatCard
          label="Positions"
          value={String(totalTrades)}
          positive={true}
          icon={Award}
        />
      </div>

      {/* Open Positions */}
      {positions.length > 0 && (
        <div className="space-y-2 mt-2">
          <p className="text-[9px] font-black text-slate-600 uppercase tracking-widest">Open Positions</p>
          {positions.slice(0, 4).map((pos) => (
            <div key={pos.symbol} className="flex items-center justify-between p-3 bg-slate-950/50 rounded-xl border border-white/5">
              <div>
                <span className="text-[11px] font-black text-slate-200">{pos.symbol}</span>
                <span className={`ml-2 text-[9px] font-bold ${pos.direction === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {pos.direction}
                </span>
              </div>
              <motion.span
                key={pos.pnlPct}
                initial={{ opacity: 0.5 }}
                animate={{ opacity: 1 }}
                className={`text-[11px] font-black font-mono ${pos.pnlUsd >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}
              >
                {pos.pnlUsd >= 0 ? '+' : ''}${pos.pnlUsd.toFixed(0)}
              </motion.span>
            </div>
          ))}
        </div>
      )}

      <p className="text-[8px] text-slate-700 font-bold uppercase tracking-widest text-center">
        Simulated only · Not financial advice
      </p>
    </div>
  );
};

const StatCard = ({ label, value, positive, icon: Icon }: {
  label: string; value: string; positive: boolean; icon: any
}) => (
  <div className="p-3 bg-slate-950/50 rounded-xl border border-white/5 space-y-1">
    <div className="flex items-center gap-1.5">
      <Icon className={`w-3 h-3 ${positive ? 'text-emerald-500' : 'text-rose-500'}`} />
      <span className="text-[9px] font-bold text-slate-600 uppercase tracking-widest">{label}</span>
    </div>
    <span className={`text-sm font-black font-mono ${positive ? 'text-emerald-400' : 'text-rose-400'}`}>{value}</span>
  </div>
);
