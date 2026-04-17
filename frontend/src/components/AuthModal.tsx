import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Eye, EyeOff, Mail, Lock, User, Phone, Globe, Briefcase,
  ChevronRight, AlertCircle, CheckCircle2, LayoutDashboard
} from 'lucide-react';

interface AuthModalProps {
  open: boolean;
  defaultTab?: 'login' | 'register';
  onClose: () => void;
  onSuccess: (token: string, user: UserProfile) => void;
}

export interface UserProfile {
  id: string;
  email: string;
  username: string;
  full_name: string;
  account_type: 'retail' | 'institutional';
  phone: string;
  country: string;
  bio: string;
}

const COUNTRIES = [
  'Thailand', 'United States', 'Singapore', 'United Kingdom', 'Japan',
  'Hong Kong', 'Australia', 'Germany', 'France', 'Canada', 'Other'
];

const INPUT_BASE = `w-full bg-slate-900/60 border rounded-xl px-4 py-3 text-sm font-medium text-white
  placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/40
  transition-all autofill:bg-slate-900`;

export const AuthModal = ({ open, defaultTab = 'login', onClose, onSuccess }: AuthModalProps) => {
  const [tab, setTab] = useState<'login' | 'register'>(defaultTab);
  const [showPass, setShowPass] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  // Login state
  const [loginEmail, setLoginEmail]       = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  // Register state
  const [reg, setReg] = useState({
    full_name: '', username: '', email: '', password: '', confirm: '',
    phone: '', country: 'Thailand', account_type: 'retail' as 'retail' | 'institutional', bio: ''
  });

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(''); setLoading(true);
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: loginEmail, password: loginPassword })
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || 'Login failed'); return; }
      localStorage.setItem('cs_jwt', data.token);
      localStorage.setItem('cs_user', JSON.stringify(data.user));
      localStorage.setItem('crypto_terminal_key', 'demo');
      onSuccess(data.token, data.user);
    } catch {
      setError('Network error — please try again');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (reg.password !== reg.confirm) { setError('Passwords do not match'); return; }
    if (reg.password.length < 6) { setError('Password must be at least 6 characters'); return; }
    setLoading(true);
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: reg.email, username: reg.username, full_name: reg.full_name,
          password: reg.password, phone: reg.phone, country: reg.country,
          account_type: reg.account_type, bio: reg.bio
        })
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || 'Registration failed'); return; }
      setSuccess('Account created! Logging you in…');
      localStorage.setItem('cs_jwt', data.token);
      localStorage.setItem('cs_user', JSON.stringify(data.user));
      localStorage.setItem('crypto_terminal_key', 'demo');
      setTimeout(() => onSuccess(data.token, data.user), 800);
    } catch {
      setError('Network error — please try again');
    } finally {
      setLoading(false);
    }
  };

  const switchTab = (t: 'login' | 'register') => {
    setTab(t); setError(''); setSuccess('');
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm z-[9990]"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 20 }}
            transition={{ type: 'spring', damping: 28, stiffness: 300 }}
            className="fixed inset-0 z-[9991] flex items-center justify-center p-4 pointer-events-none"
          >
            <div className="pointer-events-auto w-full max-w-md max-h-[92vh] overflow-y-auto bg-slate-950 border border-white/8 rounded-[2rem] shadow-2xl shadow-black/60 relative">

              {/* Glow */}
              <div className="absolute top-0 left-1/2 -translate-x-1/2 w-64 h-32 bg-blue-600/10 blur-[60px] rounded-full pointer-events-none" />

              {/* Header */}
              <div className="flex items-center justify-between p-7 pb-0">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20">
                    <LayoutDashboard className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <p className="text-base font-black text-white tracking-tighter">CryptoStream AI</p>
                    <p className="text-[10px] font-black text-blue-400 uppercase tracking-widest opacity-80">Tactical Terminal</p>
                  </div>
                </div>
                <button onClick={onClose} className="p-2 text-slate-500 hover:text-white rounded-xl hover:bg-white/5 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Tab Toggle */}
              <div className="px-7 pt-6 pb-0">
                <div className="flex p-1 bg-slate-900/50 rounded-xl border border-white/5">
                  {(['login', 'register'] as const).map(t => (
                    <button
                      key={t}
                      onClick={() => switchTab(t)}
                      className={`flex-1 py-2.5 text-xs font-black uppercase tracking-widest rounded-lg transition-all ${
                        tab === t ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/30' : 'text-slate-500 hover:text-slate-300'
                      }`}
                    >
                      {t === 'login' ? 'Login' : 'Register'}
                    </button>
                  ))}
                </div>
              </div>

              {/* Error / Success */}
              <AnimatePresence>
                {(error || success) && (
                  <motion.div
                    initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
                    className={`mx-7 mt-5 px-4 py-3 rounded-xl flex items-center gap-3 text-xs font-bold ${
                      error ? 'bg-rose-500/10 border border-rose-500/20 text-rose-400' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400'
                    }`}
                  >
                    {error ? <AlertCircle className="w-4 h-4 shrink-0" /> : <CheckCircle2 className="w-4 h-4 shrink-0" />}
                    {error || success}
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Forms */}
              <AnimatePresence mode="wait">
                {tab === 'login' ? (
                  <motion.form
                    key="login"
                    initial={{ opacity: 0, x: -20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 20 }}
                    transition={{ duration: 0.2 }}
                    onSubmit={handleLogin}
                    className="p-7 space-y-4"
                  >
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Email</label>
                      <div className="relative">
                        <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input
                          type="email" required value={loginEmail}
                          onChange={e => setLoginEmail(e.target.value)}
                          placeholder="your@email.com"
                          className={`${INPUT_BASE} pl-10 border-white/8 focus:border-blue-500/40`}
                        />
                      </div>
                    </div>

                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Password</label>
                      <div className="relative">
                        <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input
                          type={showPass ? 'text' : 'password'} required value={loginPassword}
                          onChange={e => setLoginPassword(e.target.value)}
                          placeholder="Enter password"
                          className={`${INPUT_BASE} pl-10 pr-10 border-white/8 focus:border-blue-500/40`}
                        />
                        <button type="button" onClick={() => setShowPass(o => !o)}
                          className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400">
                          {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                    </div>

                    <button
                      type="submit" disabled={loading}
                      className="w-full py-3.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-black text-xs uppercase tracking-widest transition-all flex items-center justify-center gap-2 shadow-lg shadow-blue-600/20 mt-2"
                    >
                      {loading ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" /> : <>Login <ChevronRight className="w-4 h-4" /></>}
                    </button>

                    <p className="text-center text-xs text-slate-600 font-medium">
                      Don't have an account?{' '}
                      <button type="button" onClick={() => switchTab('register')} className="text-blue-400 hover:text-blue-300 font-black transition-colors">
                        Register now
                      </button>
                    </p>
                  </motion.form>
                ) : (
                  <motion.form
                    key="register"
                    initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}
                    transition={{ duration: 0.2 }}
                    onSubmit={handleRegister}
                    className="p-7 space-y-4"
                  >
                    {/* Account Type */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-2 block">Account Type</label>
                      <div className="flex gap-3">
                        {(['retail', 'institutional'] as const).map(type => (
                          <button
                            key={type} type="button"
                            onClick={() => setReg(r => ({ ...r, account_type: type }))}
                            className={`flex-1 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest border transition-all ${
                              reg.account_type === type
                                ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                                : 'border-white/8 text-slate-500 hover:border-white/20 hover:text-slate-300'
                            }`}
                          >
                            {type === 'institutional' ? '🏛 Institutional' : '👤 Retail'}
                          </button>
                        ))}
                      </div>
                      <p className="mt-1.5 text-[10px] text-slate-600 font-medium">
                        {reg.account_type === 'institutional'
                          ? 'Full platform access — quant tools, multi-asset whale tracking, risk engine'
                          : 'Simplified mode — crypto charts, AI chat, basic signals'}
                      </p>
                    </div>

                    {/* Full Name */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Full Name *</label>
                      <div className="relative">
                        <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input
                          type="text" required value={reg.full_name}
                          onChange={e => setReg(r => ({ ...r, full_name: e.target.value }))}
                          placeholder="John Doe"
                          className={`${INPUT_BASE} pl-10 border-white/8 focus:border-blue-500/40`}
                        />
                      </div>
                    </div>

                    {/* Username */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Username *</label>
                      <div className="relative">
                        <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-600 font-black text-sm">@</span>
                        <input
                          type="text" required value={reg.username}
                          onChange={e => setReg(r => ({ ...r, username: e.target.value.replace(/[^a-zA-Z0-9_]/g, '') }))}
                          placeholder="trader_john"
                          className={`${INPUT_BASE} pl-8 border-white/8 focus:border-blue-500/40`}
                        />
                      </div>
                    </div>

                    {/* Email */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Email *</label>
                      <div className="relative">
                        <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input
                          type="email" required value={reg.email}
                          onChange={e => setReg(r => ({ ...r, email: e.target.value }))}
                          placeholder="your@email.com"
                          className={`${INPUT_BASE} pl-10 border-white/8 focus:border-blue-500/40`}
                        />
                      </div>
                    </div>

                    {/* Phone + Country */}
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Phone</label>
                        <div className="relative">
                          <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                          <input
                            type="tel" value={reg.phone}
                            onChange={e => setReg(r => ({ ...r, phone: e.target.value }))}
                            placeholder="+66 81 234 5678"
                            className={`${INPUT_BASE} pl-10 border-white/8 focus:border-blue-500/40`}
                          />
                        </div>
                      </div>
                      <div>
                        <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Country</label>
                        <div className="relative">
                          <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600 pointer-events-none" />
                          <select
                            value={reg.country}
                            onChange={e => setReg(r => ({ ...r, country: e.target.value }))}
                            className={`${INPUT_BASE} pl-10 border-white/8 focus:border-blue-500/40 appearance-none`}
                          >
                            {COUNTRIES.map(c => <option key={c} value={c} className="bg-slate-900">{c}</option>)}
                          </select>
                        </div>
                      </div>
                    </div>

                    {/* Bio */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">
                        <Briefcase className="w-3 h-3 inline mr-1" />Bio / Trading Style
                      </label>
                      <textarea
                        rows={2} value={reg.bio}
                        onChange={e => setReg(r => ({ ...r, bio: e.target.value }))}
                        placeholder="e.g. Swing trader, focus on BTC + NVDA options…"
                        className={`${INPUT_BASE} border-white/8 focus:border-blue-500/40 resize-none`}
                      />
                    </div>

                    {/* Password */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Password * (min 6 chars)</label>
                      <div className="relative">
                        <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input
                          type={showPass ? 'text' : 'password'} required value={reg.password}
                          onChange={e => setReg(r => ({ ...r, password: e.target.value }))}
                          placeholder="Create a password"
                          className={`${INPUT_BASE} pl-10 pr-10 border-white/8 focus:border-blue-500/40`}
                        />
                        <button type="button" onClick={() => setShowPass(o => !o)}
                          className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400">
                          {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                    </div>

                    {/* Confirm Password */}
                    <div>
                      <label className="text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 block">Confirm Password *</label>
                      <div className="relative">
                        <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                        <input
                          type={showConfirm ? 'text' : 'password'} required value={reg.confirm}
                          onChange={e => setReg(r => ({ ...r, confirm: e.target.value }))}
                          placeholder="Repeat password"
                          className={`${INPUT_BASE} pl-10 pr-10 border-white/8 ${reg.confirm && reg.confirm !== reg.password ? 'border-rose-500/50 focus:border-rose-500/50' : 'focus:border-blue-500/40'}`}
                        />
                        <button type="button" onClick={() => setShowConfirm(o => !o)}
                          className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400">
                          {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                        </button>
                      </div>
                      {reg.confirm && reg.confirm !== reg.password && (
                        <p className="mt-1 text-[10px] text-rose-400 font-bold">Passwords do not match</p>
                      )}
                    </div>

                    <button
                      type="submit" disabled={loading}
                      className="w-full py-3.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-black text-xs uppercase tracking-widest transition-all flex items-center justify-center gap-2 shadow-lg shadow-blue-600/20 mt-2"
                    >
                      {loading ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" /> : <>Create Account <ChevronRight className="w-4 h-4" /></>}
                    </button>

                    <p className="text-center text-xs text-slate-600 font-medium">
                      Already have an account?{' '}
                      <button type="button" onClick={() => switchTab('login')} className="text-blue-400 hover:text-blue-300 font-black transition-colors">
                        Login
                      </button>
                    </p>
                  </motion.form>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};
