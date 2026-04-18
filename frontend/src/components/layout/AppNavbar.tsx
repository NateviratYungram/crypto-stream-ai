import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Bell, Command, Menu, Search, User, TrendingUp, TrendingDown, Brain, CheckCheck } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLanguage } from '../../contexts/LanguageContext';

interface AppNavbarProps {
  mode: 'institutional' | 'retail';
  setMode: (mode: 'institutional' | 'retail') => void;
  onOpenCommand: () => void;
  isAuthorized: boolean;
  onLogout: () => void;
  onMobileMenuClick?: () => void;
  onNavigate?: (tab: string) => void;
}

interface SignalNotif {
  id: string;
  symbol: string;
  direction: 'BUY' | 'SELL';
  confidence: number;
  reason?: string;
  timeframe?: string;
  ts: number;
  read: boolean;
}

const STORAGE_KEY = 'cs_notif_read';

function getReadIds(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')); }
  catch { return new Set(); }
}
function saveReadIds(ids: Set<string>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...ids].slice(-200)));
}
function timeAgo(ts: number, lang: string): string {
  const s = Math.floor((Date.now() - ts) / 1000);
  if (lang === 'th') {
    if (s < 60)   return `${s} วิที่แล้ว`;
    if (s < 3600) return `${Math.floor(s / 60)} นาทีที่แล้ว`;
    return `${Math.floor(s / 3600)} ชม.ที่แล้ว`;
  }
  if (s < 60)   return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
}

