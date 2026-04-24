import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  TrendingUp, TrendingDown, Plus, X, RefreshCw, Trash2,
  CheckCircle2, AlertCircle, FlaskConical, DollarSign, BarChart3, Target, Brain,
  Activity, Award, Zap, ShieldCheck
} from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

interface PaperTrade {
  id: string;
  symbol: string;
  side: 'BUY' | 'SELL';
  volume: number;
  entry_price: number;
  current_price: number;
  pnl_usd: number;
  status: 'OPEN' | 'CLOSED';
  opened_at: string;
  closed_at?: string;
  ml_score?: number | null;
  outcome?: string | null;
  entry_source?: string | null;
  entry_reason?: string | null;
  close_reason?: string | null;
  label_source?: string | null;
}

interface Stats {
  open: number;
  totalPnl: number;
  winRate: number;
  wins: number;
  losses: number;
}

interface AutoPaperStatus {
  enabled: boolean;
  symbols: string[];
  confidence_threshold: number;
  volume: number;
  cooldown_minutes: number;
  max_open_positions: number;
  scan_interval_seconds: number;
  last_run_at?: string | null;
  last_error?: string | null;
  last_summary?: {
    checked_symbols?: string[];
    opened?: Array<{ symbol: string; side: string; trade_id: string; confidence: number; price: number }>;
    skipped?: Array<{ symbol: string; reason: string }>;
  } | null;
}

const POPULAR_SYMBOLS = ['BTC', 'ETH', 'SOL', 'NVDA', 'TSLA', 'GOLD', 'AAPL', 'AMZN'];
const AUTO_SYMBOLS = ['BTCUSD', 'ETHUSD', 'GOLD', 'EURUSD'];

