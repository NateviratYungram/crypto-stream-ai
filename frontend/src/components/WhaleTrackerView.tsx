import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Clock, ArrowUpRight, ArrowDownRight, RefreshCcw, Zap, Filter, Download, TrendingUp, ArrowDownUp } from 'lucide-react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useMode } from '../contexts/ModeContext';
import { useLanguage } from '../contexts/LanguageContext';

interface WhaleEntry {
  symbol:        string;
  asset_class:   string;   // CRYPTO | STOCK | GOLD | OIL | FX | INDEX
  price:         number | string;
  quantity:      number | string;
  usd_value?:    number;
  is_buyer_maker: boolean;
  vol_ratio?:    number | null;
  timestamp:     string;
  source?:       string;
}

type WhaleTier = 'krill' | 'dolphin' | 'whale' | 'mega';
type AssetClass = 'ALL' | 'CRYPTO' | 'STOCK' | 'GOLD' | 'OIL' | 'FX' | 'INDEX';

const computeUSD = (qty: number, price: number) => qty * price;

const getUSDValue = (w: WhaleEntry): number => {
  if (w.usd_value && w.usd_value > 0) return w.usd_value;
  return computeUSD(parseFloat(String(w.quantity)), parseFloat(String(w.price)));
};

const getTier = (usdValue: number): WhaleTier => {
  if (usdValue >= 5_000_000)  return 'mega';
  if (usdValue >= 1_000_000)  return 'whale';
  if (usdValue >= 200_000)    return 'dolphin';
  return 'krill';
};

const tierConfig: Record<WhaleTier, { label: string; threshold: string; color: string; glow: string }> = {
  krill:   { label: 'KRILL',      threshold: '< $200k',  color: 'text-slate-400',   glow: '' },
  dolphin: { label: 'DOLPHIN',    threshold: '> $200k',  color: 'text-blue-400',    glow: 'shadow-[0_0_8px_rgba(59,130,246,0.25)]' },
  whale:   { label: 'WHALE',      threshold: '> $1M',    color: 'text-emerald-400', glow: 'shadow-[0_0_12px_rgba(16,185,129,0.3)]' },
  mega:    { label: 'MEGA-WHALE', threshold: '> $5M',    color: 'text-yellow-400',  glow: 'shadow-[0_0_20px_rgba(251,191,36,0.4)]' },
};

const assetClassConfig: Record<string, { color: string; bg: string; border: string; emoji: string }> = {
  CRYPTO: { color: 'text-violet-300', bg: 'bg-violet-500/10', border: 'border-violet-500/20', emoji: '₿' },
  STOCK:  { color: 'text-blue-300',   bg: 'bg-blue-500/10',   border: 'border-blue-500/20',   emoji: '📈' },
  GOLD:   { color: 'text-yellow-300', bg: 'bg-yellow-500/10', border: 'border-yellow-500/20', emoji: '🥇' },
  OIL:    { color: 'text-orange-300', bg: 'bg-orange-500/10', border: 'border-orange-500/20', emoji: '🛢' },
  FX:     { color: 'text-cyan-300',   bg: 'bg-cyan-500/10',   border: 'border-cyan-500/20',   emoji: '💱' },
  INDEX:  { color: 'text-pink-300',   bg: 'bg-pink-500/10',   border: 'border-pink-500/20',   emoji: '📊' },
};

