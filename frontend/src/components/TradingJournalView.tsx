import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { BookOpen, TrendingUp, TrendingDown, RefreshCcw, Trophy, Target, BarChart2 } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { useMode } from '../contexts/ModeContext';

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
  const { t } = useLanguage();
  const { theme } = useMode();
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
      // Only accept stats if it has the required numeric fields
      const s = d.stats;
      if (s && typeof s.total_trades === 'number') {
        setStats({
          total_trades: s.total_trades ?? 0,
          win_rate_pct: s.win_rate_pct ?? 0,
          total_pnl:    s.total_pnl   ?? 0,
          wins:         s.wins        ?? 0,
          losses:       s.losses      ?? 0,
        });
      } else {
        setStats(null);
      }
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
    <div className={`flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950/20' : 'bg-slate-50'
    }`}>
      {/* Header */}
      <header className={`flex justify-between items-center border-b pb-8 transition-colors duration-500 ${
        theme === 'dark' ? 'border-white/5' : 'border-slate-200'
      }`}>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-violet-400 font-bold text-xs uppercase tracking-[0.2em]">
            <BookOpen className="w-3.5 h-3.5" />
            {t('journal.badge')}
          </div>
          <h2 className={`text-3xl font-extrabold tracking-tight transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>{t('journal.title')}</h2>
          <p className={`text-sm transition-colors duration-500 ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}>{t('journal.subtitle')}</p>
        </div>
        <button onClick={load}
          className={`flex items-center gap-2 px-4 py-2 border rounded-xl text-xs font-bold transition-all duration-300 ${
            theme === 'dark' 
              ? 'bg-slate-900 border-white/10 hover:border-violet-500/40 text-slate-300' 
              : 'bg-white border-slate-200 hover:border-violet-300 text-slate-700 shadow-sm'
          }`}>
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''} ${theme === 'dark' ? 'text-violet-400' : 'text-violet-600'}`} />
          {t('journal.refresh')}
        </button>

      </header>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {[
            { label: t('journal.total_trades'), value: String(stats.total_trades), color: theme === 'dark' ? 'text-slate-300' : 'text-slate-700', icon: BarChart2 },
            { label: t('journal.win_rate'),     value: `${stats.win_rate_pct}%`,   color: gradeColor(stats.win_rate_pct), icon: Target },
            { label: t('journal.total_pnl'),    value: `${(stats.total_pnl ?? 0) >= 0 ? '+' : ''}$${(stats.total_pnl ?? 0).toFixed(2)}`, color: (stats.total_pnl ?? 0) >= 0 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600'), icon: TrendingUp },
            { label: t('journal.wins'),         value: String(stats.wins),         color: theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600', icon: TrendingUp },
            { label: t('journal.losses'),       value: String(stats.losses),       color: theme === 'dark' ? 'text-rose-400' : 'text-rose-600',    icon: TrendingDown },
          ].map((s, i) => (
            <div key={i} className={`p-4 border rounded-2xl flex flex-col gap-2 transition-all duration-500 ${
              theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
            }`}>
              <div className="flex items-center gap-2">
                <s.icon className={`w-4 h-4 ${s.color}`} />
                <p className={`text-[11px] font-black uppercase tracking-widest ${
                  theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
                }`}>{s.label}</p>
              </div>
              <p className={`text-xl font-black font-mono ${s.color}`}>{s.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Performance Grade */}
      {stats && stats.total_trades > 0 && (
        <div className={`flex items-center gap-4 p-5 border rounded-2xl transition-all duration-500 ${
          theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
        }`}>
          <div className={`text-5xl font-black font-mono ${gradeColor(stats.win_rate_pct)}`}>
            {grade(stats.win_rate_pct)}
          </div>
          <div>
            <p className={`font-black text-sm transition-colors duration-500 ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>{t('journal.grade')}</p>
            <p className={`text-sm mt-0.5 transition-colors duration-500 ${
              theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
            }`}>
              {stats.win_rate_pct >= 60
                ? t('journal.grade_good')
                : stats.win_rate_pct >= 50
                ? t('journal.grade_fair')
                : t('journal.grade_poor')
              }
            </p>
          </div>
          <div className={`ml-auto flex items-center gap-2 text-sm font-bold transition-colors duration-500 ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}>
            <Trophy className={`w-5 h-5 ${gradeColor(stats.win_rate_pct)}`} />
            {stats.wins}W / {stats.losses}L
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-2">
        {(['ALL','OPEN','WIN','LOSS'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest border transition-all duration-300 ${
              filter === f
                ? theme === 'dark'
                  ? f === 'WIN'  ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-400 font-black'
                  : f === 'LOSS' ? 'bg-rose-600/20    border-rose-500/40    text-rose-400 font-black'
                  : f === 'OPEN' ? 'bg-blue-600/20    border-blue-500/40    text-blue-400 font-black'
                                 : 'bg-violet-600/20  border-violet-500/40  text-violet-400 font-black'
                  : f === 'WIN'  ? 'bg-emerald-600 border-emerald-600 text-white shadow-lg shadow-emerald-200'
                  : f === 'LOSS' ? 'bg-rose-600    border-rose-600    text-white shadow-lg shadow-rose-200'
                  : f === 'OPEN' ? 'bg-blue-600    border-blue-600    text-white shadow-lg shadow-blue-200'
                                 : 'bg-violet-600  border-violet-600  text-white shadow-lg shadow-violet-200'
                : (theme === 'dark' ? 'bg-transparent border-white/10 text-slate-500 hover:text-white' : 'bg-white border-slate-200 text-slate-500 hover:text-slate-900 shadow-sm hover:border-slate-300')
            }`}>
            {f}
          </button>
        ))}
      </div>


      {/* Trade Table */}
      <div className={`border rounded-[2rem] overflow-hidden transition-all duration-500 ${
        theme === 'dark' ? 'bg-[#0a0f1d]/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
      }`}>
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className={`border-b transition-colors duration-500 ${
              theme === 'dark' ? 'bg-slate-900/80 border-white/5' : 'bg-slate-50/50 border-slate-100'
            }`}>
              {['#','Symbol','Side','Entry','Exit','Volume','P&L','Status','Opened','Closed'].map(h => (
                <th key={h} className="px-5 py-4 text-xs font-bold text-slate-500 uppercase tracking-[0.15em]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className={`divide-y transition-colors duration-500 ${
            theme === 'dark' ? 'divide-white/5' : 'divide-slate-100'
          }`}>
            {loading
              ? [1,2,3].map(i => (
                <tr key={i} className="animate-pulse">
                  <td colSpan={10} className="px-5 py-5">
                    <div className={`h-4 rounded-full ${
                      theme === 'dark' ? 'bg-slate-800/50' : 'bg-slate-100'
                    }`} />
                  </td>
                </tr>
              ))
              : filtered.length === 0
              ? (
                <tr><td colSpan={10} className="px-5 py-20 text-center">
                  <BookOpen className={`w-8 h-8 mx-auto mb-3 ${
                    theme === 'dark' ? 'text-slate-600' : 'text-slate-300'
                  }`} />
                  <p className={`font-bold ${
                    theme === 'dark' ? 'text-slate-500' : 'text-slate-600'
                  }`}>ยังไม่มี paper trade</p>
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
                    className={`transition-colors ${
                      isOpen 
                        ? (theme === 'dark' ? 'bg-blue-500/[0.02]' : 'bg-blue-50/50') 
                        : (theme === 'dark' ? 'hover:bg-white/[0.02]' : 'hover:bg-slate-50')
                    }`}>
                    <td className="px-5 py-4 text-slate-600 font-mono text-xs">#{t.id}</td>
                    <td className={`px-5 py-4 font-black transition-colors ${
                      theme === 'dark' ? 'text-white' : 'text-slate-900'
                    }`}>{t.symbol}</td>
                    <td className="px-5 py-4">
                      <span className={`text-xs font-black px-2 py-0.5 rounded-lg border ${
                        t.side === 'BUY'
                          ? (theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-600')
                          : (theme === 'dark' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-rose-50 border-rose-200 text-rose-600')
                      }`}>{t.side}</span>
                    </td>
                    <td className={`px-5 py-4 font-mono text-sm transition-colors ${
                      theme === 'dark' ? 'text-slate-300' : 'text-slate-600'
                    }`}>${(t.entry_price || 0).toLocaleString()}</td>
                    <td className={`px-5 py-4 font-mono text-sm transition-colors ${
                      theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                    }`}>{t.exit_price ? `$${t.exit_price.toLocaleString()}` : '—'}</td>
                    <td className={`px-5 py-4 font-mono text-sm transition-colors ${
                      theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                    }`}>{t.volume}</td>
                    <td className="px-5 py-4">
                      {t.pnl_usd != null ? (
                        <span className={`font-black font-mono text-sm ${isWin ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`}>
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
