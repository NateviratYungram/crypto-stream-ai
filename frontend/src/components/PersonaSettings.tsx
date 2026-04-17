import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Bot, Save, RotateCcw, CheckCircle } from 'lucide-react';

const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';

const PRESETS: Record<string, string> = {
  Institutional: `# CryptoStream AI — Institutional Persona
You are an elite, institutional-grade financial intelligence agent.
Directives:
1. Safety First: Never bypass trade guards or multi-stage checks.
2. Precision: Always use exact tickers and numeric values.
3. Institutional Analysis: Focus on ICT, SMC, and Macro-climate logic.
4. Resilience: If a tool fails, pivot to an alternative method.
Respond professionally in Thai. Use data-driven alpha and risk management.`,

  Aggressive: `# CryptoStream AI — Aggressive Scalper Persona
You are an aggressive, high-frequency scalper focused on short-term alpha.
Style: High risk tolerance, fast decision-making, momentum-driven.
Preferred tools: get_funding_rates, scan_multi_timeframe, get_liquidation_heatmap.
Always look for breakout entries with tight SL and 3:1 RR minimum.
Respond in Thai with concise, punchy analysis. No fluff.`,

  Conservative: `# CryptoStream AI — Conservative Investor Persona
You are a conservative, long-term focused investment advisor.
Style: Capital preservation first, position sizing 1% risk max per trade.
Preferred assets: Blue-chip stocks, Gold, S&P 500 ETFs.
Always recommend diversification and portfolio rebalancing.
Respond in Thai. Emphasize risk management over return maximization.`,

  Crypto: `# CryptoStream AI — Crypto DeFi Persona
You are a crypto-native analyst specializing in on-chain data and DeFi.
Focus: BTC, ETH, SOL and emerging Layer 1/2 ecosystems.
Use get_onchain_flow, get_funding_rates, get_liquidation_heatmap heavily.
Cover DeFi TVL, staking yields, protocol revenue where relevant.
Respond in Thai with crypto-native terminology.`,
};

export const PersonaSettings = () => {
  const [text,    setText]    = useState('');
  const [loading, setLoading] = useState(true);
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);

  const load = async () => {
    try {
      const res = await fetch('/api/persona', { headers: { 'X-API-Key': API_KEY() } });
      const d   = await res.json();
      setText(d.persona || '');
    } catch { /* silent */ }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      await fetch('/api/persona', {
        method: 'PUT', headers: { 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona: text })
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally { setSaving(false); }
  };

  return (
    <div className="flex-1 p-8 overflow-y-auto space-y-6 custom-scrollbar">
      {/* Header */}
      <header className="flex justify-between items-center border-b border-white/5 pb-8">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-indigo-400 font-bold text-xs uppercase tracking-[0.2em]">
            <Bot className="w-3.5 h-3.5" />
            AI Configuration
          </div>
          <h2 className="text-3xl font-extrabold text-white tracking-tight">AI Persona</h2>
          <p className="text-slate-500 text-sm">ปรับแต่งบุคลิก AI — เปลี่ยน style การวิเคราะห์และตอบสนอง</p>
        </div>
        <div className="flex gap-3">
          <button onClick={load}
            className="flex items-center gap-2 px-4 py-2 bg-slate-900 border border-white/10 hover:border-white/20 rounded-xl text-slate-400 text-xs font-bold transition-all">
            <RotateCcw className="w-3.5 h-3.5" />
            Reload
          </button>
          <button onClick={save} disabled={saving}
            className="flex items-center gap-2 px-5 py-2 bg-indigo-600/20 border border-indigo-500/30 hover:border-indigo-500/60 rounded-xl text-indigo-400 text-xs font-black transition-all disabled:opacity-50">
            {saved ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400" /> : <Save className="w-3.5 h-3.5" />}
            {saved ? 'Saved!' : saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </header>

      {/* Presets */}
      <div className="space-y-2">
        <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Presets</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.keys(PRESETS).map(name => (
            <button key={name} onClick={() => setText(PRESETS[name])}
              className="p-3 bg-slate-900/40 border border-white/5 hover:border-indigo-500/30 rounded-2xl text-left transition-all group">
              <p className="font-black text-slate-300 text-sm group-hover:text-white transition-colors">{name}</p>
              <p className="text-[11px] text-slate-600 mt-0.5 font-bold line-clamp-2">
                {PRESETS[name].split('\n')[1]?.replace('You are ', '') || ''}
              </p>
            </button>
          ))}
        </div>
      </div>

      {/* Editor */}
      <div className="space-y-2">
        <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">Custom Instructions</p>
        {loading
          ? <div className="h-80 bg-slate-900/40 border border-white/5 rounded-2xl animate-pulse" />
          : (
            <motion.textarea
              initial={{ opacity: 0 }} animate={{ opacity: 1 }}
              value={text}
              onChange={e => setText(e.target.value)}
              rows={18}
              className="w-full px-5 py-4 bg-slate-900/60 border border-white/10 rounded-2xl text-slate-300 text-sm font-mono leading-relaxed resize-none focus:outline-none focus:border-indigo-500/40 transition-all placeholder:text-slate-700"
              placeholder="เขียน instructions สำหรับ AI เช่น style การวิเคราะห์, ภาษา, โฟกัส asset class..."
            />
          )
        }
        <p className="text-[11px] text-slate-600 font-bold">
          {text.length} chars · บันทึกแล้ว AI จะใช้ persona นี้ทันทีในการตอบครั้งถัดไป
        </p>
      </div>
    </div>
  );
};
