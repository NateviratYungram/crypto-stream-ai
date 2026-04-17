import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { BookOpen, TrendingUp, TrendingDown, RefreshCcw, Trophy, Target, BarChart2 } from 'lucide-react';

interface Trade {
  id:          number;
  symbol:      string;
  side:        string;
  entry_price: number;
  exit_price:  number | null;
  volume:      number;
  pnl_usd:     number | null;
  status:      string;
  opened_at:   string;
  closed_at:   string | null;
}

interface Stats {
  total_trades: number;
  win_rate_pct: number;
  total_pnl:   number;
  wins:        number;
  losses:      number;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';

export const TradingJournalView = () => {
  const [trades,  setTrades]  = useState<Trade[]>([]);
  const [stats,   setStats]   = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter,  setFilter]  = useState<'ALL' | 'WIN' | 'LOSS' | 'OPEN'>('ALL');

  const load = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/journal?limit=100', { headers: { 'X-API-Key': API_KEY() } });
      const d   = await res.json();
      setTrades(d.trades || []);
      setStats(d.stats  || null);
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const filtered = trades.filter(t => {
    if (filter === 'ALL')  return true;
    if (filter === 'OPEN') return t.status === 'OPEN';
    if (filter === 'WIN')  return t.status === 'CLOSED' && (t.pnl_usd ?? 0) > 0;
    if (filter === 'LOSS') return t.status === 'CLOSED' && (t.pnl_usd ?? 0) <= 0;
    return true;
  });

  const gradeColor = (wr: number) =>
    wr >= 65 ? 'text-emerald-400' : wr >= 50 ? 'text-blue-400' : wr >= 40 ? 'text-amber-400' : 'text-rose-400';