export const AppNavbar: React.FC<AppNavbarProps> = ({
  mode, setMode, onOpenCommand, isAuthorized, onLogout, onMobileMenuClick, onNavigate
}) => {
  const { lang, setLang, t } = useLanguage();
  const [notifOpen, setNotifOpen]  = useState(false);
  const [notifs,    setNotifs]     = useState<SignalNotif[]>([]);
  const [lastFetch, setLastFetch]  = useState(0);
  const dropRef = useRef<HTMLDivElement>(null);

  const unread = notifs.filter(n => !n.read).length;

  const fetchSignals = useCallback(async () => {
    try {
      const res = await fetch('/api/signals');
      if (!res.ok) return;
      const data = await res.json();
      const signals: SignalNotif[] = (Array.isArray(data) ? data : data.signals ?? [])
        .slice(0, 20)
        .map((s: Record<string, unknown>, i: number) => ({
          id:         `${s.symbol}-${s.direction}-${s.timeframe ?? ''}-${Date.now()}-${i}`,
          symbol:     String(s.symbol ?? ''),
          direction:  (s.direction as 'BUY' | 'SELL') ?? 'BUY',
          confidence: Number(s.confidence ?? 0),
          reason:     String(s.reason ?? ''),
          timeframe:  String(s.timeframe ?? ''),
          ts:         Date.now(),
          read:       false,
        }));
      const readIds = getReadIds();
      setNotifs(prev => {
        const prevIds = new Set(prev.map(p => `${p.symbol}-${p.direction}-${p.timeframe}`));
        const fresh   = signals
          .filter(s => !prevIds.has(`${s.symbol}-${s.direction}-${s.timeframe}`))
          .map(s => ({ ...s, read: readIds.has(s.id) }));
        return [...fresh, ...prev].slice(0, 30);
      });
      setLastFetch(Date.now());
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    if (!isAuthorized) return;
    fetchSignals();
    const iv = setInterval(fetchSignals, 5 * 60_000);
    return () => clearInterval(iv);
  }, [isAuthorized, fetchSignals]);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) setNotifOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const markAllRead = () => {
    const readIds = getReadIds();
    setNotifs(prev => prev.map(n => { readIds.add(n.id); return { ...n, read: true }; }));
    saveReadIds(readIds);
  };

  const handleNotifClick = (n: SignalNotif) => {
    const readIds = getReadIds();
    readIds.add(n.id);
    saveReadIds(readIds);
    setNotifs(prev => prev.map(p => p.id === n.id ? { ...p, read: true } : p));
    setNotifOpen(false);
    onNavigate?.('Intelligence Hub');
  };

  const handleViewAll = () => {
    markAllRead();
    setNotifOpen(false);
    onNavigate?.('Intelligence Hub');
  };

  return (
    <header className="h-16 border-b border-white/5 bg-slate-950/50 backdrop-blur-xl flex items-center justify-between px-4 md:px-6 shrink-0 z-50">
      <div className="flex items-center gap-3">
        <button onClick={onMobileMenuClick} className="lg:hidden p-2 rounded-xl hover:bg-white/5 text-slate-400 hover:text-white transition-all active:scale-90" aria-label="Open menu">
          <Menu className="w-5 h-5" />
        </button>
        <div className="flex items-center gap-3 cursor-pointer active:scale-95 transition-all" onClick={onLogout}>
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <span className="text-white font-black text-sm">C</span>
          </div>
          <div className="hidden md:block text-left">
            <h2 className="text-sm font-black text-white tracking-tighter uppercase">CryptoStream</h2>
            <p className="text-[9px] text-slate-500 font-bold uppercase tracking-[0.2em] -mt-1">{t('navbar.tagline')}</p>
          </div>
        </div>
      </div>

      {/* Search */}
      <div className="flex-1 max-w-xl px-12 hidden md:block">
        <button onClick={onOpenCommand} className="w-full h-10 bg-white/5 border border-white/5 rounded-xl px-4 flex items-center justify-between group hover:border-blue-500/30 transition-all shadow-inner active:scale-[0.99]">
          <div className="flex items-center gap-3">
            <Search className="w-4 h-4 text-slate-500 group-hover:text-blue-400 transition-colors" />
            <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300 transition-colors">{t('navbar.search_placeholder')}</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white/5 border border-white/10">
            <Command className="w-3 h-3 text-slate-600" />
            <span className="text-[10px] font-black text-slate-300">K</span>
          </div>
        </button>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2">
        {/* Mode Toggle */}
        <button
          onClick={() => setMode(mode === 'institutional' ? 'retail' : 'institutional')}
          className={`flex items-center gap-2 px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest border transition-all shadow-lg active:scale-95 ${
            mode === 'retail'
              ? 'bg-blue-600/10 border-blue-500/20 text-blue-400'
              : 'bg-emerald-600/10 border-emerald-500/20 text-emerald-500'
          }`}
        >
          <div className={`w-1.5 h-1.5 rounded-full ${mode === 'retail' ? 'bg-blue-400' : 'bg-emerald-400'} animate-pulse`} />
          {mode === 'retail' ? t('navbar.mode_retail') : t('navbar.mode_institutional')}
        </button>

        <div className="w-px h-6 bg-white/5" />

        {/* Language Toggle */}
        <button
          onClick={() => setLang(lang === 'th' ? 'en' : 'th')}
          className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-[11px] font-black border border-white/10 hover:border-white/20 bg-white/5 hover:bg-white/10 text-slate-300 hover:text-white transition-all active:scale-95"
          title={lang === 'th' ? 'Switch to English' : 'เปลี่ยนเป็นภาษาไทย'}
        >
          <span className="text-base leading-none">{lang === 'th' ? '🇹🇭' : '🇬🇧'}</span>
          <span className="hidden sm:block">{lang === 'th' ? 'TH' : 'EN'}</span>
        </button>

        <div className="w-px h-6 bg-white/5" />

        {/* Bell */}
        <div className="relative" ref={dropRef}>
          <button
            onClick={() => setNotifOpen(o => !o)}
            className="p-2.5 rounded-xl hover:bg-white/5 text-slate-500 hover:text-white transition-all relative active:scale-90"
          >
            <Bell className={`w-5 h-5 transition-colors ${notifOpen ? 'text-blue-400' : ''}`} />
            {unread > 0 && (
              <motion.span
                key={unread}
                initial={{ scale: 0.5, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                className="absolute -top-0.5 -right-0.5 min-w-[18px] h-[18px] px-1 bg-blue-500 text-white text-[10px] font-black rounded-full flex items-center justify-center border-2 border-slate-950 tabular-nums"
              >
                {unread > 99 ? '99+' : unread}
              </motion.span>
            )}
          </button>

          <AnimatePresence>
            {notifOpen && (
              <motion.div
                initial={{ opacity: 0, y: -8, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -8, scale: 0.97 }}
                transition={{ duration: 0.15 }}
                className="absolute right-0 top-full mt-2 w-80 bg-slate-900/95 backdrop-blur-2xl border border-white/10 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden z-[200]"
              >
                <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
                  <div className="flex items-center gap-2">
                    <Brain className="w-4 h-4 text-blue-400" />
                    <span className="text-xs font-black text-white uppercase tracking-widest">{t('navbar.intelligence_center')}</span>
                    {unread > 0 && (
                      <span className="px-1.5 py-0.5 bg-blue-500/20 border border-blue-500/30 rounded-full text-[10px] font-black text-blue-400">
                        {unread} {t('navbar.new_badge')}
                      </span>
                    )}
                  </div>
                  {unread > 0 && (
                    <button onClick={markAllRead} className="flex items-center gap-1 text-[10px] text-slate-500 hover:text-blue-400 transition-colors font-bold">
                      <CheckCheck className="w-3.5 h-3.5" />
                      {t('navbar.mark_all_read')}
                    </button>
                  )}
                </div>

                <div className="max-h-80 overflow-y-auto custom-scrollbar">
                  {notifs.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-10 text-center">
                      {lastFetch === 0 ? (
                        <>
                          <div className="w-5 h-5 border-2 border-blue-500/40 border-t-blue-400 rounded-full animate-spin mb-3" />
                          <p className="text-xs text-slate-500">{t('navbar.loading_signals')}</p>
                        </>
                      ) : (
                        <>
                          <Bell className="w-8 h-8 text-slate-700 mb-3" />
                          <p className="text-xs font-bold text-slate-500">{t('navbar.no_signals')}</p>
                        </>
                      )}
                    </div>
                  ) : (
                    notifs.map((n, i) => (
                      <motion.button
                        key={n.id}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.03 }}
                        onClick={() => handleNotifClick(n)}
                        className={`w-full flex items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-white/5 border-b border-white/[0.03] last:border-0 ${!n.read ? 'bg-blue-500/[0.04]' : ''}`}
                      >
                        <div className={`mt-0.5 p-1.5 rounded-lg shrink-0 ${n.direction === 'BUY' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400'}`}>
                          {n.direction === 'BUY' ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5">
                              <span className="text-sm font-black text-white">{n.symbol}</span>
                              <span className={`text-[10px] font-black px-1.5 py-0.5 rounded-md ${n.direction === 'BUY' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-rose-500/15 text-rose-400'}`}>
                                {n.direction}
                              </span>
                              {n.timeframe && <span className="text-[10px] text-slate-600 font-mono">{n.timeframe}</span>}
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0">
                              <span className={`text-[10px] font-black tabular-nums ${n.confidence >= 80 ? 'text-emerald-400' : n.confidence >= 65 ? 'text-amber-400' : 'text-slate-500'}`}>
                                {n.confidence.toFixed(0)}%
                              </span>
                              {!n.read && <span className="w-1.5 h-1.5 bg-blue-400 rounded-full" />}
                            </div>
                          </div>
                          {n.reason && <p className="text-[11px] text-slate-500 mt-0.5 truncate">{n.reason}</p>}
                          <p className="text-[10px] text-slate-600 mt-0.5">{timeAgo(n.ts, lang)}</p>
                        </div>
                      </motion.button>
                    ))
                  )}
                </div>

                <button
                  onClick={handleViewAll}
                  className="w-full px-4 py-3 text-[11px] font-black text-blue-400 hover:text-blue-300 uppercase tracking-widest border-t border-white/5 hover:bg-white/5 transition-colors flex items-center justify-center gap-2"
                >
                  <Brain className="w-3.5 h-3.5" />
                  {t('navbar.view_all_intelligence')}
                </button>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <button onClick={onLogout} className="flex items-center gap-2 p-1 pr-3 rounded-2xl bg-white/10 hover:bg-white/20 transition-all text-slate-200 hover:text-white border border-white/20 active:scale-95 shadow-xl">
          <div className="w-8 h-8 rounded-xl bg-slate-900 border border-white/10 flex items-center justify-center overflow-hidden">
            <User className="w-5 h-5" />
          </div>
          <span className="text-[10px] font-black uppercase tracking-widest hidden md:block">{t('navbar.signout')}</span>
        </button>
      </div>
    </header>
  );
};
