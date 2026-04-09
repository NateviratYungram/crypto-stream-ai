import { Activity, ArrowUpRight, ArrowDownRight, Zap } from 'lucide-react';
import { motion } from 'framer-motion';

export const MarketFeed = () => {
  return (
    <div className="w-80 min-w-[320px] bg-slate-900/40 border-l border-white/5 flex flex-col p-6 gap-6">
      <div className="space-y-4">
        <h2 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest px-2 group flex items-center gap-2">
          <Zap className="w-3 h-3 text-yellow-400" />
          Live Whale Alerts
        </h2>
        <div className="space-y-3">
          <WhaleAlert symbol="BTCUSDT" amount="12.4" side="BUY" time="2m ago" />
          <WhaleAlert symbol="ETHUSDT" amount="450.0" side="SELL" time="5m ago" />
          <WhaleAlert symbol="BTCUSDT" amount="8.1" side="BUY" time="12m ago" />
        </div>
      </div>

      <div className="space-y-4">
        <h2 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest px-2 flex items-center gap-2">
          <Activity className="w-3 h-3 text-blue-400" />
          Pipeline Metrics (M1)
        </h2>
        <div className="bg-slate-800/20 rounded-2xl p-4 border border-white/5 space-y-4">
          <MetricRow label="Throughput" value="1.2k req/s" trend="up" />
          <MetricRow label="Latency" value="14ms" trend="down" />
          <MetricRow label="DQ Pass Rate" value="99.98%" trend="stable" />
        </div>
      </div>
      
      <div className="mt-auto p-4 bg-blue-600/10 border border-blue-500/20 rounded-2xl">
        <p className="text-[11px] font-semibold text-blue-300">Strategy Insight</p>
        <p className="text-[10px] text-slate-400 mt-2 leading-relaxed">
          Whale accumulation detected in BTCUSDT over the last 15 minutes. High volatility expected at next H1 close.
        </p>
      </div>
    </div>
  );
};

const WhaleAlert = ({ symbol, amount, side, time }: { symbol: string; amount: string; side: 'BUY' | 'SELL', time: string }) => (
  <motion.div 
    initial={{ opacity: 0, x: 20 }}
    animate={{ opacity: 1, x: 0 }}
    className="bg-slate-900 border border-white/5 p-3 rounded-2xl flex items-center justify-between"
  >
    <div className="flex items-center gap-3">
      <div className={`p-2 rounded-lg ${side === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
        {side === 'BUY' ? <ArrowUpRight className="w-4 h-4" /> : <ArrowDownRight className="w-4 h-4" />}
      </div>
      <div>
        <p className="text-xs font-bold text-slate-200">{symbol}</p>
        <p className="text-[10px] text-slate-500">{time}</p>
      </div>
    </div>
    <div className="text-right">
      <p className={`text-xs font-bold ${side === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
        {side === 'BUY' ? '+' : '-'}{amount} {symbol.replace('USDT', '')}
      </p>
      <p className="text-[9px] text-slate-600 font-medium">Institutional</p>
    </div>
  </motion.div>
);

const MetricRow = ({ label, value, trend }: { label: string; value: string; trend: 'up' | 'down' | 'stable' }) => (
  <div className="flex items-center justify-between">
    <span className="text-[11px] text-slate-500 font-medium">{label}</span>
    <div className="flex items-center gap-2">
      <span className="text-[11px] font-bold text-slate-200">{value}</span>
      <div className={`w-1 h-1 rounded-full ${trend === 'up' ? 'bg-emerald-400' : trend === 'down' ? 'bg-rose-400' : 'bg-blue-400'}`} />
    </div>
  </div>
);
