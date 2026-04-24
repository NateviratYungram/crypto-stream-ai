import React, { useEffect, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronRight, Copy, RefreshCw, Shield, Star, Target, TrendingDown, TrendingUp, Zap } from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';
import { useMode } from '../contexts/ModeContext';

interface AuditLog {
  id: number;
  symbol: string;
  confidence: number;
  reasoning: string;
  price: number;
  timestamp: string;
  recommendation?: string;
}

interface Tactic {
  name: string;
  style: string;
  score: number;
  move: string;
  trigger: string;
  invalidation: string;
  tp: string;
  logic: string;
}

interface TacticsData {
  symbol: string;
  price: number;
  recommendation: string;
  best_persona: string;
  tactics: Tactic[];
  timestamp: number;
  v7_status?: {
    active: boolean;
    sniper_mode: boolean;
    sniper_locked: boolean;
    lock_reason: string | null;
    institutional_flow: {
      bullish_sweep?: { active?: boolean } | null;
      bearish_sweep?: { active?: boolean } | null;
    };
  };
  ai_edge?: {
    win_pct?: number;
    model_accuracy?: number;
    signal_confidence?: number;
    ml_available?: boolean;
    ml_note?: string;
    n_samples?: number;
    data_points?: number;
    attention_impact?: number[];
    hurst_exponent?: number;
    hurst_regime?: string;
    drift_score?: number;
    vol_skew?: number;
    portfolio_health?: string;
  };
}

const REQUEST_TIMEOUT_MS = 30000;
const RECENT_SYMBOLS_STORAGE_KEY = 'crypto_tactics_recent_symbols';
const TACTICS_CACHE_KEY = 'crypto_tactics_cache_v1';
const TACTICS_AUDIT_CACHE_KEY = 'crypto_tactics_audits_v1';

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null;

