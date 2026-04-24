import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  LogIn,
  RefreshCcw,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMode } from '../contexts/ModeContext';

// ── Types ──────────────────────────────────────────────────────────────────────
interface PaperTrade {
  id: string;
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  exit_price?: number;
  pnl?: number;
  status: 'OPEN' | 'CLOSED';
  opened_at: string;
  closed_at?: string;
}

interface PaperStats {
  open_trades: PaperTrade[];
  closed_trades: PaperTrade[];
  total_simulated_pnl: number;
}

interface LogEntry {
  type: string;
  detail: string;
  time: string;
}

type FilterType = 'ALL' | 'PAPER_TRADE' | 'USER_LOGIN' | 'DQ_ERROR' | 'SNIPER_SIGNAL';

function getLogConfig(type: string, theme: 'light' | 'dark') {
  const configs: Record<string, { label: string; color: string; bg: string; border: string; icon: React.ReactNode }> = {
    PAPER_TRADE:    { 
      label: 'Trade',    
      color: theme === 'dark' ? 'text-blue-300' : 'text-blue-600',   
      bg: theme === 'dark' ? 'bg-blue-500/10' : 'bg-blue-50',   
      border: theme === 'dark' ? 'border-blue-500/20' : 'border-blue-200',   
      icon: <Activity className="w-4 h-4" /> 
    },
    USER_LOGIN:     { 
      label: 'Login',    
      color: theme === 'dark' ? 'text-slate-300' : 'text-slate-600',  
      bg: theme === 'dark' ? 'bg-slate-500/10' : 'bg-slate-50',  
      border: theme === 'dark' ? 'border-slate-500/20' : 'border-slate-200',  
      icon: <LogIn className="w-4 h-4" /> 
    },
    USER_REGISTER:  { 
      label: 'New user', 
      color: theme === 'dark' ? 'text-indigo-300' : 'text-indigo-600', 
      bg: theme === 'dark' ? 'bg-indigo-500/10' : 'bg-indigo-50', 
      border: theme === 'dark' ? 'border-indigo-500/20' : 'border-indigo-200', 
      icon: <LogIn className="w-4 h-4" /> 
    },
    DQ_ERROR:       { 
      label: 'Alert',    
      color: theme === 'dark' ? 'text-rose-300' : 'text-rose-600',   
      bg: theme === 'dark' ? 'bg-rose-500/10' : 'bg-rose-50',   
      border: theme === 'dark' ? 'border-rose-500/20' : 'border-rose-200',   
      icon: <AlertTriangle className="w-4 h-4" /> 
    },
    SNIPER_SIGNAL:  { 
      label: 'Signal',   
      color: theme === 'dark' ? 'text-amber-300' : 'text-amber-600',  
      bg: theme === 'dark' ? 'bg-amber-500/10' : 'bg-amber-50',  
      border: theme === 'dark' ? 'border-amber-500/20' : 'border-amber-200',  
      icon: <Zap className="w-4 h-4" /> 
    },
  };
  return configs[type] ?? { 
    label: 'System', 
    color: theme === 'dark' ? 'text-slate-400' : 'text-slate-500', 
    bg: theme === 'dark' ? 'bg-slate-500/10' : 'bg-slate-50', 
    border: theme === 'dark' ? 'border-slate-500/20' : 'border-slate-200', 
    icon: <ShieldCheck className="w-4 h-4" /> 
  };
}

