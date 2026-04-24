import { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useMode } from '../contexts/ModeContext';
import {
  AlertCircle,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Landmark,
  RefreshCcw,
  Search,
  Wallet,
  X,
  Activity,
  TrendingUp,
  Globe,
  Shield,
  PieChart,
  Filter,
  History,
  ArrowDownRight,
} from 'lucide-react';

type Chain = 'ETH' | 'SOL';

interface Asset {
  symbol: string;
  name?: string;
  balance: number;
  price: number;
  usd_value: number;
  change_24h: number;
  allocation: number;
  kind?: 'native' | 'token';
  token_address?: string | null;
  logo?: string;
  priced?: boolean;
}

interface WalletIdentity {
  display_name: string;
  resolved_name: string;
  avatar: string;
  description: string;
  twitter: string;
  website: string;
  explorer_url: string;
}

interface WalletData {
  address: string;
  chain: Chain;
  total_usd: number;
  assets: Asset[];
  source: string;
  identity?: WalletIdentity | null;
  explorer_url?: string;
}

interface FamousWallet {
  name: string;
  title: string;
  address: string;
  chain: Chain;
  explorerUrl: string;
}

interface PortfolioCenterProps {
  tickerPrices?: Record<string, { price: number; delta: number }>;
}

const FAMOUS_WALLETS: FamousWallet[] = [
  {
    name: 'Vitalik Buterin',
    title: 'ETH co-founder',
    address: '0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045',
  },
  {
    name: 'Justin Sun',
    title: 'TRON founder',
    address: '0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0x3DdfA8eC3052539b6C9549F12cEA2C295cfF5296',
  },
  {
    name: 'Ethereum Foundation',
    title: 'Treasury wallet',
    address: '0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe',
  },
  {
    name: 'Binance Hot Wallet',
    title: 'Exchange cold storage',
    address: '0xBE0eB53F46cd790Cd13851d5EFf43D12404d33E8',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0xBE0eB53F46cd790Cd13851d5EFf43D12404d33E8',
  },
  {
    name: 'Coinbase',
    title: 'Exchange wallet',
    address: '0x71660c4005BA85c37ccec55d0C4493E66Fe775d3',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0x71660c4005BA85c37ccec55d0C4493E66Fe775d3',
  },
  {
    name: 'a16z Crypto',
    title: 'VC fund wallet',
    address: '0x05E793cE0C6027323Ac150F6d45C2344d28B6019',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0x05E793cE0C6027323Ac150F6d45C2344d28B6019',
  },
  {
    name: 'Mark Cuban',
    title: 'Billionaire investor',
    address: '0xF76e3b4ca5f1B1851Dd7E29C3e97a10F23BC1D00',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0xF76e3b4ca5f1B1851Dd7E29C3e97a10F23BC1D00',
  },
  {
    name: 'MicroStrategy',
    title: 'BTC Treasury Corp',
    address: '0x4DA82a8AC033fdD9Ba0d3F0Cc0feAeEDf2Ee5158',
    chain: 'ETH',
    explorerUrl: 'https://etherscan.io/address/0x4DA82a8AC033fdD9Ba0d3F0Cc0feAeEDf2Ee5158',
  },
];

function isEthAddress(v: string) { return /^0x[0-9a-fA-F]{40}$/.test(v.trim()); }

function shortenHash(v: string, head = 6, tail = 4) {
  if (!v || v.length <= head + tail + 3) return v;
  return `${v.slice(0, head)}...${v.slice(-tail)}`;
}

function fmt(v: number) {
  if (v === 0) return '$0';
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (v >= 1) return `$${v.toFixed(2)}`;
  return `$${v.toFixed(6)}`;
}

function fmtPrice(v: number) {
  if (v <= 0) return '—';
  if (v >= 1_000) return `$${v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (v >= 1) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(8)}`;
}

function fmtBal(v: number) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (v >= 1) return v.toFixed(4);
  return v.toFixed(8);
}

