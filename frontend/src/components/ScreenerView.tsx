import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Copy, ExternalLink, RefreshCw, Search, SlidersHorizontal, Star, TrendingDown, TrendingUp, Zap } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { useMode } from '../contexts/ModeContext';

interface ScreenerResult {
  symbol: string;
  timeframe?: string;
  price: number;
  rsi: number;
  vol_ratio: number;
  pct_from_52wh: number;
  pct_from_period_high?: number;
  return_1w_pct: number;
  return_pct?: number;
  ai_score?: number;
  rationale?: string;
}

interface QuickFilterSet {
  rsiMin?: string;
  rsiMax?: string;
  priceMin?: string;
  priceMax?: string;
  volSpikeMin?: string;
  volSpikeMax?: string;
  pctMin?: string;
  pctMax?: string;
  retMin?: string;
  retMax?: string;
}

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';
const WATCHLIST_API_HEADERS = () => ({
  'X-API-Key': API_KEY(),
  'Content-Type': 'application/json',
});
const AUTO_REFRESH_MS = 20000;
const WATCHLIST_STORAGE_KEY = 'crypto_screener_watchlist';
const SCREENER_STATE_STORAGE_KEY = 'crypto_screener_state';

const UNIVERSES = ['NASDAQ100', 'SP500', 'NASDAQ', 'CRYPTO', 'SMALL_CAP', 'CUSTOM'];
const TIMEFRAMES = [
  { key: '1h', label: '1H' },
  { key: '4h', label: '4H' },
  { key: '1d', label: '1D' },
  { key: '1w', label: '1W' },
  { key: '1mo', label: '1M' },
  { key: '1y', label: '1Y' },
];