export const PaperTradingDashboard = () => {
  const { theme } = useMode();
  const [openTrades,   setOpenTrades]   = useState<PaperTrade[]>([]);
  const [closedTrades, setClosedTrades] = useState<PaperTrade[]>([]);
  const [stats,        setStats]        = useState<Stats>({ open: 0, totalPnl: 0, winRate: 0, wins: 0, losses: 0 });
  const [loading,      setLoading]      = useState(true);
  const [closing,      setClosing]      = useState<string | null>(null);
  const [resetting,    setResetting]    = useState(false);
  const [showForm,     setShowForm]     = useState(false);
  const [tab,          setTab]          = useState<'open' | 'history'>('open');
  const [toast,        setToast]        = useState<{ type: 'ok' | 'err'; msg: string } | null>(null);
  const [autoPaper,    setAutoPaper]    = useState<AutoPaperStatus | null>(null);
  const [autoForm,     setAutoForm]     = useState({
    enabled: false,
    confidence_threshold: '0.68',
    volume: '0.01',
    cooldown_minutes: '90',
    max_open_positions: '2',
    symbols: AUTO_SYMBOLS,
  });
  const [savingAuto,   setSavingAuto]   = useState(false);
  const [runningAuto,  setRunningAuto]  = useState(false);

  // New trade form
  const [form, setForm] = useState({ symbol: 'BTC', side: 'BUY' as 'BUY' | 'SELL', volume: '1', price: '' });
  const [opening, setOpening] = useState(false);

  const showToast = (type: 'ok' | 'err', msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3000);
  };

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const [tradesRes, autoRes] = await Promise.all([
        fetch('/api/paper-trades', { headers: { 'X-API-Key': 'demo' } }),
        fetch('/api/paper-trades/auto', { headers: { 'X-API-Key': 'demo' } }),
      ]);
      const data = await tradesRes.json();
      const auto = await autoRes.json();
      const open   = (data.open_trades   || []) as PaperTrade[];
      const closed = (data.closed_trades || []) as PaperTrade[];
      setOpenTrades(open);
      setClosedTrades(closed);
      setAutoPaper(auto);
      setAutoForm({
        enabled: Boolean(auto.enabled),
        confidence_threshold: String(auto.confidence_threshold ?? 0.68),
        volume: String(auto.volume ?? 0.01),
        cooldown_minutes: String(auto.cooldown_minutes ?? 90),
        max_open_positions: String(auto.max_open_positions ?? 2),
        symbols: Array.isArray(auto.symbols) && auto.symbols.length ? auto.symbols : AUTO_SYMBOLS,
      });
      const wins   = closed.filter(t => t.pnl_usd > 0).length;
      const losses = closed.filter(t => t.pnl_usd <= 0).length;
      setStats({
        open:     open.length,
        totalPnl: data.total_simulated_pnl || 0,
        winRate:  closed.length ? Math.round((wins / closed.length) * 100) : 0,
        wins, losses
      });
    } catch {
      showToast('err', 'Failed to load paper trades');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const id = setInterval(() => { void load(true); }, 10_000);
    return () => clearInterval(id);
  }, [load]);

  const saveAutoConfig = async (nextForm = autoForm) => {
    setSavingAuto(true);
    try {
      const res = await fetch('/api/paper-trades/auto', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'demo' },
        body: JSON.stringify({
          enabled: nextForm.enabled,
          confidence_threshold: parseFloat(nextForm.confidence_threshold) || 0.68,
          volume: parseFloat(nextForm.volume) || 0.01,
          cooldown_minutes: parseInt(nextForm.cooldown_minutes, 10) || 90,
          max_open_positions: parseInt(nextForm.max_open_positions, 10) || 2,
          symbols: nextForm.symbols,
        }),
      });
      const data = await res.json();
      setAutoPaper(data);
      showToast('ok', `Auto Paper ${data.enabled ? 'enabled' : 'updated'}`);
      await load();
    } catch (err: any) {
      showToast('err', err.message || 'Failed to update auto paper');
    } finally {
      setSavingAuto(false);
    }
  };

  const handleAutoSave = async () => {
    await saveAutoConfig(autoForm);
  };

  const handleAutoRun = async () => {
    setRunningAuto(true);
    try {
      const res = await fetch('/api/paper-trades/auto/run', {
        method: 'POST',
        headers: { 'X-API-Key': 'demo' },
      });
      const data = await res.json();
      const opened = data?.summary?.opened?.length || 0;
      showToast('ok', opened > 0 ? `Auto Paper opened ${opened} trade(s)` : 'Auto Paper scan completed');
      await load();
    } catch (err: any) {
      showToast('err', err.message || 'Failed to run auto paper');
    } finally {
      setRunningAuto(false);
    }
  };

  const handleOpen = async (e: React.FormEvent) => {
    e.preventDefault();
    setOpening(true);
    try {
      const body: Record<string, unknown> = {
        symbol: form.symbol.toUpperCase(),
        side:   form.side,
        volume: parseFloat(form.volume) || 1,
      };
      if (form.price) body.price = parseFloat(form.price);
      const res = await fetch('/api/paper-trades', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'demo' },
        body: JSON.stringify(body)
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      showToast('ok', `Paper ${form.side} ${form.symbol} opened (ID: ${data.trade_id})`);
      setShowForm(false);
      setForm(f => ({ ...f, price: '' }));
      await load();
    } catch (err: any) {
      showToast('err', err.message || 'Failed to open trade');
    } finally {
      setOpening(false);
    }
  };

  const handleClose = async (id: string) => {
    setClosing(id);
    try {
      const res = await fetch(`/api/paper-trades/${id}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'demo' },
        body: JSON.stringify({})
      });
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      const pnl = data.pnl_usd ?? 0;
      showToast(pnl >= 0 ? 'ok' : 'err', `Closed at ${data.exit_price} — P&L: ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`);
      await load();
    } catch (err: any) {
      showToast('err', err.message || 'Failed to close trade');
    } finally {
      setClosing(null);
    }
  };

  const handleReset = async () => {
    if (!confirm('Reset all paper trading history? This cannot be undone.')) return;
    setResetting(true);
    try {
      await fetch('/api/paper-trades', { method: 'DELETE', headers: { 'X-API-Key': 'demo' } });
      showToast('ok', 'Paper trading history cleared');
      await load();
    } finally {
      setResetting(false);
    }
  };

  const unrealizedPnl = openTrades.reduce((sum, t) => {
    const dir = t.side === 'BUY' ? 1 : -1;
    return sum + dir * (t.current_price - t.entry_price) * t.volume;
  }, 0);

  // --- Performance Analytics (computed from closed trades) ---
  const perf = useMemo(() => {
    if (closedTrades.length === 0) return null;
    const wins  = closedTrades.filter(t => t.pnl_usd > 0);
    const losses = closedTrades.filter(t => t.pnl_usd <= 0);
    const grossWin  = wins.reduce((s, t) => s + t.pnl_usd, 0);
    const grossLoss = Math.abs(losses.reduce((s, t) => s + t.pnl_usd, 0));
    const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 999 : 0;
    const avgWin  = wins.length   ? grossWin  / wins.length   : 0;
    const avgLoss = losses.length ? grossLoss / losses.length : 0;
    const rr = avgLoss > 0 ? avgWin / avgLoss : 0;
    // Equity curve: running cumulative PnL
    const sorted = [...closedTrades].sort((a, b) =>
      new Date(a.closed_at || a.opened_at).getTime() - new Date(b.closed_at || b.opened_at).getTime()
    );
    let cum = 0;
    const curve = sorted.map(t => { cum += t.pnl_usd; return cum; });
    // Max drawdown
    let peak = -Infinity, maxDd = 0;
    for (const v of curve) {
      if (v > peak) peak = v;
      const dd = peak - v;
      if (dd > maxDd) maxDd = dd;
    }
    const winRate = closedTrades.length ? (wins.length / closedTrades.length) * 100 : 0;
    const grade = winRate >= 70 ? 'SNIPER' : winRate >= 55 ? 'PRECISION' : winRate >= 45 ? 'STANDARD' : 'NEEDS WORK';
    const gradeColor = winRate >= 70 ? 'text-emerald-400' : winRate >= 55 ? 'text-indigo-400' : winRate >= 45 ? 'text-amber-400' : 'text-rose-400';
    return { profitFactor, avgWin, avgLoss, rr, curve, maxDd, winRate, grade, gradeColor, totalTrades: closedTrades.length };
  }, [closedTrades]);

  return (
    <div className={`flex-1 overflow-y-auto p-6 lg:p-8 space-y-6 scrollbar-hide transition-colors duration-500 ${
      theme === 'dark' ? 'bg-[#030712]/20' : 'bg-slate-50'
    }`}>
      {/* Toast */}
      <AnimatePresence>
        {toast && (
          <motion.div
            initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
            className={`fixed top-4 right-4 z-[9999] flex items-center gap-3 px-5 py-3 rounded-2xl border shadow-2xl text-sm font-bold ${
              toast.type === 'ok' 
                ? (theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-white border-emerald-200 text-emerald-600 shadow-emerald-500/10')
                : (theme === 'dark' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-white border-rose-200 text-rose-600 shadow-rose-500/10')
            }`}
          >
            {toast.type === 'ok' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
            {toast.msg}
          </motion.div>
        )}
      </AnimatePresence>

      {/* Simulation Notice */}
      <div className={`flex items-center gap-3 p-4 border rounded-2xl transition-all ${
        theme === 'dark' ? 'bg-blue-500/5 border-blue-500/20' : 'bg-blue-50 border-blue-200 shadow-sm'
      }`}>
        <FlaskConical className={`w-4 h-4 shrink-0 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
        <div>
          <span className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-blue-400' : 'text-blue-700'}`}>🎮 Simulation Mode</span>
          <span className={`text-sm ml-3 ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>ไม่ใช้เงินจริง — ทุกการเทรดเป็นการจำลองเพื่อฝึกฝนเท่านั้น ไม่มีความเสี่ยงทางการเงิน</span>
        </div>
      </div>

      <div className={`border rounded-2xl p-5 transition-all ${
        theme === 'dark' ? 'bg-violet-500/5 border-violet-500/20' : 'bg-white border-violet-200 shadow-sm'
      }`}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Zap className={`w-4 h-4 ${theme === 'dark' ? 'text-violet-300' : 'text-violet-600'}`} />
              <p className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-violet-300' : 'text-violet-700'}`}>
                Auto Paper Trading
              </p>
              <span className={`px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${
                autoPaper?.enabled
                  ? (theme === 'dark' ? 'bg-emerald-500/10 text-emerald-300' : 'bg-emerald-50 text-emerald-700')
                  : (theme === 'dark' ? 'bg-slate-800 text-slate-300' : 'bg-slate-100 text-slate-600')
              }`}>
                {autoPaper?.enabled ? 'Running' : 'Stopped'}
              </span>
            </div>
            <p className={`text-sm ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>
              ให้ระบบเปิด paper trade อัตโนมัติจาก institutional setup ของ `BTCUSD`, `ETHUSD`, `GOLD`, `EURUSD`
            </p>
            <div className={`text-xs font-medium space-y-1 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>
              <p>Last run: {autoPaper?.last_run_at ? new Date(autoPaper.last_run_at).toLocaleString() : 'never'}</p>
              <p>Error: {autoPaper?.last_error || 'none'}</p>
              <p>Opened last cycle: {autoPaper?.last_summary?.opened?.length || 0} | Skipped: {autoPaper?.last_summary?.skipped?.length || 0}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleAutoRun}
              disabled={runningAuto}
              className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                theme === 'dark'
                  ? 'bg-white/5 border border-white/10 text-white hover:bg-white/10'
                  : 'bg-slate-900 text-white hover:bg-slate-800'
              } disabled:opacity-50`}
            >
              {runningAuto ? 'Running...' : 'Run Once'}
            </button>
            <button
              onClick={() => {
                const nextForm = { ...autoForm, enabled: !autoForm.enabled };
                setAutoForm(nextForm);
                void saveAutoConfig(nextForm);
              }}
              disabled={savingAuto}
              className={`px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                autoForm.enabled
                  ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  : 'bg-violet-600 hover:bg-violet-500 text-white'
              } disabled:opacity-50`}
            >
              {autoForm.enabled ? 'Stop Auto' : 'Start Auto'}
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-5">
          <div>
            <label className={`block text-[10px] font-black uppercase tracking-widest mb-2 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>Confidence</label>
            <input value={autoForm.confidence_threshold} onChange={(e) => setAutoForm((prev) => ({ ...prev, confidence_threshold: e.target.value }))} className={`w-full px-3 py-2 rounded-xl border text-sm font-bold ${theme === 'dark' ? 'bg-slate-950 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900'}`} />
          </div>
          <div>
            <label className={`block text-[10px] font-black uppercase tracking-widest mb-2 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>Volume</label>
            <input value={autoForm.volume} onChange={(e) => setAutoForm((prev) => ({ ...prev, volume: e.target.value }))} className={`w-full px-3 py-2 rounded-xl border text-sm font-bold ${theme === 'dark' ? 'bg-slate-950 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900'}`} />
          </div>
          <div>
            <label className={`block text-[10px] font-black uppercase tracking-widest mb-2 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>Cooldown Min</label>
            <input value={autoForm.cooldown_minutes} onChange={(e) => setAutoForm((prev) => ({ ...prev, cooldown_minutes: e.target.value }))} className={`w-full px-3 py-2 rounded-xl border text-sm font-bold ${theme === 'dark' ? 'bg-slate-950 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900'}`} />
          </div>
          <div>
            <label className={`block text-[10px] font-black uppercase tracking-widest mb-2 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>Max Open</label>
            <input value={autoForm.max_open_positions} onChange={(e) => setAutoForm((prev) => ({ ...prev, max_open_positions: e.target.value }))} className={`w-full px-3 py-2 rounded-xl border text-sm font-bold ${theme === 'dark' ? 'bg-slate-950 border-white/10 text-white' : 'bg-white border-slate-200 text-slate-900'}`} />
          </div>
        </div>

        <div className="mt-4">
          <p className={`text-[10px] font-black uppercase tracking-widest mb-2 ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>Core Symbols</p>
          <div className="flex flex-wrap gap-2">
            {AUTO_SYMBOLS.map((symbol) => {
              const active = autoForm.symbols.includes(symbol);
              return (
                <button
                  key={symbol}
                  type="button"
                  onClick={() => setAutoForm((prev) => ({
                    ...prev,
                    symbols: active ? prev.symbols.filter((item) => item !== symbol) : [...prev.symbols, symbol],
                  }))}
                  className={`px-3 py-2 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
                    active
                      ? (theme === 'dark' ? 'bg-violet-500/20 border-violet-400/30 text-violet-200' : 'bg-violet-50 border-violet-200 text-violet-700')
                      : (theme === 'dark' ? 'bg-slate-900 border-white/10 text-slate-400' : 'bg-white border-slate-200 text-slate-500')
                  }`}
                >
                  {symbol}
                </button>
              );
            })}
          </div>
        </div>

        <div className="mt-4 flex justify-end">
          <button
            onClick={handleAutoSave}
            disabled={savingAuto}
            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-black uppercase tracking-widest transition-all disabled:opacity-50"
          >
            {savingAuto ? 'Saving...' : 'Save Auto Config'}
          </button>
        </div>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-xl flex items-center justify-center border transition-all ${
              theme === 'dark' ? 'bg-blue-600/20 border-blue-500/30' : 'bg-blue-50 border-blue-200'
            }`}>
              <FlaskConical className={`w-4 h-4 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
            </div>
            <h1 className={`text-2xl font-black tracking-tighter transition-colors ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>Paper Trading</h1>
          </div>
          <p className="text-sm text-slate-500 font-medium mt-1 ml-11">Simulate trades with zero risk — track performance in real-time</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={load} className={`p-2 rounded-xl transition-all border ${
            theme === 'dark' ? 'text-slate-500 hover:text-white bg-slate-900/50 border-white/5' : 'text-slate-400 hover:text-slate-900 bg-white border-slate-200 shadow-sm'
          }`}>
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button onClick={() => setShowForm(o => !o)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-black text-xs uppercase tracking-widest rounded-xl transition-all shadow-lg shadow-blue-600/20">
            <Plus className="w-4 h-4" /> New Trade
          </button>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<Target className={`w-4 h-4 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />}  label="Open Positions" value={String(stats.open)} color="blue" theme={theme} />
        <StatCard
          icon={<DollarSign className={`w-4 h-4 ${stats.totalPnl >= 0 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`} />}
          label="Total P&L" value={`${stats.totalPnl >= 0 ? '+' : ''}$${stats.totalPnl.toFixed(2)}`}
          color={stats.totalPnl >= 0 ? 'emerald' : 'rose'}
          theme={theme}
        />
        <StatCard icon={<BarChart3 className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />} label="Win Rate" value={`${stats.winRate}%`} color="indigo" theme={theme} />
        <StatCard icon={<TrendingUp className={`w-4 h-4 ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`} />} label="Wins / Losses" value={`${stats.wins}W / ${stats.losses}L`} color="amber" theme={theme} />
      </div>

      {/* Performance Analytics Panel */}
      {perf && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className={`border rounded-2xl p-6 space-y-5 transition-all duration-500 ${
            theme === 'dark' ? 'bg-[#0a0f1d]/60 border-white/8' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
          }`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
              <span className={`text-xs font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Performance Analytics</span>
            </div>
            <div className={`flex items-center gap-1.5 px-3 py-1 rounded-xl border text-[10px] font-black uppercase tracking-widest ${
              perf.winRate >= 70 
                ? (theme === 'dark' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' : 'border-emerald-200 bg-emerald-50 text-emerald-700')
                : perf.winRate >= 55 
                ? (theme === 'dark' ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-400' : 'border-indigo-200 bg-indigo-50 text-indigo-700')
                : perf.winRate >= 45 
                ? (theme === 'dark' ? 'border-amber-500/30 bg-amber-500/10 text-amber-400' : 'border-amber-200 bg-amber-50 text-amber-700')
                : (theme === 'dark' ? 'border-rose-500/30 bg-rose-500/10 text-rose-400' : 'border-rose-200 bg-rose-50 text-rose-700')
            }`}>
              {perf.winRate >= 70 ? <Award className="w-3 h-3" /> : <ShieldCheck className="w-3 h-3" />}
              {perf.grade}
            </div>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div className={`rounded-xl p-4 space-y-1 ${theme === 'dark' ? 'bg-black/20' : 'bg-slate-50 border border-slate-100'}`}>
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Win Rate</p>
              <p className={`text-2xl font-black tabular-nums font-mono ${
                perf.winRate >= 60 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : 
                perf.winRate >= 45 ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600') : 
                (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
              }`}>
                {perf.winRate.toFixed(1)}%
              </p>
              <p className="text-[10px] text-slate-600 font-bold">{perf.totalTrades} closed trades</p>
            </div>
            <div className={`rounded-xl p-4 space-y-1 ${theme === 'dark' ? 'bg-black/20' : 'bg-slate-50 border border-slate-100'}`}>
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Profit Factor</p>
              <p className={`text-2xl font-black tabular-nums font-mono ${
                perf.profitFactor >= 1.5 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : 
                perf.profitFactor >= 1 ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600') : 
                (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
              }`}>
                {perf.profitFactor >= 999 ? '∞' : perf.profitFactor.toFixed(2)}x
              </p>
              <p className="text-[10px] text-slate-600 font-bold">gross win / gross loss</p>
            </div>
            <div className={`rounded-xl p-4 space-y-1 ${theme === 'dark' ? 'bg-black/20' : 'bg-slate-50 border border-slate-100'}`}>
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Avg RR Ratio</p>
              <p className={`text-2xl font-black tabular-nums font-mono ${
                perf.rr >= 1.5 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : 
                perf.rr >= 1 ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600') : 
                (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')
              }`}>
                {perf.rr.toFixed(2)}R
              </p>
              <p className="text-[10px] text-slate-600 font-bold">avg win / avg loss</p>
            </div>
            <div className={`rounded-xl p-4 space-y-1 transition-all ${theme === 'dark' ? 'bg-black/20' : 'bg-slate-50 border border-slate-200'}`}>
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Max Drawdown</p>
              <p className={`text-2xl font-black tabular-nums font-mono ${theme === 'dark' ? 'text-rose-400' : 'text-rose-600'}`}>
                -${perf.maxDd.toFixed(2)}
              </p>
              <p className="text-[10px] text-slate-500 font-bold">peak-to-trough loss</p>
            </div>
          </div>

          {/* Equity Curve */}
          {perf.curve.length >= 2 && (
            <div className="space-y-2">
              <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest flex items-center gap-2">
                <Zap className="w-3 h-3" /> Equity Curve
              </p>
              <MiniEquityCurve data={perf.curve} theme={theme} />
            </div>
          )}
        </motion.div>
      )}

      {/* Unrealized P&L banner */}
      {openTrades.length > 0 && (
        <div className={`p-4 rounded-2xl border flex items-center justify-between transition-all ${
          unrealizedPnl >= 0 
            ? (theme === 'dark' ? 'bg-emerald-500/5 border-emerald-500/15' : 'bg-emerald-50 border-emerald-200 shadow-sm')
            : (theme === 'dark' ? 'bg-rose-500/5 border-rose-500/15' : 'bg-rose-50 border-rose-200 shadow-sm')
        }`}>
          <div className="flex items-center gap-3">
            {unrealizedPnl >= 0 
              ? <TrendingUp className={`w-4 h-4 ${theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'}`} /> 
              : <TrendingDown className={`w-4 h-4 ${theme === 'dark' ? 'text-rose-400' : 'text-rose-600'}`} />}
            <span className={`text-sm font-black ${theme === 'dark' ? 'text-slate-300' : 'text-slate-700'}`}>Unrealized P&L (open positions)</span>
          </div>
          <span className={`text-lg font-black ${unrealizedPnl >= 0 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`}>
            {unrealizedPnl >= 0 ? '+' : ''}${unrealizedPnl.toFixed(2)}
          </span>
        </div>
      )}

      {/* New Trade Form */}
      <AnimatePresence>
        {showForm && (
          <motion.form
            initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}
            onSubmit={handleOpen}
            className={`border rounded-2xl p-6 overflow-hidden transition-all ${
              theme === 'dark' ? 'bg-slate-900/50 border-blue-500/20' : 'bg-white border-blue-200 shadow-xl'
            }`}
          >
            <div className="flex items-center justify-between mb-5">
              <h3 className={`text-sm font-black uppercase tracking-widest ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Open Paper Trade</h3>
              <button type="button" onClick={() => setShowForm(false)} className="text-slate-500 hover:text-white transition-colors">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Symbol */}
              <div>
                <label className={`field-label text-[10px] font-black uppercase tracking-widest mb-1.5 block ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>Symbol</label>
                <input type="text" value={form.symbol}
                  onChange={e => setForm(f => ({ ...f, symbol: e.target.value.toUpperCase() }))}
                  placeholder="BTC"
                  className={`w-full border rounded-xl px-3 py-2.5 text-sm font-black focus:outline-none focus:ring-2 focus:ring-blue-500/30 uppercase transition-all ${
                    theme === 'dark' ? 'bg-slate-950/60 border-white/8 text-white' : 'bg-slate-50 border-slate-200 text-slate-900'
                  }`}
                />
                <div className="flex flex-wrap gap-1 mt-2">
                  {POPULAR_SYMBOLS.slice(0, 4).map(s => (
                    <button key={s} type="button" onClick={() => setForm(f => ({ ...f, symbol: s }))}
                      className={`px-2 py-0.5 rounded-lg text-[10px] font-black uppercase border transition-all ${
                        form.symbol === s 
                          ? (theme === 'dark' ? 'border-blue-500/40 text-blue-400 bg-blue-500/10' : 'border-blue-300 text-blue-600 bg-blue-50')
                          : (theme === 'dark' ? 'border-white/8 text-slate-600 hover:text-slate-400' : 'border-slate-200 text-slate-400 hover:text-slate-600')
                      }`}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>

              {/* Side */}
              <div>
                <label className={`field-label text-[10px] font-black uppercase tracking-widest mb-1.5 block ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>Direction</label>
                <div className="flex gap-2 mt-1.5">
                  {(['BUY', 'SELL'] as const).map(side => (
                    <button key={side} type="button"
                      onClick={() => setForm(f => ({ ...f, side }))}
                      className={`flex-1 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
                        form.side === side
                          ? side === 'BUY'
                            ? (theme === 'dark' ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400' : 'bg-emerald-50 border-emerald-500 text-emerald-700 shadow-sm shadow-emerald-500/10')
                            : (theme === 'dark' ? 'bg-rose-500/20 border-rose-500/40 text-rose-400' : 'bg-rose-50 border-rose-500 text-rose-700 shadow-sm shadow-rose-500/10')
                          : (theme === 'dark' ? 'border-white/8 text-slate-500 hover:border-white/20 hover:text-slate-300' : 'border-slate-200 text-slate-400 hover:border-slate-300 bg-slate-50/50')
                      }`}>
                      {side === 'BUY' ? '▲ Long' : '▼ Short'}
                    </button>
                  ))}
                </div>
              </div>

              {/* Volume */}
              <div>
                <label className={`field-label text-[10px] font-black uppercase tracking-widest mb-1.5 block ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>Volume / Qty</label>
                <input type="number" min="0.001" step="0.001" value={form.volume}
                  onChange={e => setForm(f => ({ ...f, volume: e.target.value }))}
                  className={`w-full border rounded-xl px-3 py-2.5 text-sm font-black focus:outline-none focus:ring-2 focus:ring-blue-500/30 transition-all ${
                    theme === 'dark' ? 'bg-slate-950/60 border-white/8 text-white' : 'bg-slate-50 border-slate-200 text-slate-900'
                  }`}
                />
              </div>

              {/* Entry Price (optional) */}
              <div>
                <label className={`field-label text-[10px] font-black uppercase tracking-widest mb-1.5 block ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>Entry Price <span className="text-slate-600 normal-case">(optional)</span></label>
                <input type="number" min="0" step="any" value={form.price}
                  onChange={e => setForm(f => ({ ...f, price: e.target.value }))}
                  placeholder="Auto (live price)"
                  className={`w-full border rounded-xl px-3 py-2.5 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500/30 transition-all ${
                    theme === 'dark' ? 'bg-slate-950/60 border-white/8 text-white placeholder:text-slate-600' : 'bg-slate-50 border-slate-200 text-slate-900 placeholder:text-slate-400'
                  }`}
                />
              </div>
            </div>

            <div className="mt-5 flex justify-end">
              <button type="submit" disabled={opening}
                className={`flex items-center gap-2 px-6 py-3 rounded-xl font-black text-xs uppercase tracking-widest transition-all shadow-lg ${
                  form.side === 'BUY'
                    ? 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-600/20'
                    : 'bg-rose-600 hover:bg-rose-500 shadow-rose-600/20'
                } text-white disabled:opacity-50`}>
                {opening
                  ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
                  : <>{form.side === 'BUY' ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />} Open {form.side}</>}
              </button>
            </div>
          </motion.form>
        )}
      </AnimatePresence>

      {/* Tabs */}
      <div className="flex items-center justify-between">
        <div className={`flex p-1 border rounded-xl w-fit gap-0.5 transition-all ${
          theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-slate-100 border-slate-200'
        }`}>
          {(['open', 'history'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-5 py-2 text-xs font-black uppercase tracking-widest rounded-lg transition-all ${
                tab === t 
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/30' 
                  : (theme === 'dark' ? 'text-slate-500 hover:text-slate-300' : 'text-slate-500 hover:text-slate-700')
              }`}>
              {t === 'open' ? `Open (${stats.open})` : `History (${closedTrades.length})`}
            </button>
          ))}
        </div>
        {closedTrades.length > 0 && (
          <button onClick={handleReset} disabled={resetting}
            className={`flex items-center gap-1.5 px-3 py-1.5 text-[10px] font-black uppercase tracking-widest transition-all border rounded-xl ${
              theme === 'dark' 
                ? 'text-slate-600 hover:text-rose-400 border-white/5 hover:border-rose-500/20' 
                : 'text-slate-400 hover:text-rose-600 border-slate-200 hover:border-rose-300 hover:bg-rose-50'
            }`}>
            <Trash2 className="w-3 h-3" /> Reset All
          </button>
        )}
      </div>

      {/* Trade Tables */}
      {tab === 'open' ? (
        <div className={`border rounded-2xl overflow-hidden transition-all duration-500 ${
          theme === 'dark' ? 'bg-[#0a0f1d]/60 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
        }`}>
          {openTrades.length === 0 ? (
            <div className="py-16 text-center">
              <FlaskConical className={`w-8 h-8 mx-auto mb-3 ${theme === 'dark' ? 'text-slate-700' : 'text-slate-200'}`} />
              <p className={`font-bold text-sm ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>No open paper trades</p>
              <p className={`text-xs font-medium mt-1 ${theme === 'dark' ? 'text-slate-700' : 'text-slate-300'}`}>Click "New Trade" to start simulating</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className={`border-b ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                    {['Symbol', 'Side', 'Volume', 'Entry', 'Current', 'Unr. P&L', 'Opened', 'Action'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-[10px] font-black text-slate-500 uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {openTrades.map(t => {
                    const dir = t.side === 'BUY' ? 1 : -1;
                    const unr = dir * (t.current_price - t.entry_price) * t.volume;
                    const pct = t.entry_price ? (unr / (t.entry_price * t.volume)) * 100 : 0;
                    return (
                      <tr key={t.id} className={`border-b transition-colors ${
                        theme === 'dark' ? 'border-white/3 hover:bg-white/2' : 'border-slate-50 hover:bg-slate-50'
                      }`}>
                        <td className={`px-4 py-3 font-black text-sm ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{t.symbol}</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-lg text-[10px] font-black uppercase ${
                            t.side === 'BUY' 
                              ? (theme === 'dark' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-50 text-emerald-600') 
                              : (theme === 'dark' ? 'bg-rose-500/10 text-rose-400' : 'bg-rose-50 text-rose-600')
                          }`}>
                            {t.side === 'BUY' ? '▲ Long' : '▼ Short'}
                          </span>
                        </td>
                        <td className={`px-4 py-3 font-bold text-sm font-mono ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>{t.volume}</td>
                        <td className={`px-4 py-3 font-bold text-sm font-mono ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>${t.entry_price.toLocaleString()}</td>
                        <td className={`px-4 py-3 font-bold text-sm font-mono ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>${t.current_price.toLocaleString()}</td>
                        <td className="px-4 py-3">
                          <div className={`font-black text-sm font-mono ${unr >= 0 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`}>
                            {unr >= 0 ? '+' : ''}{unr.toFixed(2)}
                          </div>
                          <div className={`text-[10px] font-bold ${unr >= 0 ? (theme === 'dark' ? 'text-emerald-500/70' : 'text-emerald-500') : (theme === 'dark' ? 'text-rose-500/70' : 'text-rose-500')}`}>
                            {pct >= 0 ? '+' : ''}{pct.toFixed(2)}%
                          </div>
                        </td>
                        <td className={`px-4 py-3 text-xs font-medium ${theme === 'dark' ? 'text-slate-600' : 'text-slate-400'}`}>
                          {new Date(t.opened_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3">
                          <button onClick={() => handleClose(t.id)} disabled={closing === t.id}
                            className="px-3 py-1.5 bg-rose-600/80 hover:bg-rose-600 text-white text-[10px] font-black uppercase tracking-widest rounded-lg transition-all disabled:opacity-50 shadow-sm shadow-rose-600/20">
                            {closing === t.id
                              ? <span className="animate-spin w-3 h-3 border border-white/30 border-t-white rounded-full inline-block" />
                              : 'Close'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        <div className={`border rounded-2xl overflow-hidden transition-all duration-500 ${
          theme === 'dark' ? 'bg-[#0a0f1d]/60 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
        }`}>
          {closedTrades.length === 0 ? (
            <div className="py-16 text-center">
              <BarChart3 className={`w-8 h-8 mx-auto mb-3 ${theme === 'dark' ? 'text-slate-700' : 'text-slate-200'}`} />
              <p className={`font-bold text-sm ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>No closed trades yet</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className={`border-b ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                    {['Symbol', 'Side', 'Volume', 'Entry', 'Exit', 'P&L', 'ML Score', 'Result', 'Closed'].map(h => (
                      <th key={h} className="px-4 py-3 text-left text-[10px] font-black text-slate-500 uppercase tracking-widest">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                    {closedTrades.map(t => (
                      <tr key={t.id} className={`border-b transition-colors ${
                        theme === 'dark' ? 'border-white/3 hover:bg-white/2' : 'border-slate-50 hover:bg-slate-100/50'
                      }`}>
                        <td className={`px-4 py-3 font-black text-sm ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{t.symbol}</td>
                        <td className="px-4 py-3">
                          <span className={`px-2 py-0.5 rounded-lg text-[10px] font-black uppercase ${
                            t.side === 'BUY' 
                              ? (theme === 'dark' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-600 text-white shadow-sm shadow-emerald-500/10') 
                              : (theme === 'dark' ? 'bg-rose-500/10 text-rose-400' : 'bg-rose-600 text-white shadow-sm shadow-rose-500/10')
                          }`}>
                            {t.side === 'BUY' ? '▲ Long' : '▼ Short'}
                          </span>
                        </td>
                      <td className={`px-4 py-3 font-bold text-sm font-mono ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>{t.volume}</td>
                      <td className={`px-4 py-3 font-bold text-sm font-mono ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>${t.entry_price.toLocaleString()}</td>
                      <td className={`px-4 py-3 font-bold text-sm font-mono ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>${t.current_price.toLocaleString()}</td>
                      <td className={`px-4 py-3 font-black text-sm font-mono ${t.pnl_usd >= 0 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : (theme === 'dark' ? 'text-rose-400' : 'text-rose-600')}`}>
                        {t.pnl_usd >= 0 ? '+' : ''}${t.pnl_usd.toFixed(2)}
                      </td>
                      <td className="px-4 py-3">
                        {t.ml_score != null ? (
                          <div className="flex items-center gap-1.5">
                            <Brain className={`w-3 h-3 shrink-0 ${
                              t.ml_score >= 65 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : 
                              t.ml_score >= 50 ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600') : 
                              (theme === 'dark' ? 'text-red-400' : 'text-red-600')
                            }`} />
                            <span className={`font-black text-sm tabular-nums font-mono ${
                              t.ml_score >= 65 ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : 
                              t.ml_score >= 50 ? (theme === 'dark' ? 'text-amber-400' : 'text-amber-600') : 
                              (theme === 'dark' ? 'text-red-400' : 'text-red-600')
                            }`}>
                              {t.ml_score.toFixed(0)}%
                            </span>
                          </div>
                        ) : (
                          <span className={`${theme === 'dark' ? 'text-slate-700' : 'text-slate-300'} text-xs`}>—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`px-2 py-0.5 rounded-lg text-[10px] font-black uppercase ${
                          t.outcome === 'WIN' || t.pnl_usd > 0 
                            ? (theme === 'dark' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-emerald-50 text-emerald-600') 
                            : (theme === 'dark' ? 'bg-rose-500/10 text-rose-400' : 'bg-rose-50 text-rose-600')
                        }`}>
                          {t.outcome || (t.pnl_usd >= 0 ? 'WIN' : 'LOSS')}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-xs font-medium ${theme === 'dark' ? 'text-slate-600' : 'text-slate-400'}`}>
                        {t.closed_at ? new Date(t.closed_at).toLocaleDateString() : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const StatCard = ({ icon, label, value, color, theme }: { icon: React.ReactNode; label: string; value: string; color: string; theme?: string }) => {
  const colors: Record<string, string> = {
    blue:    theme === 'dark' ? 'border-blue-500/15 bg-blue-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40',
    emerald: theme === 'dark' ? 'border-emerald-500/15 bg-emerald-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40',
    rose:    theme === 'dark' ? 'border-rose-500/15 bg-rose-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40',
    indigo:  theme === 'dark' ? 'border-indigo-500/15 bg-indigo-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40',
    amber:   theme === 'dark' ? 'border-amber-500/15 bg-amber-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40',
  };
  return (
    <div className={`p-4 rounded-2xl border transition-all ${colors[color] || colors.blue}`}>
      <div className="flex items-center gap-2 mb-2">{icon}<span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">{label}</span></div>
      <p className={`text-xl font-black tabular-nums transition-colors ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{value}</p>
    </div>
  );
};

// Equity curve SVG sparkline
const MiniEquityCurve = ({ data, theme }: { data: number[]; theme?: string }) => {
  const W = 600, H = 80, PAD = 4;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = PAD + (i / (data.length - 1)) * (W - PAD * 2);
    const y = H - PAD - ((v - min) / range) * (H - PAD * 2);
    return `${x},${y}`;
  }).join(' ');
  const lastY = H - PAD - ((data[data.length - 1] - min) / range) * (H - PAD * 2);
  const isPos = data[data.length - 1] >= data[0];
  const color = isPos ? '#10b981' : '#f43f5e';
  const fillId = isPos ? 'eqGreen' : 'eqRed';
  const fillColor = isPos ? '#10b981' : '#f43f5e';
  // Zero line
  const zeroY = min < 0 && max > 0 ? H - PAD - ((0 - min) / range) * (H - PAD * 2) : null;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className={`w-full h-16 rounded-xl overflow-hidden ${theme === 'light' ? 'bg-slate-50' : ''}`} preserveAspectRatio="none">
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={fillColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={fillColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      {zeroY !== null && (
        <line x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY} stroke={theme === 'dark' ? "#ffffff10" : "#00000010"} strokeWidth="1" strokeDasharray="4 4" />
      )}
      {/* Area fill */}
      <polyline
        points={`${PAD},${H - PAD} ${pts} ${W - PAD},${H - PAD}`}
        fill={`url(#${fillId})`}
        stroke="none"
      />
      {/* Line */}
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      {/* End dot */}
      <circle cx={W - PAD} cy={lastY} r="4" fill={color} />
    </svg>
  );
};
