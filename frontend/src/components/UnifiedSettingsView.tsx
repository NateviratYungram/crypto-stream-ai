import { useState, useEffect, lazy, Suspense } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot, User, Activity, ChevronRight,
  Save, RotateCcw, CheckCircle, RotateCcw as Reload,
  Mail, Phone, Globe, Briefcase, Lock,
  CheckCircle2, AlertCircle, ShieldCheck, Calendar, Edit3, KeyRound, LogOut,
  FlaskConical
} from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

const MLStats = lazy(() => import('./MLStatsPanel'));

/* ─── Constants ─────────────────────────────────────────── */
const API_KEY = () => localStorage.getItem('crypto_terminal_key') || '';
const token   = () => localStorage.getItem('cs_jwt') || '';

const PERSONA_PRESETS: Record<string, string> = {
  Institutional: `# CryptoStream AI — Institutional Persona\nYou are an elite, institutional-grade financial intelligence agent.\nDirectives:\n1. Safety First: Never bypass trade guards or multi-stage checks.\n2. Precision: Always use exact tickers and numeric values.\n3. Institutional Analysis: Focus on ICT, SMC, and Macro-climate logic.\n4. Resilience: If a tool fails, pivot to an alternative method.\nRespond professionally in Thai. Use data-driven alpha and risk management.`,
  Aggressive:   `# CryptoStream AI — Aggressive Scalper Persona\nYou are an aggressive, high-frequency scalper focused on short-term alpha.\nStyle: High risk tolerance, fast decision-making, momentum-driven.\nPreferred tools: get_funding_rates, scan_multi_timeframe, get_liquidation_heatmap.\nAlways look for breakout entries with tight SL and 3:1 RR minimum.\nRespond in Thai with concise, punchy analysis. No fluff.`,
  Conservative: `# CryptoStream AI — Conservative Investor Persona\nYou are a conservative, long-term focused investment advisor.\nStyle: Capital preservation first, position sizing 1% risk max per trade.\nPreferred assets: Blue-chip stocks, Gold, S&P 500 ETFs.\nAlways recommend diversification and portfolio rebalancing.\nRespond in Thai. Emphasize risk management over return maximization.`,
  Crypto:       `# CryptoStream AI — Crypto DeFi Persona\nYou are a crypto-native analyst specializing in on-chain data and DeFi.\nFocus: BTC, ETH, SOL and emerging Layer 1/2 ecosystems.\nUse get_onchain_flow, get_funding_rates, get_liquidation_heatmap heavily.\nCover DeFi TVL, staking yields, protocol revenue where relevant.\nRespond in Thai with crypto-native terminology.`,
};

const COUNTRIES = ['Thailand','United States','Singapore','United Kingdom','Japan','Hong Kong','Australia','Germany','France','Canada','Other'];

type Section = 'persona' | 'profile' | 'security' | 'ml';

