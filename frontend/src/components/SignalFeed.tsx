import { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  Loader2,
  RefreshCw,
  Target,
  X,
  Eye,
  Minus,
  ShieldCheck,
  TrendingDown,
  TrendingUp,
  Zap,
} from 'lucide-react';

import { useMode } from '../contexts/ModeContext';
import type { WSMessage } from '../hooks/useWebSocket';

interface Signal {
  symbol: string;
  direction: 'BUY' | 'SELL' | 'HOLD' | 'WATCH';
  confidence: number;
  signal_grade?: 'A+' | 'A' | 'B' | 'C' | 'WATCH';
  actionable?: boolean;
  tradeable?: boolean;
  ml_win_pct?: number;
  timeframe?: string;
  reason: string;
  price: number;
  delta_pct: number;
  vol_surge: number;
  timestamp: string;
  feedback_ready?: {
    source_ready?: boolean;
    symbol_ready?: boolean;
  };
  feedback_notes?: string[];
}

interface AnalysisLevel {
  low?: number;
  high?: number;
  value?: number;
}

interface SignalAnalysis {
  symbol: string;
  timeframe: string;
  master_decision?: string;
  master_confidence?: number;
  master_reasoning?: string;
  master_report?: string;
  trend_report?: string;
  indicator_report?: string;
  sentiment_report?: string;
  decision_report?: string;
  confluence_score?: number;
  risk_reward?: number;
  entry_zone?: AnalysisLevel;
  stop_loss?: AnalysisLevel;
  take_profit?: AnalysisLevel;
}

type SignalFilter = 'all' | 'actionable' | 'tradeable';
type ActionToast = { type: 'ok' | 'err'; message: string } | null;

const getDirectionConfig = (dir: string, theme: 'light' | 'dark') => {
  const isDark = theme === 'dark';
  const configs: Record<string, Record<string, string | typeof TrendingUp>> = {
    BUY: {
      icon: TrendingUp,
      label: 'LONG',
      bg: isDark ? 'bg-emerald-500/10' : 'bg-emerald-50',
      border: isDark ? 'border-emerald-500/30' : 'border-emerald-200',
      text: isDark ? 'text-emerald-400' : 'text-emerald-600',
    },
    SELL: {
      icon: TrendingDown,
      label: 'SHORT',
      bg: isDark ? 'bg-rose-500/10' : 'bg-rose-50',
      border: isDark ? 'border-rose-500/30' : 'border-rose-200',
      text: isDark ? 'text-rose-400' : 'text-rose-600',
    },
    HOLD: {
      icon: Minus,
      label: 'HOLD',
      bg: isDark ? 'bg-amber-500/10' : 'bg-amber-50',
      border: isDark ? 'border-amber-500/30' : 'border-amber-200',
      text: isDark ? 'text-amber-400' : 'text-amber-600',
    },
    WATCH: {
      icon: Eye,
      label: 'WATCH',
      bg: isDark ? 'bg-blue-500/10' : 'bg-blue-50',
      border: isDark ? 'border-blue-500/30' : 'border-blue-200',
      text: isDark ? 'text-blue-400' : 'text-blue-600',
    },
  };
  return configs[dir] || configs.HOLD;
};

const gradeTone = (grade: string, tradeable: boolean, actionable: boolean) => {
  if (tradeable) return 'bg-emerald-500/15 text-emerald-400';
  if (actionable) return 'bg-amber-500/15 text-amber-400';
  if (grade === 'WATCH') return 'bg-blue-500/15 text-blue-400';
  return 'bg-slate-500/10 text-slate-400';
};

