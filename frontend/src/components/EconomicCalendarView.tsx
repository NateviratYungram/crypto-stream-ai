import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { CalendarDays, RefreshCw, AlertTriangle, TrendingUp, Minus, ChevronDown, ChevronUp } from 'lucide-react';

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
}

type DayGroup = { date: string; label: string; events: CalendarEvent[] };

const IMPACT_CONFIG: Record<string, { dot: string; badge: string; text: string; label: string }> = {
  CRITICAL: { dot: 'bg-red-500',    badge: 'bg-red-500/10 border-red-500/30',    text: 'text-red-400',    label: 'CRITICAL' },
  HIGH:     { dot: 'bg-amber-400',  badge: 'bg-amber-400/10 border-amber-400/30',  text: 'text-amber-400',  label: 'HIGH' },
  MEDIUM:   { dot: 'bg-blue-400',   badge: 'bg-blue-400/10 border-blue-400/30',   text: 'text-blue-400',   label: 'MEDIUM' },
  LOW:      { dot: 'bg-slate-600',  badge: 'bg-slate-600/10 border-slate-600/30',  text: 'text-slate-500',  label: 'LOW' },
};

const fmt = (v: string | number | null | undefined) => (v == null || v === '') ? '—' : String(v);

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
  const [days,      setDays]      = useState<DayGroup[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [range,     setRange]     = useState(7);
  const [filter,    setFilter]    = useState<'ALL' | 'CRITICAL' | 'HIGH' | 'EARNINGS'>('ALL');
  const [expanded,  setExpanded]  = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/market/calendar?days=${range}`, { headers: { 'X-API-Key': 'demo' } });
      const data = await res.json();
      const events: CalendarEvent[] = data.events || data.upcoming_events || [];

      // Group by date
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
      // Auto-expand today + tomorrow
      const autoExpand = new Set<string>();
      sorted.forEach(d => { if (isToday(d.date) || isTomorrow(d.date)) autoExpand.add(d.date); });
      setExpanded(autoExpand);
    } catch {
      setDays([]);
    } finally {
      setLoading(false);
    }
  }, [range]);

  useEffect(() => { load(); }, [load]);

  const toggle = (date: string) =>
    setExpanded(prev => { const n = new Set(prev); n.has(date) ? n.delete(date) : n.add(date); return n; });

  const filteredDays = days.map(d => ({
    ...d,
    events: d.events.filter(ev => {
      if (filter === 'ALL') return true;
      if (filter === 'EARNINGS') return ev.type === 'EARNINGS';
      return ev.impact === filter;
    })
  })).filter(d => d.events.length > 0);

  const totalEvents    = filteredDays.reduce((s, d) => s + d.events.length, 0);
  const criticalCount  = days.flatMap(d => d.events).filter(e => e.impact === 'CRITICAL').length;
  const highCount      = days.flatMap(d => d.events).filter(e => e.impact === 'HIGH').length;
  const earningsCount  = days.flatMap(d => d.events).filter(e => e.type === 'EARNINGS').length;

  return (
    <div className="flex-1 overflow-y-auto p-6 lg:p-8 space-y-6 scrollbar-hide">
      {/* Header */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-amber-500/20 border border-amber-500/30 rounded-xl flex items-center justify-center">
              <CalendarDays className="w-4 h-4 text-amber-400" />
            </div>
            <h1 className="text-2xl font-black text-white tracking-tighter">Economic Calendar</h1>
          </div>
          <p className="text-sm text-slate-500 font-medium mt-1 ml-11">Upcoming macro events, Fed decisions & earnings</p>
        </div>
        <div className="flex items-center gap-2">
          {/* Range selector */}
          <div className="flex p-0.5 bg-slate-900/50 border border-white/5 rounded-xl">
            {[7, 14, 30].map(d => (
              <button key={d} onClick={() => setRange(d)}
                className={`px-3 py-1.5 text-[10px] font-black uppercase tracking-widest rounded-lg transition-all ${
                  range === d ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-slate-300'
                }`}>
                {d}D
              </button>
            ))}
          </div>
          <button onClick={load} className="p-2 text-slate-500 hover:text-white bg-slate-900/50 border border-white/5 rounded-xl transition-all">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Events', value: String(totalEvents), color: 'border-slate-700 bg-slate-900/30', text: 'text-white' },
          { label: 'Critical', value: String(criticalCount), color: 'border-red-500/20 bg-red-500/5', text: 'text-red-400' },
          { label: 'High Impact', value: String(highCount), color: 'border-amber-400/20 bg-amber-400/5', text: 'text-amber-400' },
          { label: 'Earnings', value: String(earningsCount), color: 'border-indigo-500/20 bg-indigo-500/5', text: 'text-indigo-400' },
        ].map(({ label, value, color, text }) => (
          <div key={label} className={`p-4 rounded-2xl border ${color}`}>
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1">{label}</p>
            <p className={`text-2xl font-black ${text}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Impact Filter */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-black text-slate-600 uppercase tracking-widest">Filter:</span>
        {(['ALL', 'CRITICAL', 'HIGH', 'EARNINGS'] as const).map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-xl text-[10px] font-black uppercase tracking-widest border transition-all ${
              filter === f
                ? 'bg-blue-600 border-blue-500 text-white'
                : 'border-white/8 text-slate-500 hover:border-white/20 hover:text-slate-300'
            }`}>
            {f === 'CRITICAL' && <span className="w-1.5 h-1.5 bg-red-500 rounded-full inline-block mr-1.5" />}
            {f === 'HIGH'     && <span className="w-1.5 h-1.5 bg-amber-400 rounded-full inline-block mr-1.5" />}
            {f}
          </button>
        ))}
      </div>

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
          <p className="text-slate-500 font-bold text-sm">No events found for this period</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredDays.map(({ date, label, events }) => {
            const isOpen  = expanded.has(date);
            const today   = isToday(date);
            const tomorrow = isTomorrow(date);
            const hasCritical = events.some(e => e.impact === 'CRITICAL');

            return (
              <motion.div
                key={date}
                initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                className={`rounded-2xl border overflow-hidden ${
                  today ? 'border-blue-500/25 bg-blue-500/3' : 'border-white/5 bg-slate-900/40'
                }`}
              >
                {/* Day Header */}
                <button
                  onClick={() => toggle(date)}
                  className="w-full flex items-center justify-between px-5 py-4 hover:bg-white/2 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className={`text-center min-w-[2.5rem] ${today ? 'text-blue-400' : 'text-slate-300'}`}>
                      <div className="text-xl font-black leading-none">{new Date(date).getDate()}</div>
                      <div className="text-[9px] font-black uppercase tracking-widest opacity-60">
                        {new Date(date).toLocaleDateString('en-US', { month: 'short' })}
                      </div>
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-black ${today ? 'text-blue-300' : 'text-white'}`}>{label}</span>
                        {today    && <span className="px-2 py-0.5 bg-blue-500/20 border border-blue-500/30 text-blue-400 text-[9px] font-black uppercase rounded-full">Today</span>}
                        {tomorrow && <span className="px-2 py-0.5 bg-slate-700/50 text-slate-400 text-[9px] font-black uppercase rounded-full border border-white/10">Tomorrow</span>}
                        {hasCritical && <AlertTriangle className="w-3.5 h-3.5 text-red-400" />}
                      </div>
                      <p className="text-xs text-slate-600 font-medium mt-0.5">{events.length} event{events.length !== 1 ? 's' : ''}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="flex gap-1">
                      {['CRITICAL','HIGH','MEDIUM'].map(imp => {
                        const count = events.filter(e => e.impact === imp).length;
                        return count > 0 ? (
                          <span key={imp} className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-black ${IMPACT_CONFIG[imp].dot} bg-opacity-20 ${IMPACT_CONFIG[imp].text}`}>
                            {count}
                          </span>
                        ) : null;
                      })}
                    </div>
                    {isOpen ? <ChevronUp className="w-4 h-4 text-slate-500" /> : <ChevronDown className="w-4 h-4 text-slate-500" />}
                  </div>
                </button>

                {/* Events */}
                {isOpen && (
                  <div className="border-t border-white/5 divide-y divide-white/3">
                    {events.map((ev, idx) => {
                      const cfg = IMPACT_CONFIG[ev.impact] || IMPACT_CONFIG.LOW;
                      return (
                        <div key={idx} className="px-5 py-4 hover:bg-white/2 transition-colors">
                          <div className="flex items-start justify-between gap-4">
                            <div className="flex items-start gap-4 flex-1">
                              {/* Time */}
                              <div className="min-w-[3.5rem] text-right">
                                <span className="text-xs font-black text-slate-500 font-mono">
                                  {ev.time ? ev.time.slice(0, 5) : '—'}
                                </span>
                              </div>

                              {/* Impact dot */}
                              <div className="flex items-center mt-1">
                                <div className={`w-2 h-2 rounded-full ${cfg.dot} shadow-[0_0_6px_currentColor]`} />
                              </div>

                              {/* Content */}
                              <div className="flex-1">
                                <div className="flex items-center gap-2 flex-wrap">
                                  {ev.currency && (
                                    <span className="px-1.5 py-0.5 bg-slate-800 border border-white/8 text-[9px] font-black text-slate-400 rounded uppercase">
                                      {ev.currency}
                                    </span>
                                  )}
                                  {ev.symbol && (
                                    <span className="px-1.5 py-0.5 bg-indigo-500/10 border border-indigo-500/20 text-[9px] font-black text-indigo-400 rounded uppercase">
                                      {ev.symbol}
                                    </span>
                                  )}
                                  <span className={`px-2 py-0.5 rounded-lg text-[9px] font-black uppercase border ${cfg.badge} ${cfg.text}`}>
                                    {cfg.label}
                                  </span>
                                  <span className="px-2 py-0.5 bg-slate-800/50 border border-white/5 text-[9px] font-black text-slate-500 rounded uppercase">
                                    {ev.type}
                                  </span>
                                </div>
                                <p className="text-sm font-black text-white mt-1.5">{ev.name}</p>
                                {ev.desc && <p className="text-xs text-slate-500 font-medium mt-0.5">{ev.desc}</p>}
                              </div>
                            </div>

                            {/* Actual / Forecast / Previous */}
                            {(ev.actual != null || ev.forecast != null || ev.previous != null || ev.estimate_eps != null) && (
                              <div className="flex gap-4 shrink-0 text-right">
                                {ev.type === 'EARNINGS' ? (
                                  <DataCell label="EPS Est." value={ev.estimate_eps != null ? `$${ev.estimate_eps}` : '—'} />
                                ) : (
                                  <>
                                    <DataCell label="Actual"   value={fmt(ev.actual)}   highlight={ev.actual != null} />
                                    <DataCell label="Forecast" value={fmt(ev.forecast)} />
                                    <DataCell label="Previous" value={fmt(ev.previous)} />
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

const DataCell = ({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) => (
  <div>
    <p className="text-[9px] font-black text-slate-600 uppercase tracking-wider mb-0.5">{label}</p>
    <p className={`text-xs font-black font-mono ${highlight ? 'text-amber-400' : 'text-slate-400'}`}>{value}</p>
  </div>
);
