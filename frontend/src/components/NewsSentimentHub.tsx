import { useState, useEffect, useRef, useCallback, memo } from 'react';
import { createChart, ColorType, AreaSeries, type ISeriesApi } from 'lightweight-charts';
import { motion, AnimatePresence } from 'framer-motion';
import { useMode } from '../contexts/ModeContext';
import {
  BrainCircuit, RefreshCcw, Activity, Globe,
  TrendingUp, TrendingDown, Minus, Newspaper,
  ShieldAlert, BarChart3, Wifi, WifiOff, Clock,
  ExternalLink, ChevronDown, ChevronUp, Zap
} from 'lucide-react';
import { HoverGlowCard } from './HoverGlowCard';

// ────────────────────────────────────────────────────────────────
// Types
// ────────────────────────────────────────────────────────────────
interface FGHistory {
  value: number;
  label: string;
}

interface FGData {
  value: number;
  label: string;
  timestamp?: string;
  history?: {
    yesterday: FGHistory;
    last_week: FGHistory;
    last_month: FGHistory;
  };
}

interface IndexData {
  name: string;
  price: number;
  change_pct: number;
  previous_close: number;
  series: { time: number; value: number }[];
}

interface IndicesData {
  nasdaq: IndexData;
  dow: IndexData;
  sp500: IndexData;
  dxy: IndexData;
}

interface NewsArticle {
  title: string;
  summary: string;
  source: string;
  published: string;
  link: string;
}

interface SentimentData {
  overall: {
    sentiment: string;
    score: number;
    summary: string;
    key_factors?: string[];
  };
  articles: NewsArticle[];
}

interface DataStatus {
  loading: boolean;
  error: boolean;
  lastUpdate: Date | null;
}

// ────────────────────────────────────────────────────────────────
// Institutional Chart Component (Powered by lightweight-charts)
// ────────────────────────────────────────────────────────────────
const InstitutionalChart = memo(({ 
  data, 
  color = '#6366f1', 
  height = 180,
  showPriceScale = false,
  showTimeScale = false
}: { 
  data: { time: number; value: number }[]; 
  color?: string;
  height?: number;
  showPriceScale?: boolean;
  showTimeScale?: boolean;
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  const { theme } = useMode();

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: theme === 'dark' ? '#94a3b8' : '#64748b',
        fontSize: 10,
      },
      grid: {
        vertLines: { color: theme === 'dark' ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)' },
        horzLines: { color: theme === 'dark' ? 'rgba(255, 255, 255, 0.03)' : 'rgba(0, 0, 0, 0.03)' },
      },
      rightPriceScale: {
        visible: showPriceScale,
        borderVisible: false,
      },
      timeScale: {
        visible: showTimeScale,
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
    });

    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor: color,
      topColor: color + '22',
      bottomColor: color + '00',
      lineWidth: 2,
      priceLineVisible: false,
      crosshairMarkerVisible: true,
    });

    seriesRef.current = areaSeries;
    chartRef.current = chart;

    const handleResize = () => {
      chart.applyOptions({ width: chartContainerRef.current?.clientWidth });
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
    // Removed color from dependencies to prevent re-creating chart on price direction change
  }, [height, showPriceScale, showTimeScale]);

  // Update series options when color changes without re-creating the entire chart
  useEffect(() => {
    if (seriesRef.current) {
      seriesRef.current.applyOptions({
        lineColor: color,
        topColor: color + '22',
        bottomColor: color + '00',
      });
    }
  }, [color]);

  useEffect(() => {
    if (seriesRef.current && data && data.length > 0) {
      // Filter out duplicate timestamps and sort to prevent Lightweight Charts crash
      const uniqueData = data.reduce((acc, current) => {
        const x = acc.find(item => item.time === current.time);
        if (!x) {
          return acc.concat([current]);
        } else {
          return acc;
        }
      }, [] as { time: number; value: number }[]);
      
      const sorted = [...uniqueData]
        .sort((a, b) => a.time - b.time)
        .map(d => ({ time: d.time as any, value: d.value }));
      seriesRef.current.setData(sorted);
      chartRef.current?.timeScale().fitContent();
    }
  }, [data]);

  return <div ref={chartContainerRef} className="w-full h-full" />;
});

// ────────────────────────────────────────────────────────────────
// Needle Gauge (reusable, same as before)
// ────────────────────────────────────────────────────────────────
const getZone = (score: number) => {
  if (score <= 25) return { label: 'Extreme Fear', hex: '#E11D48', short: 'X.FEAR' };
  if (score <= 45) return { label: 'Fear', hex: '#F97316', short: 'FEAR' };
  if (score <= 55) return { label: 'Neutral', hex: '#F59E0B', short: 'NEUTRAL' };
  if (score <= 75) return { label: 'Greed', hex: '#10B981', short: 'GREED' };
  return { label: 'Extreme Greed', hex: '#22C55E', short: 'X.GREED' };
};

