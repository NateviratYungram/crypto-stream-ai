import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TrendingUp, TrendingDown, Minus, Sparkles, AlertCircle } from 'lucide-react';
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

const RISK_LABEL = (signals: Signal[]) => {
  const avgSurge = signals.reduce((s, x) => s + x.vol_surge, 0) / (signals.length || 1);
  if (avgSurge > 2.0) return { level: 'HIGH', color: 'text-rose-400', dot: 'bg-rose-500', emoji: '🔴' };
  if (avgSurge > 1.4) return { level: 'MEDIUM', color: 'text-amber-400', dot: 'bg-amber-500', emoji: '🟡' };
  return { level: 'LOW', color: 'text-emerald-400', dot: 'bg-emerald-500', emoji: '🟢' };
};

const PLAIN_SUMMARY = (signals: Signal[]) => {
  const buys = signals.filter(s => s.direction === 'BUY').length;
  const sells = signals.filter(s => s.direction === 'SELL').length;
  const total = signals.length;
  if (total === 0) return 'กำลังวิเคราะห์ข้อมูลตลาด...';
  if (buys > sells && buys / total > 0.6) {
    const topBuy = signals.find(s => s.direction === 'BUY');
    return `ตลาดวันนี้มีแนวโน้ม Bullish 📈 ${topBuy?.symbol || 'BTC'} ราคาขึ้น ${topBuy?.delta_pct?.toFixed(2) || '0'}% พร้อม Volume ที่เพิ่มขึ้น ${topBuy?.vol_surge?.toFixed(1) || '1.0'}× AI แนะนำ: พิจารณา Long`;
  }
  if (sells > buys && sells / total > 0.6) {
    return 'ตลาดมีแรงขายสูง ⚠️ ควรระวังความเสี่ยง AI แนะนำ: ระวัง Short-term pullback';
  }
  return 'ตลาดยังไม่มีทิศทางชัดเจน 🔄 ราคาเคลื่อนไหวในกรอบ Sideways ควรรอสัญญาณที่ชัดกว่านี้';
};

export const MarketSummary = () => {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const { isRetail } = useMode();

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch('/api/signals');
        const json = await res.json();
        setSignals(json.signals || []);
      } catch (_) {}
      setLoading(false);
    };
    load();
    const iv = setInterval(load, 300000); // refresh every 5 min
    return () => clearInterval(iv);
  }, []);

  const risk = RISK_LABEL(signals);
  const summary = PLAIN_SUMMARY(signals);
  const buyCount = signals.filter(s => s.direction === 'BUY').length;
  const sellCount = signals.filter(s => s.direction === 'SELL').length;
  const totalSig = signals.length || 1;
  const bullPct = Math.round((buyCount / totalSig) * 100);

  if (!isRetail) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="mx-8 mt-8 p-6 rounded-[2rem] border border-blue-500/15 bg-gradient-to-br from-blue-950/40 via-slate-900/60 to-indigo-950/30 relative overflow-hidden"
      >
        <div className="absolute -top-12 -right-12 w-48 h-48 bg-blue-500/5 blur-[60px] rounded-full pointer-events-none" />

        <div className="flex items-start justify-between gap-4 relative z-10">
          <div className="flex items-center gap-3 mb-3">
            <div className="p-2 bg-blue-600/10 rounded-xl border border-blue-500/20">
              <Sparkles className="w-4 h-4 text-blue-400" />
            </div>
            <div>
              <h3 className="text-sm font-black text-white">สรุปตลาดวันนี้</h3>
              <p className="text-[9px] text-slate-500 font-bold uppercase tracking-widest">AI Market Summary · อัปเดตทุก 5 นาที</p>
            </div>
          </div>
          {/* Risk badge */}
          <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-slate-900/60 border border-white/5`}>
            <div className={`w-2 h-2 rounded-full ${risk.dot} animate-pulse`} />
            <span className={`text-[9px] font-black uppercase tracking-widest ${risk.color}`}>
              Risk: {risk.level}
            </span>
          </div>
        </div>

        {loading ? (
          <div className="h-8 bg-slate-800/50 animate-pulse rounded-xl mt-2" />
        ) : (
          <p className="text-sm text-slate-200 font-medium leading-relaxed relative z-10">{summary}</p>
        )}

        {/* Signal bar */}
        {!loading && signals.length > 0 && (
          <div className="mt-4 space-y-2 relative z-10">
            <div className="flex justify-between text-[9px] font-black uppercase tracking-widest">
              <span className="text-emerald-400">🔼 {buyCount} BUY ({bullPct}%)</span>
              <span className="text-rose-400">{sellCount} SELL ({100 - bullPct}%) 🔽</span>
            </div>
            <div className="h-1.5 w-full flex rounded-full overflow-hidden">
              <motion.div
                animate={{ width: `${bullPct}%` }}
                className="h-full bg-emerald-500/70"
                transition={{ duration: 0.8 }}
              />
              <motion.div
                animate={{ width: `${100 - bullPct}%` }}
                className="h-full bg-rose-500/70"
                transition={{ duration: 0.8 }}
              />
            </div>
          </div>
        )}
      </motion.div>
    </AnimatePresence>
  );
};