function fmt(n: number) {
  const abs = Math.abs(n);
  const s = abs >= 1000 ? `$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : `$${abs.toFixed(2)}`;
  return (n >= 0 ? '+' : '−') + s;
}

function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

const FILTER_PILLS: { key: FilterType; label: string }[] = [
  { key: 'ALL',           label: 'All' },
  { key: 'PAPER_TRADE',   label: 'Trade' },
  { key: 'USER_LOGIN',    label: 'Login' },
  { key: 'DQ_ERROR',      label: 'Alert' },
  { key: 'SNIPER_SIGNAL', label: 'Signal' },
];

// ── Component ──────────────────────────────────────────────────────────────────
export const RiskAuditsView = () => {
  const { theme } = useMode();
  const [stats,   setStats]   = useState<PaperStats | null>(null);
  const [logs,    setLogs]    = useState<LogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter,  setFilter]  = useState<FilterType>('ALL');
  const [showAll, setShowAll] = useState(false);
  const { wsStatus, lastMessage } = useWebSocket();

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [ptRes, logRes] = await Promise.all([
        fetch('/api/paper-trades', { headers: { 'X-API-Key': localStorage.getItem('crypto_terminal_key') || 'demo' } }),
        fetch('/api/data/audits'),
      ]);
      if (ptRes.ok)  setStats(await ptRes.json());
      if (logRes.ok) setLogs((await logRes.json()).data || []);
    } catch {/* silent */} finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);

  useEffect(() => {
    if (lastMessage?.type === 'DQ_ALERT') {
      setLogs(prev => [{
        type: 'DQ_ERROR',
        detail: `DQ Violation: ${lastMessage.data.error_reason} | ${lastMessage.data.symbol}`,
        time: new Date().toISOString(),
      }, ...prev.slice(0, 49)]);
    }
  }, [lastMessage]);

  // ── Derived P&L stats ────────────────────────────────────────────────────────
  const closed  = stats?.closed_trades ?? [];
  const open    = stats?.open_trades ?? [];
  const winners = closed.filter(t => (t.pnl ?? 0) > 0);
  const losers  = closed.filter(t => (t.pnl ?? 0) < 0);
  const totalPnl = stats?.total_simulated_pnl ?? 0;
  const winRate  = closed.length ? Math.round((winners.length / closed.length) * 100) : 0;
  const bestTrade  = closed.reduce<PaperTrade | null>((mx, t) => (!mx || (t.pnl ?? 0) > (mx.pnl ?? 0)) ? t : mx, null);
  const worstTrade = closed.reduce<PaperTrade | null>((mn, t) => (!mn || (t.pnl ?? 0) < (mn.pnl ?? 0)) ? t : mn, null);

  // ── Filtered logs ────────────────────────────────────────────────────────────
  const filteredLogs = useMemo(() => {
    if (filter === 'ALL') return logs;
    if (filter === 'USER_LOGIN') return logs.filter(l => l.type === 'USER_LOGIN' || l.type === 'USER_REGISTER');
    return logs.filter(l => l.type === filter);
  }, [logs, filter]);

  const visibleLogs = showAll ? filteredLogs : filteredLogs.slice(0, 12);

  return (
    <div className={`flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950' : 'bg-slate-50'
    }`}>
      {/* Header */}
      <header className={`flex justify-between items-center border-b pb-8 ${
        theme === 'dark' ? 'border-white/5' : 'border-slate-200'
      }`}>
        <div className="space-y-1">
          <div className={`flex items-center gap-2 font-bold text-xs uppercase tracking-[0.2em] ${
            theme === 'dark' ? 'text-blue-400' : 'text-blue-600'
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full ${
              wsStatus === 'connected' ? (theme === 'dark' ? 'bg-blue-400 animate-pulse' : 'bg-blue-600 animate-pulse') : 'bg-slate-600'
            }`} />
            P&L + Activity
          </div>
          <h2 className={`text-3xl font-extrabold tracking-tight ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Performance & Log</h2>
          <p className={`${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'} text-sm font-medium`}>
            Paper trading P&L summary · system activity · real-time alerts
          </p>
        </div>
        <button onClick={fetchAll}
          className={`group flex items-center gap-2 px-4 py-2 border rounded-xl transition-all font-bold text-xs ${
            theme === 'dark' 
              ? 'bg-slate-900 border-white/10 text-slate-300 hover:border-blue-500/40 hover:text-white' 
              : 'bg-white border-slate-200 text-slate-600 hover:border-blue-300 hover:text-slate-900 shadow-sm'
          }`}>
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`} />
          Refresh
        </button>
      </header>

      {/* P&L Summary Cards */}
      <section className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          {
            label: 'Total P&L',
            value: totalPnl !== 0 ? fmt(totalPnl) : '$0.00',
            sub: `${closed.length} closed trades`,
            color: totalPnl >= 0 
              ? (theme === 'dark' ? 'text-emerald-300' : 'text-emerald-600') 
              : (theme === 'dark' ? 'text-rose-300' : 'text-rose-600'),
            icon: totalPnl >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />,
            border: totalPnl >= 0 
              ? (theme === 'dark' ? 'border-emerald-500/15' : 'border-emerald-200') 
              : (theme === 'dark' ? 'border-rose-500/15' : 'border-rose-200'),
            bg: totalPnl >= 0 
              ? (theme === 'dark' ? 'bg-emerald-500/5' : 'bg-emerald-50/50') 
              : (theme === 'dark' ? 'bg-rose-500/5' : 'bg-rose-50/50'),
          },
          {
            label: 'Win Rate',
            value: `${winRate}%`,
            sub: `${winners.length}W / ${losers.length}L`,
            color: winRate >= 50 
              ? (theme === 'dark' ? 'text-emerald-300' : 'text-emerald-600') 
              : (theme === 'dark' ? 'text-rose-300' : 'text-rose-600'),
            icon: <CheckCircle2 className="w-5 h-5" />,
            border: theme === 'dark' ? 'border-white/10' : 'border-slate-200',
            bg: theme === 'dark' ? 'bg-slate-900/60' : 'bg-white shadow-xl shadow-slate-200/40',
          },
          {
            label: 'Open Positions',
            value: String(open.length),
            sub: open.length ? open.map(t => t.symbol).slice(0, 3).join(', ') + (open.length > 3 ? '…' : '') : 'No open trades',
            color: theme === 'dark' ? 'text-blue-300' : 'text-blue-600',
            icon: <Activity className="w-5 h-5" />,
            border: theme === 'dark' ? 'border-blue-500/15' : 'border-blue-200',
            bg: theme === 'dark' ? 'bg-blue-500/10' : 'bg-blue-50/50',
          },
          {
            label: 'Best Trade',
            value: bestTrade ? fmt(bestTrade.pnl ?? 0) : '—',
            sub: bestTrade ? bestTrade.symbol : 'No closed trades yet',
            color: theme === 'dark' ? 'text-amber-300' : 'text-amber-600',
            icon: <Zap className="w-5 h-5" />,
            border: theme === 'dark' ? 'border-amber-500/15' : 'border-amber-200',
            bg: theme === 'dark' ? 'bg-amber-500/10' : 'bg-amber-50/50',
          },
        ].map(card => (
          <div key={card.label} className={`rounded-[1.5rem] border p-5 transition-all ${card.border} ${card.bg}`}>
            <div className="flex items-center justify-between mb-3">
              <p className="text-[10px] font-black uppercase tracking-[0.22em] text-slate-500">{card.label}</p>
              <span className={card.color}>{card.icon}</span>
            </div>
            <p className={`text-2xl font-black ${card.color}`}>{card.value}</p>
            <p className={`mt-1 text-xs font-semibold truncate ${theme === 'dark' ? 'text-slate-600' : 'text-slate-500'}`}>{card.sub}</p>
          </div>
        ))}
      </section>

      {/* Open Positions mini-table */}
      {open.length > 0 && (
        <section className={`rounded-[1.75rem] border overflow-hidden transition-all duration-500 ${
          theme === 'dark' ? 'border-white/10 bg-slate-900/60' : 'border-slate-200 bg-white shadow-xl shadow-slate-200/40'
        }`}>
          <div className={`border-b px-5 py-3 ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
            <p className={`text-[11px] font-black uppercase tracking-[0.22em] ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>Open Positions</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b text-left text-[10px] font-black uppercase tracking-[0.22em] ${
                  theme === 'dark' ? 'border-white/5 text-slate-600' : 'border-slate-100 text-slate-400'
                }`}>
                  <th className="py-2 pl-5 pr-4">Symbol</th>
                  <th className="py-2 pr-4">Side</th>
                  <th className="py-2 pr-4 text-right">Qty</th>
                  <th className="py-2 pr-4 text-right">Entry</th>
                  <th className="py-2 pr-5 text-right">Unrealised P&L</th>
                </tr>
              </thead>
              <tbody>
                {open.map(t => (
                  <tr key={t.id} className={`border-b transition-colors ${
                    theme === 'dark' ? 'border-white/[0.03] hover:bg-white/[0.02]' : 'border-slate-50 hover:bg-slate-50/50'
                  }`}>
                    <td className={`py-2.5 pl-5 pr-4 font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{t.symbol}</td>
                    <td className={`py-2.5 pr-4 font-black text-xs uppercase ${
                      t.side === 'BUY' 
                        ? (theme === 'dark' ? 'text-emerald-300' : 'text-emerald-600') 
                        : (theme === 'dark' ? 'text-rose-300' : 'text-rose-600')
                    }`}>{t.side}</td>
                    <td className={`py-2.5 pr-4 text-right font-semibold ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>{t.quantity}</td>
                    <td className={`py-2.5 pr-4 text-right font-semibold ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>${t.entry_price.toLocaleString()}</td>
                    <td className="py-2.5 pr-5 text-right font-black text-slate-500">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Best / Worst closed trades */}
      {closed.length > 0 && (
        <section className="grid gap-4 sm:grid-cols-2">
          {[
            { label: 'Best trade', trade: bestTrade, color: 'emerald' },
            { label: 'Worst trade', trade: worstTrade, color: 'rose' },
          ].map(({ label, trade, color }) => trade && (
            <div key={label} className={`rounded-[1.5rem] border p-5 flex items-center gap-4 transition-all ${
              theme === 'dark' ? 'border-white/8 bg-slate-900/60' : 'border-slate-200 bg-white shadow-sm'
            }`}>
              <div className={`flex h-11 w-11 items-center justify-center rounded-2xl border shrink-0 ${
                color === 'emerald' 
                  ? (theme === 'dark' ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-600')
                  : (theme === 'dark' ? 'border-rose-500/20 bg-rose-500/10 text-rose-300' : 'border-rose-200 bg-rose-50 text-rose-600')
              }`}>
                {color === 'emerald' ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
              </div>
              <div className="min-w-0">
                <p className="text-[10px] font-black uppercase tracking-[0.22em] text-slate-500">{label}</p>
                <p className={`font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                  {trade.symbol} <span className="text-slate-500 text-xs font-medium">{trade.side}</span>
                </p>
                <p className={`text-sm font-black ${
                  color === 'emerald' 
                    ? (theme === 'dark' ? 'text-emerald-300' : 'text-emerald-600')
                    : (theme === 'dark' ? 'text-rose-300' : 'text-rose-600')
                }`}>{fmt(trade.pnl ?? 0)}</p>
              </div>
            </div>
          ))}
        </section>
      )}

      {/* Activity Log */}
      <section className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className={`text-[11px] font-black uppercase tracking-[0.22em] ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>Activity Log</p>
          {/* Filter pills */}
          <div className="flex flex-wrap gap-1.5">
            {FILTER_PILLS.map(pill => (
              <button key={pill.key} onClick={() => { setFilter(pill.key); setShowAll(false); }}
                className={`rounded-xl border px-3 py-1 text-[10px] font-black uppercase tracking-[0.18em] transition-all ${
                  filter === pill.key
                    ? (theme === 'dark' ? 'border-blue-400/30 bg-blue-500/15 text-blue-200' : 'border-blue-200 bg-blue-50 text-blue-600 shadow-sm')
                    : (theme === 'dark' ? 'border-white/10 text-slate-500 hover:border-white/20 hover:text-slate-300' : 'border-slate-200 text-slate-400 hover:border-slate-300 hover:text-slate-600 bg-white shadow-sm')
                }`}>
                {pill.key === 'ALL'
                  ? `${pill.label} · ${logs.length}`
                  : `${pill.label} · ${logs.filter(l => pill.key === 'USER_LOGIN' ? (l.type === 'USER_LOGIN' || l.type === 'USER_REGISTER') : l.type === filter).length}`}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3, 4].map(i => (
              <div key={i} className={`h-16 rounded-2xl border animate-pulse ${
                theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'border-slate-100 bg-white shadow-sm'
              }`} />
            ))}
          </div>
        ) : filteredLogs.length === 0 ? (
          <div className={`flex flex-col items-center gap-3 rounded-[2rem] border border-dashed py-16 text-center ${
            theme === 'dark' ? 'border-white/8' : 'border-slate-200'
          }`}>
            <ShieldCheck className="w-10 h-10 text-slate-600 opacity-20" />
            <p className="text-sm font-bold text-slate-500">No activity in this category</p>
          </div>
        ) : (
          <>
            <AnimatePresence initial={false}>
              <div className="space-y-2">
                {visibleLogs.map((log, i) => {
                  const cfg = getLogConfig(log.type, theme);
                  return (
                    <motion.div key={log.time + i}
                      initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.02 }}
                      className={`flex items-start gap-4 rounded-2xl border px-5 py-4 transition-all ${cfg.border} ${cfg.bg} ${theme === 'light' ? 'shadow-sm' : ''}`}>
                      <div className={`mt-0.5 shrink-0 ${cfg.color}`}>{cfg.icon}</div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <span className={`text-[10px] font-black uppercase tracking-[0.18em] ${cfg.color}`}>{cfg.label}</span>
                          <span className={`text-[10px] font-semibold ${theme === 'dark' ? 'text-slate-600' : 'text-slate-400'}`}>{fmtTime(log.time)}</span>
                        </div>
                        <p className={`text-sm font-semibold leading-6 truncate ${theme === 'dark' ? 'text-slate-200' : 'text-slate-700'}`}>{log.detail}</p>
                      </div>
                    </motion.div>
                  );
                })}
              </div>
            </AnimatePresence>

            {filteredLogs.length > 12 && (
              <button onClick={() => setShowAll(p => !p)}
                className={`flex w-full items-center justify-center gap-2 rounded-2xl border py-3 text-[11px] font-black uppercase tracking-[0.18em] transition-all ${
                  theme === 'dark' 
                    ? 'border-white/8 text-slate-500 hover:border-white/16 hover:text-slate-300' 
                    : 'border-slate-200 bg-white text-slate-400 hover:border-slate-300 hover:text-slate-600 shadow-sm'
                }`}>
                <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showAll ? 'rotate-180' : ''}`} />
                {showAll ? 'Show less' : `Show all ${filteredLogs.length} entries`}
              </button>
            )}
          </>
        )}
      </section>
    </div>
  );
};
