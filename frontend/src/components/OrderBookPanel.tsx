import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Activity } from 'lucide-react';

interface OrderBookProps {
  symbol: string;
  currentPrice: number;
  history: { time: number; value: number }[];
}

export const OrderBookPanel = ({ symbol, currentPrice, history }: OrderBookProps) => {
  const [bids, setBids] = useState<{ price: number; depth: number }[]>([]);
  const [asks, setAsks] = useState<{ price: number; depth: number }[]>([]);
  const [totalBidPressure, setTotalBidPressure] = useState(0);
  const [totalAskPressure, setTotalAskPressure] = useState(0);

  // Derive simulated order book from price history volatility
  useEffect(() => {
    if (!currentPrice || history.length < 2) return;

    // Calculate recent volatility for spread estimation
    const prices = history.map(h => h.value);
    const maxP = Math.max(...prices);
    const minP = Math.min(...prices);
    const spread = (maxP - minP) * 0.1 || currentPrice * 0.001;

    // Generate synthetic book from real price + volatility
    const newBids = Array.from({ length: 5 }, (_, i) => ({
      price: currentPrice - spread * (i + 1) * 0.3,
      depth: Math.random() * 0.8 + 0.2,
    }));
    const newAsks = Array.from({ length: 5 }, (_, i) => ({
      price: currentPrice + spread * (i + 1) * 0.3,
      depth: Math.random() * 0.8 + 0.2,
    }));

    // Bias based on recent price direction
    const recentTrend = prices[prices.length - 1] > prices[0];
    const bidMult = recentTrend ? 1.3 : 0.7;
    const askMult = recentTrend ? 0.7 : 1.3;

    const bidTotal = newBids.reduce((s, b) => s + b.depth * bidMult, 0);
    const askTotal = newAsks.reduce((s, a) => s + a.depth * askMult, 0);

    setBids(newBids);
    setAsks(newAsks);
    setTotalBidPressure(bidTotal);
    setTotalAskPressure(askTotal);
  }, [currentPrice, history]);

  const total = totalBidPressure + totalAskPressure || 1;
  const bidPct = Math.round((totalBidPressure / total) * 100);
  const askPct = 100 - bidPct;
  const dominated = bidPct > 55 ? 'BID' : askPct > 55 ? 'ASK' : 'NEUTRAL';

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Activity className="w-3 h-3 text-slate-500" />
          <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Order Pressure</span>
        </div>
        <span className={`text-[9px] font-black uppercase tracking-widest ${
          dominated === 'BID' ? 'text-emerald-400' :
          dominated === 'ASK' ? 'text-rose-400' : 'text-slate-400'
        }`}>
          {dominated} DOMINANT
        </span>
      </div>

      {/* Bid/Ask pressure bar */}
      <div className="h-2 w-full flex rounded-full overflow-hidden">
        <motion.div
          animate={{ width: `${bidPct}%` }}
          className="h-full bg-emerald-500/70 shadow-[0_0_8px_rgba(16,185,129,0.3)]"
          transition={{ duration: 0.6 }}
        />
        <motion.div
          animate={{ width: `${askPct}%` }}
          className="h-full bg-rose-500/70 shadow-[0_0_8px_rgba(244,63,94,0.3)]"
          transition={{ duration: 0.6 }}
        />
      </div>

      <div className="flex justify-between">
        <span className="text-[9px] font-black text-emerald-400">{bidPct}% BID</span>
        <span className="text-[9px] font-black text-rose-400">{askPct}% ASK</span>
      </div>

      {/* Mini depth bars */}
      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          {asks.slice(0,3).map((ask, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="flex-1 h-1 bg-slate-900 rounded-full overflow-hidden">
                <div
                  className="h-full bg-rose-500/40 rounded-full"
                  style={{ width: `${ask.depth * 100}%` }}
                />
              </div>
              <span className="text-[8px] font-mono text-rose-500 w-16 text-right tabular-nums">
                {ask.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
            </div>
          ))}
        </div>
        <div className="space-y-1">
          {bids.slice(0,3).map((bid, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="text-[8px] font-mono text-emerald-500 w-16 tabular-nums">
                {bid.price.toLocaleString(undefined, { maximumFractionDigits: 0 })}
              </span>
              <div className="flex-1 h-1 bg-slate-900 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500/40 rounded-full"
                  style={{ width: `${bid.depth * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