const fmtUSD = (v: number) => {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000)     return `$${(v / 1_000).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
};

export const WhaleTrackerView = () => {
  const { t } = useLanguage();
  const [whales, setWhales]             = useState<WhaleEntry[]>([]);
  const [loading, setLoading]           = useState(true);
  const [filterTier, setFilterTier]     = useState<WhaleTier | 'all'>('all');
  const [filterDir,  setFilterDir]      = useState<'all' | 'buy' | 'sell'>('all');
  const [filterAsset, setFilterAsset]   = useState<AssetClass>('ALL');
  const [sortOrder,  setSortOrder]      = useState<'desc' | 'asc'>('desc');
  const { isConnected, lastMessage, latency } = useWebSocket();
  const { isRetail } = useMode();

  const fetchWhales = async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/whales/all', {
        headers: { 'X-API-Key': localStorage.getItem('crypto_terminal_key') || '' }
      });
      const json = await res.json();
      setWhales(json.data || []);
    } catch (error) {
      // fallback to old endpoint
      try {
        const res2 = await fetch('/api/data/whales');
        const json2 = await res2.json();
        setWhales((json2.data || []).map((w: WhaleEntry) => ({ ...w, asset_class: 'CRYPTO' })));
      } catch { /* silent */ }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchWhales(); }, []);

  useEffect(() => {
    if (lastMessage?.type === 'WHALE_ALERT') {
      const d = lastMessage.data;
      const entry: WhaleEntry = {
        symbol:        d.symbol,
        asset_class:   d.asset_class || 'CRYPTO',
        price:         d.price,
        quantity:      d.quantity,
        usd_value:     d.usd_value,
        is_buyer_maker: d.is_buyer_maker,
        vol_ratio:     d.vol_ratio,
        timestamp:     d.timestamp,
        source:        'live',
      };
      setWhales(prev => [entry, ...prev].slice(0, 100));
    }
  }, [lastMessage]);

  // ── Filtering + Sorting ──
  const filtered = whales
    .filter(w => {
      const usd   = getUSDValue(w);
      const tier  = getTier(usd);
      const tierOk  = filterTier === 'all' || tier === filterTier;
      const dirOk   = filterDir  === 'all'
        || (filterDir === 'buy'  && !w.is_buyer_maker)
        || (filterDir === 'sell' &&  w.is_buyer_maker);
      const assetOk = filterAsset === 'ALL' || w.asset_class === filterAsset;
      return tierOk && dirOk && assetOk;
    })
    .sort((a, b) => {
      const diff = getUSDValue(b) - getUSDValue(a);
      return sortOrder === 'desc' ? diff : -diff;
    });

  // ── Aggregate stats ──
  const buyWhales  = whales.filter(w => !w.is_buyer_maker);
  const sellWhales = whales.filter(w =>  w.is_buyer_maker);
  const totalBuyUSD  = buyWhales.reduce((s, w) => s + getUSDValue(w), 0);
  const totalSellUSD = sellWhales.reduce((s, w) => s + getUSDValue(w), 0);
  const totalVolUSD  = totalBuyUSD + totalSellUSD;
  const flowImbalance = totalVolUSD > 0 ? ((totalBuyUSD - totalSellUSD) / totalVolUSD) * 100 : 0;
  const largest = whales.reduce(
    (mx, w) => getUSDValue(w) > getUSDValue(mx) ? w : mx,
    whales[0] || { price: '0', quantity: '0', usd_value: 0 } as WhaleEntry
  );

  // Asset class breakdown for mini-stats
  const byClass = whales.reduce<Record<string, number>>((acc, w) => {
    const cls = w.asset_class || 'CRYPTO';
    acc[cls] = (acc[cls] || 0) + 1;
    return acc;
  }, {});

  const exportCSV = () => {
    const header = "Time,Symbol,AssetClass,Side,Price,Volume,USD_Value,Tier,VolRatio\n";
    const rows = filtered.map(w => {
      const ts  = parseInt(w.timestamp) > 1e12
        ? new Date(parseInt(w.timestamp)).toISOString()
        : new Date(w.timestamp).toISOString();
      const usd = getUSDValue(w);
      return [
        ts, w.symbol, w.asset_class,
        w.is_buyer_maker ? 'SELL' : 'BUY',
        w.price, w.quantity,
        usd.toFixed(2), getTier(usd),
        w.vol_ratio ?? ''
      ].join(',');
    }).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = `whale_flow_${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  const ASSET_CLASSES: AssetClass[] = ['ALL', 'CRYPTO', 'STOCK', 'GOLD', 'OIL', 'FX', 'INDEX'];

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-emerald-500 font-bold text-xs uppercase tracking-[0.2em]">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)] status-breath" />
            {t('whale.badge')}
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">{t('whale.title')}</h2>
          <p className="text-slate-500 text-sm font-medium">
            {t('whale.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className={`flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-bold tracking-widest uppercase transition-all ${
            isConnected
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
          }`}>
            <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
            {isConnected ? `${t('whale.live')} · ${latency ?? '--'}ms` : t('whale.syncing')}
          </div>
          {!isRetail && (
            <button onClick={exportCSV}
              className="group flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-blue-500/50 rounded-xl text-slate-300 transition-all font-bold text-xs">
              <Download className="w-3.5 h-3.5 group-hover:-translate-y-0.5 transition-transform" />
              {t('whale.csv')}
            </button>
          )}
          <button onClick={fetchWhales}
            className="group flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-emerald-500/50 rounded-xl text-slate-300 transition-all font-bold text-xs">
            <RefreshCcw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : 'group-hover:rotate-180 transition-transform duration-500'}`} />
            {t('whale.sync')}
          </button>
        </div>
      </header>

      {/* What is Whale Data? */}
      <div className="flex items-start gap-3 p-4 bg-emerald-500/5 border border-emerald-500/20 rounded-2xl">
        <TrendingUp className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
        <div className="space-y-1">
          <p className="text-xs font-black text-emerald-400 uppercase tracking-widest">{t('whale.how_to_read')}</p>
          <p className="text-sm text-slate-400">{t('whale.explanation')}</p>
        </div>
      </div>

      {/* Aggregate Stats */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: t('whale.buy_pressure'),   value: fmtUSD(totalBuyUSD),                                          color: 'text-emerald-400' },
          { label: t('whale.sell_pressure'),  value: fmtUSD(totalSellUSD),                                         color: 'text-rose-400'    },
          { label: t('whale.flow_imbalance'), value: `${flowImbalance > 0 ? '+' : ''}${flowImbalance.toFixed(1)}%`,color: flowImbalance > 0 ? 'text-emerald-400' : 'text-rose-400' },
          { label: t('whale.largest_trade'),  value: largest ? fmtUSD(getUSDValue(largest)) : '—',                 color: 'text-yellow-400'  },
        ].map((s, i) => (
          <div key={i} className="p-4 bg-slate-900/40 border border-white/5 rounded-2xl">
            <p className="text-[11px] font-black text-slate-600 uppercase tracking-widest mb-1">{s.label}</p>
            <p className={`text-base font-black font-mono ${s.color}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Asset class breakdown pill row */}
      <div className="flex items-center gap-2 flex-wrap">
        <TrendingUp className="w-3.5 h-3.5 text-slate-500" />
        <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest mr-1">{t('whale.markets')}</span>
        {Object.entries(byClass).map(([cls, count]) => {
          const cfg = assetClassConfig[cls] || assetClassConfig['CRYPTO'];
          return (
            <span key={cls}
              className={`px-2.5 py-0.5 rounded-full text-[10px] font-black uppercase tracking-widest border ${cfg.bg} ${cfg.border} ${cfg.color}`}>
              {cfg.emoji} {cls} ({count})
            </span>
          );
        })}
      </div>

      {/* Filters */}
      <div className="space-y-2">
        {/* Asset Class filter */}
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{t('whale.asset')}</span>
          {ASSET_CLASSES.map(cls => {
            const cfg = assetClassConfig[cls];
            const activeClass = cls === 'ALL'
              ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
              : cfg ? `${cfg.bg} ${cfg.border} ${cfg.color}` : 'bg-blue-600/20 border-blue-500/40 text-blue-400';
            return (
              <button key={cls} onClick={() => setFilterAsset(cls)}
                className={`px-3 py-1 rounded-xl text-[11px] font-black uppercase tracking-widest border transition-all ${
                  filterAsset === cls
                    ? activeClass
                    : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
                }`}>
                {cls === 'ALL' ? t('whale.all') : `${cfg?.emoji ?? ''} ${cls}`}
              </button>
            );
          })}
        </div>

        {/* Tier + Direction filter */}
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{t('whale.tier')}</span>
          {(['all', 'krill', 'dolphin', 'whale', 'mega'] as const).map(tier => (
            <button key={tier} onClick={() => setFilterTier(tier)}
              className={`px-3 py-1 rounded-xl text-[11px] font-black uppercase tracking-widest border transition-all ${
                filterTier === tier
                  ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                  : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
              }`}>
              {tier === 'all' ? t('whale.all') : tierConfig[tier].label}
            </button>
          ))}
          <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest ml-4">{t('whale.side')}</span>
          {(['all', 'buy', 'sell'] as const).map(d => (
            <button key={d} onClick={() => setFilterDir(d)}
              className={`px-3 py-1 rounded-xl text-[11px] font-black uppercase tracking-widest border transition-all ${
                filterDir === d
                  ? d === 'buy'  ? 'bg-emerald-600/20 border-emerald-500/40 text-emerald-400'
                  : d === 'sell' ? 'bg-rose-600/20    border-rose-500/40    text-rose-400'
                                 : 'bg-blue-600/20    border-blue-500/40    text-blue-400'
                  : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
              }`}>
              {d.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Sort order */}
        <div className="flex items-center gap-2">
          <ArrowDownUp className="w-3.5 h-3.5 text-slate-500" />
          <span className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{t('whale.sort')}</span>
          {([['desc', t('whale.sort_high')], ['asc', t('whale.sort_low')]] as const).map(([val, label]) => (
            <button key={val} onClick={() => setSortOrder(val)}
              className={`px-3 py-1 rounded-xl text-[11px] font-black uppercase tracking-widest border transition-all ${
                sortOrder === val
                  ? 'bg-amber-600/20 border-amber-500/40 text-amber-400'
                  : 'bg-transparent border-white/10 text-slate-500 hover:text-white'
              }`}>
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-900/40 backdrop-blur-xl border border-white/5 rounded-[2rem] overflow-hidden shadow-2xl relative">
        <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-500/5 blur-[100px] pointer-events-none" />
        <table className="w-full text-left border-collapse relative z-10">
          <thead>
            <tr className="bg-slate-900/80 border-b border-white/5">
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{t('whale.time')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{t('whale.tier_col')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{t('whale.asset_col')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{t('whale.class_col')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em]">{t('whale.direction')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em] text-right">{t('whale.usd')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em] text-right">{t('whale.price')}</th>
              <th className="px-5 py-5 text-xs font-bold text-slate-500 uppercase tracking-[0.2em] text-right" title="Volume ratio vs. average — higher = unusual activity">{t('whale.vol_spike')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            <AnimatePresence mode="popLayout">
              {loading
                ? [1,2,3,4,5].map(i => (
                    <tr key={i} className="animate-pulse">
                      <td colSpan={8} className="px-5 py-6">
                        <div className="h-4 bg-slate-800/50 rounded-full w-full" />
                      </td>
                    </tr>
                  ))
                : filtered.map((whale, i) => {
                    const usdVal  = getUSDValue(whale);
                    const tier    = getTier(usdVal);
                    const tierCfg = tierConfig[tier];
                    const aClass  = whale.asset_class || 'CRYPTO';
                    const aCfg    = assetClassConfig[aClass] || assetClassConfig['CRYPTO'];
                    const isMega  = tier === 'mega';

                    const tsNum = parseInt(whale.timestamp);
                    const tsDate = tsNum > 1e12
                      ? new Date(tsNum)
                      : new Date(whale.timestamp);
                    const timeStr = isNaN(tsDate.getTime())
                      ? whale.timestamp
                      : tsDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

                    return (
                      <motion.tr
                        key={`${whale.symbol}-${whale.timestamp}-${i}`}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: Math.min(i * 0.02, 0.5) }}
                        className={`hover:bg-white/[0.02] transition-colors ${isMega ? 'bg-yellow-500/[0.02]' : ''}`}
                      >
                        {/* Time */}
                        <td className="px-5 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2 text-slate-500 font-mono text-[11px] font-bold">
                            <Clock className="w-3 h-3 opacity-50" />
                            {timeStr}
                          </div>
                        </td>

                        {/* Tier */}
                        <td className="px-5 py-4">
                          <span className={`text-[11px] font-black uppercase tracking-widest ${tierCfg.color}`}>
                            {tierCfg.label}
                          </span>
                        </td>

                        {/* Symbol */}
                        <td className="px-5 py-4">
                          <span className="font-black text-slate-100 tracking-tight">{whale.symbol}</span>
                        </td>

                        {/* Asset Class badge */}
                        <td className="px-5 py-4">
                          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[10px] font-black uppercase tracking-widest border ${aCfg.bg} ${aCfg.border} ${aCfg.color}`}>
                            {aCfg.emoji} {aClass}
                          </span>
                        </td>

                        {/* Direction */}
                        <td className="px-5 py-4">
                          <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-xl text-xs font-black tracking-wider border ${
                            whale.is_buyer_maker
                              ? 'bg-rose-500/5 text-rose-400 border-rose-500/20'
                              : 'bg-emerald-500/5 text-emerald-400 border-emerald-500/20'
                          }`}>
                            {whale.is_buyer_maker
                              ? <ArrowDownRight className="w-3 h-3" />
                              : <ArrowUpRight   className="w-3 h-3" />}
                            {whale.is_buyer_maker ? 'SELL' : 'BUY'}
                          </div>
                        </td>

                        {/* USD Value */}
                        <td className="px-5 py-4 text-right">
                          <span className={`text-base font-black font-mono ${tierCfg.color}`}>
                            {fmtUSD(usdVal)}
                          </span>
                        </td>

                        {/* Price */}
                        <td className="px-5 py-4 text-right">
                          <span className="text-sm text-slate-400 font-black font-mono">
                            ${parseFloat(String(whale.price)).toLocaleString(undefined, { maximumFractionDigits: 4 })}
                          </span>
                        </td>

                        {/* Vol Ratio (only for poller data) */}
                        <td className="px-5 py-4 text-right">
                          {whale.vol_ratio != null
                            ? (
                              <span className={`text-[11px] font-black font-mono ${
                                whale.vol_ratio >= 5 ? 'text-yellow-400' :
                                whale.vol_ratio >= 3 ? 'text-emerald-400' : 'text-slate-500'
                              }`}>
                                {whale.vol_ratio.toFixed(1)}×
                              </span>
                            )
                            : <span className="text-slate-700 text-[11px]">—</span>
                          }
                        </td>
                      </motion.tr>
                    );
                  })
              }
            </AnimatePresence>
          </tbody>
        </table>

        {!loading && filtered.length === 0 && (
          <div className="p-24 text-center space-y-4">
            <div className="w-16 h-16 bg-slate-800/40 rounded-full flex items-center justify-center mx-auto border border-white/5">
              <Zap className="w-8 h-8 text-slate-600" />
            </div>
            <p className="text-slate-400 font-bold text-base">{t('whale.no_results')}</p>
            <p className="text-slate-600 text-sm">
              {t('whale.no_results_hint')}
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
