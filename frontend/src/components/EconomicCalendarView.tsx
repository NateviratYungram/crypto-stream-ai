import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { CalendarDays, RefreshCw, AlertTriangle, TrendingUp, Minus, ChevronDown, ChevronUp, ExternalLink } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

interface CalendarEvent {
  date: string;
  time?: string;
  type: 'MACRO' | 'EARNINGS';
  name: string;
  symbol?: string;
  impact: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  currency?: string;
  actual?: string | number | null;
  forecast?: string | number | null;
  previous?: string | number | null;
  estimate_eps?: number | null;
  desc?: string;
  source?: string;
  source_url?: string;
  is_estimated?: boolean;
}

type DayGroup = { date: string; label: string; events: CalendarEvent[] };
type MacroWatch = { name: string; abbrev?: string; impact: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'; desc?: string };
const CALENDAR_CACHE_KEY = 'economic_calendar_cache_v1';

const IMPACT_CONFIG: Record<string, { dot: string; badge: string; text: string; label: string }> = {
  CRITICAL: { dot: 'bg-red-500',    badge: 'bg-red-500/10 border-red-500/30',    text: 'text-red-400',    label: 'CRITICAL' },
  HIGH:     { dot: 'bg-amber-400',  badge: 'bg-amber-400/10 border-amber-400/30',  text: 'text-amber-400',  label: 'HIGH' },
  MEDIUM:   { dot: 'bg-blue-400',   badge: 'bg-blue-400/10 border-blue-400/30',   text: 'text-blue-400',   label: 'MEDIUM' },
  LOW:      { dot: 'bg-slate-600',  badge: 'bg-slate-600/10 border-slate-600/30',  text: 'text-slate-500',  label: 'LOW' },
};

const fmt = (v: string | number | null | undefined) => (v == null || v === '') ? '—' : String(v);

const buildEventSourceUrl = (ev: CalendarEvent) => {
  if (ev.source_url) return ev.source_url;
  const q = encodeURIComponent([ev.symbol, ev.name, ev.currency, 'economic calendar news'].filter(Boolean).join(' '));
  return `https://www.google.com/search?q=${q}`;
};

const isToday = (dateStr: string) => {
  const today = new Date();
  const d = new Date(dateStr);
  return d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
};

const isTomorrow = (dateStr: string) => {
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const d = new Date(dateStr);
  return d.getFullYear() === tomorrow.getFullYear() && d.getMonth() === tomorrow.getMonth() && d.getDate() === tomorrow.getDate();
};

const dayLabel = (dateStr: string) => {
  if (isToday(dateStr)) return 'Today';
  if (isTomorrow(dateStr)) return 'Tomorrow';
  return new Date(dateStr).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
};

export const EconomicCalendarView = () => {
  const { theme } = useMode();
  const [days,        setDays]        = useState<DayGroup[]>([]);
  const [macroWatch,  setMacroWatch]  = useState<MacroWatch[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [range,       setRange]       = useState(7);
  const [filter,      setFilter]      = useState<'ALL' | 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'EARNINGS'>('ALL');
  const [expanded,    setExpanded]    = useState<Set<string>>(new Set());
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [tradingNote, setTradingNote] = useState('');
  const [sourceStatus, setSourceStatus] = useState<'live_feed' | 'watch_only' | 'error' | 'invalid_payload' | ''>('');
  const [error, setError] = useState<string | null>(null);

  const applyCalendarData = useCallback((data: any) => {
    const events: CalendarEvent[] = data.events || data.upcoming_events || [];
    setMacroWatch(Array.isArray(data.macro_watch) ? data.macro_watch : []);
    setTradingNote(typeof data.trading_note === 'string' ? data.trading_note : '');
    setSourceStatus(typeof data.source_status === 'string' ? data.source_status : '');
    setError(data.status === 'ERROR' ? (data.error || 'Calendar source unavailable.') : null);

    const map = new Map<string, CalendarEvent[]>();
    events.forEach(ev => {
      const dateKey = (ev.date || '').split('T')[0];
      if (!dateKey) return;
      if (!map.has(dateKey)) map.set(dateKey, []);
      map.get(dateKey)!.push(ev);
    });

    const sorted = Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, evs]) => ({
        date,
        label: dayLabel(date),
        events: evs.sort((a, b) => {
          const order = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };
          return (order[a.impact] ?? 3) - (order[b.impact] ?? 3);
        })
      }));

    setDays(sorted);
    setLastUpdated(new Date());
    const autoExpand = new Set<string>();
    sorted.forEach(d => { if (isToday(d.date) || isTomorrow(d.date)) autoExpand.add(d.date); });
    setExpanded(autoExpand);
  }, []);

  useEffect(() => {
    try {
      const cachedRaw = localStorage.getItem(CALENDAR_CACHE_KEY);
      if (!cachedRaw) return;
      const cached = JSON.parse(cachedRaw);
      if (!cached || typeof cached !== 'object' || !cached.data) return;
      applyCalendarData(cached.data);
      setLoading(false);
    } catch {
      // ignore cache read issues
    }
  }, [applyCalendarData]);

  const load = useCallback(async () => {
    setLoading(days.length === 0);
    try {
      const res = await fetch(`/api/market/calendar?days=${range}`, { headers: { 'X-API-Key': 'demo' } });
      if (!res.ok) {
        throw new Error(`Calendar request failed (${res.status})`);
      }
      const data = await res.json();
      applyCalendarData(data);
      try {
        localStorage.setItem(CALENDAR_CACHE_KEY, JSON.stringify({ savedAt: Date.now(), data }));
      } catch {
        // ignore cache write issues
      }
    } catch (err) {
      setSourceStatus(prev => prev || 'error');
      setError(err instanceof Error ? err.message : 'Calendar source unavailable.');
    } finally {
      setLoading(false);
    }
  }, [applyCalendarData, range]);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 30 minutes
  useEffect(() => {
    const id = setInterval(() => load(), 30 * 60 * 1000);
    return () => clearInterval(id);
  }, [load]);

  const toggle = (date: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(date) ? n.delete(date) : n.add(date); return n; });

  const filteredDays = days.map(d => ({
    ...d,
    events: d.events.filter(ev => {
      if (filter === 'ALL')      return true;
      if (filter === 'EARNINGS') return ev.type === 'EARNINGS';
      if (filter === 'HIGH')     return ev.impact === 'HIGH' || ev.impact === 'CRITICAL';
      return ev.impact === filter;
    })
  })).filter(d => d.events.length > 0);

  const totalEvents    = filteredDays.reduce((s, d) => s + d.events.length, 0);
  const criticalCount  = days.flatMap(d => d.events).filter(e => e.impact === 'CRITICAL').length;
  const highCount      = days.flatMap(d => d.events).filter(e => e.impact === 'HIGH').length;
  const earningsCount  = days.flatMap(d => d.events).filter(e => e.type === 'EARNINGS').length;
  const estimatedCount = days.flatMap(d => d.events).filter(e => e.is_estimated).length;
  const nextCritical = days
    .flatMap(d => d.events)
    .filter(e => e.impact === 'CRITICAL' || e.impact === 'HIGH')
    .sort((a, b) => `${a.date} ${a.time ?? ''}`.localeCompare(`${b.date} ${b.time ?? ''}`))[0];

  return (
    <div className={`flex-1 overflow-y-auto p-4 lg:p-5 space-y-4 scrollbar-hide transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950/20' : 'bg-slate-50'
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-amber-500/20 border border-amber-500/30 rounded-lg flex items-center justify-center">
              <CalendarDays className="w-3 h-3 text-amber-400" />
            </div>
            <h1 className={`text-xl font-black tracking-tighter transition-colors duration-500 ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>Economic Calendar</h1>
          </div>
          <p className="text-[11px] text-slate-500 font-medium mt-0.5 ml-8">Upcoming macro events, Fed decisions & earnings</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Range selector */}
          <div className={`flex p-0.5 border rounded-lg transition-all duration-500 ${
            theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200'
          }`}>
            {[7, 14, 30].map(d => (
              <button key={d} onClick={() => setRange(d)}
                className={`px-2 py-1 text-[9px] font-black uppercase tracking-widest rounded-md transition-all ${
                  range === d ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20' : 'text-slate-500 hover:text-slate-300'
                }`}>
                {d}D
              </button>
            ))}
          </div>
          <button onClick={load} title={lastUpdated ? `Last updated: ${lastUpdated.toLocaleTimeString()}` : 'Refresh'}
            className={`p-1.5 rounded-lg transition-all border ${
              theme === 'dark' ? 'bg-slate-900/50 border-white/5 text-slate-500 hover:text-white' : 'bg-white border-slate-200 text-slate-400 hover:text-slate-900 shadow-sm'
            }`}>
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: 'Total Events', value: String(totalEvents), color: theme === 'dark' ? 'border-slate-700 bg-slate-900/30' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40', text: theme === 'dark' ? 'text-white' : 'text-slate-900' },
          { label: 'Critical', value: String(criticalCount), color: theme === 'dark' ? 'border-red-500/20 bg-red-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40', text: 'text-red-500' },
          { label: 'High Impact', value: String(highCount), color: theme === 'dark' ? 'border-amber-400/20 bg-amber-400/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40', text: theme === 'dark' ? 'text-amber-400' : 'text-amber-600' },
          { label: 'Earnings', value: String(earningsCount), color: theme === 'dark' ? 'border-indigo-500/20 bg-indigo-500/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40', text: theme === 'dark' ? 'text-indigo-400' : 'text-indigo-600' },
        ].map(({ label, value, color, text }) => (
          <div key={label} className={`p-3 rounded-xl border transition-all duration-500 ${color}`}>
            <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-0.5">{label}</p>
            <p className={`text-xl font-black ${text}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <div className={`p-4 rounded-xl border transition-all duration-500 ${
          theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
        }`}>
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Next Risk Window</p>
          {nextCritical ? (
            <>
              <p className={`mt-2 text-sm font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{nextCritical.name}</p>
              <p className="mt-1 text-[11px] text-slate-500">
                {dayLabel(nextCritical.date)} {nextCritical.time ? `· ${nextCritical.time.slice(0, 5)}` : ''}
              </p>
            </>
          ) : (
            <p className="mt-2 text-[11px] text-slate-500">No high-priority window in the selected range.</p>
          )}
        </div>

        <div className={`p-4 rounded-xl border transition-all duration-500 ${
          theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
        }`}>
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Feed Mix</p>
          <p className={`mt-2 text-sm font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
            {totalEvents - estimatedCount} live · {estimatedCount} estimated
          </p>
          <p className="mt-1 text-[11px] text-slate-500">Estimated windows are guidance only and should be confirmed before execution.</p>
        </div>

        <div className={`p-4 rounded-xl border transition-all duration-500 ${
          theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
        }`}>
          <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Execution Hint</p>
          <p className={`mt-2 text-sm font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
            {criticalCount > 0 ? 'Avoid fresh entries into critical windows.' : 'No critical window detected.'}
          </p>
          <p className="mt-1 text-[11px] text-slate-500">Use the timeline below to plan around spreads and volatility expansion.</p>
        </div>
      </div>

      {/* Impact Filter */}
      <div className="flex items-center gap-1.5 flex-wrap">
        <span className="text-[9px] font-black text-slate-600 uppercase tracking-widest">Filter:</span>
        {(['ALL', 'CRITICAL', 'HIGH', 'MEDIUM', 'EARNINGS'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-2 py-1 rounded-lg text-[9px] font-black uppercase tracking-widest border transition-all ${
              filter === f
                ? 'bg-blue-600 border-blue-500 text-white shadow-lg shadow-blue-500/20'
                : (theme === 'dark' ? 'border-white/8 text-slate-500 hover:border-white/20 hover:text-slate-300' : 'bg-white border-slate-200 text-slate-400 hover:text-slate-700 shadow-sm')
            }`}>
            {f === 'CRITICAL' && <span className="w-1.5 h-1.5 bg-red-500    rounded-full inline-block mr-1.5" />}
            {f === 'HIGH'     && <span className="w-1.5 h-1.5 bg-amber-400  rounded-full inline-block mr-1.5" />}
            {f === 'MEDIUM'   && <span className="w-1.5 h-1.5 bg-blue-400   rounded-full inline-block mr-1.5" />}
            {f}
          </button>
        ))}
        {lastUpdated && (
          <span className="ml-auto text-[10px] text-slate-600 font-mono">
            อัปเดตล่าสุด {lastUpdated.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit' })}
          </span>
        )}
      </div>

      {(tradingNote || macroWatch.length > 0 || error) && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
          <div className={`xl:col-span-2 p-4 rounded-xl border transition-all duration-500 ${
            theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
          }`}>
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div>
                <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest">Trading Note</p>
                <p className={`mt-1 text-sm font-bold leading-relaxed ${theme === 'dark' ? 'text-slate-200' : 'text-slate-700'}`}>
                  {tradingNote || 'No calendar note available yet.'}
                </p>
              </div>
              <span className={`px-2 py-1 rounded-lg border text-[9px] font-black uppercase tracking-widest ${
                sourceStatus === 'live_feed'
                  ? theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-600'
                  : sourceStatus === 'watch_only'
                    ? theme === 'dark' ? 'bg-amber-500/10 border-amber-500/20 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-600'
                    : theme === 'dark' ? 'bg-rose-500/10 border-rose-500/20 text-rose-400' : 'bg-rose-50 border-rose-200 text-rose-600'
              }`}>
                {sourceStatus === 'live_feed' ? 'Live Feed' : sourceStatus === 'watch_only' ? 'Watch Only' : 'Source Error'}
              </span>
            </div>
            {error && (
              <p className={`mt-2 text-[11px] ${theme === 'dark' ? 'text-rose-300' : 'text-rose-600'}`}>
                {error}
              </p>
            )}
          </div>

          <div className={`p-4 rounded-xl border transition-all duration-500 ${
            theme === 'dark' ? 'bg-slate-900/40 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/30'
          }`}>
            <p className="text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">Macro Watch</p>
            <div className="space-y-2">
              {macroWatch.length === 0 ? (
                <p className="text-[11px] text-slate-500">No macro watch items yet.</p>
              ) : macroWatch.slice(0, 3).map((item, index) => {
                const cfg = IMPACT_CONFIG[item.impact] || IMPACT_CONFIG.LOW;
                return (
                  <div key={`${item.name}-${index}`} className={`p-2.5 rounded-lg border ${theme === 'dark' ? 'border-white/5 bg-white/5' : 'border-slate-100 bg-slate-50'}`}>
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${cfg.dot}`} />
                      <p className={`text-[11px] font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{item.abbrev || item.name}</p>
                    </div>
                    {item.desc && <p className="mt-1 text-[10px] text-slate-500 leading-relaxed">{item.desc}</p>}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Calendar Timeline */}
      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="flex flex-col items-center gap-3">
            <RefreshCw className="w-6 h-6 text-blue-400 animate-spin" />
            <p className="text-sm text-slate-500 font-bold">Loading economic calendar…</p>
          </div>
        </div>
      ) : filteredDays.length === 0 ? (
        <div className="py-20 text-center">
          <CalendarDays className="w-8 h-8 text-slate-700 mx-auto mb-3" />
          <p className="text-slate-500 font-bold text-sm">
            {sourceStatus === 'watch_only' ? 'No dated events in feed yet. Use Macro Watch above.' : 'No events found for this period'}
          </p>
          {sourceStatus && (
            <p className="mt-2 text-[11px] text-slate-500">
              {sourceStatus === 'live_feed'
                ? 'Live sources returned no upcoming items for this window.'
                : sourceStatus === 'watch_only'
                  ? 'Calendar is still usable through the macro watchlist and trading note.'
                  : 'Calendar source is currently unavailable.'}
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {filteredDays.map(({ date, label, events }) => {
            const isOpen  = expanded.has(date);
            const today   = isToday(date);
            const tomorrow = isTomorrow(date);
            const hasCritical = events.some(e => e.impact === 'CRITICAL');

            return (
              <motion.div
                key={date}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className={`rounded-xl border overflow-hidden transition-all duration-500 ${
                  today ? (theme === 'dark' ? 'border-blue-500/25 bg-blue-500/3' : 'border-blue-500/25 bg-blue-50/50 shadow-xl shadow-blue-100/40') : (theme === 'dark' ? 'border-white/5 bg-slate-900/40' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40')
                }`}
              >
                {/* Day Header */}
                <button
                  onClick={() => toggle(date)}
                  className={`w-full flex items-center justify-between px-4 py-3 transition-colors ${
                    theme === 'dark' ? 'hover:bg-white/2' : 'hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`text-center min-w-[2rem] ${today ? 'text-blue-400' : 'text-slate-300'}`}>
                      <div className="text-lg font-black leading-none">{new Date(date).getDate()}</div>
                      <div className="text-[8px] font-black uppercase tracking-widest opacity-60">
                        {new Date(date).toLocaleDateString('en-US', { month: 'short' })}
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-black transition-colors ${today ? (theme === 'dark' ? 'text-blue-300' : 'text-blue-600') : (theme === 'dark' ? 'text-white' : 'text-slate-900')}`}>{label}</span>
                        {today    && <span className={`px-1.5 py-0.5 border text-[8px] font-black uppercase rounded-full transition-all ${
                          theme === 'dark' ? 'bg-blue-500/20 border-blue-500/30 text-blue-400' : 'bg-blue-600 border-blue-600 text-white shadow-md shadow-blue-500/20'
                        }`}>Today</span>}
                        {tomorrow && <span className={`px-1.5 py-0.5 text-[8px] font-black uppercase rounded-full border transition-all ${
                          theme === 'dark' ? 'bg-slate-700/50 text-slate-400 border-white/10' : 'bg-slate-100 text-slate-600 border-slate-200'
                        }`}>Tomorrow</span>}
                        {hasCritical && <AlertTriangle className="w-3 h-3 text-red-500" />}
                      </div>
                      <p className="text-[10px] text-slate-500 font-medium mt-0.5">{events.length} event{events.length !== 1 ? 's' : ''}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      {['CRITICAL','HIGH','MEDIUM'].map(imp => {
                        const count = events.filter(e => e.impact === imp).length;
                        return count > 0 ? (
                          <span key={imp} className={`w-4 h-4 rounded-full flex items-center justify-center text-[8px] font-black ${IMPACT_CONFIG[imp].dot} bg-opacity-20 ${IMPACT_CONFIG[imp].text}`}>
                            {count}
                          </span>
                        ) : null;
                      })}
                    </div>
                    {isOpen ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
                  </div>
                </button>

                  {isOpen && (
                <div className={`border-t transition-colors duration-500 ${theme === 'dark' ? 'border-white/5 divide-y divide-white/3' : 'border-slate-100 divide-y divide-slate-100'}`}>
                    {events.map((ev, idx) => {
                      const cfg = IMPACT_CONFIG[ev.impact] || IMPACT_CONFIG.LOW;
                      return (
                        <div key={idx} className={`px-4 py-3 transition-colors ${
                          theme === 'dark' ? 'hover:bg-white/2' : 'hover:bg-slate-50/50'
                        }`}>
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex items-start gap-3 flex-1">
                              {/* Time */}
                              <div className="min-w-[3rem] text-right">
                                <span className="text-[10px] font-black text-slate-500 font-mono">
                                  {ev.time ? ev.time.slice(0, 5) : '—'}
                                </span>
                              </div>

                              {/* Impact dot */}
                              <div className="flex items-center mt-1">
                                <div className={`w-2 h-2 rounded-full ${cfg.dot} shadow-[0_0_6px_currentColor]`} />
                              </div>

                              {/* Content */}
                              <div className="flex-1">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                  {ev.currency && (
                                    <span className="px-1 py-0.5 bg-slate-800 border border-white/8 text-[8px] font-black text-slate-400 rounded uppercase">
                                      {ev.currency}
                                    </span>
                                  )}
                                {ev.symbol && (
                                  <span className="px-1 py-0.5 bg-indigo-500/10 border border-indigo-500/20 text-[8px] font-black text-indigo-400 rounded uppercase">
                                    {ev.symbol}
                                  </span>
                                )}
                                {ev.is_estimated && (
                                  <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase border ${
                                    theme === 'dark' ? 'bg-amber-500/10 border-amber-500/20 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-600'
                                  }`}>
                                    Estimated
                                  </span>
                                )}
                                <span className={`px-1.5 py-0.5 rounded text-[8px] font-black uppercase border ${cfg.badge} ${cfg.text}`}>
                                  {cfg.label}
                                </span>
                                <span className="px-1.5 py-0.5 bg-slate-800/50 border border-white/5 text-[8px] font-black text-slate-500 rounded uppercase">
                                  {ev.type}
                                </span>
                              </div>
                              <p className={`text-xs font-black mt-1 transition-colors ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{ev.name}</p>
                              {ev.desc && <p className="text-[10px] text-slate-500 font-medium mt-0.5">{ev.desc}</p>}
                              {(ev.source || ev.source_url) && (
                                <div className="mt-2 flex items-center gap-2 flex-wrap">
                                  {ev.source && (
                                    <p className="text-[9px] text-slate-400 uppercase tracking-widest">
                                      Source: {ev.source.replaceAll('_', ' ')}
                                    </p>
                                  )}
                                  <a
                                    href={buildEventSourceUrl(ev)}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[9px] font-black uppercase tracking-[0.16em] transition-all ${
                                      theme === 'dark'
                                        ? 'border-blue-400/20 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20'
                                        : 'border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100'
                                    }`}
                                  >
                                    View Source
                                    <ExternalLink className="h-2.5 w-2.5" />
                                  </a>
                                </div>
                              )}
                            </div>
                          </div>

                            {/* Actual / Forecast / Previous */}
                            {(ev.actual != null || ev.forecast != null || ev.previous != null || ev.estimate_eps != null) && (
                              <div className="flex gap-3 shrink-0 text-right">
                                {ev.type === 'EARNINGS' ? (
                                  <DataCell label="EPS Est." value={ev.estimate_eps != null ? `$${ev.estimate_eps}` : '—'} theme={theme} />
                                ) : (
                                  <>
                                    <DataCell label="Actual"   value={fmt(ev.actual)}   highlight={ev.actual != null} theme={theme} />
                                    <DataCell label="Forecast" value={fmt(ev.forecast)} theme={theme} />
                                    <DataCell label="Previous" value={fmt(ev.previous)} theme={theme} />
                                  </>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </motion.div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const DataCell = ({ label, value, highlight, theme }: { label: string; value: string; highlight?: boolean; theme: string }) => (
  <div>
    <p className="text-[8px] font-black text-slate-500 uppercase tracking-wider mb-0.5">{label}</p>
    <p className={`text-[10px] font-black font-mono transition-colors ${highlight ? 'text-amber-500' : (theme === 'dark' ? 'text-slate-400' : 'text-slate-600')}`}>{value}</p>
  </div>
);
