import React, { useState, useEffect } from 'react';
import { Clock, Globe, Zap } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLanguage } from '../../contexts/LanguageContext';

interface MarketData {
  status: 'OPEN' | 'CLOSED' | 'HOLIDAY';
  next_event: 'OPEN' | 'CLOSE';
  seconds_remaining: number;
  event_time: string;
}

interface MarketStatusResponse {
  crypto: { status: string; label: string };
  forex: MarketData;
  stocks: MarketData;
  timestamp_utc: string;
}

export const MarketStatusClock = () => {
  const { t } = useLanguage();
  const [data, setData] = useState<MarketStatusResponse | null>(null);
  const [index, setIndex] = useState(0);

  // ── Sync with Backend ──
  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const res = await fetch('/api/system/market-status');
        if (res.ok) {
          const json = await res.json();
          setData(json);
        }
      } catch (err) {
        console.error('Failed to sync market status:', err);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 30000); // Sync every 30s
    return () => clearInterval(interval);
  }, []);

  // ── Local Fallback Calculation ──
  const calculateLocalStatus = () => {
    const now = new Date();
    const nowUtc = new Date(now.getTime() + now.getTimezoneOffset() * 60000);
    const weekday = nowUtc.getDay(); // 0=Sun, 1=Mon...
    const hour = nowUtc.getHours();
    const timeVal = hour * 100 + nowUtc.getMinutes();

    // Forex (Sun 21:00 - Fri 21:00)
    let forexStatus = 'CLOSED';
    let forexNext = 'OPEN';
    let forexTarget = new Date(nowUtc);
    if ((weekday === 0 && hour >= 21) || (weekday > 0 && weekday < 5) || (weekday === 5 && hour < 21)) {
      forexStatus = 'OPEN';
      forexNext = 'CLOSE';
      const daysToFri = (5 - weekday + 7) % 7;
      forexTarget.setDate(nowUtc.getDate() + daysToFri);
      forexTarget.setHours(21, 0, 0, 0);
    } else {
      const daysToSun = (7 - weekday) % 7;
      forexTarget.setDate(nowUtc.getDate() + daysToSun);
      forexTarget.setHours(21, 0, 0, 0);
    }

    // Stocks (Mon-Fri 13:30 - 20:00)
    let stocksStatus = 'CLOSED';
    let stocksNext = 'OPEN';
    let stocksTarget = new Date(nowUtc);
    if (weekday >= 1 && weekday <= 5 && timeVal >= 1330 && timeVal < 2000) {
      stocksStatus = 'OPEN';
      stocksNext = 'CLOSE';
      stocksTarget.setHours(20, 0, 0, 0);
    } else {
      if (weekday >= 1 && weekday <= 5 && timeVal < 1330) {
        stocksTarget.setHours(13, 30, 0, 0);
      } else {
        const daysToAdd = weekday === 5 ? 3 : weekday === 6 ? 2 : 1;
        stocksTarget.setDate(nowUtc.getDate() + daysToAdd);
        stocksTarget.setHours(13, 30, 0, 0);
      }
    }

    return {
      crypto: { status: 'OPEN', label: '24/7' },
      forex: { 
        status: forexStatus as any, 
        next_event: forexNext as any, 
        seconds_remaining: Math.floor((forexTarget.getTime() - nowUtc.getTime()) / 1000),
        event_time: forexTarget.toISOString()
      },
      stocks: { 
        status: stocksStatus as any, 
        next_event: stocksNext as any, 
        seconds_remaining: Math.floor((stocksTarget.getTime() - nowUtc.getTime()) / 1000),
        event_time: stocksTarget.toISOString()
      },
      timestamp_utc: nowUtc.toISOString()
    };
  };

  // Initial local state
  useEffect(() => {
    if (!data) {
      setData(calculateLocalStatus());
    }
  }, []);

  // ── Mode Switcher ──
  useEffect(() => {
    const timer = setInterval(() => {
      setIndex(prev => (prev + 1) % 2);
    }, 6000);
    return () => clearInterval(timer);
  }, []);

  const getMarketInfo = () => {
    if (!data) return null;
    const markets = [
      { id: 'forex', label: t('navbar.market_gold'), info: data.forex },
      { id: 'stocks', label: t('navbar.market_stocks'), info: data.stocks },
    ];
    return markets[index % markets.length];
  };

  const formatTime = (seconds: number) => {
    if (!seconds || seconds < 0) return '00:00:00';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const current = getMarketInfo();

  if (!data || !current?.info) {
    return (
      <div className="flex items-center justify-center w-[360px] h-10 px-4 bg-blue-500/10 border border-blue-500/30 rounded-xl backdrop-blur-xl shadow-[0_0_15px_rgba(59,130,246,0.1)]">
        <div className="flex items-center gap-3 animate-pulse">
           <div className="w-2 h-2 bg-blue-400 rounded-full shadow-[0_0_8px_rgba(96,165,250,0.5)]" />
           <span className="text-[10px] uppercase tracking-[0.2em] font-black text-blue-400/80">Syncing Market Data...</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative flex items-center justify-center w-[360px] h-10 px-4 rounded-xl transition-all duration-500 cursor-default select-none overflow-hidden backdrop-blur-md group
      ${current.info.status === 'OPEN' ? 'bg-emerald-500/5 border border-emerald-500/20 shadow-[0_0_20px_rgba(16,185,129,0.05)] hover:border-emerald-500/40 hover:shadow-[0_0_25px_rgba(16,185,129,0.1)]' : 
        current.info.status === 'HOLIDAY' ? 'bg-blue-500/5 border border-blue-500/20 shadow-[0_0_20px_rgba(59,130,246,0.05)] hover:border-blue-500/40' : 
        'bg-rose-500/5 border border-rose-500/20 shadow-[0_0_20px_rgba(244,63,94,0.05)] hover:border-rose-500/40 hover:shadow-[0_0_25px_rgba(244,63,94,0.1)]'
      }`}
    >
      {/* Background ambient glow line at bottom */}
      <div className={`absolute bottom-0 left-0 h-[1px] w-full bg-gradient-to-r from-transparent via-[rgba(255,255,255,0.1)] to-transparent opacity-50 group-hover:opacity-100 transition-opacity`} />
      
      <AnimatePresence mode="wait">
        <motion.div
           key={current.id}
           initial={{ opacity: 0, scale: 0.95, filter: "blur(4px)" }}
           animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
           exit={{ opacity: 0, scale: 1.05, filter: "blur(4px)" }}
           transition={{ duration: 0.3, ease: "easeOut" }}
           className="flex items-center justify-between w-full"
        >
          {/* Label & Indicator */}
          <div className="flex items-center gap-3">
            <div className={`flex items-center justify-center w-7 h-7 rounded-lg border shadow-inner ${
                current.info.status === 'OPEN' ? 'bg-emerald-500/10 border-emerald-500/20 shadow-emerald-500/20' : 
                current.info.status === 'HOLIDAY' ? 'bg-blue-500/10 border-blue-500/20 shadow-blue-500/20' : 
                'bg-rose-500/10 border-rose-500/20 shadow-rose-500/20'
            }`}>
              {current.id === 'forex' ? (
                <Globe className={`w-3.5 h-3.5 ${current.info.status === 'OPEN' ? 'text-emerald-400' : current.info.status === 'HOLIDAY' ? 'text-blue-400' : 'text-rose-400'}`} />
              ) : (
                <Zap className={`w-3.5 h-3.5 ${current.info.status === 'OPEN' ? 'text-emerald-400' : current.info.status === 'HOLIDAY' ? 'text-blue-400' : 'text-rose-400'}`} />
              )}
            </div>
            <div className="flex flex-col items-start leading-none">
              <span className="text-[10px] font-black text-slate-300 uppercase tracking-[0.2em] mb-0.5">
                {current.label}
              </span>
              <div className="flex items-center gap-1.5">
                <div className={`w-1.5 h-1.5 rounded-full ${
                  current.info.status === 'OPEN' ? 'bg-emerald-400 shadow-[0_0_8px_#34d399] animate-pulse' : 
                  current.info.status === 'HOLIDAY' ? 'bg-blue-400 shadow-[0_0_8px_#60a5fa]' : 'bg-rose-400 shadow-[0_0_8px_#fb7185]'
                }`} />
                <span className={`text-[9px] font-bold uppercase tracking-widest ${
                  current.info.status === 'OPEN' ? 'text-emerald-400' : 
                  current.info.status === 'HOLIDAY' ? 'text-blue-400' : 'text-rose-400'
                }`}>
                  {current.info.status === 'OPEN' ? t('navbar.market_open') : 
                   current.info.status === 'HOLIDAY' ? 'HOLIDAY' : t('navbar.market_closed')}
                </span>
              </div>
            </div>
          </div>

          {/* Time & Countdown */}
          <div className="flex flex-col items-end leading-none">
            <div className="flex items-center gap-1.5 mb-0.5">
              <Clock className={`w-3 h-3 ${current.info.status === 'OPEN' ? 'text-emerald-500/50' : 'text-slate-500/50'}`} />
              <span className={`text-[12px] font-mono font-black tabular-nums tracking-tight ${
                 current.info.status === 'OPEN' ? 'text-white' : 'text-slate-300'
              }`}>
                {formatTime(current.info.seconds_remaining)}
              </span>
            </div>
            <span className="text-[8px] font-bold text-slate-500 uppercase tracking-[0.1em] text-right">
              {current.info.next_event === 'OPEN' ? t('navbar.opens_in') : t('navbar.closes_in')}
              {current.info.event_time && (
                <span className="ml-[3px] opacity-70">
                  (@ {
                    (() => {
                      try {
                        return new Date(current.info.event_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                      } catch (e) {
                        return '--:--';
                      }
                    })()
                  })
                </span>
              )}
            </span>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
};