function fmtTotal(v: number) {
  if (v >= 1_000_000_000) return `$${(v / 1_000_000_000).toFixed(2)}B`;
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
  if (v >= 1_000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  return `$${v.toFixed(2)}`;
}

type SortKey = 'usd_value' | 'balance' | 'change_24h' | 'symbol';

export const PortfolioCenter = ({ tickerPrices: _tickerPrices = {} }: PortfolioCenterProps) => {
  const { theme } = useMode();
  const [activeTab, setActiveTab] = useState<'overview' | 'assets' | 'history'>('overview');
  const [address, setAddress]       = useState('');
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState('');
  const [walletData, setWalletData] = useState<WalletData | null>(null);
  const [attribution, setAttribution] = useState<FamousWallet | null>(null);
  const [sortKey, setSortKey]       = useState<SortKey>('usd_value');
  const [sortAsc, setSortAsc]       = useState(false);
  const [filterPriced, setFilterPriced] = useState(false);
  const [page, setPage]             = useState(0);
  const PAGE_SIZE = 50;

  const liveMode = Boolean(walletData);
  const assets   = walletData?.assets ?? [];

  const displayAssets = useMemo(() => {
    let list = filterPriced ? assets.filter(a => a.priced) : assets;
    list = [...list].sort((a, b) => {
      const av = a[sortKey] as number | string;
      const bv = b[sortKey] as number | string;
      const diff = typeof av === 'string' ? av.localeCompare(bv as string) : (av as number) - (bv as number);
      return sortAsc ? diff : -diff;
    });
    return list;
  }, [assets, sortKey, sortAsc, filterPriced]);

  const paginated   = displayAssets.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages  = Math.ceil(displayAssets.length / PAGE_SIZE);
  const pricedCount = assets.filter(a => a.priced).length;

  const walletName = (() => {
    const id = walletData?.identity;
    if (id?.resolved_name) return id.resolved_name;
    if (id?.display_name)  return id.display_name;
    if (attribution?.name) return attribution.name;
    if (walletData?.address) return shortenHash(walletData.address, 8, 6);
    return '';
  })();

  const handleReset = () => {
    setAddress(''); setError(''); setWalletData(null);
    setAttribution(null); setPage(0);
  };

  const loadAddress = async (addr: string, famous?: FamousWallet) => {
    setLoading(true); setError(''); setAttribution(famous ?? null); setPage(0);
    try {
      const res = await fetch(`/api/portfolio/wallet?address=${encodeURIComponent(addr)}`, {
        headers: { 'X-API-Key': localStorage.getItem('crypto_terminal_key') || 'demo' },
      });
      const payload = await res.json();
      if (!res.ok) throw new Error(payload.detail || 'Wallet lookup failed.');
      setWalletData(payload);
    } catch (e: unknown) {
      setWalletData(null);
      setError(e instanceof Error ? e.message : 'Unknown error.');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const a = address.trim();
    if (!a) return;
    loadAddress(a);
  };

  const handleQuickLoad = (w: FamousWallet) => {
    setAddress(w.address);
    loadAddress(w.address, w);
  };

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(p => !p);
    else { setSortKey(key); setSortAsc(false); }
    setPage(0);
  };

  const SortIcon = ({ k }: { k: SortKey }) =>
    sortKey === k
      ? sortAsc ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
      : <ChevronDown className="h-3 w-3 opacity-30" />;

  return (
    <div className={`flex-1 overflow-y-auto p-4 lg:p-6 space-y-4 scrollbar-hide transition-all duration-700 ${
      theme === 'dark' ? 'bg-slate-950 text-slate-200' : 'bg-slate-50 text-slate-900'
    }`}>
      {/* Header Section */}
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-3">
            <div className={`w-9 h-9 rounded-xl flex items-center justify-center border transition-all ${
              theme === 'dark' ? 'bg-indigo-600/20 border-indigo-500/30 shadow-lg shadow-indigo-500/10' : 'bg-indigo-600 border-indigo-600 shadow-lg shadow-indigo-500/20'
            }`}>
              <Wallet className={`w-4 h-4 ${theme === 'dark' ? 'text-indigo-400' : 'text-white'}`} />
            </div>
            <div>
              <h1 className={`text-xl lg:text-2xl font-black tracking-tighter transition-colors ${
                theme === 'dark' ? 'text-white' : 'text-slate-900'
              }`}>Portfolio Center</h1>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`text-[8px] font-black uppercase tracking-widest px-1.5 py-0.5 rounded-md border ${
                  theme === 'dark' ? 'bg-indigo-500/10 border-indigo-500/20 text-indigo-400' : 'bg-indigo-50 border-indigo-200 text-indigo-700'
                }`}>Institutional Wallet</span>
                <span className="text-slate-500 text-[9px] font-bold">Updated just now</span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className={`flex p-1 border rounded-xl transition-all ${
            theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-sm'
          }`}>
            {(['overview', 'assets', 'history'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-3 py-1.5 rounded-lg text-[10px] font-black uppercase tracking-widest transition-all ${
                  activeTab === tab
                    ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/20'
                    : (theme === 'dark' ? 'text-slate-500 hover:text-slate-300' : 'text-slate-500 hover:text-slate-800')
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
          <button className={`p-2 rounded-xl border transition-all ${
            theme === 'dark' ? 'bg-slate-900/50 border-white/5 text-slate-400 hover:text-white' : 'bg-white border-slate-200 text-slate-500 hover:text-slate-900 shadow-sm'
          }`}>
            <RefreshCcw className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-5">
        {/* Search Panel */}
        <div className={`rounded-[1.25rem] border p-4 transition-all duration-500 ${
          theme === 'dark' ? 'bg-slate-900/60 border-white/10' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
        }`}>
          <form onSubmit={handleSubmit} className="flex gap-2">
            <label className="relative flex-1">
              <Search className="pointer-events-none absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
              <input
                type="text"
                value={address}
                onChange={e => setAddress(e.target.value)}
                placeholder="Paste ETH (0x...) or SOL address..."
                className={`w-full rounded-xl border py-2.5 pl-10 pr-4 text-xs font-semibold outline-none transition-all ${
                  theme === 'dark' 
                    ? 'bg-slate-950/70 border-white/10 text-white placeholder:text-slate-600 focus:border-indigo-400/50' 
                    : 'bg-slate-50 border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-indigo-500/50'
                } focus:ring-2 focus:ring-indigo-500/20`}
              />
            </label>
            <button type="submit" disabled={!address.trim() || loading}
              className="inline-flex min-w-[90px] items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-black uppercase tracking-[0.16em] text-white hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40 transition-colors shadow-lg shadow-indigo-600/20">
              {loading ? <RefreshCcw className="h-3.5 w-3.5 animate-spin" /> : <Wallet className="h-3.5 w-3.5" />}
              {loading ? 'Wait' : 'Inspect'}
            </button>
            {liveMode && (
              <button type="button" onClick={handleReset}
                className={`rounded-xl border px-3 py-2.5 text-xs font-black uppercase tracking-[0.16em] transition-colors ${
                  theme === 'dark' ? 'border-white/10 text-slate-300 hover:border-white/20 hover:text-white' : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:bg-slate-50'
                }`}>
                Clear
              </button>
            )}
          </form>

          {/* Famous wallets */}
          <div className="mt-3 space-y-2">
            <p className="text-[9px] font-black uppercase tracking-[0.22em] text-slate-600">Quick load — notable public wallets</p>
            <div className="flex flex-wrap gap-1.5">
              {FAMOUS_WALLETS.map(w => (
                <button key={w.address} type="button" onClick={() => handleQuickLoad(w)} disabled={loading}
                  className={`rounded-lg border px-2.5 py-1 text-[10px] font-black uppercase tracking-[0.12em] transition-all disabled:opacity-50 ${
                    walletData?.address === w.address
                      ? (theme === 'dark' ? 'border-indigo-400/40 bg-indigo-500/20 text-indigo-200' : 'border-indigo-300 bg-indigo-50 text-indigo-700')
                      : (theme === 'dark' ? 'border-white/10 bg-white/[0.03] text-slate-400 hover:border-indigo-400/30 hover:text-white' : 'border-slate-200 bg-slate-50 text-slate-500 hover:border-slate-300 hover:text-slate-800')
                  }`}>
                  {w.name}
                  <span className={`ml-1 font-semibold normal-case ${theme === 'dark' ? 'text-slate-600' : 'text-slate-400'}`}>· {w.title}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className={`flex items-start gap-3 rounded-[1.5rem] border p-4 ${
            theme === 'dark' ? 'border-rose-500/20 bg-rose-500/10' : 'border-rose-200 bg-rose-50'
          }`}>
            <AlertCircle className={`mt-0.5 h-4 w-4 shrink-0 ${theme === 'dark' ? 'text-rose-300' : 'text-rose-600'}`} />
            <div>
              <p className={`text-sm font-black uppercase tracking-[0.18em] ${theme === 'dark' ? 'text-rose-100' : 'text-rose-700'}`}>Lookup error</p>
              <p className={`mt-1 text-sm font-semibold ${theme === 'dark' ? 'text-rose-200/90' : 'text-rose-600/90'}`}>{error}</p>
            </div>
          </div>
        )}

        {/* Identity Banner */}
        <AnimatePresence>
          {liveMode && walletData && (
            <motion.div key="identity"
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className={`rounded-[1.25rem] border p-5 transition-all duration-500 ${
                theme === 'dark' ? 'bg-slate-900/60 border-white/10' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
              }`}>
              <div className={`flex items-start justify-between gap-4 relative z-10`}>
                <div className="flex items-start gap-4">
                  {walletData.identity?.avatar ? (
                    <img src={walletData.identity.avatar} alt={walletName}
                      className={`h-12 w-12 rounded-xl border object-cover shrink-0 shadow-xl ${theme === 'dark' ? 'border-white/10' : 'border-slate-200'}`} />
                  ) : (
                    <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl border text-xl font-black ${
                      theme === 'dark' ? 'border-white/10 bg-indigo-500/10 text-indigo-100' : 'border-indigo-200 bg-indigo-600 text-white shadow-xl shadow-indigo-500/10'
                    }`}>
                      {(walletName || 'W').slice(0, 1).toUpperCase()}
                    </div>
                  )}
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className={`text-base font-black uppercase tracking-tight ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{walletName || shortenHash(walletData.address, 8, 6)}</p>
                      {walletData.identity?.resolved_name && (
                        <span className={`rounded-full border px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.18em] ${
                          theme === 'dark' ? 'border-indigo-400/20 bg-indigo-500/10 text-indigo-200' : 'border-indigo-200 bg-indigo-50 text-indigo-700'
                        }`}>
                          {walletData.identity.resolved_name}
                        </span>
                      )}
                      <span className={`rounded-full border px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.18em] ${
                        theme === 'dark' ? 'border-white/8 bg-white/5 text-slate-400' : 'border-slate-200 bg-slate-50 text-slate-500'
                      }`}>
                        {walletData.chain}
                      </span>
                    </div>
                    <p className="font-mono text-xs text-slate-500">{walletData.address}</p>
                    {walletData.identity?.description && (
                      <p className={`text-sm leading-6 max-w-2xl ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>{walletData.identity.description}</p>
                    )}
                    <div className="flex flex-wrap gap-2 pt-1">
                      {walletData.identity?.twitter && (
                        <span className={`rounded-full border px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.16em] ${
                          theme === 'dark' ? 'border-sky-500/20 bg-sky-500/10 text-sky-300' : 'border-sky-200 bg-sky-50 text-sky-600'
                        }`}>
                          @{walletData.identity.twitter}
                        </span>
                      )}
                      {walletData.identity?.website && (
                        <span className={`rounded-full border px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.16em] ${
                          theme === 'dark' ? 'border-white/10 text-slate-400' : 'border-slate-200 text-slate-500'
                        }`}>
                          {walletData.identity.website.replace(/^https?:\/\//i, '')}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2 relative z-10">
                  {walletData.explorer_url && (
                    <a href={walletData.explorer_url} target="_blank" rel="noopener noreferrer"
                      className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-[9px] font-black uppercase tracking-[0.18em] transition-all shadow-sm ${
                        theme === 'dark' ? 'border-indigo-400/20 bg-indigo-500/10 text-indigo-200 hover:bg-indigo-500/20' : 'bg-white border-slate-200 text-slate-700 hover:bg-slate-50 hover:border-indigo-500/30'
                      }`}>
                      View on Explorer <ExternalLink className="h-2.5 w-2.5" />
                    </a>
                  )}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Stats Row */}
        <AnimatePresence>
          {liveMode && walletData && (
            <motion.div key="stats"
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { label: 'Total Value', value: fmtTotal(walletData.total_usd), sub: 'USD at current prices' },
                { label: 'Total Assets', value: String(assets.length), sub: `${pricedCount} have market price` },
                { label: 'Largest Position', value: assets[0]?.symbol || '—', sub: assets[0] ? fmt(assets[0].usd_value) : '—' },
                { label: 'Price Coverage', value: `${assets.length ? Math.round(pricedCount / assets.length * 100) : 0}%`, sub: `${pricedCount}/${assets.length} priced` },
              ].map(s => (
                <div key={s.label} className={`rounded-[1.25rem] border p-4 transition-all duration-500 ${
                  theme === 'dark' ? 'bg-slate-900/60 border-white/10' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
                }`}>
                  <p className="text-[9px] font-black uppercase tracking-[0.24em] text-slate-500">{s.label}</p>
                  <p className={`mt-1.5 text-2xl font-black transition-colors ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{s.value}</p>
                  <p className="mt-0.5 text-[10px] font-semibold text-slate-500">{s.sub}</p>
                </div>
              ))}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Token Table */}
        <AnimatePresence>
          {liveMode && walletData && (
            <motion.div key="table"
              initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className={`rounded-[1.25rem] border overflow-hidden transition-all duration-500 ${
                theme === 'dark' ? 'bg-slate-900/60 border-white/10 shadow-2xl' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
              }`}>

              {/* Table toolbar */}
              <div className={`flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3 ${
                theme === 'dark' ? 'border-white/5' : 'border-slate-100 bg-slate-50/50'
              }`}>
                <div className="flex items-center gap-2">
                  <p className="text-[10px] font-black uppercase tracking-[0.24em] text-slate-400">
                    {displayAssets.length} assets
                  </p>
                  <span className="text-slate-700">·</span>
                  <p className="text-[10px] font-semibold text-slate-500">{walletData.source}</p>
                </div>
                <button onClick={() => { setFilterPriced(p => !p); setPage(0); }}
                  title={filterPriced ? 'Show all assets' : `Filter to ${pricedCount} assets that have a USD price`}
                  className={`inline-flex items-center gap-2 rounded-lg border px-2 py-1 text-[9px] font-black uppercase tracking-[0.18em] transition-all ${
                    filterPriced
                      ? (theme === 'dark' ? 'border-emerald-400/30 bg-emerald-500/15 text-emerald-200' : 'border-emerald-300 bg-emerald-50 text-emerald-700')
                      : (theme === 'dark' ? 'border-white/10 bg-white/[0.02] text-slate-500 hover:border-white/20 hover:text-slate-300' : 'border-slate-200 bg-slate-50 text-slate-500 hover:border-slate-300 hover:text-slate-700')
                  }`}>
                  <span className={`h-1 w-1 rounded-full ${filterPriced ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                  {filterPriced ? `Priced · ${pricedCount}` : `All · ${assets.length}`}
                </button>
              </div>

              {/* Table */}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className={`border-b text-left ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                      {[
                        { key: 'symbol' as SortKey, label: 'Asset', cls: 'pl-5 w-[220px]' },
                        { key: 'balance' as SortKey, label: 'Balance', cls: 'text-right' },
                        { key: 'usd_value' as SortKey, label: 'USD Value', cls: 'text-right' },
                        { key: 'change_24h' as SortKey, label: '24h', cls: 'text-right' },
                        { key: null, label: 'Allocation', cls: 'text-right' },
                        { key: null, label: '', cls: 'pr-5 w-12' },
                      ].map((col, i) => (
                        <th key={i}
                          className={`py-3 pr-4 text-[10px] font-black uppercase tracking-[0.22em] text-slate-600 ${col.cls} ${col.key ? 'cursor-pointer hover:text-slate-400 select-none' : ''}`}
                          onClick={col.key ? () => toggleSort(col.key!) : undefined}>
                          <span className="inline-flex items-center gap-1">
                            {col.label}
                            {col.key && <SortIcon k={col.key} />}
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {paginated.map((asset, i) => {
                      const pos = asset.change_24h >= 0;
                      const explorerHref = asset.token_address
                        ? `https://etherscan.io/token/${asset.token_address}?a=${walletData.address}`
                        : walletData.explorer_url;
                      return (
                        <motion.tr key={`${asset.symbol}-${asset.token_address ?? i}`}
                          initial={{ opacity: 0 }} animate={{ opacity: 1 }}
                          transition={{ delay: i * 0.015 }}
                          className={`border-b transition-colors ${
                            theme === 'dark' ? 'border-white/[0.04] hover:bg-white/[0.02]' : 'border-slate-50 hover:bg-slate-50'
                          }`}>
                          {/* Asset */}
                          <td className="py-3 pl-5 pr-4">
                            <div className="flex items-center gap-3">
                              {asset.logo ? (
                                <img src={asset.logo} alt={asset.symbol}
                                  className={`h-8 w-8 rounded-xl border object-cover shrink-0 ${theme === 'dark' ? 'border-white/10' : 'border-slate-200'}`}
                                  onError={e => { (e.target as HTMLImageElement).style.display = 'none' }} />
                              ) : (
                                <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border font-black ${
                                  theme === 'dark' ? 'border-white/10 bg-white/[0.04] text-white' : 'border-slate-200 bg-slate-50 text-slate-900'
                                } text-[10px]`}>
                                  {asset.symbol.slice(0, 3)}
                                </div>
                              )}
                              <div className="min-w-0">
                                <p className={`truncate font-black uppercase tracking-[0.1em] ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                                  {asset.symbol}
                                </p>
                                <p className="truncate text-xs text-slate-500">{asset.name || '—'}</p>
                              </div>
                            </div>
                          </td>
                          {/* Balance */}
                          <td className={`py-3 pr-4 text-right font-semibold ${theme === 'dark' ? 'text-slate-300' : 'text-slate-600'}`}>
                            {fmtBal(asset.balance)}
                          </td>
                          {/* USD Value */}
                          <td className={`py-3 pr-4 text-right font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
                            {asset.usd_value > 0 ? fmt(asset.usd_value) : <span className="text-slate-600">—</span>}
                          </td>
                          {/* 24h */}
                          <td className={`py-3 pr-4 text-right font-black ${
                            asset.price > 0 
                              ? (pos 
                                  ? (theme === 'dark' ? 'text-emerald-300' : 'text-emerald-600') 
                                  : (theme === 'dark' ? 'text-rose-300' : 'text-rose-600')) 
                              : 'text-slate-700'
                          }`}>
                            {asset.price > 0
                              ? `${pos ? '+' : ''}${asset.change_24h.toFixed(2)}%`
                              : '—'}
                          </td>
                          {/* Allocation bar */}
                          <td className="py-3 pr-4">
                            <div className="flex items-center justify-end gap-2">
                              <span className="text-xs font-bold text-slate-500 w-10 text-right">
                                {asset.allocation > 0 ? `${asset.allocation.toFixed(1)}%` : '—'}
                              </span>
                              <div className={`h-1.5 w-16 overflow-hidden rounded-full ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-100'}`}>
                                <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-cyan-400"
                                  style={{ width: `${Math.min(asset.allocation, 100)}%` }} />
                              </div>
                            </div>
                          </td>
                          {/* Explorer link */}
                          <td className="py-3 pr-5">
                            {explorerHref && (
                              <a href={explorerHref} target="_blank" rel="noopener noreferrer"
                                className={`inline-flex items-center justify-center rounded-lg border p-1.5 transition-colors ${
                                  theme === 'dark' ? 'border-white/10 text-slate-500 hover:border-white/20 hover:text-slate-200' : 'border-slate-200 text-slate-400 hover:border-slate-300 hover:text-slate-700'
                                }`}>
                                <ArrowUpRight className="h-3.5 w-3.5" />
                              </a>
                            )}
                          </td>
                        </motion.tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className={`flex items-center justify-between border-t px-5 py-3 ${theme === 'dark' ? 'border-white/5' : 'border-slate-100'}`}>
                  <p className="text-[11px] font-semibold text-slate-500">
                    Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, displayAssets.length)} of {displayAssets.length}
                  </p>
                  <div className="flex gap-2">
                    <button onClick={() => setPage(p => p - 1)} disabled={page === 0}
                      className={`rounded-xl border px-3 py-1.5 text-[11px] font-black uppercase tracking-[0.18em] transition-all disabled:opacity-30 ${
                        theme === 'dark' ? 'border-white/10 text-slate-300 hover:border-white/20 hover:text-white' : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700'
                      }`}>
                      Prev
                    </button>
                    <span className="self-center text-[11px] font-bold text-slate-600">
                      {page + 1} / {totalPages}
                    </span>
                    <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1}
                      className={`rounded-xl border px-3 py-1.5 text-[11px] font-black uppercase tracking-[0.18em] transition-all disabled:opacity-30 ${
                        theme === 'dark' ? 'border-white/10 text-slate-300 hover:border-white/20 hover:text-white' : 'border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-700'
                      }`}>
                      Next
                    </button>
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Empty state */}
        {!liveMode && !loading && !error && (
          <div className={`flex flex-col items-center justify-center gap-4 rounded-[1.75rem] border border-dashed py-20 text-center transition-all duration-500 ${
            theme === 'dark' ? 'border-white/10 bg-slate-900/20' : 'border-slate-200 bg-white shadow-xl shadow-slate-200/40'
          }`}>
            <div className={`flex h-16 w-16 items-center justify-center rounded-3xl border transition-all ${
              theme === 'dark' ? 'border-indigo-500/20 bg-indigo-500/10' : 'border-indigo-100 bg-indigo-50'
            }`}>
              <Wallet className={`h-7 w-7 ${theme === 'dark' ? 'text-indigo-300' : 'text-indigo-600'}`} />
            </div>
            <div className="space-y-1">
              <p className={`text-lg font-black uppercase tracking-[0.12em] ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>No wallet loaded</p>
              <p className="text-sm font-semibold text-slate-500">
                Paste any ETH or SOL address above, or pick a quick-load example.
              </p>
            </div>
            <p className={`text-xs font-bold uppercase tracking-[0.2em] ${theme === 'dark' ? 'text-slate-700' : 'text-slate-300'}`}>
              Public on-chain data only · no private keys required
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