  const grade = (wr: number) =>
    wr >= 70 ? 'A+' : wr >= 60 ? 'A' : wr >= 50 ? 'B' : wr >= 40 ? 'C' : 'D';

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-violet-400 font-bold text-xs uppercase tracking-[0.2em]">
            <BookOpen className="w-3.5 h-3.5" />
            Trade Journal
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">Trading Journal</h2>
          <p className="text-slate-500 text-sm">ประวัติ Paper Trade ทั้งหมด + AI performance analysis</p>
        </div>
        <button onClick={load}
          className="flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-violet-500/40 rounded-xl text-slate-300 text-xs font-bold transition-all">
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </header>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: 'Total Trades', value: String(stats.total_trades), color: 'text-slate-300', icon: BarChart2 },
            { label: 'Win Rate',     value: `${stats.win_rate_pct}%`,   color: gradeColor(stats.win_rate_pct), icon: Target },
            { label: 'Total P&L',    value: `${stats.total_pnl >= 0 ? '+' : ''}$${stats.total_pnl.toFixed(2)}`, color: stats.total_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400', icon: TrendingUp },
            { label: 'Wins',         value: String(stats.wins),         color: 'text-emerald-400', icon: TrendingUp },
            { label: 'Losses',       value: String(stats.losses),       color: 'text-rose-400',    icon: TrendingDown },
          ].map((s, i) => (
            <div key={i} className="p-4 bg-slate-900/40 border border-white/5 rounded-2xl flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <s.icon className={`w-4 h-4 ${s.color}`} />
                <p className="text-[11px] font-black text-slate-600 uppercase tracking-widest">{s.label}</p>
              </div>
              <p className={`text-xl font-black font-mono ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Performance Grade */}
      {stats && stats.total_trades > 0 && (
        <div className="flex items-center gap-4 p-5 bg-slate-900/40 border border-white/5 rounded-2xl">
          <div className={`text-5xl font-black font-mono ${gradeColor(stats.win_rate_pct)}`}>
            {grade(stats.win_rate_pct)}
          </div>
          <div>
            <p className="font-black text-white text-sm">Performance Grade</p>
            <p className="text-slate-500 text-sm mt-0.5">
              {stats.win_rate_pct >= 60
                ? 'ผลงานดี — ทำต่อไปตาม process เดิม'
                : stats.win_rate_pct >= 50
                ? 'พอใช้ได้ — ทบทวน entry criteria เพิ่มเติม'
                : 'Win rate ต่ำกว่า 50% — ควรหยุดทบทวน strategy ก่อน'
              }
            </p>
          </div>
          <div className="ml-auto flex items-center gap-2 text-sm text-slate-500 font-bold">
            <Trophy className={`w-5 h-5 ${gradeColor(stats.win_rate_pct)}`} />
            {stats.wins}W / {stats.losses}L
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2">
        {(['ALL','OPEN','WIN','LOSS'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
              filter === f
                ? f === 'WIN'  ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-400'
                : f === 'LOSS' ? 'bg-rose-600/20    border-rose-500/40    text-rose-400'
                : f === 'OPEN' ? 'bg-blue-600/20    border-blue-500/40    text-blue-400'
                               : 'bg-violet-600/20  border-violet-500/40  text-violet-400'
                : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
            }`}>
            {f}
          </button>
        ))}
      </div>

      {/* Trade Table */}
      <div className="bg-slate-900/40 border border-white/5 rounded-[2rem] overflow-hidden">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-900/80 border-b border-white/5">
              {['#','Symbol','Side','Entry','Exit','Volume','P&L','Status','Opened','Closed'].map(h => (
                <th key={h} className="px-5 py-4 text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {loading
              ? [1,2,3].map(i => <tr key={i} className="animate-pulse"><td colSpan={10} className="px-5 py-5"><div className="h-4 bg-slate-800/50 rounded-full" /></td></tr>)
              : filtered.length === 0
              ? (
                <tr><td colSpan={10} className="px-5 py-20 text-center">
                  <BookOpen className="w-8 h-8 text-slate-600 mx-auto mb-3" />
                  <p className="text-slate-500 font-bold">ยังไม่มี paper trade</p>
                  <p className="text-slate-600 text-sm mt-1">สั่ง AI ว่า "paper trade BTC buy 0.01" เพื่อเริ่ม</p>
                </td></tr>
              )
              : filtered.map((t, i) => {
                const isWin  = (t.pnl_usd ?? 0) > 0;
                const isOpen = t.status === 'OPEN';
                const fmt    = (v: string) => v ? new Date(v).toLocaleDateString('th-TH', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' }) : '—';
                return (
                  <motion.tr key={t.id}
                    initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.03 }}
                    className={`hover:bg-white/[0.02] transition-colors ${isOpen ? 'bg-blue-500/[0.02]' : ''}`}>
                    <td className="px-5 py-4 text-slate-600 font-mono text-xs">#{t.id}</td>
                    <td className="px-5 py-4 font-black text-white">{t.symbol}</td>
                    <td className="px-5 py-4">
                      <span className={`text-xs font-black px-2 py-0.5 rounded-lg border ${
                        t.side === 'BUY'
                          ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                          : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
                      }`}>{t.side}</span>
                    </td>
                    <td className="px-5 py-4 font-mono text-sm text-slate-300">${(t.entry_price || 0).toLocaleString()}</td>
                    <td className="px-5 py-4 font-mono text-sm text-slate-400">{t.exit_price ? `$${t.exit_price.toLocaleString()}` : '—'}</td>
                    <td className="px-5 py-4 font-mono text-sm text-slate-400">{t.volume}</td>
                    <td className="px-5 py-4">
                      {t.pnl_usd != null ? (
                        <span className={`font-black font-mono text-sm ${isWin ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {isWin ? '+' : ''}${t.pnl_usd.toFixed(2)}
                        </span>
                      ) : <span className="text-slate-600 text-xs">Unrealized</span>}
                    </td>
                    <td className="px-5 py-4">
                      <span className={`text-[11px] font-black uppercase tracking-widest ${
                        isOpen ? 'text-blue-400' : isWin ? 'text-emerald-400' : 'text-rose-400'
                      }`}>{isOpen ? 'OPEN' : isWin ? 'WIN' : 'LOSS'}</span>
                    </td>
                    <td className="px-5 py-4 text-slate-500 text-xs font-mono">{fmt(t.opened_at)}</td>
                    <td className="px-5 py-4 text-slate-500 text-xs font-mono">{t.closed_at ? fmt(t.closed_at) : '—'}</td>
                  </motion.tr>
                );
              })
            }
          </tbody>
        </table>
      </div>
    </div>
  );
};