// ────────────────────────────────────────────────────────────────
// Modern Radial Gauge (The "Interesting" Neon Circle)
// ────────────────────────────────────────────────────────────────
const ModernRadialGauge = ({
  title, score, subtitle, Icon, badge, children, status, sourceUrl,
}: {
  title: string;
  score: number;
  subtitle?: string;
  Icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  children?: React.ReactNode;
  status?: DataStatus;
  sourceUrl?: string;
}) => {
  const { theme } = useMode();
  const safeScore = isNaN(score) ? 50 : score;
  const clampedScore = Math.max(0, Math.min(100, safeScore));
  const zone = getZone(clampedScore);
  const uid = `r${title.replace(/\W/g, '')}`;

  // SVG parameters for the ring
  const size = 150;
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  // Offset to leave a 1/4 gap at the bottom (270-degree arc)
  const arcLength = circumference * 0.75;
  const dashOffset = arcLength - (clampedScore / 100) * arcLength;

  return (
    <div className={`rounded-2xl border shadow-2xl p-5 flex flex-col items-center gap-5 relative overflow-hidden group transition-all duration-500 ${
      theme === 'dark' ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200'
    }`}>
      {/* Background Glow */}
      <div 
        className="absolute inset-0 opacity-10 blur-[80px] transition-colors duration-1000"
        style={{ backgroundColor: zone.hex }}
      />

      {/* Header Section */}
      <div className="w-full flex justify-between items-start z-10">
        <div className="flex gap-3">
          <div className={`p-1.5 rounded-lg border shadow-lg transition-colors duration-500 ${
            theme === 'dark' ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200'
          }`}>
            <Icon className={`w-4 h-4 ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className={`text-sm font-bold tracking-tight transition-colors duration-500 ${
                theme === 'dark' ? 'text-white' : 'text-slate-900'
              }`}>{title}</h4>
              {sourceUrl && (
                <a 
                  href={sourceUrl} 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className={`p-1.5 rounded-lg border transition-all ${
                    theme === 'dark' 
                      ? 'bg-white/5 hover:bg-blue-500/20 text-slate-500 hover:text-blue-400 border-white/5 hover:border-blue-500/20' 
                      : 'bg-slate-50 hover:bg-blue-50 text-slate-400 hover:text-blue-600 border-slate-200 hover:border-blue-200'
                  }`}
                >
                  <Globe className="w-3.5 h-3.5" />
                </a>
              )}
            </div>
            <p className="text-[10px] text-slate-500 font-medium mt-0.5 uppercase tracking-widest">{subtitle}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
           {badge && (
             <span className={`text-[8px] font-black uppercase tracking-[0.2em] px-2.5 py-1 rounded-lg border shadow-sm ${
               theme === 'dark' 
                 ? 'border-emerald-500/20 bg-emerald-500/5 text-emerald-400/80' 
                 : 'border-emerald-200 bg-emerald-50 text-emerald-700'
             }`}>
               {badge}
             </span>
           )}
           <span 
             className="text-[10px] font-black uppercase tracking-widest px-3.5 py-1 rounded-full border shadow-lg"
             style={{ color: zone.hex, borderColor: zone.hex + '33', background: zone.hex + '11' }}
           >
             {zone.label}
           </span>
        </div>
      </div>

      {/* Main Gauge Circle */}
      <div className="relative flex items-center justify-center z-10 py-2">
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="rotate-[135deg]">
          <defs>
            <filter id={`${uid}-glow`} x="-20%" y="-20%" width="140%" height="140%">
               <feGaussianBlur stdDeviation="4" result="blur" />
               <feComposite in="SourceGraphic" in2="blur" operator="over" />
            </filter>
            <linearGradient id={`${uid}-grad`} x1="0%" y1="0%" x2="100%" y2="0%">
               <stop offset="0%" stopColor="#ef4444" />
               <stop offset="50%" stopColor="#f59e0b" />
               <stop offset="100%" stopColor="#10b981" />
            </linearGradient>
          </defs>
          
          {/* Background Ring Track */}
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" stroke={theme === 'dark' ? '#1e293b' : '#e2e8f0'} strokeWidth={strokeWidth}
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeLinecap="round"
          />

          {/* Color Gradient Reference Track (Faded) */}
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" stroke={`url(#${uid}-grad)`} strokeWidth={strokeWidth}
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeLinecap="round"
            opacity="0.15"
          />

          {/* Active Glowing Progress */}
          <motion.circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none" stroke={zone.hex} strokeWidth={strokeWidth}
            strokeDasharray={`${arcLength} ${circumference}`}
            strokeLinecap="round"
            initial={{ strokeDashoffset: arcLength }}
            animate={{ strokeDashoffset: dashOffset }}
            transition={{ type: 'spring', stiffness: 45, damping: 15 }}
            filter={`url(#${uid}-glow)`}
          />
        </svg>

        {/* Central Readout */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
           <motion.div 
             key={clampedScore}
             initial={{ scale: 0.8, opacity: 0 }}
             animate={{ scale: 1, opacity: 1 }}
             className="flex flex-col items-center"
           >
              <span className={`text-4xl font-black leading-none tracking-tighter shadow-sm transition-colors duration-500 ${
                theme === 'dark' ? 'text-white' : 'text-slate-900'
              }`}>
                {Math.round(clampedScore)}
              </span>
              <div className="flex items-center gap-1 mt-1.5">
                 <div className="w-1 h-1 rounded-full animate-pulse shadow-[0_0_8px_currentColor]" style={{ backgroundColor: zone.hex }} />
                 <span className="text-[9px] font-black text-slate-500 uppercase tracking-[0.15em]">Pulse</span>
              </div>
           </motion.div>
        </div>
      </div>

      {/* Contextual Data / Whale Alerts */}
      <div className="w-full z-10">
        {children ? children : (
           <div className={`flex flex-col gap-4 p-5 rounded-2xl border shadow-inner transition-colors duration-500 ${
             theme === 'dark' ? 'bg-white/[0.03] border-white/5' : 'bg-slate-50 border-slate-200'
           }`}>
              <div className="flex justify-between items-center">
                 <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Sentiment Context</span>
                 <div className={`w-8 h-px ${theme === 'dark' ? 'bg-white/10' : 'bg-slate-200'}`} />
              </div>
              <p className={`text-xs font-medium leading-relaxed transition-colors duration-500 ${
                theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
              }`}>
                Analyzing macro drivers and sentiment pulses across institutional channels...
              </p>
           </div>
        )}
      </div>

      {/* Footer Status */}
      <div className={`w-full pt-4 border-t flex items-center justify-between z-10 transition-colors duration-500 ${
        theme === 'dark' ? 'border-white/5' : 'border-slate-100'
      }`}>
        <div className="flex items-center gap-1.5">
          <div className={`w-1 h-1 rounded-full ${status?.error ? 'bg-rose-500' : status?.loading ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]'} `} />
          <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest">
            {status?.error ? 'Sync Error' : status?.loading ? 'Syncing...' : 'Realtime Feed'}
          </span>
        </div>
        {status?.lastUpdate && (
          <span className="text-[9px] text-slate-600 font-bold uppercase tracking-widest">
            {status.lastUpdate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>
    </div>
  );
};

// ────────────────────────────────────────────────────────────────
// DXY Card — US Dollar Index
// ────────────────────────────────────────────────────────────────
const DXYCard = ({ data, status, news }: { 
  data: IndexData | undefined, 
  status?: DataStatus,
  news?: SentimentData | null 
}) => {
  const { theme } = useMode();
  const sourceUrl = "https://finance.yahoo.com/quote/DX-Y.NYB";
  const newsSourceUrl = "https://www.investing.com/currencies/us-dollar-index-news";
  const price = data?.price || 0;
  const changePct = data?.change_pct || 0;
  const up = changePct >= 0;

  const getZoneColor = (val: number) => {
    if (val < 97) return '#10b981';
    if (val < 104) return '#f59e0b';
    return '#f43f5e';
  };

  const zoneColor = getZoneColor(price);
  const needlePct = Math.min(100, Math.max(0, ((price - 88) / 27) * 100));

  return (
    <div className={`rounded-[2.5rem] border shadow-2xl p-10 flex flex-col h-full relative overflow-hidden group transition-all duration-500 ${
      theme === 'dark' ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200'
    }`}>
      {/* Background Accent */}
      <div className={`absolute top-0 right-0 w-[500px] h-[500px] blur-[120px] pointer-events-none ${
        theme === 'dark' ? 'bg-sky-500/5' : 'bg-sky-400/5'
      }`} />
      
      {/* 1. Header & Primary Price */}
      <div className="flex flex-col gap-8 z-10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`p-2 rounded-lg border shadow-lg transition-colors duration-500 ${
              theme === 'dark' ? 'bg-white/5 border-white/10' : 'bg-slate-50 border-slate-200 shadow-sm'
            }`}>
              <Globe className={`w-4 h-4 ${theme === 'dark' ? 'text-sky-400' : 'text-sky-600'}`} />
            </div>
            <h4 className={`text-base font-black tracking-tight uppercase transition-colors duration-500 ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>US Dollar Index</h4>
          </div>
          <a href={sourceUrl} target="_blank" rel="noopener noreferrer" className={`p-2 rounded-xl border transition-all ${
            theme === 'dark' ? 'bg-white/5 hover:bg-sky-500/20 text-slate-500 hover:text-sky-400 border-white/5' : 'bg-slate-50 hover:bg-sky-50 text-slate-400 hover:text-sky-600 border-slate-200'
          }`}>
            <ExternalLink className="w-4 h-4" />
          </a>
        </div>

        <div className="flex items-baseline gap-4">
          <span className={`text-5xl lg:text-6xl font-black tabular-nums tracking-tighter leading-none transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>
            {price > 0 ? price.toFixed(2) : '—'}
          </span>
          <div className={`flex items-center gap-1 px-3 py-1 rounded-xl text-[11px] font-black shadow-lg ${up ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'}`}>
            {up ? '▲' : '▼'} {Math.abs(changePct).toFixed(2)}%
          </div>
        </div>
      </div>

      {/* 2. Sentiment Gauge (Minimal) */}
      <div className="mt-10 mb-8 z-10 space-y-4">
         <div className={`h-2 w-full rounded-full relative border overflow-hidden transition-colors duration-500 ${
           theme === 'dark' ? 'bg-slate-800/50 border-white/5' : 'bg-slate-200 border-slate-300'
         }`}>
            <div className={`h-full bg-gradient-to-r ${
              theme === 'dark' 
                ? 'from-emerald-500/40 via-amber-500/30 to-rose-500/40' 
                : 'from-emerald-400 via-amber-300 to-rose-400'
            }`} />
            <motion.div
              className={`absolute top-0 bottom-0 w-2 shadow-[0_0_20px_white] z-10 rounded-full ${
                theme === 'dark' ? 'bg-white' : 'bg-slate-800'
              }`}
              initial={{ left: '50%' }}
              animate={{ left: `${isNaN(needlePct) ? 50 : needlePct}%` }}
              transition={{ type: 'spring', stiffness: 40, damping: 15 }}
            />
         </div>
         <div className="flex justify-between text-[10px] font-black uppercase tracking-widest">
            <span className={theme === 'dark' ? 'text-emerald-400/60' : 'text-emerald-600/70'}>Bullish BTC</span>
            <span className="font-black" style={{ color: zoneColor }}>
              {price < 97 ? 'Weak USD' : price < 104 ? 'Neutral' : 'Strong USD'}
            </span>
            <span className={theme === 'dark' ? 'text-rose-400/60' : 'text-rose-600/70'}>Bearish BTC</span>
         </div>
      </div>

      {/* 3. Mid Ticker Tape (Chart) */}
      <div className={`flex-1 min-h-[180px] rounded-[1.5rem] border p-4 shadow-inner z-10 transition-colors duration-500 ${
        theme === 'dark' ? 'bg-slate-950/20 border-white/5' : 'bg-slate-50 border-slate-200'
      }`}>
        {data?.series && data.series.length > 0 ? (
          <InstitutionalChart data={data.series} color={zoneColor} height={180} showPriceScale />
        ) : (
          <div className="w-full h-full flex flex-col items-center justify-center gap-3">
             <RefreshCcw className={`w-6 h-6 animate-spin ${theme === 'dark' ? 'text-slate-800' : 'text-slate-300'}`} />
             <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Syncing Tape...</span>
          </div>
        )}
      </div>

      {/* 4. AI Intelligence Verdict (Consolidated) */}
      <div className={`mt-6 p-6 rounded-[1.5rem] border space-y-4 relative overflow-hidden z-10 transition-colors duration-500 ${
        theme === 'dark' ? 'bg-sky-500/5 border-sky-500/10' : 'bg-sky-50 border-sky-100'
      }`}>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className={`w-4 h-4 ${theme === 'dark' ? 'text-sky-400' : 'text-sky-600'}`} />
            <span className={`text-[11px] font-black uppercase tracking-[0.2em] ${
              theme === 'dark' ? 'text-sky-300' : 'text-sky-700'
            }`}>AI Intelligence Verdict</span>
          </div>
          {newsSourceUrl && (
            <a href={newsSourceUrl} target="_blank" rel="noopener noreferrer" className={`p-1.5 rounded-lg border transition-all ${
              theme === 'dark' ? 'bg-white/5 hover:bg-sky-500/20 text-slate-500 hover:text-sky-300 border-white/5' : 'bg-white hover:bg-sky-50 text-slate-400 hover:text-sky-600 border-slate-200'
            }`}>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          )}
        </div>
        <p className={`text-sm leading-relaxed font-medium transition-colors duration-500 ${
          theme === 'dark' ? 'text-slate-300' : 'text-slate-600'
        }`}>
          {news?.overall?.summary || "Analyzing current macro drivers for Dollar strength..."}
        </p>
      </div>
    </div>
  );
};

// ────────────────────────────────────────────────────────────────
// Market Indices Card (Nasdaq + Dow)
// ────────────────────────────────────────────────────────────────
const IndexRow = memo(({ d, label }: { d?: IndexData; label: string }) => {
  const { theme } = useMode();
  if (!d) return null;
  const up = d.change_pct >= 0;
  const Icon = up ? TrendingUp : d.change_pct === 0 ? Minus : TrendingDown;
  const color = up ? '#10B981' : d.change_pct === 0 ? '#F59E0B' : '#E11D48';
  
  return (
    <div className={`group/row flex flex-col gap-4 py-4 border-b last:border-0 hover:bg-white/[0.02] transition-all rounded-2xl px-4 ${
      theme === 'dark' ? 'border-white/5' : 'border-slate-100 hover:bg-slate-50'
    }`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg border shadow-inner transition-colors duration-500 ${
            theme === 'dark' ? 'bg-slate-800/50 border-white/5 group-hover/row:border-white/10' : 'bg-slate-50 border-slate-200 group-hover/row:border-blue-200 shadow-sm'
          }`}>
            <Icon className="w-3.5 h-3.5" style={{ color }} />
          </div>
          <span className={`text-sm font-black tracking-tight transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>{label}</span>
        </div>
        <div className="text-right flex flex-col items-end">
          <span className={`text-lg font-black tabular-nums tracking-tighter transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>
            {d.price > 0 ? d.price.toLocaleString('en-US', { minimumFractionDigits: 2 }) : '—'}
          </span>
          <div className={`flex items-center gap-1 px-2 py-0.5 rounded-lg text-[9px] font-black mt-0.5`} style={{ backgroundColor: color + '15', color }}>
             {up ? '▲' : '▼'} {Math.abs(d.change_pct).toFixed(2)}%
          </div>
        </div>
      </div>

      {/* Minimal Sparkline */}
      <div className="h-16 w-full opacity-40 group-hover/row:opacity-100 transition-opacity">
         <InstitutionalChart data={d.series} color={color} height={64} />
      </div>
    </div>
  );
});

const MarketIndicesCard = ({ data, status, onRefresh }: { 
  data: IndicesData | null; 
  status: DataStatus; 
  onRefresh: () => void 
}) => {
  const { theme } = useMode();
  return (
    <div className={`rounded-[1.5rem] border shadow-2xl p-6 lg:p-8 flex flex-col h-full relative overflow-hidden group transition-all duration-500 ${
      theme === 'dark' ? 'bg-slate-900/60 border-white/5' : 'bg-white border-slate-200'
    }`}>
      <div className={`absolute top-0 right-0 w-32 h-32 blur-[60px] rounded-full pointer-events-none ${
        theme === 'dark' ? 'bg-indigo-500/5' : 'bg-indigo-400/5'
      }`} />
      
      <div className="flex items-center justify-between mb-6 z-10">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg border shadow-inner transition-colors duration-500 ${
            theme === 'dark' ? 'border-white/10 bg-white/5' : 'border-slate-200 bg-slate-50'
          }`}>
            <BarChart3 className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
          </div>
          <h4 className={`text-base font-black uppercase tracking-tight transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}>Market Benchmarks</h4>
        </div>
        <button
          onClick={onRefresh}
          disabled={status.loading}
          className={`p-2 rounded-lg border transition-all active:scale-95 shadow-lg ${
            theme === 'dark' ? 'bg-white/5 hover:bg-white/10 border-white/10' : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-500'
          }`}
        >
          <motion.div animate={status.loading ? { rotate: 360 } : {}} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
            <RefreshCcw className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
          </motion.div>
        </button>
      </div>

      <div className="flex-1 z-10">
        <AnimatePresence mode="wait">
          {status.loading && !data ? (
            <motion.div key="loading" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
              className="flex flex-col items-center justify-center h-full gap-4 py-20"
            >
              <RefreshCcw className="w-8 h-8 text-indigo-500 animate-spin" />
              <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest animate-pulse">Syncing feed...</span>
            </motion.div>
          ) : status.error && !data ? (
            <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              className="flex flex-col items-center justify-center h-full gap-4 py-20 text-rose-400"
            >
              <WifiOff className="w-8 h-8 opacity-20" />
              <span className="text-[10px] font-black uppercase tracking-widest">Network Outage</span>
            </motion.div>
          ) : data ? (
            <motion.div key="data" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex flex-col h-full justify-between">
              <IndexRow d={data.nasdaq} label="Nasdaq 100" />
              <IndexRow d={data.dow} label="Dow Jones" />
              <IndexRow d={data.sp500} label="S&P 500" />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
};

// ────────────────────────────────────────────────────────────────
// hook: useGaugePoll — polls an endpoint, returns score + status
// ────────────────────────────────────────────────────────────────
function useGaugePoll(endpoint: string, transform: (json: any) => number) {
  const [score, setScore] = useState<number>(50);
  const [rawData, setRawData] = useState<any>(null);
  const [status, setStatus] = useState<DataStatus>({ loading: true, error: false, lastUpdate: null });

  const poll = useCallback(async () => {
    setStatus(s => ({ ...s, loading: true }));
    try {
      const r = await window.fetch(endpoint);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      setRawData(json);
      setScore(Math.max(0, Math.min(100, transform(json))));
      setStatus({ loading: false, error: false, lastUpdate: new Date() });
    } catch {
      setStatus(s => ({ ...s, loading: false, error: true }));
    }
  }, [endpoint]);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 300_000); // 5 min
    return () => clearInterval(id);
  }, [poll]);

  return { score, rawData, status, refresh: poll };
}

// ────────────────────────────────────────────────────────────────
// Institutional News Timeline (Optimized to prevent flicker)
// ────────────────────────────────────────────────────────────────
const InstitutionalTimeline = () => {
  const { theme } = useMode();
  return (
    <div className={`h-[250px] md:h-[450px] rounded-[1.5rem] border overflow-hidden shadow-2xl backdrop-blur-3xl transition-all duration-500 ${
      theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200'
    }`}>
      <div 
        className="tradingview-widget-container w-full h-full" 
        ref={(el) => {
          if (!el || el.querySelector('script')) return;
          const script = document.createElement('script');
          script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-timeline.js';
          script.type = 'text/javascript';
          script.async = true;
          script.innerHTML = JSON.stringify({
            feedMode: 'all_symbols',
            isTransparent: true,
            displayMode: 'regular',
            width: '100%',
            height: '100%',
            colorTheme: theme,
            locale: 'th',
          });
          const wrapper = document.createElement('div');
          wrapper.className = 'tradingview-widget-container__widget w-full h-full';
          el.appendChild(wrapper);
          el.appendChild(script);
        }} 
      />
    </div>
  );
};

// ────────────────────────────────────────────────────────────────
// Top News Feed (Real-time from /api/sentiment)
// ────────────────────────────────────────────────────────────────
const TopNewsFeed = ({ articles, status }: { articles: NewsArticle[], status: DataStatus }) => {
  const { theme } = useMode();
  if (status.loading && articles.length === 0) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[1, 2, 3, 4, 5, 6].map(i => (
          <div key={i} className={`h-48 rounded-3xl animate-pulse border transition-colors duration-500 ${
            theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-slate-100 border-slate-200'
          }`} />
        ))}
      </div>
    );
  }

  if (status.error && articles.length === 0) {
    return (
      <div className={`h-48 rounded-3xl border flex items-center justify-center transition-colors duration-500 ${
        theme === 'dark' ? 'border-rose-500/20 bg-rose-500/5' : 'border-rose-200 bg-rose-50'
      }`}>
        <div className="flex flex-col items-center gap-2">
          <WifiOff className={`w-6 h-6 ${theme === 'dark' ? 'text-rose-500/40' : 'text-rose-300'}`} />
          <span className={`text-[10px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'text-rose-400' : 'text-rose-600'
          }`}>Failed to load breaking news</span>
        </div>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <AnimatePresence mode="popLayout">
        {articles.slice(0, 9).map((art, i) => (
          <motion.div
            key={art.title + i}
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: i * 0.05 }}
            className={`group relative rounded-[1.5rem] border transition-all duration-500 p-5 flex flex-col gap-3 overflow-hidden shadow-xl hover:shadow-indigo-500/10 ${
              theme === 'dark' ? 'bg-slate-900/60 border-white/5 hover:border-indigo-500/30' : 'bg-white border-slate-200 hover:border-indigo-200'
            }`}
          >
            {/* Source & Date */}
            <div className="flex items-center justify-between z-10">
              <div className="flex items-center gap-2">
                <div className={`w-6 h-6 rounded-lg border flex items-center justify-center transition-all ${
                  theme === 'dark' ? 'bg-indigo-500/10 border-indigo-500/20' : 'bg-indigo-50 border-indigo-100'
                }`}>
                  <Globe className={`w-3 h-3 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
                </div>
                <span className={`text-[10px] font-black uppercase tracking-widest transition-colors ${
                  theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'
                }`}>{art.source}</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-500">
                <Clock className="w-3 h-3" />
                <span className="text-[9px] font-bold uppercase">{art.published.split(' ').slice(0, 4).join(' ')}</span>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 space-y-2 z-10">
              <h4 className={`text-sm font-black leading-tight group-hover:text-indigo-300 transition-colors line-clamp-2 ${
                theme === 'dark' ? 'text-white' : 'text-slate-900 group-hover:text-indigo-600'
              }`}>
                {art.title}
              </h4>
              <p className={`text-[11px] leading-relaxed line-clamp-3 transition-colors ${
                theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
              }`}>
                {art.summary.replace(/<[^>]*>?/gm, '')}
              </p>
            </div>

            {/* Footer */}
            <div className={`flex items-center justify-between pt-4 border-t z-10 transition-colors ${
              theme === 'dark' ? 'border-white/5' : 'border-slate-100'
            }`}>
              <div className="flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest">Live Now</span>
              </div>
              {art.link ? (
                <a
                  href={art.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`text-[9px] font-black uppercase tracking-widest transition-colors flex items-center gap-1 ${
                    theme === 'dark' ? 'text-indigo-400 hover:text-indigo-300' : 'text-indigo-600 hover:text-indigo-700'
                  }`}
                >
                  Read Full <ExternalLink className="w-3 h-3" />
                </a>
              ) : (
                <span className="text-[9px] font-black text-slate-600 uppercase tracking-widest flex items-center gap-1 cursor-not-allowed">
                  Read Full <ExternalLink className="w-3 h-3" />
                </span>
              )}
            </div>

            {/* Decorative BG Glow */}
            <div className="absolute -right-8 -bottom-8 w-24 h-24 bg-indigo-500/5 blur-3xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

// ────────────────────────────────────────────────────────────────
// AI Pulse Banner — with Sources Dropdown
// ────────────────────────────────────────────────────────────────
const AIPulseBanner = ({ overall, articles }: {
  overall: SentimentData['overall'];
  articles: NewsArticle[];
}) => {
  const [showSources, setShowSources] = useState(false);
  const { theme } = useMode();
  const sourcedArticles = articles.filter(a => a.link);
  const hasAnyArticles = articles.length > 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`p-6 rounded-[1.5rem] border shadow-2xl relative overflow-hidden transition-all duration-500 ${
        theme === 'dark' 
          ? 'bg-gradient-to-br from-indigo-600/20 via-slate-900/40 to-blue-900/20 border-indigo-500/20' 
          : 'bg-white border-indigo-100'
      }`}
    >
      <div className={`absolute top-0 right-0 w-96 h-96 blur-[100px] rounded-full -translate-y-1/2 translate-x-1/2 ${
        theme === 'dark' ? 'bg-indigo-500/10' : 'bg-indigo-400/5'
      }`} />

      <div className="relative z-10 flex flex-col lg:flex-row gap-10 items-center">
        <div className="flex-1 space-y-4">
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded-lg border transition-colors ${
              theme === 'dark' ? 'bg-indigo-500/10 border-indigo-500/20' : 'bg-indigo-50 border-indigo-100'
            }`}>
              <BrainCircuit className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
            </div>
            <h3 className={`text-lg font-black uppercase tracking-widest italic transition-colors ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>AI Market Pulse</h3>
          </div>

          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <span className={`text-2xl font-black px-4 py-1.5 rounded-xl border ${
                overall.sentiment === 'BULLISH' ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400' :
                overall.sentiment === 'BEARISH' ? 'border-rose-500/30 bg-rose-500/10 text-rose-400' :
                'border-slate-500/30 bg-slate-500/10 text-slate-400'
              }`}>
                {overall.sentiment}
              </span>
              <div className="flex flex-col">
                <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Sentiment Score</span>
                <span className={`text-xl font-black tracking-tighter transition-colors ${
                  theme === 'dark' ? 'text-white' : 'text-slate-900'
                }`}>{overall.score > 0 ? '+' : ''}{overall.score}/100</span>
              </div>
            </div>
            <p className={`text-base font-medium leading-relaxed italic transition-colors ${
              theme === 'dark' ? 'text-slate-200' : 'text-slate-700'
            }`}>
              "{overall.summary}"
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-2">
            {overall.key_factors?.map((f, i) => (
              <span key={i} className={`text-[9px] font-black uppercase tracking-widest px-3 py-1.5 rounded-lg border transition-colors ${
                theme === 'dark' ? 'bg-white/5 border-white/10 text-slate-400' : 'bg-slate-50 border-slate-200 text-slate-500'
              }`}>
                # {f}
              </span>
            ))}
            {hasAnyArticles && (
              <button
                onClick={() => setShowSources(s => !s)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border transition-all text-[9px] font-black uppercase tracking-widest ${
                  theme === 'dark' 
                    ? 'bg-indigo-500/10 border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/20' 
                    : 'bg-indigo-50 border-indigo-200 text-indigo-600 hover:bg-indigo-100 shadow-sm'
                }`}
              >
                <ExternalLink className="w-3 h-3" />
                Sources ({articles.length})
                {showSources ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </button>
            )}
          </div>

          <AnimatePresence>
            {showSources && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                  <div className={`space-y-2 pt-2 border-t transition-colors ${
                    theme === 'dark' ? 'border-white/5' : 'border-slate-100'
                  }`}>
                  <span className={`text-[9px] font-black uppercase tracking-widest ${
                    theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                  }`}>News Sources Used in Analysis</span>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-60 overflow-y-auto pr-1">
                    {articles.slice(0, 12).map((a, i) => (
                      a.link ? (
                        <a
                          key={i}
                          href={a.link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={`flex items-start gap-2 p-2.5 rounded-xl border transition-all group/item shadow-sm ${
                            theme === 'dark' 
                              ? 'bg-white/[0.03] border-white/5 hover:bg-indigo-500/10 hover:border-indigo-500/20' 
                              : 'bg-slate-50 border-slate-100 hover:bg-indigo-50 hover:border-indigo-200'
                          }`}
                        >
                          <ExternalLink className={`w-3 h-3 shrink-0 mt-0.5 opacity-0 group-hover/item:opacity-100 transition-opacity ${
                            theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'
                          }`} />
                          <div className="min-w-0">
                            <p className={`text-[10px] font-bold leading-tight line-clamp-2 transition-colors ${
                              theme === 'dark' ? 'text-slate-300 group-hover/item:text-white' : 'text-slate-700 group-hover/item:text-indigo-700'
                            }`}>{a.title}</p>
                            <span className="text-[8px] font-black text-indigo-400/70 uppercase tracking-wider">{a.source}</span>
                          </div>
                        </a>
                      ) : (
                        <div
                          key={i}
                          className="flex items-start gap-2 p-2.5 rounded-xl bg-white/[0.03] border border-white/5"
                        >
                          <div className="min-w-0">
                            <p className="text-[10px] font-bold text-slate-400 leading-tight line-clamp-2">{a.title}</p>
                            <span className="text-[8px] font-black text-slate-600 uppercase tracking-wider">{a.source}</span>
                          </div>
                        </div>
                      )
                    ))}
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <div className="w-full lg:w-64 shrink-0 p-5 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-sm space-y-3">
          <div className="flex justify-between items-center text-[10px] font-black text-slate-500 uppercase tracking-widest">
            <span>Sentiment Gauge</span>
            <span className="text-indigo-400">{overall.score}%</span>
          </div>
            <div className={`h-3 w-full rounded-full overflow-hidden flex transition-colors ${
              theme === 'dark' ? 'bg-slate-800' : 'bg-slate-200'
            }`}>
            <motion.div
              initial={{ width: 0 }}
              animate={{ width: `${(overall.score + 100) / 2}%` }}
              className={`h-full ${overall.score > 0 ? 'bg-emerald-500' : 'bg-rose-500 shadow-[0_0_15px_rgba(244,63,94,0.5)]'}`}
            />
          </div>
          <p className="text-[9px] text-slate-500 font-medium leading-relaxed">
            Analyzing real-time signals from CoinDesk, CoinTelegraph, and CryptoSlate using AI Market Analysis.
          </p>
        </div>
      </div>
    </motion.div>
  );
};

// ────────────────────────────────────────────────────────────────
// Main Component
// ────────────────────────────────────────────────────────────────
export const NewsSentimentHub = () => {
  const { theme } = useMode();
  // 1. Crypto Fear & Greed
  const { score: cryptoScore, rawData: cryptoRaw, status: cryptoStatus, refresh: refreshCrypto } =
    useGaugePoll('/api/market/crypto-fear-greed', (j: FGData) => j.value);

  // 2. CNN Fear & Greed
  const { score: cnnScore, rawData: cnnRaw, status: cnnStatus, refresh: refreshCnn } =
    useGaugePoll('/api/market/cnn-fear-greed', (j: FGData) => j.value);

  // 3. Global Market Indices
  const [indices, setIndices] = useState<IndicesData | null>(null);
  const [indicesStatus, setIndicesStatus] = useState<DataStatus>({ loading: true, error: false, lastUpdate: null });

  // 4. Real-time News Articles
  const [newsData, setNewsData] = useState<SentimentData | null>(null);
  const [newsStatus, setNewsStatus] = useState<DataStatus>({ loading: true, error: false, lastUpdate: null });

  // 5. DXY Specific News
  const [dxyNews, setDxyNews] = useState<SentimentData | null>(null);
  const [dxyNewsStatus, setDxyNewsStatus] = useState<DataStatus>({ loading: true, error: false, lastUpdate: null });

  const fetchIndices = useCallback(async () => {
    setIndicesStatus(s => ({ ...s, loading: true }));
    try {
      const r = await window.fetch('/api/market/indices');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json: IndicesData = await r.json();
      setIndices(json);
      setIndicesStatus({ loading: false, error: false, lastUpdate: new Date() });
    } catch {
      setIndicesStatus(s => ({ ...s, loading: false, error: true }));
    }
  }, []);

  const fetchNews = useCallback(async () => {
    setNewsStatus(s => ({ ...s, loading: true }));
    try {
      const r = await window.fetch('/api/sentiment');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json: SentimentData = await r.json();
      setNewsData(json);
      setNewsStatus({ loading: false, error: false, lastUpdate: new Date() });
    } catch {
      setNewsStatus(s => ({ ...s, loading: false, error: true }));
    }
  }, []);

  const fetchDxyNews = useCallback(async () => {
    setDxyNewsStatus(s => ({ ...s, loading: true }));
    try {
      const r = await window.fetch('/api/market/dxy-news');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json: SentimentData = await r.json();
      setDxyNews(json);
      setDxyNewsStatus({ loading: false, error: false, lastUpdate: new Date() });
    } catch {
      setDxyNewsStatus(s => ({ ...s, loading: false, error: true }));
    }
  }, []);

  useEffect(() => {
    fetchIndices();
    fetchNews();
    fetchDxyNews();

    const id = setInterval(() => {
      fetchIndices();
      fetchNews();
      fetchDxyNews();
    }, 60_000);
    return () => clearInterval(id);
  }, [fetchIndices, fetchNews, fetchDxyNews]);

  const refreshAll = () => {
    refreshCrypto();
    refreshCnn();
    fetchIndices();
    fetchNews();
    fetchDxyNews();
  };

  const anyLoading = cryptoStatus.loading || cnnStatus.loading || indicesStatus.loading || newsStatus.loading;

  return (
    <div className={`flex-1 flex flex-col h-full custom-scrollbar overflow-y-auto pb-20 transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950/20' : 'bg-slate-50'
    }`}>
      {/* Header */}
      <header className={`h-20 border-b flex items-center justify-between pl-8 pr-10 backdrop-blur-3xl z-30 sticky top-0 shrink-0 shadow-2xl transition-all duration-500 ${
        theme === 'dark' ? 'bg-slate-950/40 border-white/5' : 'bg-white border-slate-200'
      }`}>
        <div className="flex items-center gap-6">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center border shadow-inner transition-colors ${
            theme === 'dark' ? 'bg-indigo-600/10 border-indigo-500/20' : 'bg-indigo-50 border-indigo-100'
          }`}>
            <BrainCircuit className={`w-6 h-6 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
          </div>
          <div>
            <h1 className={`text-2xl font-black tracking-widest uppercase italic transition-colors ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>
              Macro Sentiment <span className="text-indigo-500">Hub</span>
            </h1>
            <div className="flex items-center gap-3 mt-0.5">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse shadow-[0_0_8px_#10B981]" />
              <div className="flex items-center gap-2">
                <span className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em]">
                  Real-Time Sentiment • Institutional Trace
                </span>
                {newsStatus.lastUpdate && (
                  <span className={`text-[9px] font-black uppercase tracking-widest border-l pl-2 transition-colors ${
                    theme === 'dark' ? 'text-indigo-400/60 border-white/10' : 'text-indigo-600/60 border-slate-200'
                  }`}>
                    อัปเดตล่าสุด: {newsStatus.lastUpdate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Data source badges */}
          <div className="hidden lg:flex items-center gap-2">
            {[
              { label: 'Yahoo Live', color: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' },
              { label: 'CNN Scraper', color: 'text-rose-400 border-rose-500/30 bg-rose-500/10' },
              { label: 'Native Charts', color: 'text-sky-400 border-sky-500/30 bg-sky-500/10' },
            ].map(b => (
              <span key={b.label} className={`text-[8px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full border ${b.color}`}>
                {b.label}
              </span>
            ))}
          </div>
          <button
            onClick={refreshAll}
            disabled={anyLoading}
            className={`flex items-center gap-2 px-6 py-2.5 border rounded-xl transition-all active:scale-95 ${
              theme === 'dark' 
                ? 'bg-white/5 hover:bg-white/10 border-white/10 text-white' 
                : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-800 shadow-sm'
            }`}
          >
            <motion.div animate={anyLoading ? { rotate: 360 } : {}} transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}>
              <RefreshCcw className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600'}`} />
            </motion.div>
            <span className="text-[10px] font-black uppercase tracking-[0.2em]">Refresh All</span>
          </button>
        </div>
      </header>

      <div className="p-8 space-y-8 max-w-[1700px] mx-auto w-full">

        {/* ── 1. Breaking News Analysis (AI Driven) ── */}
        <AnimatePresence mode="wait">
          {newsData?.overall && (
            <AIPulseBanner overall={newsData.overall} articles={newsData.articles || []} />
          )}
        </AnimatePresence>

        {/* ── 2. Real-time News Feed ── */}
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Newspaper className={`w-5 h-5 ${theme === 'dark' ? 'text-indigo-500' : 'text-indigo-600'}`} />
              <h3 className={`text-xl font-black uppercase tracking-[0.2em] transition-colors ${
                theme === 'dark' ? 'text-white' : 'text-slate-900'
              }`}>Real-time News Feed</h3>
              <div className={`hidden sm:block h-px w-32 transition-colors ${
                theme === 'dark' ? 'bg-white/10' : 'bg-slate-200'
              }`} />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[9px] font-black text-indigo-400 uppercase tracking-widest">
                อัปเดตล่าสุด: {newsStatus.lastUpdate?.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              </span>
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_#10B981]" />
            </div>
          </div>
          
          <TopNewsFeed articles={newsData?.articles || []} status={newsStatus} />
        </div>

        {/* ── 3. 4 Gauges Grid ── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* ① Crypto Fear & Greed */}
          <ModernRadialGauge
            title="Crypto Fear & Greed"
            score={cryptoScore}
            subtitle="alternative.me • Global Crypto Sentiment"
            Icon={Activity}
            badge="LIVE API"
            status={cryptoStatus}
            sourceUrl="https://alternative.me/crypto/fear-and-greed-index/"
          >
            <div className="flex flex-col gap-5">
              {/* Historical Table */}
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Yesterday', data: cryptoRaw?.history?.yesterday },
                  { label: 'Last Week', data: cryptoRaw?.history?.last_week },
                  { label: 'Last Month', data: cryptoRaw?.history?.last_month },
                ].map((item, i) => (
                  <div key={i} className="flex flex-col items-center p-2.5 rounded-xl bg-white/[0.03] border border-white/5 shadow-inner">
                    <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest mb-1.5">{item.label}</span>
                    <span className="text-lg font-black text-white leading-none mb-1">{item.data?.value ?? '--'}</span>
                    <span className="text-[7px] font-bold uppercase tracking-tighter truncate w-full text-center" style={{ color: item.data ? getZone(item.data.value).hex : '#64748b' }}>
                      {item.data?.label ?? '---'}
                    </span>
                  </div>
                ))}
              </div>

              {/* Data Factors Insight */}
              <div className={`p-4 rounded-2xl border shadow-inner transition-colors ${
                theme === 'dark' ? 'bg-indigo-500/5 border-indigo-500/10' : 'bg-indigo-50/50 border-indigo-100'
              }`}>
                 <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                       <BrainCircuit className="w-3.5 h-3.5 text-indigo-400" />
                       <span className="text-[10px] font-black text-indigo-300 uppercase tracking-widest">Market Insight</span>
                    </div>
                    {cryptoRaw?.history?.yesterday && (
                       <div className="flex items-center gap-1.5">
                          {cryptoScore > cryptoRaw.history.yesterday.value ? (
                             <TrendingUp className="w-3 h-3 text-emerald-400" />
                          ) : cryptoScore < cryptoRaw.history.yesterday.value ? (
                             <TrendingDown className="w-3 h-3 text-rose-400" />
                          ) : (
                             <Minus className="w-3 h-3 text-slate-500" />
                          )}
                          <span className="text-[8px] font-black text-slate-500 uppercase">24H Trend</span>
                       </div>
                    )}
                 </div>
                 <p className="text-[11px] text-slate-400 leading-relaxed font-medium">
                   {cryptoScore <= 25 
                     ? "Extreme fear could be a buying opportunity. Investors are overly worried."
                     : cryptoScore >= 75
                     ? "Investors are getting too greedy. The market might be due for a correction."
                     : "Market sentiment is stabilizing. Volume and volatility are within normal bounds."}
                   {" "}
                   {cryptoRaw?.history?.yesterday && (
                     cryptoScore < cryptoRaw.history.yesterday.value 
                       ? "Sentiment is worsening compared to yesterday."
                       : cryptoScore > cryptoRaw.history.yesterday.value
                       ? "Sentiment is improving since yesterday."
                       : "Sentiment remains unchanged."
                   )}
                 </p>
                 <div className={`mt-4 grid grid-cols-2 gap-x-4 gap-y-2 border-t pt-3 transition-colors ${
                   theme === 'dark' ? 'border-white/5' : 'border-slate-100'
                 }`}>
                    <div className="flex justify-between items-center">
                       <span className="text-[8px] text-slate-500 font-bold uppercase">Volatility</span>
                       <span className="text-[8px] text-slate-400 font-black">25%</span>
                    </div>
                    <div className="flex justify-between items-center">
                       <span className="text-[8px] text-slate-500 font-bold uppercase">Momentum</span>
                       <span className="text-[8px] text-slate-400 font-black">25%</span>
                    </div>
                    <div className="flex justify-between items-center">
                       <span className="text-[8px] text-slate-500 font-bold uppercase">Social</span>
                       <span className="text-[8px] text-slate-400 font-black">15%</span>
                    </div>
                    <div className="flex justify-between items-center">
                       <span className="text-[8px] text-slate-500 font-bold uppercase">Trends</span>
                       <span className="text-[8px] text-slate-400 font-black">10%</span>
                    </div>
                 </div>
              </div>
            </div>
          </ModernRadialGauge>

          {/* ② CNN Fear & Greed */}
          <ModernRadialGauge
            title="CNN Fear & Greed"
            score={cnnScore}
            subtitle="CNN DataViz scraper • US Equity Markets"
            Icon={Globe}
            badge="LIVE SCRAPE"
            status={cnnStatus}
            sourceUrl="https://www.cnn.com/markets/fear-and-greed"
          >
            <div className="flex flex-col gap-5">
              {/* Historical Table */}
              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'Yesterday', data: cnnRaw?.history?.yesterday },
                  { label: 'Last Week', data: cnnRaw?.history?.last_week },
                  { label: 'Last Month', data: cnnRaw?.history?.last_month },
                ].map((item, i) => (
                  <div key={i} className={`flex flex-col items-center p-2.5 rounded-xl border shadow-inner transition-colors ${
                    theme === 'dark' ? 'bg-white/[0.03] border-white/5' : 'bg-white border-slate-200'
                  }`}>
                    <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest mb-1.5">{item.label}</span>
                    <span className={`text-lg font-black leading-none mb-1 ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{item.data?.value ?? '--'}</span>
                    <span className="text-[7px] font-bold uppercase tracking-tighter truncate w-full text-center" style={{ color: item.data ? getZone(item.data.value).hex : '#64748b' }}>
                      {item.data?.label ?? '---'}
                    </span>
                  </div>
                ))}
              </div>

              {/* Data Factors Insight */}
              <div className={`p-4 rounded-2xl border shadow-inner transition-colors ${
                theme === 'dark' ? 'bg-amber-500/5 border-amber-500/10' : 'bg-amber-50/50 border-amber-100'
              }`}>
                 <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                       <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                       <span className="text-[10px] font-black text-amber-300 uppercase tracking-widest">Equity Context</span>
                    </div>
                    {cnnRaw?.history?.yesterday && (
                       <div className="flex items-center gap-1.5">
                          {cnnScore > cnnRaw.history.yesterday.value ? (
                             <TrendingUp className="w-3 h-3 text-emerald-400" />
                          ) : cnnScore < cnnRaw.history.yesterday.value ? (
                             <TrendingDown className="w-3 h-3 text-rose-400" />
                          ) : (
                             <Minus className="w-3 h-3 text-slate-500" />
                          )}
                          <span className="text-[8px] font-black text-slate-500 uppercase">24H Trend</span>
                       </div>
                    )}
                 </div>
                 <p className="text-[11px] text-slate-400 leading-relaxed font-medium">
                   Measuring Junk Bond Demand, Market Volatility, and Safe Haven Demand.
                   {" "}
                   {cnnRaw?.history?.yesterday && (
                     cnnScore < cnnRaw.history.yesterday.value 
                       ? "Equity fear is rising since previous close."
                       : cnnScore > cnnRaw.history.yesterday.value
                       ? "Equity greed is gaining momentum."
                       : "Equity market sentiment is flat."
                   )}
                 </p>
                 <div className="mt-4 flex items-center justify-between border-t border-white/5 pt-3">
                    <span className="text-[8px] text-slate-500 font-bold uppercase">Status</span>
                    <div className="flex items-center gap-1.5">
                       <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                       <span className="text-[8px] text-emerald-400 font-black uppercase">Monitoring 7 Indicators</span>
                    </div>
                 </div>
              </div>
            </div>
          </ModernRadialGauge>

          {/* ③ DXY — Native Chart */}
           {indices ? (
            <DXYCard
              data={indices.dxy}
              status={indicesStatus}
              news={dxyNews}
            />
          ) : (
            <div className={`rounded-[2.5rem] border p-10 flex items-center justify-center h-full min-h-[200px] md:min-h-[400px] transition-colors duration-500 ${
              theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'border-slate-200 bg-white'
            }`}>
              <p className="text-sm text-slate-500">Loading market data...</p>
            </div>
          )}

          {/* ④ Market Indices — Native Charts */}
          {indices ? (
            <MarketIndicesCard 
              data={indices} 
              status={indicesStatus} 
              onRefresh={fetchIndices} 
            />
          ) : (
            <div className={`rounded-[2.5rem] border p-10 flex items-center justify-center h-full min-h-[200px] md:min-h-[400px] transition-colors duration-500 ${
              theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'border-slate-200 bg-white'
            }`}>
              <p className="text-sm text-slate-500">Loading market data...</p>
            </div>
          )}
        </div>

        {/* ── 4. Institutional Timeline ── */}
        <div className="space-y-4 pt-6">
          <div className="flex items-center gap-3">
            <Globe className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-500' : 'text-indigo-600'}`} />
            <h3 className={`text-lg font-black uppercase tracking-[0.2em] transition-colors ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>Institutional Timeline</h3>
            <div className={`h-px flex-1 transition-colors ${
              theme === 'dark' ? 'bg-white/5' : 'bg-slate-200'
            }`} />
          </div>
          <InstitutionalTimeline />
        </div>

        {/* ── 5. Banner: Data Sources Overview (Footer Style) ── */}
        <HoverGlowCard className="p-6 rounded-3xl bg-indigo-600/10 border-indigo-500/20 shadow-2xl relative overflow-hidden">
          <div className="relative z-10 flex flex-col gap-4">
            <div className="flex items-center gap-3 text-indigo-400">
              <Globe className="w-5 h-5" />
              <h2 className="text-xs font-black uppercase tracking-[0.4em]">Institutional Data Flow • Source Transparency</h2>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                {
                  name: '① Crypto Fear & Greed',
                  source: 'alternative.me API',
                  badge: 'LIVE • Daily',
                  color: 'emerald',
                  detail: 'Market momentum, social media, and trends index for the crypto economy.',
                  url: 'https://alternative.me/crypto/fear-and-greed-index/',
                },
                {
                  name: '② CNN Fear & Greed',
                  source: 'CNN DataViz scraper',
                  badge: 'LIVE • Daily',
                  color: 'rose',
                  detail: 'US Equity momentum, safe haven demand, and junk bond spread composite.',
                  url: 'https://edition.cnn.com/markets/fear-and-greed',
                },
                {
                  name: '③ US Dollar Index (DXY)',
                  source: 'Yahoo Finance Trace',
                  badge: 'REALTIME • Latency < 1m',
                  color: 'sky',
                  detail: 'USD strength vs 6 major currencies. DXY rising = crypto headwind.',
                  url: 'https://finance.yahoo.com/quote/DX-Y.NYB',
                },
                {
                  name: '④ Market Indices',
                  source: 'Yahoo Finance Trace',
                  badge: 'REALTIME • Latency < 1m',
                  color: 'violet',
                  detail: 'Nasdaq and Dow Jones benchmarks with native intraday drawing.',
                  url: 'https://finance.yahoo.com/world-indices',
                },
              ].map((s) => {
                const colorMap: Record<string, string> = {
                  emerald: '#10b981',
                  rose: '#f43f5e',
                  sky: '#38bdf8',
                  violet: '#8b5cf6',
                };
                const c = colorMap[s.color] || '#64748b';
                return (
                  <a
                    key={s.name}
                    href={s.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-xl p-4 flex flex-col gap-2 group/src transition-all hover:scale-[1.02]"
                    style={{
                      backgroundColor: `${c}0d`,
                      border: `1px solid ${c}33`,
                    }}
                  >
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs font-black transition-colors duration-500" style={{ color: theme === 'dark' ? c : (s.color === 'emerald' ? '#059669' : s.color === 'rose' ? '#dc2626' : s.color === 'sky' ? '#0284c7' : '#7c3aed') }}>{s.name}</p>
                        <p className="text-[10px] text-slate-500 mt-0.5">{s.source}</p>
                      </div>
                      <ExternalLink className={`w-3 h-3 transition-colors duration-500 ${theme === 'dark' ? 'text-slate-600 group-hover/src:text-slate-400' : 'text-slate-400 group-hover/src:text-slate-600'} shrink-0 mt-0.5`} />
                    </div>
                    <span
                      className="text-[9px] font-black uppercase tracking-widest px-2 py-0.5 rounded-full border self-start transition-all duration-500"
                      style={{
                        borderColor: theme === 'dark' ? `${c}4d` : `${c}66`,
                        backgroundColor: theme === 'dark' ? `${c}1a` : `${c}10`,
                        color: theme === 'dark' ? c : (s.color === 'emerald' ? '#059669' : s.color === 'rose' ? '#dc2626' : s.color === 'sky' ? '#0284c7' : '#7c3aed'),
                      }}
                    >
                      {s.badge}
                    </span>
                    <p className={`text-[10px] leading-relaxed transition-colors duration-500 ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600 font-medium'}`}>{s.detail}</p>
                  </a>

                );
              })}
            </div>
          </div>
          <div className="absolute -right-16 -top-16 w-64 h-64 bg-indigo-500/10 blur-[80px] rounded-full" />
        </HoverGlowCard>
      </div>
    </div>
  );
};