export const SignalFeed = ({
  bootstrapSignals = [],
  skipInitialFetch = false,
  wsLastMessage = null,
}: {
  bootstrapSignals?: Signal[];
  skipInitialFetch?: boolean;
  wsLastMessage?: WSMessage | null;
}) => {
  const { theme } = useMode();
  const lastMessage = wsLastMessage;
  const [signals, setSignals] = useState<Signal[]>(bootstrapSignals);
  const [filterMode, setFilterMode] = useState<SignalFilter>('actionable');
  const [loading, setLoading] = useState(bootstrapSignals.length === 0);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [analysis, setAnalysis] = useState<SignalAnalysis | null>(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<'paper' | 'alert' | null>(null);
  const [actionToast, setActionToast] = useState<ActionToast>(null);

  const showActionToast = (type: 'ok' | 'err', message: string) => {
    setActionToast({ type, message });
    window.setTimeout(() => {
      setActionToast((current) => (current?.message === message ? null : current));
    }, 2800);
  };

  const formatLevel = (level?: AnalysisLevel) => {
    if (!level) return 'N/A';
    if (typeof level.low === 'number' && typeof level.high === 'number') {
      return `$${level.low.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} - $${level.high.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    }
    if (typeof level.value === 'number') {
      return `$${level.value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
    }
    return 'N/A';
  };

  const resolveTradeSide = () => {
    const decision = (analysis?.master_decision || selectedSignal?.direction || '').toUpperCase();
    if (decision.includes('SELL') || decision.includes('SHORT')) return 'SELL';
    return 'BUY';
  };

  const resolveAlertTarget = () => {
    const side = resolveTradeSide();
    if (analysis?.entry_zone) {
      if (side === 'BUY') {
        return {
          condition: 'above' as const,
          price:
            analysis.entry_zone.high ??
            analysis.entry_zone.value ??
            selectedSignal?.price ??
            0,
        };
      }
      return {
        condition: 'below' as const,
        price:
          analysis.entry_zone.low ??
          analysis.entry_zone.value ??
          selectedSignal?.price ??
          0,
      };
    }
    return {
      condition: side === 'BUY' ? ('above' as const) : ('below' as const),
      price: selectedSignal?.price ?? 0,
    };
  };

  const fetchAnalysis = async (signal: Signal) => {
    setSelectedSignal(signal);
    setAnalysis(null);
    setAnalysisError(null);
    setAnalysisLoading(true);

    try {
      const response = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: signal.symbol.replace('USDT', ''),
          timeframe: signal.timeframe || '15m',
          include_charts: false,
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload?.detail || 'Unable to load analysis');
      }

      setAnalysis(payload);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unexpected analysis request error';
      setAnalysisError(message);
    } finally {
      setAnalysisLoading(false);
    }
  };

  const closeAnalysis = () => {
    setSelectedSignal(null);
    setAnalysis(null);
    setAnalysisError(null);
    setAnalysisLoading(false);
    setActionLoading(null);
    setActionToast(null);
  };

  const handleCreatePaperTrade = async () => {
    if (!selectedSignal) return;
    setActionLoading('paper');
    try {
      const side = resolveTradeSide();
      const entryPrice =
        analysis?.entry_zone?.value ??
        (side === 'BUY' ? analysis?.entry_zone?.high : analysis?.entry_zone?.low) ??
        selectedSignal.price;
      const stopLoss =
        analysis?.stop_loss?.value ??
        (side === 'BUY' ? analysis?.stop_loss?.low : analysis?.stop_loss?.high) ??
        null;
      const takeProfit =
        analysis?.take_profit?.value ??
        (side === 'BUY' ? analysis?.take_profit?.high : analysis?.take_profit?.low) ??
        null;
      const entryReasonParts = [
        `SignalFeed ${selectedSignal.direction}`,
        `grade ${selectedSignal.signal_grade || 'C'}`,
        `confidence ${selectedSignal.confidence}%`,
        analysis?.master_decision ? `master ${analysis.master_decision}` : null,
      ].filter(Boolean);

      const response = await fetch('/api/paper-trades', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': 'demo',
        },
        body: JSON.stringify({
          symbol: selectedSignal.symbol.replace('USDT', ''),
          side,
          volume: 0.01,
          price: entryPrice,
          stop_loss: stopLoss,
          take_profit: takeProfit,
          entry_source: 'signal_feed_analysis',
          entry_reason: entryReasonParts.join(' | '),
          ml_score: analysis?.master_confidence ?? selectedSignal.ml_win_pct ?? selectedSignal.confidence,
          signal_grade: selectedSignal.signal_grade || 'C',
          macro_bias: analysis?.master_decision || selectedSignal.direction,
          features: {
            signal_symbol: selectedSignal.symbol,
            signal_timeframe: selectedSignal.timeframe || '15m',
            signal_direction: selectedSignal.direction,
            signal_confidence: selectedSignal.confidence,
            signal_grade: selectedSignal.signal_grade || 'C',
            ml_win_pct: selectedSignal.ml_win_pct ?? null,
            confluence_score: analysis?.confluence_score ?? null,
            risk_reward: analysis?.risk_reward ?? null,
            master_decision: analysis?.master_decision ?? null,
            master_confidence: analysis?.master_confidence ?? null,
          },
        }),
      });

      const payload = await response.json();
      if (!response.ok || payload?.error) {
        throw new Error(payload?.detail || payload?.error || 'Unable to open paper trade');
      }

      showActionToast('ok', `Paper ${side} ${selectedSignal.symbol} opened`);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unexpected paper trade error';
      showActionToast('err', message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreateAlert = () => {
    if (!selectedSignal) return;
    setActionLoading('alert');
    const authKey = localStorage.getItem('crypto_terminal_key') || 'demo';

    void (async () => {
      try {
      const target = resolveAlertTarget();
      if (!target.price || target.price <= 0) {
        throw new Error('No valid alert price available');
      }

        const response = await fetch('/api/alerts', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': authKey,
          },
          body: JSON.stringify({
            symbol: selectedSignal.symbol,
            condition: target.condition,
            price: target.price,
            timeframe: selectedSignal.timeframe || '15m',
            entry_source: 'signal_feed_analysis',
            message: `Signal alert for ${selectedSignal.symbol} ${target.condition} $${target.price.toFixed(2)} from ${selectedSignal.signal_grade || 'C'} grade setup.`,
            meta: {
              signal_direction: selectedSignal.direction,
              signal_grade: selectedSignal.signal_grade || 'C',
              signal_confidence: selectedSignal.confidence,
              ml_win_pct: selectedSignal.ml_win_pct ?? null,
            },
          }),
        });

        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || 'Unable to save alert');
        }

        showActionToast(
          'ok',
          `Alert saved: ${selectedSignal.symbol} ${target.condition} $${target.price.toFixed(2)}`,
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unexpected alert error';
        showActionToast('err', message);
      } finally {
        setActionLoading(null);
      }
    })();
  };

  const filteredSignals = signals.filter((signal) => {
    if (filterMode === 'actionable') return Boolean(signal.actionable);
    if (filterMode === 'tradeable') return Boolean(signal.tradeable);
    return true;
  });

  const stats = {
    total: signals.length,
    actionable: signals.filter((signal) => signal.actionable).length,
    tradeable: signals.filter((signal) => signal.tradeable).length,
  };

  useEffect(() => {
    if (bootstrapSignals.length > 0) {
      setSignals(bootstrapSignals);
      setLastRefresh(new Date());
      setLoading(false);
      return;
    }
    if (skipInitialFetch) {
      setLoading(false);
      return;
    }
    fetch('/api/signals?limit=12')
      .then((r) => r.json())
      .then((json) => {
        if (json.signals?.length > 0) {
          setSignals(json.signals);
          setLastRefresh(new Date());
        }
      })
      .catch((err) => console.error('Signal initial fetch error:', err))
      .finally(() => setLoading(false));
  }, [bootstrapSignals, skipInitialFetch]);

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'SIGNALS') return;
    const incoming: Signal[] = lastMessage.data?.signals ?? [];
    if (incoming.length > 0) {
      setSignals(incoming);
      setLastRefresh(new Date());
      setLoading(false);
    }
  }, [lastMessage]);

  useEffect(() => {
    if (!selectedSignal) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeAnalysis();
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedSignal]);

  return (
    <div className="flex flex-col h-full space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          <h3
            className={`text-[11px] font-black uppercase tracking-[0.3em] transition-colors ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}
          >
            Neural Signal Stream
          </h3>
        </div>
        <div
          className={`px-3 py-1 rounded-full border text-[9px] font-black uppercase tracking-widest ${
            theme === 'dark'
              ? 'bg-white/5 border-white/5 text-slate-500'
              : 'bg-slate-50 border-slate-200 text-slate-400'
          }`}
        >
          {lastRefresh.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        {[
          { key: 'all', label: 'All', value: stats.total, icon: Zap },
          { key: 'actionable', label: 'Actionable', value: stats.actionable, icon: Eye },
          { key: 'tradeable', label: 'Tradeable', value: stats.tradeable, icon: ShieldCheck },
        ].map((item) => {
          const Icon = item.icon;
          const active = filterMode === item.key;
          return (
            <button
              key={item.key}
              onClick={() => setFilterMode(item.key as SignalFilter)}
              className={`flex items-center justify-between rounded-2xl border px-3 py-2 text-left transition-all ${
                active
                  ? theme === 'dark'
                    ? 'bg-blue-500/10 border-blue-500/30 text-blue-300'
                    : 'bg-blue-50 border-blue-200 text-blue-700'
                  : theme === 'dark'
                    ? 'bg-slate-900/40 border-white/5 text-slate-400'
                    : 'bg-white border-slate-200 text-slate-500'
              }`}
            >
              <div>
                <p className="text-[9px] font-black uppercase tracking-widest">{item.label}</p>
                <p className="mt-1 text-base font-black">{item.value}</p>
              </div>
              <Icon className="w-4 h-4" />
            </button>
          );
        })}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto custom-scrollbar pr-2">
        {loading ? (
          [1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className={`h-24 animate-pulse rounded-[1.5rem] border ${
                theme === 'dark'
                  ? 'bg-slate-900/40 border-white/5'
                  : 'bg-slate-50 border-slate-200'
              }`}
            />
          ))
        ) : filteredSignals.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
            <div
              className={`w-12 h-12 rounded-2xl flex items-center justify-center border ${
                theme === 'dark'
                  ? 'bg-white/5 border-white/5'
                  : 'bg-slate-50 border-slate-200'
              }`}
            >
              <Minus className="w-6 h-6 text-slate-700" />
            </div>
            <div className="space-y-1">
              <p className="text-[10px] text-slate-500 font-black uppercase tracking-widest">
                No Signals In View
              </p>
              <p className="text-[9px] text-slate-700 font-bold uppercase tracking-widest">
                Switch to a broader filter.
              </p>
            </div>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            {filteredSignals.map((signal, i) => {
              const cfg = getDirectionConfig(signal.direction, theme);
              const Icon = cfg.icon as typeof TrendingUp;
              const grade = signal.signal_grade || 'C';
              const feedbackNotes = signal.feedback_notes || [];
              const feedbackReady = signal.feedback_ready || {};
              const sourceReady = feedbackReady.source_ready;
              const symbolReady = feedbackReady.symbol_ready;
              return (
                <motion.button
                  key={signal.symbol + signal.timestamp}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.05 }}
                  onClick={() => void fetchAnalysis(signal)}
                  className={`p-4 rounded-[1.4rem] border backdrop-blur-2xl transition-all duration-500 group relative overflow-hidden ${
                    theme === 'dark'
                      ? 'bg-slate-900/40 border-white/5 hover:border-white/10'
                      : 'bg-white border-slate-200 shadow-sm hover:shadow-md'
                  } text-left w-full`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div
                        className={`p-1.5 rounded-lg border transition-all duration-500 ${cfg.bg} ${cfg.border}`}
                      >
                        <Icon className={`w-3.5 h-3.5 ${cfg.text}`} />
                      </div>
                      <div className="space-y-0">
                        <span
                          className={`text-sm font-black tracking-tighter italic uppercase ${
                            theme === 'dark' ? 'text-white' : 'text-slate-950'
                          }`}
                        >
                          {signal.symbol}
                        </span>
                        <div
                          className={`flex items-center gap-1 text-[7px] font-black uppercase tracking-widest ${cfg.text}`}
                        >
                          <div
                            className={`w-1 h-1 rounded-full bg-current ${
                              signal.direction !== 'HOLD' ? 'animate-pulse' : ''
                            }`}
                          />
                          {cfg.label}
                        </div>
                      </div>
                    </div>

                    <div className="text-right space-y-1">
                      <div
                        className={`inline-flex items-center rounded-full px-2 py-1 text-[8px] font-black uppercase tracking-[0.22em] ${gradeTone(
                          grade,
                          Boolean(signal.tradeable),
                          Boolean(signal.actionable),
                        )}`}
                      >
                        {grade}
                      </div>
                      <p className={`text-base font-black font-mono leading-none ${cfg.text}`}>
                        {signal.confidence}%
                      </p>
                      <p className="text-[7px] font-black text-slate-600 uppercase tracking-widest">
                        Conf
                      </p>
                    </div>
                  </div>

                  <p
                    className={`text-[9px] leading-relaxed font-bold mb-3 line-clamp-2 italic ${
                      theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
                    }`}
                  >
                    "{signal.reason}"
                  </p>

                  {(feedbackNotes.length > 0 || sourceReady !== undefined || symbolReady !== undefined) && (
                    <div className="mb-3 flex flex-wrap gap-1.5">
                      {feedbackNotes.map((note) => (
                        <span
                          key={note}
                          className={`rounded-full px-2 py-1 text-[7px] font-black uppercase tracking-widest ${
                            note.includes('tailwind') || note.includes('strength')
                              ? theme === 'dark'
                                ? 'bg-emerald-500/10 text-emerald-300'
                                : 'bg-emerald-50 text-emerald-700'
                              : theme === 'dark'
                                ? 'bg-amber-500/10 text-amber-300'
                                : 'bg-amber-50 text-amber-700'
                          }`}
                        >
                          {note}
                        </span>
                      ))}
                      {sourceReady !== undefined && (
                        <span
                          className={`rounded-full px-2 py-1 text-[7px] font-black uppercase tracking-widest ${
                            sourceReady
                              ? theme === 'dark'
                                ? 'bg-blue-500/10 text-blue-300'
                                : 'bg-blue-50 text-blue-700'
                              : theme === 'dark'
                                ? 'bg-rose-500/10 text-rose-300'
                                : 'bg-rose-50 text-rose-700'
                          }`}
                        >
                          Source {sourceReady ? 'ready' : 'guarded'}
                        </span>
                      )}
                      {symbolReady !== undefined && (
                        <span
                          className={`rounded-full px-2 py-1 text-[7px] font-black uppercase tracking-widest ${
                            symbolReady
                              ? theme === 'dark'
                                ? 'bg-indigo-500/10 text-indigo-300'
                                : 'bg-indigo-50 text-indigo-700'
                              : theme === 'dark'
                                ? 'bg-rose-500/10 text-rose-300'
                                : 'bg-rose-50 text-rose-700'
                          }`}
                        >
                          Symbol {symbolReady ? 'ready' : 'guarded'}
                        </span>
                      )}
                    </div>
                  )}

                  <div
                    className={`flex items-center justify-between pt-3 border-t ${
                      theme === 'dark' ? 'border-white/5' : 'border-slate-100'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`text-[9px] font-black font-mono ${
                          theme === 'dark' ? 'text-slate-200' : 'text-slate-900'
                        }`}
                      >
                        ${signal.price.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                      </span>
                      <span
                        className={`text-[9px] font-black font-mono ${
                          (signal.delta_pct ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'
                        }`}
                      >
                        {(signal.delta_pct ?? 0) >= 0 ? '+' : ''}
                        {(signal.delta_pct ?? 0).toFixed(3)}%
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <div
                        className={`px-1.5 py-0.5 rounded-lg text-[7px] font-black uppercase tracking-widest ${
                          theme === 'dark'
                            ? 'bg-white/5 text-slate-500'
                            : 'bg-slate-50 text-slate-400'
                        }`}
                      >
                        {(signal.timeframe || '15m').toUpperCase()}
                      </div>
                      <div
                        className={`px-1.5 py-0.5 rounded-lg text-[7px] font-black uppercase tracking-widest ${
                          theme === 'dark'
                            ? 'bg-white/5 text-slate-500'
                            : 'bg-slate-50 text-slate-400'
                        }`}
                      >
                        x{(signal.vol_surge ?? 1.0).toFixed(2)}
                      </div>
                      <div
                        className={`px-1.5 py-0.5 rounded-lg text-[7px] font-black uppercase tracking-widest ${
                          theme === 'dark'
                            ? 'bg-blue-500/10 text-blue-300'
                            : 'bg-blue-50 text-blue-600'
                        }`}
                      >
                        Edge {(signal.ml_win_pct ?? signal.confidence).toFixed(1)}%
                      </div>
                      <div
                        className={`px-1.5 py-0.5 rounded-lg text-[7px] font-black uppercase tracking-widest ${
                          theme === 'dark'
                            ? 'bg-white/5 text-slate-300'
                            : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        Analyze
                      </div>
                    </div>
                  </div>

                  <div className="absolute bottom-0 left-0 w-full h-[2px] bg-white/5 overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${signal.confidence}%` }}
                      className={`h-full ${
                        signal.direction === 'BUY'
                          ? 'bg-emerald-500'
                          : signal.direction === 'SELL'
                            ? 'bg-rose-500'
                            : signal.direction === 'HOLD'
                              ? 'bg-amber-500'
                              : 'bg-blue-500'
                      }`}
                    />
                  </div>
                </motion.button>
              );
            })}
          </AnimatePresence>
        )}
      </div>

      <AnimatePresence>
        {selectedSignal ? (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[1100] flex items-end justify-center bg-black/70 backdrop-blur-md p-3 sm:items-center sm:p-6"
          >
            <button className="absolute inset-0" onClick={closeAnalysis} aria-label="Close analysis" />
            <motion.div
              initial={{ opacity: 0, y: 24, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 24, scale: 0.98 }}
              transition={{ duration: 0.2 }}
              className={`relative z-10 w-full max-w-3xl overflow-hidden rounded-[1.75rem] border ${
                theme === 'dark'
                  ? 'border-white/10 bg-slate-950/95 text-white'
                  : 'border-slate-200 bg-white text-slate-900'
              } shadow-2xl`}
            >
              <div
                className={`flex items-start justify-between gap-4 border-b px-5 py-4 ${
                  theme === 'dark' ? 'border-white/10' : 'border-slate-200'
                }`}
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-lg font-black uppercase tracking-tight">
                      {selectedSignal.symbol}
                    </span>
                    <span
                      className={`rounded-full px-2 py-1 text-[9px] font-black uppercase tracking-[0.22em] ${gradeTone(
                        selectedSignal.signal_grade || 'C',
                        Boolean(selectedSignal.tradeable),
                        Boolean(selectedSignal.actionable),
                      )}`}
                    >
                      {selectedSignal.signal_grade || 'C'}
                    </span>
                  </div>
                  <p
                    className={`text-[10px] font-black uppercase tracking-[0.28em] ${
                      theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                    }`}
                  >
                    Full analysis for {(selectedSignal.timeframe || '15m').toUpperCase()}
                  </p>
                </div>

                <button
                  onClick={closeAnalysis}
                  className={`rounded-xl border p-2 transition-colors ${
                    theme === 'dark'
                      ? 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                      : 'border-slate-200 bg-slate-50 text-slate-600 hover:bg-slate-100'
                  }`}
                  aria-label="Close analysis"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <div className="max-h-[80vh] overflow-y-auto px-5 py-5">
                <div className="mb-5 flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => void handleCreatePaperTrade()}
                    disabled={actionLoading !== null}
                    className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-[10px] font-black uppercase tracking-[0.22em] transition-colors ${
                      theme === 'dark'
                        ? 'border-blue-400/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/15 disabled:opacity-50'
                        : 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 disabled:opacity-50'
                    }`}
                  >
                    {actionLoading === 'paper' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Target className="h-3.5 w-3.5" />
                    )}
                    Paper Trade
                  </button>
                  <button
                    onClick={handleCreateAlert}
                    disabled={actionLoading !== null}
                    className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-[10px] font-black uppercase tracking-[0.22em] transition-colors ${
                      theme === 'dark'
                        ? 'border-amber-400/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/15 disabled:opacity-50'
                        : 'border-amber-200 bg-amber-50 text-amber-700 hover:bg-amber-100 disabled:opacity-50'
                    }`}
                  >
                    {actionLoading === 'alert' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <AlertTriangle className="h-3.5 w-3.5" />
                    )}
                    Set Alert
                  </button>
                  {actionToast ? (
                    <div
                      className={`rounded-xl border px-3 py-2 text-[10px] font-bold uppercase tracking-[0.18em] ${
                        actionToast.type === 'ok'
                          ? theme === 'dark'
                            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                            : 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : theme === 'dark'
                            ? 'border-rose-500/30 bg-rose-500/10 text-rose-300'
                            : 'border-rose-200 bg-rose-50 text-rose-700'
                      }`}
                    >
                      {actionToast.message}
                    </div>
                  ) : null}
                </div>

                {analysisLoading ? (
                  <div className="flex min-h-[280px] flex-col items-center justify-center gap-4 text-center">
                    <Loader2 className="h-8 w-8 animate-spin text-blue-500" />
                    <div className="space-y-1">
                      <p className="text-sm font-black uppercase tracking-[0.22em]">
                        Building analysis
                      </p>
                      <p
                        className={`text-xs font-bold uppercase tracking-[0.18em] ${
                          theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                        }`}
                      >
                        Running the multi-agent read on this setup.
                      </p>
                    </div>
                  </div>
                ) : analysisError ? (
                  <div className="flex min-h-[280px] flex-col items-center justify-center gap-4 text-center">
                    <AlertTriangle className="h-8 w-8 text-amber-500" />
                    <div className="space-y-2">
                      <p className="text-sm font-black uppercase tracking-[0.22em]">
                        Analysis unavailable
                      </p>
                      <p
                        className={`max-w-lg text-sm ${
                          theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
                        }`}
                      >
                        {analysisError}
                      </p>
                    </div>
                    <button
                      onClick={() => void fetchAnalysis(selectedSignal)}
                      className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-[10px] font-black uppercase tracking-[0.22em] ${
                        theme === 'dark'
                          ? 'border-white/10 bg-white/5 text-slate-200 hover:bg-white/10'
                          : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100'
                      }`}
                    >
                      <RefreshCw className="h-3.5 w-3.5" />
                      Retry
                    </button>
                  </div>
                ) : analysis ? (
                  <div className="space-y-5">
                    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                      {[
                        {
                          label: 'Decision',
                          value: analysis.master_decision || selectedSignal.direction,
                        },
                        {
                          label: 'Confidence',
                          value: `${analysis.master_confidence ?? selectedSignal.confidence}%`,
                        },
                        {
                          label: 'Confluence',
                          value: `${analysis.confluence_score ?? 0}`,
                        },
                        {
                          label: 'Risk / Reward',
                          value:
                            typeof analysis.risk_reward === 'number'
                              ? analysis.risk_reward.toFixed(2)
                              : 'N/A',
                        },
                      ].map((item) => (
                        <div
                          key={item.label}
                          className={`rounded-2xl border px-4 py-3 ${
                            theme === 'dark'
                              ? 'border-white/10 bg-white/5'
                              : 'border-slate-200 bg-slate-50'
                          }`}
                        >
                          <p
                            className={`text-[9px] font-black uppercase tracking-[0.22em] ${
                              theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                            }`}
                          >
                            {item.label}
                          </p>
                          <p className="mt-2 text-sm font-black uppercase tracking-wide">
                            {item.value}
                          </p>
                        </div>
                      ))}
                    </div>

                    <div className="grid gap-3 sm:grid-cols-3">
                      {[
                        { label: 'Entry Zone', value: formatLevel(analysis.entry_zone), icon: Target },
                        {
                          label: 'Stop Loss',
                          value: formatLevel(analysis.stop_loss),
                          icon: ShieldCheck,
                        },
                        {
                          label: 'Take Profit',
                          value: formatLevel(analysis.take_profit),
                          icon: TrendingUp,
                        },
                      ].map((item) => {
                        const Icon = item.icon;
                        return (
                          <div
                            key={item.label}
                            className={`rounded-2xl border px-4 py-4 ${
                              theme === 'dark'
                                ? 'border-white/10 bg-slate-900/60'
                                : 'border-slate-200 bg-white'
                            }`}
                          >
                            <div className="flex items-center gap-2">
                              <Icon className="h-4 w-4 text-blue-500" />
                              <p
                                className={`text-[9px] font-black uppercase tracking-[0.22em] ${
                                  theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                                }`}
                              >
                                {item.label}
                              </p>
                            </div>
                            <p className="mt-3 text-sm font-black">{item.value}</p>
                          </div>
                        );
                      })}
                    </div>

                    <div className="grid gap-3 lg:grid-cols-2">
                      {[
                        {
                          title: 'Master Reasoning',
                          body: analysis.master_reasoning || analysis.master_report,
                        },
                        {
                          title: 'Decision Notes',
                          body: analysis.decision_report || analysis.trend_report,
                        },
                        {
                          title: 'Indicator Read',
                          body: analysis.indicator_report,
                        },
                        {
                          title: 'Sentiment',
                          body: analysis.sentiment_report,
                        },
                      ]
                        .filter((section) => section.body)
                        .map((section) => (
                          <div
                            key={section.title}
                            className={`rounded-2xl border px-4 py-4 ${
                              theme === 'dark'
                                ? 'border-white/10 bg-white/[0.03]'
                                : 'border-slate-200 bg-slate-50'
                            }`}
                          >
                            <p
                              className={`text-[9px] font-black uppercase tracking-[0.22em] ${
                                theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                              }`}
                            >
                              {section.title}
                            </p>
                            <p
                              className={`mt-3 whitespace-pre-wrap text-sm leading-6 ${
                                theme === 'dark' ? 'text-slate-200' : 'text-slate-700'
                              }`}
                            >
                              {section.body}
                            </p>
                          </div>
                        ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
};