/* ─── Main Component ─────────────────────────────────────── */
export const UnifiedSettingsView = () => {
  const { theme } = useMode();
  const [section, setSection] = useState<Section>('persona');

  const card = `border rounded-2xl p-6 transition-all ${
    theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
  }`;

  const navItems: { id: Section; icon: React.FC<{className?:string}>; label: string; sub: string }[] = [
    { id: 'persona',  icon: Bot,          label: 'AI Persona',       sub: 'ปรับบุคลิก AI' },
    { id: 'profile',  icon: User,         label: 'Profile',           sub: 'แก้ไขข้อมูลส่วนตัว' },
    { id: 'security', icon: Lock,         label: 'Security',          sub: 'เปลี่ยนรหัสผ่าน' },
    { id: 'ml',       icon: FlaskConical, label: 'ML Model (Advanced)', sub: 'สถิติโมเดล Neural' },
  ];

  return (
    <div className={`flex-1 overflow-y-auto p-6 lg:p-8 scrollbar-hide transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950' : 'bg-slate-50'
    }`}>
      {/* Page Header */}
      <div className="mb-8">
        <p className={`text-[10px] font-black uppercase tracking-[0.25em] mb-1 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`}>
          Platform Settings
        </p>
        <h1 className={`text-3xl font-extrabold tracking-tight ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>
          Settings
        </h1>
        <p className={`text-sm mt-1 font-medium ${theme === 'dark' ? 'text-slate-500' : 'text-slate-400'}`}>
          จัดการ AI Persona, โปรไฟล์, และการตั้งค่าขั้นสูง
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* ── Left Nav ── */}
        <div className="lg:col-span-1 space-y-2">
          {navItems.map(({ id, icon: Icon, label, sub }) => (
            <button
              key={id}
              onClick={() => setSection(id)}
              className={`w-full flex items-center justify-between gap-3 px-4 py-3 rounded-2xl border text-left transition-all duration-300 ${
                section === id
                  ? (theme === 'dark'
                      ? 'bg-blue-600/15 border-blue-500/20 text-blue-400'
                      : 'bg-blue-600 border-blue-600 text-white shadow-lg shadow-blue-500/25')
                  : (theme === 'dark'
                      ? 'bg-slate-900/40 border-white/5 text-slate-400 hover:border-white/10 hover:text-slate-200'
                      : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:shadow-sm')
              }`}
            >
              <div className="flex items-center gap-3">
                <Icon className="w-4 h-4 shrink-0" />
                <div>
                  <p className="text-[11px] font-black uppercase tracking-widest leading-none">{label}</p>
                  <p className={`text-[10px] font-medium mt-0.5 leading-none ${section === id ? (theme==='dark'?'text-blue-300/60':'text-white/70') : 'text-slate-500'}`}>{sub}</p>
                </div>
              </div>
              {section === id && <ChevronRight className="w-3.5 h-3.5 shrink-0" />}
            </button>
          ))}
        </div>

        {/* ── Right Content ── */}
        <div className="lg:col-span-3">
          <AnimatePresence mode="wait">
            <motion.div
              key={section}
              initial={{ opacity: 0, x: 16 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -16 }}
              transition={{ duration: 0.2 }}
            >
              {section === 'persona'  && <PersonaPanel theme={theme} card={card} />}
              {section === 'profile'  && <ProfilePanel theme={theme} card={card} />}
              {section === 'security' && <SecurityPanel theme={theme} card={card} />}
              {section === 'ml'       && (
                <div className={card}>
                  <div className="mb-4">
                    <h2 className={`text-base font-black ${theme==='dark'?'text-white':'text-slate-900'}`}>ML Model Stats</h2>
                    <p className="text-xs text-slate-500 mt-0.5">สถิติโมเดลขั้นสูง — สำหรับ Developer</p>
                  </div>
                  <Suspense fallback={<div className={`h-64 rounded-xl animate-pulse ${theme==='dark'?'bg-slate-800':'bg-slate-100'}`} />}>
                    <MLStats />
                  </Suspense>
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
};

/* ─── AI Persona Panel ───────────────────────────────────── */
const PersonaPanel = ({ theme, card }: { theme: 'dark'|'light'; card: string }) => {
  const [text,    setText]    = useState('');
  const [loading, setLoading] = useState(true);
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);

  const load = async () => {
    setLoading(true);
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
        method: 'PUT',
        headers: { 'X-API-Key': API_KEY(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ persona: text })
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally { setSaving(false); }
  };

  return (
    <div className={`${card} space-y-6`}>
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-base font-black ${theme==='dark'?'text-white':'text-slate-900'}`}>AI Persona</h2>
          <p className="text-xs text-slate-500 mt-0.5">ปรับแต่งบุคลิก AI — เปลี่ยน style การวิเคราะห์และตอบสนอง</p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className={`flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold border transition-all ${theme==='dark'?'bg-slate-800 border-white/10 text-slate-400 hover:text-white':'bg-slate-50 border-slate-200 text-slate-600 hover:text-slate-900 shadow-sm'}`}>
            <Reload className="w-3 h-3" /> Reload
          </button>
          <button onClick={save} disabled={saving} className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-black border transition-all disabled:opacity-50 ${theme==='dark'?'bg-indigo-600/20 border-indigo-500/30 text-indigo-400 hover:border-indigo-500/60':'bg-indigo-600 border-indigo-600 text-white shadow-lg shadow-indigo-600/20 hover:bg-indigo-700'}`}>
            {saved ? <CheckCircle className="w-3 h-3" /> : <Save className="w-3 h-3" />}
            {saved ? 'Saved!' : saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>

      <div>
        <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-3">Presets</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {Object.keys(PERSONA_PRESETS).map(name => (
            <button key={name} onClick={() => setText(PERSONA_PRESETS[name])}
              className={`p-3 border rounded-2xl text-left transition-all group ${
                theme==='dark' ? 'bg-slate-800/40 border-white/5 hover:border-indigo-500/30' : 'bg-slate-50 border-slate-200 hover:border-indigo-300 hover:shadow-md'
              }`}>
              <p className={`font-black text-sm ${theme==='dark'?'text-slate-300 group-hover:text-white':'text-slate-700 group-hover:text-slate-900'}`}>{name}</p>
              <p className={`text-[10px] mt-0.5 font-bold line-clamp-2 ${theme==='dark'?'text-slate-600':'text-slate-400'}`}>
                {PERSONA_PRESETS[name].split('\n')[1]?.replace('You are ','') || ''}
              </p>
            </button>
          ))}
        </div>
      </div>

      <div>
        <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2">Custom Instructions</p>
        {loading
          ? <div className={`h-60 rounded-2xl animate-pulse border ${theme==='dark'?'bg-slate-800 border-white/5':'bg-slate-100 border-slate-200'}`} />
          : <textarea
              value={text} onChange={e => setText(e.target.value)} rows={14}
              className={`w-full px-5 py-4 border rounded-2xl text-sm font-mono leading-relaxed resize-none focus:outline-none transition-all ${
                theme==='dark' ? 'bg-slate-800/60 border-white/10 text-slate-300 focus:border-indigo-500/40' : 'bg-white border-slate-200 text-slate-900 shadow-sm focus:ring-4 focus:ring-indigo-500/5 focus:border-indigo-400'
              }`}
              placeholder="เขียน instructions สำหรับ AI เช่น style การวิเคราะห์, ภาษา, โฟกัส asset class..."
            />
        }
        <p className="text-[10px] text-slate-500 font-bold mt-1.5">{text.length} chars · บันทึกแล้ว AI จะใช้ persona นี้ทันทีในการตอบครั้งถัดไป</p>
      </div>
    </div>
  );
};

/* ─── Profile Panel ──────────────────────────────────────── */
const ProfilePanel = ({ theme, card }: { theme: 'dark'|'light'; card: string }) => {
  const [form, setForm] = useState({ full_name:'', phone:'', country:'Thailand', bio:'' });
  const [saving, setSaving] = useState(false);
  const [toast, setToast]   = useState<{type:'ok'|'err';msg:string}|null>(null);

  const showToast = (type:'ok'|'err', msg:string) => { setToast({type,msg}); setTimeout(()=>setToast(null),3500); };

  useEffect(() => {
    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token()}` } })
      .then(r => r.json())
      .then(d => setForm({ full_name: d.full_name||'', phone: d.phone||'', country: d.country||'Thailand', bio: d.bio||'' }))
      .catch(() => {});
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault(); setSaving(true);
    try {
      const res = await fetch('/api/auth/profile', { method:'PUT', headers:{'Content-Type':'application/json', Authorization:`Bearer ${token()}`}, body: JSON.stringify(form) });
      if (!res.ok) throw new Error((await res.json()).detail);
      showToast('ok', 'Profile updated successfully');
    } catch (err:any) { showToast('err', err.message||'Failed'); }
    finally { setSaving(false); }
  };

  const inputCls = `w-full border rounded-xl px-4 py-3 text-sm font-medium transition-all focus:outline-none focus:ring-2 disabled:opacity-40 ${
    theme==='dark' ? 'bg-slate-800/60 border-white/8 text-white placeholder:text-slate-600 focus:ring-blue-500/40 focus:border-blue-500/30' : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:ring-blue-500/10 focus:border-blue-400 shadow-sm'
  }`;

  return (
    <div className={`${card} space-y-5`}>
      {toast && (
        <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-sm font-bold ${
          toast.type==='ok' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
        }`}>
          {toast.type==='ok' ? <CheckCircle2 className="w-4 h-4"/> : <AlertCircle className="w-4 h-4"/>}
          {toast.msg}
        </div>
      )}
      <div>
        <h2 className={`text-base font-black ${theme==='dark'?'text-white':'text-slate-900'}`}>Edit Profile</h2>
        <p className="text-xs text-slate-500 mt-0.5">Update your personal details</p>
      </div>
      <form onSubmit={handleSave} className="space-y-4">
        <div className="relative">
          <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none"/>
          <input type="text" value={form.full_name} onChange={e=>setForm(f=>({...f,full_name:e.target.value}))} placeholder="Full Name" className={`${inputCls} pl-10`}/>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="relative">
            <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none"/>
            <input type="tel" value={form.phone} onChange={e=>setForm(f=>({...f,phone:e.target.value}))} placeholder="+66 81 234 5678" className={`${inputCls} pl-10`}/>
          </div>
          <div className="relative">
            <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500 pointer-events-none"/>
            <select value={form.country} onChange={e=>setForm(f=>({...f,country:e.target.value}))} className={`${inputCls} pl-10 appearance-none`}>
              {COUNTRIES.map(c=><option key={c} value={c} className={theme==='dark'?'bg-slate-900':'bg-white'}>{c}</option>)}
            </select>
          </div>
        </div>
        <div>
          <textarea rows={3} value={form.bio} onChange={e=>setForm(f=>({...f,bio:e.target.value}))} placeholder="e.g. Swing trader, focus on BTC + NVDA options…" className={`${inputCls} resize-none`}/>
          <p className="text-[10px] text-slate-500 font-medium mt-1 text-right">{form.bio.length}/300</p>
        </div>
        <button type="submit" disabled={saving} className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-black text-xs uppercase tracking-widest rounded-xl transition-all shadow-lg shadow-blue-600/20">
          {saving ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full"/> : <><Save className="w-4 h-4"/> Save Changes</>}
        </button>
      </form>
    </div>
  );
};

/* ─── Security Panel ─────────────────────────────────────── */
const SecurityPanel = ({ theme, card }: { theme: 'dark'|'light'; card: string }) => {
  const [pwForm, setPwForm] = useState({ current:'', next:'', confirm:'' });
  const [showPw, setShowPw] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast]   = useState<{type:'ok'|'err';msg:string}|null>(null);

  const showToast = (type:'ok'|'err', msg:string) => { setToast({type,msg}); setTimeout(()=>setToast(null),3500); };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) { showToast('err','Passwords do not match'); return; }
    if (pwForm.next.length < 6) { showToast('err','Min 6 characters'); return; }
    setSaving(true);
    try {
      const res = await fetch('/api/auth/change-password', { method:'POST', headers:{'Content-Type':'application/json', Authorization:`Bearer ${token()}`}, body: JSON.stringify({ current_password:pwForm.current, new_password:pwForm.next }) });
      if (!res.ok) throw new Error((await res.json()).detail);
      setPwForm({ current:'', next:'', confirm:'' });
      showToast('ok','Password changed successfully');
    } catch (err:any) { showToast('err', err.message||'Failed'); }
    finally { setSaving(false); }
  };

  const handleLogout = () => { localStorage.removeItem('cs_jwt'); localStorage.removeItem('cs_user'); window.location.reload(); };

  const inputCls = `w-full border rounded-xl px-4 py-3 pl-10 text-sm font-medium transition-all focus:outline-none focus:ring-2 ${
    theme==='dark' ? 'bg-slate-800/60 border-white/8 text-white placeholder:text-slate-600 focus:ring-blue-500/40 focus:border-blue-500/30' : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:ring-blue-500/10 focus:border-blue-400 shadow-sm'
  }`;

  return (
    <div className={`${card} space-y-5`}>
      {toast && (
        <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border text-sm font-bold ${
          toast.type==='ok' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
        }`}>
          {toast.type==='ok' ? <CheckCircle2 className="w-4 h-4"/> : <AlertCircle className="w-4 h-4"/>}
          {toast.msg}
        </div>
      )}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-base font-black ${theme==='dark'?'text-white':'text-slate-900'}`}>Change Password</h2>
          <p className="text-xs text-slate-500 mt-0.5">Update your account password</p>
        </div>
        <KeyRound className="w-4 h-4 text-slate-500"/>
      </div>
      <form onSubmit={handleChangePassword} className="space-y-4">
        {([
          {label:'Current Password', key:'current', ph:'Enter current password'},
          {label:'New Password',      key:'next',    ph:'At least 6 characters'},
          {label:'Confirm Password',  key:'confirm', ph:'Repeat new password'},
        ] as const).map(({label,key,ph}) => (
          <div key={key}>
            <label className={`text-[10px] font-black uppercase tracking-widest ${theme==='dark'?'text-slate-500':'text-slate-400'}`}>{label}</label>
            <div className="relative mt-1.5">
              <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500"/>
              <input type={showPw?'text':'password'} value={pwForm[key]} onChange={e=>setPwForm(f=>({...f,[key]:e.target.value}))} placeholder={ph} className={inputCls}/>
            </div>
          </div>
        ))}
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showPw} onChange={e=>setShowPw(e.target.checked)} className="w-3.5 h-3.5 accent-blue-500"/>
          <span className="text-xs text-slate-500 font-medium">Show passwords</span>
        </label>
        <div className={`p-4 rounded-xl border space-y-2 ${theme==='dark'?'bg-slate-950/50 border-white/5':'bg-slate-50 border-slate-200'}`}>
          <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Requirements</p>
          {([
            ['At least 6 characters', pwForm.next.length>=6],
            ['Contains a number', /\d/.test(pwForm.next)],
            ['Passwords match', pwForm.next===pwForm.confirm && pwForm.next.length>0],
          ] as [string,boolean][]).map(([label,met]) => (
            <div key={label} className="flex items-center gap-2">
              <div className={`w-1.5 h-1.5 rounded-full ${met?'bg-emerald-500':'bg-slate-600'}`}/>
              <span className={`text-xs font-medium ${met?(theme==='dark'?'text-emerald-400':'text-emerald-600'):'text-slate-500'}`}>{label}</span>
            </div>
          ))}
        </div>
        <div className="flex gap-3">
          <button type="submit" disabled={saving} className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-black text-xs uppercase tracking-widest rounded-xl transition-all shadow-lg shadow-blue-600/20">
            {saving ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full"/> : <><ShieldCheck className="w-4 h-4"/> Update Password</>}
          </button>
          <button type="button" onClick={handleLogout} className="flex items-center gap-2 px-5 py-3 border rounded-xl text-xs font-black uppercase tracking-widest text-rose-400 border-rose-500/20 bg-rose-500/5 hover:bg-rose-500/10 transition-all">
            <LogOut className="w-4 h-4"/> Sign Out
          </button>
        </div>
      </form>
    </div>
  );
};