const normalizeNumber = (value: unknown, fallback = 0) => {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const normalizeTactic = (value: unknown): Tactic | null => {
  if (!isRecord(value)) return null;

  return {
    name: typeof value.name === 'string' ? value.name : 'Unknown Persona',
    style: typeof value.style === 'string' ? value.style : 'Adaptive',
    score: normalizeNumber(value.score, 0),
    move: typeof value.move === 'string' ? value.move : 'WATCH',
    trigger: typeof value.trigger === 'string' ? value.trigger : 'Await confirmation',
    invalidation: typeof value.invalidation === 'string' ? value.invalidation : 'Reassess structure',
    tp: typeof value.tp === 'string' ? value.tp : 'Dynamic target',
    logic: typeof value.logic === 'string' ? value.logic : 'No tactical rationale returned.',
  };
};

const normalizeAuditLog = (value: unknown, index: number): AuditLog | null => {
  if (!isRecord(value)) return null;

  return {
    id: normalizeNumber(value.id, index),
    symbol: typeof value.symbol === 'string' ? value.symbol : 'N/A',
    confidence: normalizeNumber(value.confidence, 0),
    reasoning: typeof value.reasoning === 'string' ? value.reasoning : 'No reasoning provided.',
    price: normalizeNumber(value.price, 0),
    timestamp: typeof value.timestamp === 'string' ? value.timestamp : new Date().toISOString(),
    recommendation: typeof value.recommendation === 'string' ? value.recommendation : 'WATCH',
  };
};

const normalizeTacticsData = (value: unknown, symbol: string): TacticsData | null => {
  if (!isRecord(value)) return null;

  const tactics = Array.isArray(value.tactics)
    ? value.tactics.map(normalizeTactic).filter((item): item is Tactic => item !== null)
    : [];

  if (tactics.length === 0) return null;

  const v7Status = isRecord(value.v7_status) ? value.v7_status : null;
  const aiEdge = isRecord(value.ai_edge) ? value.ai_edge : null;

  return {
    symbol: typeof value.symbol === 'string' ? value.symbol : symbol,
    price: normalizeNumber(value.price, 0),
    recommendation: typeof value.recommendation === 'string' ? value.recommendation : 'WATCH',
    best_persona: typeof value.best_persona === 'string' ? value.best_persona : tactics[0].name,
    tactics,
    timestamp: normalizeNumber(value.timestamp, Date.now()),
    v7_status: v7Status ? {
      active: Boolean(v7Status.active),
      sniper_mode: Boolean(v7Status.sniper_mode),
      sniper_locked: Boolean(v7Status.sniper_locked),
      lock_reason: typeof v7Status.lock_reason === 'string' ? v7Status.lock_reason : null,
      institutional_flow: isRecord(v7Status.institutional_flow)
        ? {
            bullish_sweep: isRecord(v7Status.institutional_flow.bullish_sweep) ? v7Status.institutional_flow.bullish_sweep as { active?: boolean } : null,
            bearish_sweep: isRecord(v7Status.institutional_flow.bearish_sweep) ? v7Status.institutional_flow.bearish_sweep as { active?: boolean } : null,
          }
        : {},
    } : undefined,
    ai_edge: aiEdge ? {
      win_pct: normalizeNumber(aiEdge.win_pct, 0),
      model_accuracy: normalizeNumber(aiEdge.model_accuracy, 0),
      signal_confidence: normalizeNumber(aiEdge.signal_confidence, 0),
      ml_available: Boolean(aiEdge.ml_available),
      ml_note: typeof aiEdge.ml_note === 'string' ? aiEdge.ml_note : undefined,
      n_samples: normalizeNumber(aiEdge.n_samples, 0),
      data_points: normalizeNumber(aiEdge.data_points, 0),
      attention_impact: Array.isArray(aiEdge.attention_impact)
        ? aiEdge.attention_impact.map((item) => normalizeNumber(item, 0))
        : undefined,
      hurst_exponent: normalizeNumber(aiEdge.hurst_exponent, 0.5),
      hurst_regime: typeof aiEdge.hurst_regime === 'string' ? aiEdge.hurst_regime : 'RANDOM',
      drift_score: normalizeNumber(aiEdge.drift_score, 0),
      vol_skew: normalizeNumber(aiEdge.vol_skew, 0),
      portfolio_health: typeof aiEdge.portfolio_health === 'string' ? aiEdge.portfolio_health : 'READY',
    } : undefined,
  };
};

const fetchAuditLogs = async (headers: Record<string, string>) => {
  const response = await fetch('/api/tactics/audit/logs', { headers });
  if (!response.ok) return [] as AuditLog[];

  const text = await response.text();
  if (!text || text.trim() === '') return [] as AuditLog[];

  try {
    const payload = JSON.parse(text);
    return Array.isArray(payload.logs)
      ? payload.logs
          .map((item: unknown, index: number) => normalizeAuditLog(item, index))
          .filter((item: AuditLog | null): item is AuditLog => item !== null)
      : [];
  } catch {
    return [] as AuditLog[];
  }
};

export const TacticsHub = () => {
  const { theme } = useMode();
  const [symbol, setSymbol] = useState('BTC');
  const [data, setData] = useState<TacticsData | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentSymbols, setRecentSymbols] = useState<string[]>(() => {
    try {
      const stored = localStorage.getItem(RECENT_SYMBOLS_STORAGE_KEY);
      const parsed = stored ? JSON.parse(stored) : null;
      return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : [];
    } catch {
      return [];
    }
  });
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>([]);
  const isTimeoutError = typeof error === 'string' && error.toLowerCase().includes('longer than 30s');

  const apiKey = () => localStorage.getItem('crypto_terminal_key') || 'demo';
  const watchlistHeaders = () => ({
    'X-API-Key': apiKey(),
    'Content-Type': 'application/json',
  });

  const readCachedTactics = (targetSymbol: string) => {
    try {
      const raw = localStorage.getItem(TACTICS_CACHE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      return normalizeTacticsData(parsed[targetSymbol], targetSymbol);
    } catch {
      return null;
    }
  };

  const writeCachedTactics = (payload: TacticsData) => {
    try {
      const raw = localStorage.getItem(TACTICS_CACHE_KEY);
      const parsed = raw ? JSON.parse(raw) as Record<string, unknown> : {};
      parsed[payload.symbol] = payload;
      localStorage.setItem(TACTICS_CACHE_KEY, JSON.stringify(parsed));
    } catch {
      // ignore cache write issues
    }
  };

  const readCachedAudits = () => {
    try {
      const raw = localStorage.getItem(TACTICS_AUDIT_CACHE_KEY);
      if (!raw) return [] as AuditLog[];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed)
        ? parsed
            .map((item: unknown, index: number) => normalizeAuditLog(item, index))
            .filter((item: AuditLog | null): item is AuditLog => item !== null)
        : [];
    } catch {
      return [] as AuditLog[];
    }
  };

  const writeCachedAudits = (logs: AuditLog[]) => {
    try {
      localStorage.setItem(TACTICS_AUDIT_CACHE_KEY, JSON.stringify(logs.slice(0, 20)));
    } catch {
      // ignore cache write issues
    }
  };

  const safeJson = async (response: Response) => {
    const text = await response.text();
    if (!text || text.trim() === '') {
      throw new Error('Backend offline. Please start the Python server first.');
    }
    try {
      return JSON.parse(text);
    } catch {
      throw new Error(`Invalid JSON: ${text.slice(0, 120)}`);
    }
  };

  const fetchTactics = async (targetSymbol: string) => {
    const cached = readCachedTactics(targetSymbol);
    if (cached) {
      setData(cached);
      setAuditLogs(readCachedAudits());
    }
    setLoading(!cached);
    setError(null);

    const headers = { 'X-API-Key': apiKey() };
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    try {
      const tacticsResponse = await fetch(`/api/tactics/${targetSymbol}`, {
        headers,
        signal: controller.signal,
      });

      if (!tacticsResponse.ok) {
        const errText = await tacticsResponse.text().catch(() => '');
        throw new Error(`Server error ${tacticsResponse.status}${errText ? `: ${errText.slice(0, 120)}` : ''}`);
      }

      const tacticsJson = await safeJson(tacticsResponse);
      if (tacticsJson?.status === 'ERROR' && tacticsJson?.message) {
        throw new Error(String(tacticsJson.message));
      }
      if (tacticsJson?.error) throw new Error(String(tacticsJson.error));
      if (tacticsJson?.detail) throw new Error(String(tacticsJson.detail));

      const normalized = normalizeTacticsData(tacticsJson, targetSymbol);
      if (!normalized) {
        throw new Error('Tactical engine returned incomplete data.');
      }

      setData(normalized);
      writeCachedTactics(normalized);
      setRecentSymbols((current) => {
        const next = [normalized.symbol, ...current.filter((item) => item !== normalized.symbol)].slice(0, 8);
        localStorage.setItem(RECENT_SYMBOLS_STORAGE_KEY, JSON.stringify(next));
        return next;
      });

      setLoading(false);

      void fetchAuditLogs(headers)
        .then((logs) => {
          setAuditLogs(logs);
          writeCachedAudits(logs);
        })
        .catch(() => {
          if (!cached) setAuditLogs([]);
        });
    } catch (err: any) {
      if (err?.name === 'AbortError') {
        setError('Tactical engine is taking longer than 30s. The backend is likely busy, not offline.');
      } else {
        setError(err?.message || 'Unknown error');
      }
    } finally {
      window.clearTimeout(timeoutId);
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchTactics(symbol);
  }, []);

  useEffect(() => {
    const syncWatchlist = async () => {
      try {
        const response = await fetch('/api/watchlist', { headers: watchlistHeaders() });
        if (!response.ok) return;
        const payload = await safeJson(response);
        const symbols = Array.isArray(payload.watchlist)
          ? payload.watchlist
              .map((item: { symbol?: unknown }) => (typeof item.symbol === 'string' ? item.symbol.toUpperCase() : null))
              .filter((item: string | null): item is string => Boolean(item))
          : [];
        setWatchlistSymbols(symbols);
      } catch {
        setWatchlistSymbols([]);
      }
    };

    void syncWatchlist();
  }, []);

  const handleSearch = (event: React.SyntheticEvent) => {
    event.preventDefault();
    const normalized = symbol.trim().toUpperCase();
    setSymbol(normalized || 'BTC');
    void fetchTactics(normalized || 'BTC');
  };

  const togglePriorityWatchlist = async () => {
    if (!data?.symbol) return;
    const normalized = data.symbol.toUpperCase();
    const isSaved = watchlistSymbols.includes(normalized);

    setWatchlistSymbols((current) =>
      isSaved ? current.filter((item) => item !== normalized) : [normalized, ...current]
    );

    try {
      if (isSaved) {
        const response = await fetch(`/api/watchlist/${encodeURIComponent(normalized)}`, {
          method: 'DELETE',
          headers: watchlistHeaders(),
        });
        if (!response.ok) throw new Error('Failed to remove from Priority Watchlist');
      } else {
        const response = await fetch('/api/watchlist', {
          method: 'POST',
          headers: watchlistHeaders(),
          body: JSON.stringify({
            symbol: normalized,
            note: `Saved from Alpha Tactics: ${data.recommendation}`,
          }),
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({ detail: 'Unknown error' }));
          const detail = typeof payload?.detail === 'string' ? payload.detail : 'Unknown error';
          if (!detail.toLowerCase().includes('already')) {
            throw new Error(detail);
          }
        }
      }
    } catch (err) {
      console.error('Failed to sync tactics watchlist:', err);
      setWatchlistSymbols((current) =>
        isSaved ? [normalized, ...current] : current.filter((item) => item !== normalized)
      );
    }
  };

  const copyTacticalBrief = async () => {
    if (!data) return;

    const topTactic = data.tactics[0];
    const brief = [
      `Alpha Tactics: ${data.symbol}`,
      `Recommendation: ${data.recommendation}`,
      `Best Persona: ${data.best_persona}`,
      `Price: $${data.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`,
      `Win Probability: ${(data.ai_edge?.win_pct ?? 0).toFixed(1)}%`,
      topTactic ? `Entry: ${topTactic.trigger}` : null,
      topTactic ? `Invalidation: ${topTactic.invalidation}` : null,
      topTactic ? `Target: ${topTactic.tp}` : null,
      topTactic ? `Why: ${topTactic.logic}` : null,
    ].filter(Boolean).join('\n');

    try {
      await navigator.clipboard.writeText(brief);
    } catch (err) {
      console.error('Failed to copy tactical brief:', err);
    }
  };

  const getPersonaIcon = (name: string) => {
    if (name.includes('Trend')) return <TrendingUp className={`w-5 h-5 ${theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'}`} />;
    if (name.includes('Money') || name.includes('Liquidity')) return <Shield className={`w-5 h-5 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />;
    if (name.includes('Breakout') || name.includes('Sniper')) return <Zap className={`w-5 h-5 ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`} />;
    if (name.includes('Mean')) return <TrendingUp className={`w-5 h-5 rotate-180 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />;
    if (name.includes('Stock')) return <Target className={`w-5 h-5 ${theme === 'dark' ? 'text-purple-400' : 'text-purple-600'}`} />;
    if (name.includes('No Trade')) return <Shield className={`w-5 h-5 ${theme === 'dark' ? 'text-rose-400' : 'text-rose-600'}`} />;
    return <Zap className={`w-5 h-5 ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`} />;
  };

  const getScoreColor = (score: number) => {
    if (score >= 80) return theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600';
    if (score <= 30) return theme === 'dark' ? 'text-slate-500' : 'text-slate-400';
    return theme === 'dark' ? 'text-amber-400' : 'text-amber-600';
  };

  const topTactic = data?.tactics?.[0] ?? null;
  const symbolAuditLogs = data
    ? auditLogs.filter((item) => item.symbol.toUpperCase() === data.symbol.toUpperCase())
    : [];
  const displayedAuditLogs = symbolAuditLogs.length > 0 ? symbolAuditLogs : auditLogs;
  const mlAvailable = Boolean(data?.ai_edge?.ml_available);
  const modelProbabilityLabel = mlAvailable && typeof data?.ai_edge?.win_pct === 'number'
    ? `${data.ai_edge.win_pct.toFixed(1)}%`
    : 'Unavailable';
  const modelProbabilityHelper = mlAvailable
    ? `${data?.ai_edge?.n_samples ?? 0} samples`
    : (data?.ai_edge?.ml_note ?? 'ML model or data not available');
  const signalConfidenceLabel = `${(((data?.ai_edge?.signal_confidence ?? 0) as number) * 100).toFixed(0)}%`;
  const recommendationTone =
    data?.recommendation?.toUpperCase().includes('LONG') ? 'bullish' :
    data?.recommendation?.toUpperCase().includes('SHORT') ? 'bearish' :
    'neutral';
  const nextStepLabel =
    recommendationTone === 'bullish' ? 'Look for confirmation on pullbacks and protect below invalidation.' :
    recommendationTone === 'bearish' ? 'Wait for weak bounces and respect the stop above invalidation.' :
    'Stay selective and wait for the trigger to appear before committing risk.';
  const secondaryTactics = data?.tactics?.slice(1, 4) ?? [];
  const isPrioritySaved = data ? watchlistSymbols.includes(data.symbol.toUpperCase()) : false;
  const freshnessLabel = data
    ? new Date(data.timestamp).toLocaleString(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className={`flex-1 p-4 md:p-8 space-y-8 custom-scrollbar transition-all duration-700 ${
      theme === 'dark' ? 'bg-[#020617]' : 'bg-slate-50'
    }`}>
      <header className="flex flex-col xl:flex-row justify-between items-start xl:items-center gap-6 relative z-20">
        <div className="space-y-1">
          <motion.div
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            className={`flex items-center gap-2 font-black text-[9px] uppercase tracking-[0.3em] ${
              theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'
            }`}
          >
            <div className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
            Tactical Command Center
          </motion.div>
          <h1 className={`text-3xl md:text-4xl font-black tracking-tighter uppercase italic leading-none ${
            theme === 'dark' ? 'text-white' : 'text-slate-950'
          }`}>
            Alpha <span className={theme === 'dark' ? 'text-indigo-500' : 'text-indigo-600'}>Tactics</span>
          </h1>
          <p className={`text-sm ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>
            Converts tactical engine output into a readable plan with entry, invalidation, target, and audit history.
          </p>
        </div>

        <div className="flex flex-col md:flex-row items-center gap-4 w-full xl:w-auto">
          <div className="flex flex-wrap gap-2 order-2 md:order-1">
            {['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'GOLD'].map((item) => (
              <button
                key={item}
                onClick={() => {
                  setSymbol(item);
                  void fetchTactics(item);
                }}
                className={`px-3 py-1.5 rounded-xl text-[9px] font-black tracking-widest transition-all uppercase border ${
                  symbol.toUpperCase() === item
                    ? theme === 'dark'
                      ? 'bg-indigo-600 border-indigo-500 text-white shadow-[0_0_15px_rgba(79,70,229,0.3)]'
                      : 'bg-indigo-600 border-indigo-700 text-white shadow-md'
                    : theme === 'dark'
                      ? 'bg-white/5 border-white/5 text-slate-400 hover:bg-white/10'
                      : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-100 shadow-sm'
                }`}
              >
                {item}
              </button>
            ))}
            {recentSymbols
              .filter((item) => !['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'GOLD'].includes(item))
              .map((item) => (
                <button
                  key={item}
                  onClick={() => {
                    setSymbol(item);
                    void fetchTactics(item);
                  }}
                  className={`px-3 py-1.5 rounded-xl text-[9px] font-black tracking-widest transition-all uppercase border ${
                    theme === 'dark'
                      ? 'bg-white/5 border-white/5 text-slate-400 hover:bg-white/10'
                      : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-100 shadow-sm'
                  }`}
                >
                  Recent {item}
                </button>
              ))}
          </div>

          <form onSubmit={handleSearch} className="relative group w-full md:w-64 order-1 md:order-2">
            <div className="absolute inset-0 bg-indigo-500/20 blur-xl opacity-0 group-focus-within:opacity-100 transition-opacity rounded-2xl" />
            <input
              type="text"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              className={`relative w-full border rounded-xl px-4 py-2.5 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all uppercase ${
                theme === 'dark'
                  ? 'bg-slate-900/80 border-white/10 text-white placeholder:text-slate-700 backdrop-blur-xl shadow-2xl'
                  : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 shadow-sm'
              }`}
              placeholder="ENTER TICKER..."
            />
            <button
              type="submit"
              className={`absolute right-2 top-1/2 -translate-y-1/2 p-1.5 rounded-lg transition-all ${
                theme === 'dark' ? 'bg-indigo-500/20 text-indigo-400 hover:bg-indigo-500 hover:text-white' : 'bg-indigo-50 text-indigo-600 hover:bg-indigo-600 hover:text-white'
              }`}
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      </header>

      <AnimatePresence mode="wait">
        {loading ? (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-8"
          >
            {[1, 2, 3, 4, 5, 6].map((item) => (
              <div
                key={item}
                className={`h-64 rounded-[2.5rem] border animate-pulse ${
                  theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-slate-200/50 border-slate-200'
                }`}
              />
            ))}
          </motion.div>
        ) : data ? (
          <motion.div
            key="data"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -30 }}
            className="space-y-10"
          >
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
              {[
                {
                  label: 'ML Probability',
                  value: modelProbabilityLabel,
                  detail: modelProbabilityHelper,
                  accent: mlAvailable
                    ? recommendationTone === 'bullish' ? 'text-emerald-400' : recommendationTone === 'bearish' ? 'text-rose-400' : 'text-amber-400'
                    : 'text-slate-400',
                },
                {
                  label: 'Primary Trigger',
                  value: topTactic?.trigger ?? 'Await trigger',
                  detail: topTactic?.name ?? data.best_persona,
                  accent: theme === 'dark' ? 'text-white' : 'text-slate-900',
                },
                {
                  label: 'Risk Box',
                  value: topTactic?.invalidation ?? 'No stop defined',
                  detail: topTactic?.tp ?? 'No target defined',
                  accent: 'text-blue-400',
                },
                {
                  label: 'Signal Confidence',
                  value: signalConfidenceLabel,
                  detail: freshnessLabel ? `Updated ${freshnessLabel}` : 'Fresh snapshot',
                  accent: 'text-indigo-400',
                },
              ].map((card) => (
                <div
                  key={card.label}
                  className={`p-4 border rounded-2xl transition-all duration-500 ${
                    theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
                  }`}
                >
                  <p className={`text-[10px] font-black uppercase tracking-[0.2em] ${
                    theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                  }`}>{card.label}</p>
                  <p className={`mt-2 text-sm font-black ${card.accent}`}>{card.value}</p>
                  <p className={`mt-1 text-xs ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>{card.detail}</p>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 auto-rows-min">
              <div className="lg:col-span-8 group relative rounded-[2.5rem] p-0.5 bg-gradient-to-br from-indigo-500 via-blue-500 to-emerald-500 shadow-2xl overflow-hidden transition-transform duration-500 hover:scale-[1.005]">
                <div className={`relative h-full rounded-[2.45rem] p-6 md:p-10 flex flex-col md:flex-row items-center justify-between gap-8 overflow-hidden ${
                  theme === 'dark' ? 'bg-slate-950/95' : 'bg-white/95'
                }`}>
                  <div className="absolute top-0 right-0 w-full h-full pointer-events-none overflow-hidden">
                    <div className="absolute -top-24 -right-24 w-72 h-72 bg-indigo-500/10 blur-[80px] rounded-full group-hover:scale-150 transition-transform duration-1000" />
                    <div className="absolute bottom-0 left-0 w-48 h-48 bg-emerald-500/5 blur-[60px] rounded-full" />
                  </div>

                  <div className="flex items-center gap-8 relative z-10">
                    <motion.div
                      whileHover={{ rotate: [0, -5, 5, 0], scale: 1.05 }}
                      className={`w-20 h-20 rounded-[1.8rem] flex items-center justify-center border shadow-xl transition-all duration-500 bg-gradient-to-br ${
                        theme === 'dark' ? 'from-white/10 to-white/5 border-white/20 shadow-indigo-500/10' : 'from-slate-50 to-white border-slate-200 shadow-slate-200/20'
                      }`}
                    >
                      <span className={`text-2xl font-black font-mono tracking-tighter ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{data.symbol}</span>
                    </motion.div>

                    <div className="space-y-2">
                      <div className={`flex items-center gap-2 text-[8px] font-black uppercase tracking-[0.4em] ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`}>
                        <Shield className="w-3 h-3" /> Institutional Consensus
                      </div>
                      <h2 className={`text-4xl md:text-5xl font-black tracking-tighter uppercase italic leading-none ${theme === 'dark' ? 'text-white' : 'text-slate-950'}`}>
                        {data.recommendation}
                      </h2>
                      <div className="flex items-center gap-5 pt-1">
                        <div className="space-y-0.5">
                          <p className="text-[8px] font-bold text-slate-500 uppercase tracking-widest">Mark Price</p>
                          <p className={`text-xl font-black font-mono ${theme === 'dark' ? 'text-slate-200' : 'text-slate-800'}`}>
                            ${data.price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
                          </p>
                        </div>
                        <div className={`h-8 w-[1px] ${theme === 'dark' ? 'bg-white/10' : 'bg-slate-200'}`} />
                        <div className="space-y-0.5">
                          <p className="text-[8px] font-bold text-slate-500 uppercase tracking-widest">Selected Core</p>
                          <p className={`text-xs font-black uppercase ${theme === 'dark' ? 'text-indigo-300' : 'text-indigo-700'}`}>{data.best_persona}</p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-col gap-3 relative z-10 w-full md:w-auto">
                    <div className={`flex items-center gap-3 p-4 rounded-2xl border transition-all ${
                      theme === 'dark' ? 'bg-white/5 border-white/5 hover:bg-white/10' : 'bg-slate-50 border-slate-200 hover:bg-slate-100'
                    }`}>
                      <div className={`p-2 rounded-xl ${theme === 'dark' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-emerald-100 text-emerald-600'}`}>
                        <Zap className="w-5 h-5" />
                      </div>
                      <div>
                        <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">ML Status</p>
                        <p className={`text-sm font-black ${mlAvailable ? (theme === 'dark' ? 'text-white' : 'text-slate-900') : 'text-slate-500'}`}>
                          {mlAvailable ? 'MODEL ACTIVE' : 'MODEL UNAVAILABLE'}
                        </p>
                      </div>
                    </div>
                    <div className={`p-4 rounded-2xl border text-center transition-all ${
                      mlAvailable && (data.ai_edge?.win_pct ?? 0) >= 80
                        ? theme === 'dark' ? 'bg-amber-500/10 border-amber-500/30' : 'bg-amber-50 border-amber-200'
                        : theme === 'dark' ? 'bg-white/5 border-white/5' : 'bg-slate-50 border-slate-200'
                    }`}>
                      <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest mb-0.5">ML Probability</p>
                      <p className={`text-xl font-black font-mono ${
                        mlAvailable && (data.ai_edge?.win_pct ?? 0) >= 80 ? 'text-amber-500' : theme === 'dark' ? 'text-white' : 'text-slate-900'
                      }`}>
                        {modelProbabilityLabel}
                      </p>
                      {!mlAvailable && (
                        <p className="mt-1 text-[10px] text-slate-500">{data.ai_edge?.ml_note ?? 'Model unavailable'}</p>
                      )}
                    </div>
                    <div className="grid grid-cols-1 gap-2">
                      <button
                        onClick={() => void togglePriorityWatchlist()}
                        className={`inline-flex items-center justify-center gap-2 px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${
                          isPrioritySaved
                            ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                            : theme === 'dark'
                              ? 'bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10'
                              : 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-100'
                        }`}
                      >
                        <Star className={`w-4 h-4 ${isPrioritySaved ? 'fill-current' : ''}`} />
                        {isPrioritySaved ? 'In Priority Watchlist' : 'Add to Priority Watchlist'}
                      </button>
                      <button
                        onClick={() => void copyTacticalBrief()}
                        className={`inline-flex items-center justify-center gap-2 px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${
                          theme === 'dark'
                            ? 'bg-indigo-500/10 text-indigo-300 border border-indigo-500/20 hover:bg-indigo-500/20'
                            : 'bg-indigo-50 text-indigo-700 border border-indigo-100 hover:bg-indigo-100'
                        }`}
                      >
                        <Copy className="w-4 h-4" />
                        Copy Tactical Brief
                      </button>
                      <button
                        onClick={() => void fetchTactics(data.symbol)}
                        className={`inline-flex items-center justify-center gap-2 px-4 py-3 rounded-2xl text-[10px] font-black uppercase tracking-[0.2em] transition-all ${
                          theme === 'dark'
                            ? 'bg-white/5 text-slate-300 border border-white/10 hover:bg-white/10'
                            : 'bg-white text-slate-700 border border-slate-200 hover:bg-slate-100'
                        }`}
                      >
                        <RefreshCw className="w-4 h-4" />
                        Refresh Setup
                      </button>
                    </div>
                  </div>
                </div>
              </div>

              <div className={`lg:col-span-4 rounded-[2.5rem] p-6 border backdrop-blur-3xl flex flex-col justify-between transition-all duration-500 hover:border-indigo-500/30 ${
                theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
              }`}>
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <p className={`text-[9px] font-black uppercase tracking-[0.2em] ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`}>Reality Check</p>
                    <div className="flex h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                  </div>

                  <div className="space-y-3">
                    <MetricRow label="Model Status" value={mlAvailable ? 'AVAILABLE' : 'UNAVAILABLE'} theme={theme} />
                    <MetricRow label="Data Coverage" value={`${data.ai_edge?.data_points ?? 0} bars`} theme={theme} />
                    <MetricRow label="ML Samples" value={`${data.ai_edge?.n_samples ?? 0}`} theme={theme} />
                    <MetricRow label="Model Accuracy" value={mlAvailable ? `${(((data.ai_edge?.model_accuracy ?? 0) as number) * 100).toFixed(1)}%` : 'N/A'} theme={theme} />
                    <MetricRow label="Signal Confidence" value={signalConfidenceLabel} theme={theme} />
                    <MetricRow label="Fractal Hurst (H)" value={(data.ai_edge?.hurst_exponent ?? 0.5).toFixed(2)} theme={theme} />
                    <MetricRow label="Drift Score" value={`${data.ai_edge?.drift_score ?? 0}/100`} theme={theme} />
                    <MetricRow label="Risk Skewness" value={(data.ai_edge?.vol_skew ?? 0).toFixed(2)} theme={theme} />
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-white/5">
                  <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest mb-2">What To Trust</p>
                  <p className={`text-xs leading-relaxed ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>
                    {mlAvailable
                      ? 'Use ML probability as a secondary confidence input. Entry, stop, and target still come from structure and confluence.'
                      : (data.ai_edge?.ml_note ?? 'ML signal is unavailable, so use only price structure, confluence, and risk levels on this screen.')}
                  </p>
                </div>
              </div>
            </div>

            <div className={`p-6 rounded-[2.5rem] border transition-all duration-500 ${
              theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
            }`}>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    {recommendationTone === 'bullish' ? (
                      <TrendingUp className="w-4 h-4 text-emerald-400" />
                    ) : recommendationTone === 'bearish' ? (
                      <TrendingDown className="w-4 h-4 text-rose-400" />
                    ) : (
                      <Shield className="w-4 h-4 text-amber-400" />
                    )}
                    <h3 className={`text-base font-black uppercase italic ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Execution Brief</h3>
                  </div>
                  <div className="space-y-1">
                    <p className="text-[9px] font-black text-slate-500 uppercase tracking-[0.28em]">Primary Plan</p>
                    <p className={`text-xl md:text-2xl font-black leading-tight ${theme === 'dark' ? 'text-white' : 'text-slate-950'}`}>
                      {topTactic?.move ?? data.recommendation}
                    </p>
                    <p className={`max-w-3xl text-sm leading-relaxed ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>
                      {nextStepLabel}
                    </p>
                  </div>
                </div>

                <div className={`min-w-[220px] rounded-[1.75rem] border px-4 py-3 ${
                  theme === 'dark' ? 'border-white/10 bg-white/5' : 'border-slate-200 bg-slate-50'
                }`}>
                  <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Best Use</p>
                  <p className={`mt-2 text-sm font-black leading-relaxed ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                    {topTactic ? `${topTactic.trigger} -> ${topTactic.tp}` : 'Wait for clarity'}
                  </p>
                  <p className={`mt-2 text-[11px] ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>
                    {topTactic?.invalidation ?? 'Risk first'}
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-5">
                <BriefPoint
                  theme={theme}
                  label="Bias"
                  value={data.recommendation}
                  helper={data.best_persona}
                />
                <BriefPoint
                  theme={theme}
                  label="Next Step"
                  value={nextStepLabel}
                  helper={topTactic?.move ?? 'WATCH'}
                />
                <BriefPoint
                  theme={theme}
                  label="Risk Line"
                  value={topTactic?.invalidation ?? 'Risk first'}
                  helper={topTactic?.tp ?? 'No target defined'}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
              <div className="xl:col-span-8">
                {topTactic && (
                  <HoverGlowCard
                    className={`p-6 md:p-7 rounded-[2.5rem] border flex flex-col transition-all duration-500 ${
                      theme === 'dark'
                        ? 'border-indigo-500/40 bg-indigo-500/10 shadow-[0_0_30px_rgba(99,102,241,0.08)]'
                        : 'border-indigo-300 bg-white shadow-xl'
                    }`}
                  >
                    <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
                      <div className="space-y-3">
                        <div className="flex items-center gap-3">
                          <div className={`p-2.5 rounded-xl border transition-all duration-500 ${
                            theme === 'dark' ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200 shadow-sm'
                          }`}>
                            {getPersonaIcon(topTactic.name)}
                          </div>
                          <div>
                            <p className="text-[8px] text-slate-500 font-bold uppercase tracking-[0.28em]">Primary Setup</p>
                            <h4 className={`text-xl md:text-2xl font-black uppercase italic ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{topTactic.name}</h4>
                            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest">{topTactic.style}</p>
                          </div>
                        </div>
                        <p className={`max-w-3xl text-sm leading-relaxed ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>
                          {topTactic.logic}
                        </p>
                      </div>

                      <div className={`shrink-0 rounded-[1.75rem] border px-4 py-3 ${
                        theme === 'dark' ? 'border-white/10 bg-slate-950/40' : 'border-slate-200 bg-slate-50'
                      }`}>
                        <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">Confidence</p>
                        <p className={`mt-1 text-3xl font-black font-mono ${getScoreColor(topTactic.score)}`}>{topTactic.score}%</p>
                        <p className="text-[10px] text-slate-500 uppercase tracking-widest">Best persona</p>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-2.5 mt-6">
                      <TacticalPoint label="Entry Zone" val={topTactic.trigger} color="emerald" theme={theme} emphasis="strong" />
                      <TacticalPoint label="Invalidation" val={topTactic.invalidation} color="rose" theme={theme} emphasis="strong" />
                      <TacticalPoint label="Targets" val={topTactic.tp} color="blue" theme={theme} emphasis="strong" />
                    </div>
                  </HoverGlowCard>
                )}
              </div>

              <div className="xl:col-span-4 space-y-5">
                <div className={`p-6 rounded-[2.5rem] border space-y-4 transition-all duration-500 relative overflow-hidden ${
                  theme === 'dark' ? 'bg-indigo-500/5 border-indigo-500/20' : 'bg-indigo-50/50 border-indigo-200 shadow-sm'
                }`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className={`p-1.5 rounded-lg ${theme === 'dark' ? 'bg-indigo-500/20 text-indigo-400' : 'bg-indigo-100 text-indigo-600'}`}>
                        <Shield className="w-4 h-4" />
                      </div>
                      <h3 className={`text-base font-black uppercase italic ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Order Flow</h3>
                    </div>
                    <div className={`px-2.5 py-0.5 rounded-full text-[8px] font-black uppercase tracking-[0.2em] border ${
                      theme === 'dark' ? 'bg-indigo-500/10 border-indigo-500/20 text-indigo-400' : 'bg-indigo-50 border-indigo-200 text-indigo-600'
                    }`}>LIVE</div>
                  </div>

                  <div className="space-y-3">
                    <FlowSignal
                      label="Bullish Sweep"
                      active={Boolean(data.v7_status?.institutional_flow?.bullish_sweep?.active)}
                      text={data.v7_status?.institutional_flow?.bullish_sweep?.active ? 'Aggressive absorption at demand.' : 'No significant accumulation.'}
                      theme={theme}
                    />
                    <FlowSignal
                      label="Bearish Sweep"
                      active={Boolean(data.v7_status?.institutional_flow?.bearish_sweep?.active)}
                      text={data.v7_status?.institutional_flow?.bearish_sweep?.active ? 'Distribution detected at supply.' : 'No significant distribution.'}
                      theme={theme}
                    />
                  </div>
                </div>

                {secondaryTactics.map((tactic, index) => (
                  <HoverGlowCard
                    key={`${tactic.name}-${index}`}
                    className={`p-5 rounded-[2rem] border flex flex-col transition-all duration-500 ${
                      theme === 'dark' ? 'border-white/5 bg-slate-900/40 hover:border-white/20' : 'border-slate-200 bg-white shadow-sm hover:shadow-xl hover:border-indigo-200'
                    }`}
                  >
                    <div className="flex justify-between items-start gap-3 mb-3">
                      <div className="min-w-0">
                        <h4 className={`text-base font-black uppercase italic leading-tight ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{tactic.name}</h4>
                        <p className="mt-1 text-[8px] text-slate-500 font-bold uppercase tracking-widest">{tactic.style}</p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-[8px] font-black text-slate-500 uppercase tracking-widest">Conf</p>
                        <p className={`text-lg font-black font-mono ${getScoreColor(tactic.score)}`}>{tactic.score}%</p>
                      </div>
                    </div>

                    <div className="grid grid-cols-1 gap-1.5">
                      <TacticalPoint label="Entry" val={tactic.trigger} color="emerald" theme={theme} />
                      <TacticalPoint label="Stop" val={tactic.invalidation} color="rose" theme={theme} />
                      <TacticalPoint label="Target" val={tactic.tp} color="blue" theme={theme} />
                    </div>
                  </HoverGlowCard>
                ))}
              </div>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between px-4">
                <div className="flex items-center gap-2">
                  <Target className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
                  <h3 className={`text-lg font-black uppercase italic ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Intelligence Audit Log</h3>
                </div>
                <div className={`px-3 py-1.5 rounded-xl border text-[9px] font-black uppercase tracking-widest ${
                  theme === 'dark' ? 'bg-white/5 border-white/5 text-slate-500' : 'bg-white border-slate-200 text-slate-400'
                }`}>
                  Live Tactical Stream
                </div>
              </div>

              <div className={`overflow-hidden rounded-[2.5rem] border backdrop-blur-3xl transition-all duration-500 ${
                theme === 'dark' ? 'border-white/5 bg-slate-900/40 shadow-2xl' : 'border-slate-200 bg-white shadow-xl'
              }`}>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse min-w-[800px]">
                    <thead>
                      <tr className={`border-b transition-colors duration-500 ${theme === 'dark' ? 'border-white/5 bg-white/5' : 'border-slate-100 bg-slate-50/50'}`}>
                        <th className="px-6 py-4 text-[9px] font-black text-slate-500 uppercase tracking-widest">Symbol</th>
                        <th className="px-6 py-4 text-[9px] font-black text-slate-500 uppercase tracking-widest">Neural Conf</th>
                        <th className="px-6 py-4 text-[9px] font-black text-slate-500 uppercase tracking-widest">Institutional Context</th>
                        <th className="px-6 py-4 text-[9px] font-black text-slate-500 uppercase tracking-widest">Action</th>
                        <th className="px-6 py-4 text-[9px] font-black text-slate-500 uppercase tracking-widest">Timestamp</th>
                      </tr>
                    </thead>
                    <tbody className={`divide-y transition-colors duration-500 ${theme === 'dark' ? 'divide-white/5' : 'divide-slate-100'}`}>
                      {displayedAuditLogs.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="px-6 py-10 text-center text-sm text-slate-500">
                            No audit logs available yet.
                          </td>
                        </tr>
                      ) : displayedAuditLogs.slice(0, 8).map((log) => (
                        <tr key={log.id} className={`transition-colors group ${theme === 'dark' ? 'hover:bg-white/5' : 'hover:bg-slate-50'}`}>
                          <td className={`px-6 py-4 font-mono font-bold text-sm ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{log.symbol}</td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-2">
                              <span className={`font-mono font-bold text-[11px] ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`}>
                                {(log.confidence * 100).toFixed(0)}%
                              </span>
                              <div className={`w-16 h-1 rounded-full overflow-hidden ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-100'}`}>
                                <motion.div
                                  initial={{ width: 0 }}
                                  animate={{ width: `${Math.max(0, Math.min(100, log.confidence * 100))}%` }}
                                  className={`h-full ${
                                    log.confidence > 0.7 ? 'bg-emerald-500' :
                                    log.confidence > 0.4 ? 'bg-indigo-500' : 'bg-amber-500'
                                  }`}
                                />
                              </div>
                            </div>
                          </td>
                          <td className={`px-6 py-4 text-[11px] font-medium max-w-xs truncate group-hover:whitespace-normal transition-all ${
                            theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
                          }`}>
                            {log.reasoning}
                          </td>
                          <td className="px-6 py-4">
                            <span className={`px-2.5 py-1 rounded-lg text-[9px] font-black uppercase border ${
                              log.recommendation === 'LONG'
                                ? theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                : log.recommendation === 'SHORT'
                                  ? theme === 'dark' ? 'bg-rose-500/10 border-rose-500/30 text-rose-400' : 'bg-rose-50 border-rose-200 text-rose-700'
                                  : theme === 'dark' ? 'bg-white/5 border-white/10 text-slate-400' : 'bg-slate-50 border-slate-200 text-slate-500'
                            }`}>
                              {log.recommendation || 'WATCH'}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-[9px] text-slate-500 font-mono font-bold">
                            {new Date(log.timestamp).toLocaleTimeString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center justify-center p-20 text-center space-y-6"
          >
            <div className="w-16 h-16 rounded-[1.5rem] bg-rose-500/10 border border-rose-500/20 flex items-center justify-center">
              <Shield className="w-8 h-8 text-rose-500" />
            </div>
            <div className="space-y-2">
              <h2 className={`text-xl font-black uppercase italic ${theme === 'dark' ? 'text-white' : 'text-slate-950'}`}>
                {isTimeoutError ? 'Engine Delayed' : 'Link Offline'}
              </h2>
              <p className="text-[11px] text-slate-500 max-w-xs">{error || 'Tactical engine is unavailable right now.'}</p>
            </div>
            <button
              onClick={() => void fetchTactics(symbol)}
              className="px-6 py-3 rounded-xl bg-indigo-600 text-white font-black text-xs uppercase tracking-widest hover:bg-indigo-700 transition-all active:scale-95 shadow-lg shadow-indigo-600/20"
            >
              {isTimeoutError ? 'Retry Snapshot' : 'Retry Connection'}
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

const MetricRow = ({ label, value, theme }: { label: string; value: string; theme: string }) => (
  <div className="flex items-center justify-between">
    <p className="text-[9px] font-bold text-slate-500 uppercase tracking-widest">{label}</p>
    <span className={`text-sm font-black font-mono ${theme === 'dark' ? 'text-white' : 'text-slate-950'}`}>{value}</span>
  </div>
);

const BriefPoint = ({
  theme,
  label,
  value,
  helper,
}: {
  theme: string;
  label: string;
  value: string;
  helper: string;
}) => (
  <div className={`p-4 rounded-[1.75rem] border ${
    theme === 'dark' ? 'bg-white/5 border-white/10' : 'bg-slate-50/80 border-slate-200'
  }`}>
    <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">{label}</p>
    <p className={`mt-2 text-sm font-black leading-relaxed ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{value}</p>
    <p className={`mt-2 text-[11px] ${theme === 'dark' ? 'text-slate-400' : 'text-slate-500'}`}>{helper}</p>
  </div>
);

const FlowSignal = ({ label, active, text, theme }: { label: string; active: boolean; text: string; theme: string }) => (
  <div className={`p-4 rounded-2xl border transition-all duration-500 ${
    active
      ? theme === 'dark' ? 'bg-indigo-500/20 border-indigo-500/40' : 'bg-indigo-50 border-indigo-200'
      : theme === 'dark' ? 'bg-white/5 border-white/5' : 'bg-white border-slate-100 shadow-sm'
  }`}>
    <div className="flex items-center justify-between mb-1.5">
      <p className={`text-[9px] font-black uppercase tracking-widest ${
        active
          ? theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'
          : 'text-slate-500'
      }`}>{label}</p>
      <div className={`w-1.5 h-1.5 rounded-full ${active ? 'bg-emerald-500 animate-pulse' : 'bg-slate-700'}`} />
    </div>
    <p className={`text-[11px] font-bold ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>{text}</p>
  </div>
);

const TacticalPoint = ({
  label,
  val,
  color,
  theme,
  emphasis = 'default',
}: {
  label: string;
  val: string;
  color: 'emerald' | 'rose' | 'blue';
  theme: string;
  emphasis?: 'default' | 'strong';
}) => {
  const colors = {
    emerald: theme === 'dark' ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20' : 'text-emerald-700 bg-emerald-50 border-emerald-100',
    rose: theme === 'dark' ? 'text-rose-400 bg-rose-500/10 border-rose-500/20' : 'text-rose-700 bg-rose-50 border-rose-100',
    blue: theme === 'dark' ? 'text-blue-400 bg-blue-500/10 border-blue-500/20' : 'text-blue-700 bg-blue-50 border-blue-100',
  };

  return (
    <div className={`rounded-xl border transition-all ${colors[color]} ${
      emphasis === 'strong'
        ? 'px-4 py-3.5 md:px-5 md:py-4 flex flex-col gap-2'
        : 'px-4 py-2.5 flex items-center justify-between'
    }`}>
      <span className={`font-black uppercase tracking-widest opacity-70 ${
        emphasis === 'strong' ? 'text-[9px]' : 'text-[9px]'
      }`}>{label}</span>
      <span className={`font-black font-mono ${
        emphasis === 'strong'
          ? 'text-sm md:text-base leading-relaxed break-words'
          : 'text-[11px] text-right'
      }`}>{val}</span>
    </div>
  );
};