export const ScreenerView = () => {
  const { t } = useLanguage();
  const { theme } = useMode();
  const loadStoredState = () => {
    try {
      const raw = sessionStorage.getItem(SCREENER_STATE_STORAGE_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (err) {
      console.error('Failed to parse screener state:', err);
      return null;
    }
  };
  const storedState = loadStoredState();

  const [universe, setUniverse] = useState(storedState?.universe ?? 'NASDAQ100');
  const [timeframe, setTimeframe] = useState(storedState?.timeframe ?? '1d');
  const [rsiMin, setRsiMin] = useState(storedState?.rsiMin ?? '');
  const [rsiMax, setRsiMax] = useState(storedState?.rsiMax ?? '');
  const [priceMin, setPriceMin] = useState(storedState?.priceMin ?? '');
  const [priceMax, setPriceMax] = useState(storedState?.priceMax ?? '');
  const [volSpikeMin, setVolSpikeMin] = useState(storedState?.volSpikeMin ?? '');
  const [volSpikeMax, setVolSpikeMax] = useState(storedState?.volSpikeMax ?? '');
  const [pctMin, setPctMin] = useState(storedState?.pctMin ?? '');
  const [pctMax, setPctMax] = useState(storedState?.pctMax ?? '');
  const [retMin, setRetMin] = useState(storedState?.retMin ?? '');
  const [retMax, setRetMax] = useState(storedState?.retMax ?? '');
  const [sortBy, setSortBy] = useState(storedState?.sortBy ?? 'vol_ratio');
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>(storedState?.sortOrder === 'asc' ? 'asc' : 'desc');
  const [customTickers, setCustomTickers] = useState(storedState?.customTickers ?? '');
  const [results, setResults] = useState<ScreenerResult[]>(storedState?.results ?? []);
  const [loading, setLoading] = useState(false);
  const [ran, setRan] = useState(Boolean(storedState?.ran));
  const [matchCount, setMatchCount] = useState(storedState?.matchCount ?? 0);
  const [lastUpdated, setLastUpdated] = useState<string | null>(storedState?.lastUpdated ?? null);
  const [watchlist, setWatchlist] = useState<string[]>([]);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(800);

  const containerRef = useRef<HTMLDivElement>(null);
  const tableRef = useRef<HTMLDivElement>(null);
  const rowHeight = 84;
  const buffer = 15;

  useEffect(() => {
    try {
      const stored = localStorage.getItem(WATCHLIST_STORAGE_KEY);
      if (!stored) return;
      const parsed = JSON.parse(stored);
      if (Array.isArray(parsed)) {
        setWatchlist(parsed.filter((item): item is string => typeof item === 'string'));
      }
    } catch (err) {
      console.error('Failed to load screener watchlist:', err);
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(watchlist));
  }, [watchlist]);

  useEffect(() => {
    const syncWatchlistFromApi = async () => {
      try {
        const response = await fetch('/api/watchlist', { headers: WATCHLIST_API_HEADERS() });
        if (!response.ok) return;
        const data = await response.json();
        const symbols = Array.isArray(data.watchlist)
          ? data.watchlist
              .map((item: { symbol?: unknown }) => (typeof item.symbol === 'string' ? item.symbol.toUpperCase() : null))
              .filter((item: string | null): item is string => Boolean(item))
          : [];

        if (symbols.length > 0) {
          setWatchlist((current) => Array.from(new Set([...symbols, ...current])));
        }
      } catch (err) {
        console.error('Failed to sync screener watchlist:', err);
      }
    };

    void syncWatchlistFromApi();
  }, []);

  useEffect(() => {
    sessionStorage.setItem(
      SCREENER_STATE_STORAGE_KEY,
      JSON.stringify({
        universe,
        timeframe,
        rsiMin,
        rsiMax,
        priceMin,
        priceMax,
        volSpikeMin,
        volSpikeMax,
        pctMin,
        pctMax,
        retMin,
        retMax,
        sortBy,
        sortOrder,
        customTickers,
        results,
        ran,
        matchCount,
        lastUpdated,
      })
    );
  }, [
    universe,
    timeframe,
    rsiMin,
    rsiMax,
    priceMin,
    priceMax,
    volSpikeMin,
    volSpikeMax,
    pctMin,
    pctMax,
    retMin,
    retMax,
    sortBy,
    sortOrder,
    customTickers,
    results,
    ran,
    matchCount,
    lastUpdated,
  ]);

  useEffect(() => {
    const handleScroll = (event: Event) => {
      const target = event.target as HTMLElement;
      setScrollTop(target.scrollTop);
      setViewportHeight(target.clientHeight);
    };

    const scrollParent = containerRef.current?.closest('.overflow-y-auto');
    if (scrollParent) {
      scrollParent.addEventListener('scroll', handleScroll, { passive: true });
      setViewportHeight(scrollParent.clientHeight);
      setScrollTop(scrollParent.scrollTop);
    }

    return () => scrollParent?.removeEventListener('scroll', handleScroll);
  }, []);

  const run = async (overrides?: {
    rsiMin?: string;
    rsiMax?: string;
    priceMin?: string;
    priceMax?: string;
    volSpikeMin?: string;
    volSpikeMax?: string;
    pctMin?: string;
    pctMax?: string;
    retMin?: string;
    retMax?: string;
    universe?: string;
    timeframe?: string;
    sortBy?: string;
    sortOrder?: 'asc' | 'desc';
  }) => {
    const nextUniverse = overrides?.universe ?? universe;
    const nextTimeframe = overrides?.timeframe ?? timeframe;
    const nextSortBy = overrides?.sortBy ?? sortBy;
    const nextSortOrder = overrides?.sortOrder ?? sortOrder;
    const nextRsiMin = overrides?.rsiMin ?? rsiMin;
    const nextRsiMax = overrides?.rsiMax ?? rsiMax;
    const nextPriceMin = overrides?.priceMin ?? priceMin;
    const nextPriceMax = overrides?.priceMax ?? priceMax;
    const nextVolMin = overrides?.volSpikeMin ?? volSpikeMin;
    const nextVolMax = overrides?.volSpikeMax ?? volSpikeMax;
    const nextPctMin = overrides?.pctMin ?? pctMin;
    const nextPctMax = overrides?.pctMax ?? pctMax;
    const nextRetMin = overrides?.retMin ?? retMin;
    const nextRetMax = overrides?.retMax ?? retMax;

    setLoading(true);
    setRan(true);

    try {
      const params = new URLSearchParams({
        universe: nextUniverse,
        timeframe: nextTimeframe,
        sort_by: nextSortBy,
        sort_order: nextSortOrder,
      });

      if (nextRsiMin) params.set('rsi_min', nextRsiMin);
      if (nextRsiMax) params.set('rsi_max', nextRsiMax);
      if (nextPriceMin) params.set('price_min', nextPriceMin);
      if (nextPriceMax) params.set('price_max', nextPriceMax);
      if (nextVolMin) params.set('vol_spike_min', nextVolMin);
      if (nextVolMax) params.set('vol_spike_max', nextVolMax);
      if (nextPctMin) params.set('pct_from_52wh_min', nextPctMin);
      if (nextPctMax) params.set('pct_from_52wh_max', nextPctMax);
      if (nextRetMin) params.set('min_return_1w', nextRetMin);
      if (nextRetMax) params.set('max_return_1w', nextRetMax);
      if (nextUniverse === 'CUSTOM' && customTickers) params.set('custom_tickers', customTickers);

      const response = await fetch(`/api/screener?${params}`, {
        headers: { 'X-API-Key': API_KEY() },
      });
      const data = await response.json();

      setResults(data.results || []);
      setMatchCount(data.match_count ?? 0);
      setLastUpdated(data.last_updated ?? null);
    } catch (err) {
      console.error('Screener fetch error:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!ran) return;

    const intervalId = window.setInterval(() => {
      void run();
    }, AUTO_REFRESH_MS);

    return () => window.clearInterval(intervalId);
  }, [
    ran,
    universe,
    timeframe,
    rsiMin,
    rsiMax,
    priceMin,
    priceMax,
    volSpikeMin,
    volSpikeMax,
    pctMin,
    pctMax,
    retMin,
    retMax,
    sortBy,
    sortOrder,
    customTickers,
  ]);

  const selectTimeframe = (nextTimeframe: string) => {
    setTimeframe(nextTimeframe);
    if (ran) void run({ timeframe: nextTimeframe });
  };

  const applyQuickFilter = (filters: QuickFilterSet) => {
    setRsiMin(filters.rsiMin ?? '');
    setRsiMax(filters.rsiMax ?? '');
    setPriceMin(filters.priceMin ?? '');
    setPriceMax(filters.priceMax ?? '');
    setVolSpikeMin(filters.volSpikeMin ?? '');
    setVolSpikeMax(filters.volSpikeMax ?? '');
    setPctMin(filters.pctMin ?? '');
    setPctMax(filters.pctMax ?? '');
    setRetMin(filters.retMin ?? '');
    setRetMax(filters.retMax ?? '');
    void run(filters);
  };

  const clearFilters = () => {
    setRsiMin('');
    setRsiMax('');
    setPriceMin('');
    setPriceMax('');
    setVolSpikeMin('');
    setVolSpikeMax('');
    setPctMin('');
    setPctMax('');
    setRetMin('');
    setRetMax('');
  };

  const toggleWatchlist = async (symbol: string) => {
    const normalized = symbol.toUpperCase();
    const isSaved = watchlist.includes(normalized);

    setWatchlist((current) =>
      isSaved
        ? current.filter((item) => item !== normalized)
        : [normalized, ...current].slice(0, 50)
    );

    try {
      if (isSaved) {
        const response = await fetch(`/api/watchlist/${encodeURIComponent(normalized)}`, {
          method: 'DELETE',
          headers: WATCHLIST_API_HEADERS(),
        });
        if (!response.ok) throw new Error(`Failed to remove ${normalized}`);
      } else {
        const response = await fetch('/api/watchlist', {
          method: 'POST',
          headers: WATCHLIST_API_HEADERS(),
          body: JSON.stringify({ symbol: normalized, note: 'Saved from Screener' }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({ detail: 'Unknown error' }));
          const detail = typeof errorData?.detail === 'string' ? errorData.detail : 'Unknown error';
          if (!detail.toLowerCase().includes('already')) {
            throw new Error(detail);
          }
        }
      }
    } catch (err) {
      console.error('Failed to sync watchlist action:', err);
      setWatchlist((current) =>
        isSaved
          ? [normalized, ...current].slice(0, 50)
          : current.filter((item) => item !== normalized)
      );
    }
  };

  const copySymbol = async (symbol: string) => {
    try {
      await navigator.clipboard.writeText(symbol);
    } catch (err) {
      console.error('Failed to copy symbol:', err);
    }
  };

  const openChart = (symbol: string) => {
    const target = universe === 'CRYPTO' ? `${symbol}-USD` : symbol;
    window.open(`https://finance.yahoo.com/quote/${encodeURIComponent(target)}`, '_blank', 'noopener,noreferrer');
  };

  const Field = ({ label, value, setValue, placeholder }: {
    label: string;
    value: string;
    setValue: (nextValue: string) => void;
    placeholder: string;
  }) => (
    <div className="space-y-1.5">
      <label className={`text-[11px] font-black uppercase tracking-widest ${
        theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
      }`}>{label}</label>
      <input
        value={value}
        onChange={(event) => setValue(event.target.value)}
        placeholder={placeholder}
        className={`w-full px-3 py-2.5 border rounded-xl text-sm font-mono transition-all focus:outline-none ${
          theme === 'dark'
            ? 'bg-slate-900/60 border-white/10 text-white placeholder:text-slate-700 focus:border-blue-500/40'
            : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500/30 shadow-sm'
        }`}
      />
    </div>
  );

  const timeframeLabel = TIMEFRAMES.find((item) => item.key === timeframe)?.label ?? timeframe.toUpperCase();
  const getFreshness = (value: string | null) => {
    if (!value) return null;

    const updatedAt = new Date(value);
    if (Number.isNaN(updatedAt.getTime())) return null;

    const ageMs = Date.now() - updatedAt.getTime();
    const ageMinutes = Math.max(0, Math.floor(ageMs / 60000));
    const ageLabel =
      ageMinutes < 1 ? 'just now' :
      ageMinutes < 60 ? `${ageMinutes}m ago` :
      ageMinutes < 1440 ? `${Math.floor(ageMinutes / 60)}h ago` :
      `${Math.floor(ageMinutes / 1440)}d ago`;
    const freshnessTone = ageMinutes < 1 ? 'live' : ageMinutes < 5 ? 'warm' : 'stale';
    const freshnessLabel = ageMinutes < 1 ? 'Live' : ageMinutes < 5 ? 'Fresh' : 'Stale';
    const clockLabel = updatedAt.toLocaleString(undefined, {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });

    return { ageLabel, clockLabel, freshnessTone, freshnessLabel };
  };

  const freshness = getFreshness(lastUpdated);
  const topAi = results.reduce<ScreenerResult | null>(
    (best, item) => ((item.ai_score ?? -1) > (best?.ai_score ?? -1) ? item : best),
    null
  );
  const topVolume = results.reduce<ScreenerResult | null>(
    (best, item) => (item.vol_ratio > (best?.vol_ratio ?? -1) ? item : best),
    null
  );
  const mostOversold = results.reduce<ScreenerResult | null>(
    (best, item) => (item.rsi < (best?.rsi ?? Number.POSITIVE_INFINITY) ? item : best),
    null
  );
  const strongestMove = results.reduce<ScreenerResult | null>((best, item) => {
    const itemReturn = item.return_pct ?? item.return_1w_pct;
    const bestReturn = best ? (best.return_pct ?? best.return_1w_pct) : Number.NEGATIVE_INFINITY;
    return itemReturn > bestReturn ? item : best;
  }, null);

  const summaryCards = [
    { label: 'Matches', value: matchCount.toLocaleString(), detail: `${universe} ${timeframeLabel}`, accent: 'text-blue-400' },
    { label: 'Top AI', value: topAi?.symbol ?? 'N/A', detail: topAi ? `${(topAi.ai_score ?? 0).toFixed(1)}% score` : 'Run a scan', accent: 'text-emerald-400' },
    { label: 'Volume Spike', value: topVolume?.symbol ?? 'N/A', detail: topVolume ? `${topVolume.vol_ratio.toFixed(1)}x volume` : 'Run a scan', accent: 'text-amber-400' },
    { label: 'Most Oversold', value: mostOversold?.symbol ?? 'N/A', detail: mostOversold ? `RSI ${mostOversold.rsi.toFixed(1)}` : 'Run a scan', accent: 'text-rose-400' },
    { label: 'Momentum', value: strongestMove?.symbol ?? 'N/A', detail: strongestMove ? `${(strongestMove.return_pct ?? strongestMove.return_1w_pct).toFixed(2)}%` : 'Run a scan', accent: 'text-cyan-400' },
  ];

  const quickFilters = [
    { label: 'RSI < 30', filters: { rsiMax: '30' } },
    { label: 'Vol > 2x', filters: { volSpikeMin: '2' } },
    { label: 'Ret > 5%', filters: { retMin: '5' } },
    { label: 'AI + Vol', filters: { volSpikeMin: '1.8', retMin: '2', rsiMin: '45' } },
    { label: 'Cheap < $20', filters: { priceMax: '20' } },
    { label: 'Near High', filters: { pctMax: '5' } },
  ];

  const presetFilters = [
    { label: t('screener.preset_oversold'), filters: { rsiMax: '45', volSpikeMin: '1.2', pctMax: '40', rsiMin: '', retMin: '', retMax: '', priceMin: '', priceMax: '', volSpikeMax: '', pctMin: '' } },
    { label: t('screener.preset_breakout'), filters: { volSpikeMin: '2', rsiMin: '50', rsiMax: '', pctMax: '', retMin: '3', retMax: '', priceMin: '', priceMax: '', volSpikeMax: '', pctMin: '' } },
    { label: t('screener.preset_momentum'), filters: { retMin: '5', volSpikeMin: '1.5', rsiMin: '55', rsiMax: '', pctMax: '', retMax: '', priceMin: '', priceMax: '', volSpikeMax: '', pctMin: '' } },
    { label: t('screener.preset_monster'), filters: { volSpikeMin: '3', retMin: '7', rsiMin: '60', rsiMax: '', pctMax: '', retMax: '', priceMin: '', priceMax: '', volSpikeMax: '', pctMin: '' } },
    { label: t('screener.preset_bottom'), filters: { rsiMax: '30', volSpikeMin: '1.0', pctMin: '40', rsiMin: '', retMin: '', retMax: '', priceMin: '', priceMax: '', volSpikeMax: '', pctMax: '' } },
    { label: t('screener.preset_high'), filters: { pctMax: '5', rsiMin: '55', volSpikeMin: '1.5', rsiMax: '', retMin: '', retMax: '', priceMin: '', priceMax: '', volSpikeMax: '', pctMin: '' } },
    { label: t('screener.preset_penny'), filters: { priceMax: '5', volSpikeMin: '2.5', retMin: '10', rsiMin: '', rsiMax: '', pctMax: '', retMax: '', priceMin: '', volSpikeMax: '', pctMin: '' } },
  ];

  return (
    <div ref={containerRef} className={`flex flex-col p-8 space-y-6 transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950/20' : 'bg-slate-50'
    }`}>
      <header className={`flex justify-between items-center border-b pb-8 transition-colors duration-500 ${
        theme === 'dark' ? 'border-white/5' : 'border-slate-200'
      }`}>
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-blue-500 font-bold text-xs uppercase tracking-[0.2em]">
            <SlidersHorizontal className="w-3.5 h-3.5" />
            {t('screener.badge')}
          </div>
          <h2 className={`text-3xl font-extrabold tracking-tight transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>{t('screener.title')}</h2>
          <p className={`text-sm transition-colors duration-500 ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}>{t('screener.subtitle')}</p>
        </div>
      </header>

      <div className={`flex items-center gap-2 px-4 py-2.5 border rounded-xl transition-all duration-500 ${
        theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-amber-50/50 border-amber-100'
      }`}>
        <Zap className="w-3.5 h-3.5 text-amber-400 shrink-0" />
        <p className={`text-xs transition-colors duration-500 ${
          theme === 'dark' ? 'text-slate-500' : 'text-slate-600'
        }`}>{t('screener.disclaimer')}</p>
      </div>

      <div className="grid grid-cols-2 xl:grid-cols-5 gap-3">
        {summaryCards.map((card) => (
          <div
            key={card.label}
            className={`p-4 border rounded-2xl transition-all duration-500 ${
              theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
            }`}
          >
            <p className={`text-[10px] font-black uppercase tracking-[0.2em] ${
              theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
            }`}>{card.label}</p>
            <p className={`mt-2 text-xl font-black ${card.accent}`}>{card.value}</p>
            <p className={`mt-1 text-xs ${
              theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
            }`}>{card.detail}</p>
          </div>
        ))}
      </div>

      <div className={`p-6 border rounded-[2rem] space-y-5 transition-all duration-500 ${
        theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
      }`}>
        <div className="space-y-2">
          <p className={`text-[11px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}>{t('screener.universe')}</p>
          <div className="flex gap-2 flex-wrap">
            {UNIVERSES.map((item) => (
              <button
                key={item}
                onClick={() => setUniverse(item)}
                className={`px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-widest border transition-all duration-300 ${
                  universe === item
                    ? theme === 'dark'
                      ? 'bg-blue-600/20 border-blue-500/40 text-blue-400 font-black'
                      : 'bg-blue-600 border-blue-600 text-white shadow-lg shadow-blue-100'
                    : theme === 'dark'
                      ? 'bg-transparent border-white/10 text-slate-500 hover:text-white'
                      : 'bg-white border-slate-200 text-slate-500 hover:text-slate-900 shadow-sm hover:border-slate-300'
                }`}
              >
                {item === 'SMALL_CAP' ? t('screener.small_cap') : item}
              </button>
            ))}
          </div>
          {universe === 'CUSTOM' && (
            <div className="space-y-1.5 mt-2">
              <label className={`text-[11px] font-black uppercase tracking-widest ${
                theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
              }`}>{t('screener.custom_tickers')}</label>
              <input
                value={customTickers}
                onChange={(event) => setCustomTickers(event.target.value)}
                placeholder="e.g. EOSE, RKLB, IONQ, ASTS"
                className={`w-full px-3 py-2.5 border rounded-xl text-sm font-mono transition-all focus:outline-none ${
                  theme === 'dark'
                    ? 'bg-slate-900/60 border-blue-500/20 text-white placeholder:text-slate-700 focus:border-blue-500/40'
                    : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500/30 shadow-sm'
                }`}
              />
            </div>
          )}
        </div>

        <div className="space-y-2">
          <p className={`text-[11px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}>TIMEFRAME</p>
          <div className={`grid grid-cols-3 sm:grid-cols-6 gap-1.5 p-1 border rounded-2xl ${
            theme === 'dark' ? 'bg-slate-950/50 border-white/10' : 'bg-slate-50 border-slate-200'
          }`}>
            {TIMEFRAMES.map((item) => (
              <button
                key={item.key}
                onClick={() => selectTimeframe(item.key)}
                className={`h-10 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                  timeframe === item.key
                    ? theme === 'dark'
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/30'
                      : 'bg-blue-600 text-white shadow-md shadow-blue-100'
                    : theme === 'dark'
                      ? 'text-slate-500 hover:text-white hover:bg-white/5'
                      : 'text-slate-500 hover:text-slate-900 hover:bg-white'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
          <Field label={t('screener.price_min')} value={priceMin} setValue={setPriceMin} placeholder="e.g. 10" />
          <Field label={t('screener.price_max')} value={priceMax} setValue={setPriceMax} placeholder="e.g. 500" />
          <Field label={t('screener.rsi_min')} value={rsiMin} setValue={setRsiMin} placeholder="e.g. 20" />
          <Field label={t('screener.rsi_max')} value={rsiMax} setValue={setRsiMax} placeholder="e.g. 35" />
          <Field label={t('screener.vol_spike_min')} value={volSpikeMin} setValue={setVolSpikeMin} placeholder="e.g. 2.0" />
          <Field label={t('screener.vol_spike_max')} value={volSpikeMax} setValue={setVolSpikeMax} placeholder="e.g. 5.0" />
          <Field label={t('screener.pct_52w_min')} value={pctMin} setValue={setPctMin} placeholder="e.g. 5" />
          <Field label={t('screener.pct_52w_max')} value={pctMax} setValue={setPctMax} placeholder="e.g. 20" />
          <Field label={t('screener.ret_min')} value={retMin} setValue={setRetMin} placeholder="e.g. -5" />
          <Field label={t('screener.ret_max')} value={retMax} setValue={setRetMax} placeholder="e.g. 5" />
        </div>

        <div className="flex gap-2 flex-wrap items-center">
          <span className={`text-[11px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
          }`}>Quick Filters</span>
          {quickFilters.map((item) => (
            <button
              key={item.label}
              onClick={() => applyQuickFilter(item.filters)}
              className={`px-3 py-2 text-[10px] font-black uppercase tracking-widest border rounded-xl transition-all ${
                theme === 'dark'
                  ? 'bg-slate-950/50 border-white/10 text-slate-400 hover:text-white hover:border-blue-500/50'
                  : 'bg-slate-50 border-slate-200 text-slate-600 hover:text-slate-900 hover:border-blue-300'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex gap-2 flex-wrap items-center">
          <span className={`text-[11px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
          }`}>{t('screener.presets')}</span>
          {presetFilters.map((item) => (
            <button
              key={item.label}
              onClick={() => applyQuickFilter(item.filters)}
              className={`px-3 py-1.5 text-[10px] font-black uppercase tracking-widest border rounded-xl transition-all shadow-sm active:scale-95 ${
                theme === 'dark'
                  ? 'border-white/10 text-slate-500 hover:text-blue-400 hover:border-blue-500/50 bg-slate-900/40'
                  : 'border-blue-100 bg-blue-50/50 text-blue-600 hover:bg-blue-100 hover:border-blue-300'
              }`}
            >
              {item.label}
            </button>
          ))}
          <button
            onClick={clearFilters}
            className={`px-3 py-1.5 text-[10px] font-black uppercase tracking-widest border rounded-xl transition-all ml-auto ${
              theme === 'dark' ? 'border-rose-500/20 text-rose-500/60 hover:text-rose-400' : 'border-rose-200 bg-rose-50 text-rose-500 hover:bg-rose-100'
            }`}
          >
            {t('screener.clear')}
          </button>
        </div>

        <button
          onClick={() => void run()}
          disabled={loading}
          className="w-full flex items-center justify-center gap-3 py-4 bg-blue-600 hover:bg-blue-500 rounded-2xl text-white font-black text-sm transition-all disabled:opacity-50 shadow-lg shadow-blue-500/20"
        >
          <Search className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {loading ? `${t('screener.scanning')} ${universe} ${timeframeLabel}...` : `${t('screener.scan')} ${universe} ${timeframeLabel}`}
        </button>
      </div>

      {ran && (
        <div className={`border rounded-[2rem] overflow-hidden transition-all duration-500 ${
          theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-sm'
        }`}>
          <div className={`px-6 py-4 border-b flex flex-col gap-3 md:flex-row md:items-center md:justify-between transition-colors duration-500 ${
            theme === 'dark' ? 'border-white/5' : 'border-slate-100'
          }`}>
            <p className={`text-sm font-black transition-colors duration-500 ${
              theme === 'dark' ? 'text-slate-300' : 'text-slate-700'
            }`}>
              {t('screener.found')} <span className="text-blue-400">{matchCount}</span> {t('screener.matches')}
              {lastUpdated && (
                <span className={`ml-3 text-[10px] font-bold uppercase tracking-widest ${
                  theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
                }`}>
                  Updated {new Date(lastUpdated).toLocaleTimeString()}
                </span>
              )}
            </p>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              {freshness && (
                <div className={`flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 border rounded-xl ${
                  theme === 'dark' ? 'bg-slate-950/40 border-white/10' : 'bg-slate-50 border-slate-200'
                }`}>
                  <span className={`text-[10px] font-black uppercase tracking-widest ${
                    theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                  }`}>Snapshot</span>
                  <span className={`text-xs font-black ${
                    theme === 'dark' ? 'text-white' : 'text-slate-900'
                  }`}>{timeframeLabel}</span>
                  <span className={`inline-flex items-center px-2 py-1 rounded-full text-[10px] font-black uppercase tracking-widest ${
                    freshness.freshnessTone === 'live'
                      ? 'bg-emerald-500/15 text-emerald-400'
                      : freshness.freshnessTone === 'warm'
                        ? 'bg-amber-500/15 text-amber-400'
                        : 'bg-rose-500/15 text-rose-400'
                  }`}>
                    {freshness.freshnessLabel}
                  </span>
                  <span className={`text-xs font-bold ${
                    theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
                  }`}>Updated {freshness.clockLabel}</span>
                  <span className="text-xs font-black text-blue-400">{freshness.ageLabel}</span>
                  <span className={`text-[10px] font-bold uppercase tracking-widest ${
                    theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                  }`}>Auto {AUTO_REFRESH_MS / 1000}s</span>
                  <button
                    onClick={() => void run()}
                    disabled={loading}
                    className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                      theme === 'dark'
                        ? 'bg-white/5 text-slate-300 hover:bg-white/10 disabled:opacity-50'
                        : 'bg-white text-slate-600 hover:bg-slate-100 border border-slate-200 disabled:opacity-50'
                    }`}
                  >
                    <RefreshCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
                    Refresh
                  </button>
                </div>
              )}
              {results.length > 0 && (
                <p className="text-[11px] text-slate-600 font-bold uppercase tracking-widest">
                  {t('screener.sorted_by')} {sortBy.replace('_', ' ')} ({sortOrder})
                </p>
              )}
            </div>
          </div>

          <div ref={tableRef} className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className={`border-b transition-colors duration-500 ${
                  theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'border-slate-100 bg-slate-50/50'
                }`}>
                  {[
                    { key: 'symbol', label: t('screener.symbol') },
                    { key: 'price', label: t('screener.price') },
                    { key: 'ai_score', label: 'AI SCORE' },
                    { key: 'rsi', label: t('screener.rsi_col') },
                    { key: 'vol_ratio', label: t('screener.vol_col') },
                    { key: 'pct_from_52wh', label: t('screener.pct_col') },
                    { key: 'return_1w_pct', label: `${timeframeLabel} ${t('screener.ret_col')}` },
                    { key: 'actions', label: 'Actions' },
                  ].map((header) => (
                    <th
                      key={header.key}
                      onClick={header.key === 'actions' ? undefined : () => {
                        const nextOrder = sortBy === header.key && sortOrder === 'desc' ? 'asc' : 'desc';
                        setSortBy(header.key);
                        setSortOrder(nextOrder);
                        void run({ sortBy: header.key, sortOrder: nextOrder });
                      }}
                      className={`px-5 py-4 text-xs font-bold uppercase tracking-[0.15em] transition-colors ${
                        header.key === 'actions' ? 'text-slate-500' : 'cursor-pointer hover:bg-white/5'
                      } ${
                        sortBy === header.key ? 'text-blue-400' : 'text-slate-500'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        {header.label}
                        {sortBy === header.key && header.key !== 'actions' && (
                          <span className="text-[10px]">{sortOrder === 'desc' ? '▼' : '▲'}</span>
                        )}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>

              <tbody className={`divide-y transition-colors duration-500 ${
                theme === 'dark' ? 'divide-white/5' : 'divide-slate-100'
              }`}>
                <AnimatePresence>
                  {loading
                    ? [1, 2, 3].map((item) => (
                      <tr key={item} className="animate-pulse">
                        <td colSpan={8} className="px-5 py-5">
                          <div className={`h-4 rounded-full ${
                            theme === 'dark' ? 'bg-slate-800/50' : 'bg-slate-100'
                          }`} />
                        </td>
                      </tr>
                    ))
                    : results.length === 0
                      ? (
                        <tr>
                          <td colSpan={8} className="px-5 py-20 text-center">
                            <Zap className={`w-8 h-8 mx-auto mb-3 ${
                              theme === 'dark' ? 'text-slate-600' : 'text-slate-300'
                            }`} />
                            <p className={`font-bold ${
                              theme === 'dark' ? 'text-slate-500' : 'text-slate-600'
                            }`}>{t('screener.no_results')}</p>
                            <p className="text-slate-600 text-sm mt-1">{t('screener.relax')}</p>
                          </td>
                        </tr>
                      )
                      : (() => {
                        const tableOffsetTop = tableRef.current?.offsetTop || 0;
                        const relativeScrollTop = Math.max(0, scrollTop - tableOffsetTop);
                        const startIndex = Math.max(0, Math.floor(relativeScrollTop / rowHeight) - buffer);
                        const endIndex = Math.min(results.length, Math.ceil((relativeScrollTop + viewportHeight) / rowHeight) + buffer);
                        const visibleRows = results.slice(startIndex, endIndex);
                        const paddingTop = startIndex * rowHeight;
                        const paddingBottom = (results.length - endIndex) * rowHeight;

                        return (
                          <>
                            {paddingTop > 0 && <tr style={{ height: paddingTop }} aria-hidden="true"><td colSpan={8} /></tr>}
                            {visibleRows.map((result) => {
                              const rowReturn = result.return_pct ?? result.return_1w_pct;
                              const pctFromHigh = result.pct_from_period_high ?? result.pct_from_52wh;
                              const isWatched = watchlist.includes(result.symbol);
                              const retUp = rowReturn >= 0;
                              const rsiColor = result.rsi < 30
                                ? theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'
                                : result.rsi > 70
                                  ? theme === 'dark' ? 'text-rose-400' : 'text-rose-600'
                                  : theme === 'dark' ? 'text-slate-300' : 'text-slate-600';

                              return (
                                <motion.tr
                                  key={`${result.symbol}-${timeframe}`}
                                  initial={false}
                                  style={{ height: rowHeight }}
                                  className={`transition-colors border-b last:border-0 ${
                                    theme === 'dark'
                                      ? 'hover:bg-white/[0.02] border-white/5'
                                      : 'hover:bg-slate-50 border-slate-100'
                                  }`}
                                >
                                  <td className="px-5 py-4">
                                    <div className="flex items-center gap-2">
                                      <button
                                        onClick={() => toggleWatchlist(result.symbol)}
                                        className={`transition-colors ${
                                          isWatched ? 'text-amber-400' : theme === 'dark' ? 'text-slate-600 hover:text-amber-400' : 'text-slate-300 hover:text-amber-500'
                                        }`}
                                        title={isWatched ? 'Remove from watchlist' : 'Add to watchlist'}
                                      >
                                        <Star className={`w-4 h-4 ${isWatched ? 'fill-current' : ''}`} />
                                      </button>
                                      <div className="flex flex-col">
                                        <span className={`font-black transition-colors ${
                                          theme === 'dark' ? 'text-white' : 'text-slate-900'
                                        }`}>{result.symbol}</span>
                                        <span className={`text-[10px] font-bold uppercase tracking-widest ${
                                          theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
                                        }`}>{result.timeframe ?? timeframeLabel}</span>
                                      </div>
                                    </div>
                                  </td>

                                  <td className={`px-5 py-4 font-mono text-sm transition-colors ${
                                    theme === 'dark' ? 'text-slate-300' : 'text-slate-600'
                                  }`}>${result.price.toLocaleString()}</td>

                                  <td className="px-5 py-4">
                                    <div className="flex flex-col">
                                      <span className={`inline-flex items-center gap-2 text-sm font-black ${
                                        (result.ai_score ?? 0) >= 75 ? 'text-emerald-400' :
                                        (result.ai_score ?? 0) >= 50 ? 'text-amber-400' : 'text-rose-400'
                                      }`}>
                                        {(result.ai_score ?? 0) >= 80 && (
                                          <span className="px-1.5 py-0.5 rounded-md bg-emerald-500/15 text-[9px] uppercase tracking-widest">Hot</span>
                                        )}
                                        {result.ai_score?.toFixed(1)}%
                                      </span>
                                      <span className="text-[9px] text-slate-600 uppercase font-black truncate max-w-[120px]" title={result.rationale}>
                                        {result.rationale}
                                      </span>
                                    </div>
                                  </td>

                                  <td className="px-5 py-4 font-mono text-sm">
                                    <span className={`font-black ${rsiColor}`}>{result.rsi.toFixed(1)}</span>
                                  </td>

                                  <td className="px-5 py-4 font-mono text-sm">
                                    <span className={`font-black ${
                                      result.vol_ratio >= 3 ? theme === 'dark' ? 'text-amber-400' : 'text-amber-600'
                                      : result.vol_ratio >= 2 ? theme === 'dark' ? 'text-blue-400' : 'text-blue-600'
                                      : theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                                    }`}>
                                      {result.vol_ratio.toFixed(1)}x
                                    </span>
                                  </td>

                                  <td className={`px-5 py-4 font-mono text-sm transition-colors ${
                                    theme === 'dark' ? 'text-slate-400' : 'text-slate-500'
                                  }`}>{pctFromHigh.toFixed(1)}%</td>

                                  <td className="px-5 py-4">
                                    <span className={`flex items-center gap-1 font-black font-mono text-sm ${
                                      retUp
                                        ? theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'
                                        : theme === 'dark' ? 'text-rose-400' : 'text-rose-600'
                                    }`}>
                                      {retUp ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                                      {retUp ? '+' : ''}{rowReturn.toFixed(2)}%
                                    </span>
                                  </td>

                                  <td className="px-5 py-4">
                                    <div className="flex flex-wrap gap-2">
                                      <button
                                        onClick={() => void copySymbol(result.symbol)}
                                        className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                                          theme === 'dark'
                                            ? 'bg-white/5 text-slate-300 hover:bg-white/10'
                                            : 'bg-slate-50 text-slate-600 hover:bg-slate-100 border border-slate-200'
                                        }`}
                                      >
                                        <Copy className="w-3 h-3" />
                                        Copy
                                      </button>
                                      <button
                                        onClick={() => toggleWatchlist(result.symbol)}
                                        className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                                          isWatched
                                            ? 'bg-amber-500/15 text-amber-400'
                                            : theme === 'dark'
                                              ? 'bg-white/5 text-slate-300 hover:bg-white/10'
                                              : 'bg-slate-50 text-slate-600 hover:bg-slate-100 border border-slate-200'
                                        }`}
                                      >
                                        <Star className={`w-3 h-3 ${isWatched ? 'fill-current' : ''}`} />
                                        {isWatched ? 'Saved' : 'Watch'}
                                      </button>
                                      <button
                                        onClick={() => openChart(result.symbol)}
                                        className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                                          theme === 'dark'
                                            ? 'bg-blue-500/10 text-blue-300 hover:bg-blue-500/20'
                                            : 'bg-blue-50 text-blue-600 hover:bg-blue-100 border border-blue-100'
                                        }`}
                                      >
                                        <ExternalLink className="w-3 h-3" />
                                        Chart
                                      </button>
                                    </div>
                                  </td>
                                </motion.tr>
                              );
                            })}
                            {paddingBottom > 0 && <tr style={{ height: paddingBottom }} aria-hidden="true"><td colSpan={8} /></tr>}
                          </>
                        );
                      })()}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};
