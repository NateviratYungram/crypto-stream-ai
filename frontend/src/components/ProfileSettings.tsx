import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  User, Mail, Phone, Globe, Briefcase, Lock, Save, CheckCircle2,
  AlertCircle, ShieldCheck, Calendar, Edit3, KeyRound, LogOut
} from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

interface ProfileData {
  id: string;
  email: string;
  username: string;
  full_name: string;
  phone: string;
  country: string;
  bio: string;
  created_at: string;
}

const getSafeInputClass = (theme: 'light' | 'dark') => `
  w-full border rounded-xl px-4 py-3 text-sm font-medium transition-all
  disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2
  ${theme === 'dark' 
    ? 'bg-slate-900/60 border-white/8 text-white placeholder:text-slate-600 focus:ring-blue-500/40 focus:border-blue-500/30' 
    : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:ring-blue-500/10 focus:border-blue-400 shadow-sm'}
`;

const COUNTRIES = [
  'Thailand', 'United States', 'Singapore', 'United Kingdom', 'Japan',
  'Hong Kong', 'Australia', 'Germany', 'France', 'Canada', 'Other'
];

export const ProfileSettings = () => {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [form, setForm]       = useState({ full_name: '', phone: '', country: '', bio: '' });
  const [pwForm, setPwForm]   = useState({ current: '', next: '', confirm: '' });
  const [showPw, setShowPw]   = useState(false);
  const [saving, setSaving]   = useState(false);
  const [savingPw, setSavingPw] = useState(false);
  const [toast, setToast]     = useState<{ type: 'ok' | 'err'; msg: string } | null>(null);
  const [activeSection, setActiveSection] = useState<'profile' | 'security'>('profile');
  const { theme } = useMode();

  const showToast = (type: 'ok' | 'err', msg: string) => {
    setToast({ type, msg });
    setTimeout(() => setToast(null), 3500);
  };

  const token = () => localStorage.getItem('cs_jwt') || '';

  useEffect(() => {
    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token()}` } })
      .then(r => r.json())
      .then(data => {
        setProfile(data);
        setForm({
          full_name:    data.full_name    || '',
          phone:        data.phone        || '',
          country:      data.country      || 'Thailand',
          bio:          data.bio          || '',
        });
      })
      .catch(() => showToast('err', 'Failed to load profile'));
  }, []);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const res = await fetch('/api/auth/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify(form)
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      // Update cached user
      const updated = { ...profile, ...form };
      localStorage.setItem('cs_user', JSON.stringify(updated));
      setProfile(updated as ProfileData);
      showToast('ok', 'Profile updated successfully');
    } catch (err: any) {
      showToast('err', err.message || 'Failed to save profile');
    } finally {
      setSaving(false);
    }
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (pwForm.next !== pwForm.confirm) { showToast('err', 'New passwords do not match'); return; }
    if (pwForm.next.length < 6) { showToast('err', 'Password must be at least 6 characters'); return; }
    setSavingPw(true);
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token()}` },
        body: JSON.stringify({ current_password: pwForm.current, new_password: pwForm.next })
      });
      if (!res.ok) throw new Error((await res.json()).detail);
      setPwForm({ current: '', next: '', confirm: '' });
      showToast('ok', 'Password changed successfully');
    } catch (err: any) {
      showToast('err', err.message || 'Failed to change password');
    } finally {
      setSavingPw(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('cs_jwt');
    localStorage.removeItem('cs_user');
    window.location.reload();
  };

  const initials = profile?.full_name
    ? profile.full_name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
    : '??';

  const joinedDate = profile?.created_at
    ? new Date(profile.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
    : '—';

  return (
    <div className={`flex-1 overflow-y-auto p-6 lg:p-8 space-y-6 scrollbar-hide transition-colors duration-500 ${
      theme === 'dark' ? 'bg-slate-950' : 'bg-slate-50'
    }`}>
      {/* Toast */}
      {toast && (
        <motion.div
          initial={{ opacity: 0, y: -16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -16 }}
          className={`fixed top-4 right-4 z-[9999] flex items-center gap-3 px-5 py-3 rounded-2xl border shadow-2xl text-sm font-bold ${
            toast.type === 'ok'
              ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
              : 'bg-rose-500/10 border-rose-500/20 text-rose-400'
          }`}
        >
          {toast.type === 'ok' ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
          {toast.msg}
        </motion.div>
      )}

      {/* Page Header */}
      <div>
        <h1 className={`text-2xl font-black tracking-tighter ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Account Settings</h1>
        <p className="text-sm text-slate-500 font-medium mt-1">Manage your profile, security, and preferences</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Left: Profile Card ── */}
        <div className="space-y-4">
          {/* Avatar Card */}
          <div className={`border rounded-2xl p-6 flex flex-col items-center gap-4 transition-all ${
            theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
          }`}>
            <div className="w-20 h-20 bg-gradient-to-br from-blue-600 to-indigo-600 rounded-2xl flex items-center justify-center shadow-xl shadow-blue-500/20">
              <span className="text-2xl font-black text-white">{initials}</span>
            </div>
            <div className="text-center">
              <p className={`font-black text-lg ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>{profile?.full_name || '—'}</p>
              <p className="text-sm text-slate-400 font-medium">@{profile?.username || '—'}</p>
            </div>
            <div className={`px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border ${
              theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-emerald-50 border-emerald-200 text-emerald-600'
            }`}>
              Active Account
            </div>
          </div>

          {/* Info Chips */}
          <div className={`border rounded-2xl p-5 space-y-3 transition-all ${
            theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
          }`}>
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Account Info</p>
            <div className="space-y-3">
              <InfoRow icon={<Mail className="w-3.5 h-3.5" />} label="Email" value={profile?.email || '—'} theme={theme} />
              <InfoRow icon={<Calendar className="w-3.5 h-3.5" />} label="Member since" value={joinedDate} theme={theme} />
              <InfoRow icon={<ShieldCheck className="w-3.5 h-3.5" />} label="Status" value="Active" green theme={theme} />
            </div>
          </div>

          {/* Nav */}
          <div className={`border rounded-2xl p-3 space-y-1 transition-all ${
            theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
          }`}>
            {([['profile', Edit3, 'Edit Profile'], ['security', KeyRound, 'Security']] as const).map(([id, Icon, label]) => (
              <button
                key={id}
                onClick={() => setActiveSection(id)}
                className={`w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest transition-all ${
                  activeSection === id ? (theme === 'dark' ? 'bg-blue-600/15 text-blue-400 border border-blue-500/20' : 'bg-blue-600 text-white shadow-lg shadow-blue-500/20') : 'text-slate-500 hover:text-slate-300 hover:bg-white/5'
                }`}
              >
                <Icon className="w-3.5 h-3.5" /> {label}
              </button>
            ))}
            <button
              onClick={handleLogout}
              className="w-full flex items-center gap-3 px-4 py-2.5 rounded-xl text-xs font-black uppercase tracking-widest text-slate-600 hover:text-rose-400 hover:bg-rose-500/5 transition-all"
            >
              <LogOut className="w-3.5 h-3.5" /> Sign Out
            </button>
          </div>
        </div>

        {/* ── Right: Forms ── */}
        <div className="lg:col-span-2">
          {activeSection === 'profile' ? (
            <motion.form
              key="profile-form"
              initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
              onSubmit={handleSave}
              className={`border rounded-2xl p-6 space-y-5 transition-all ${
                theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <h2 className={`text-base font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Edit Profile</h2>
                  <p className="text-xs text-slate-500 font-medium mt-0.5">Update your personal details</p>
                </div>
                <Edit3 className="w-4 h-4 text-slate-600" />
              </div>

              <div>
                <label className="field-label">Full Name</label>
                <div className="relative mt-1.5">
                  <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                  <input type="text" value={form.full_name}
                    onChange={e => setForm(f => ({ ...f, full_name: e.target.value }))}
                    placeholder="John Doe" className={`${getSafeInputClass(theme)} pl-10`} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="field-label">Phone</label>
                  <div className="relative mt-1.5">
                    <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                    <input type="tel" value={form.phone}
                      onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                      placeholder="+66 81 234 5678" className={`${getSafeInputClass(theme)} pl-10`} />
                  </div>
                </div>
                <div>
                  <label className="field-label">Country</label>
                  <div className="relative mt-1.5">
                    <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600 pointer-events-none" />
                    <select value={form.country} onChange={e => setForm(f => ({ ...f, country: e.target.value }))}
                      className={`${getSafeInputClass(theme)} pl-10 appearance-none`}>
                      {COUNTRIES.map(c => <option key={c} value={c} className={theme === 'dark' ? 'bg-slate-900' : 'bg-white'}>{c}</option>)}
                    </select>
                  </div>
                </div>
              </div>

              <div>
                <label className="field-label">
                  <Briefcase className="w-3 h-3 inline mr-1" />Bio / Trading Style
                </label>
                <textarea rows={3} value={form.bio}
                  onChange={e => setForm(f => ({ ...f, bio: e.target.value }))}
                  placeholder="e.g. Swing trader, focus on BTC + NVDA options…"
                  className={`${getSafeInputClass(theme)} mt-1.5 resize-none`} />
                <p className="text-[10px] text-slate-600 font-medium mt-1 text-right">{form.bio.length}/300</p>
              </div>

              <button type="submit" disabled={saving}
                className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-black text-xs uppercase tracking-widest rounded-xl transition-all shadow-lg shadow-blue-600/20">
                {saving
                  ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
                  : <><Save className="w-4 h-4" /> Save Changes</>}
              </button>
            </motion.form>
          ) : (
            <motion.form
              key="security-form"
              initial={{ opacity: 0, x: 16 }} animate={{ opacity: 1, x: 0 }}
              onSubmit={handleChangePassword}
              className={`border rounded-2xl p-6 space-y-5 transition-all ${
                theme === 'dark' ? 'bg-slate-900/50 border-white/5' : 'bg-white border-slate-200 shadow-xl shadow-slate-200/40'
              }`}
            >
              <div className="flex items-center justify-between">
                <div>
                  <h2 className={`text-base font-black ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Change Password</h2>
                  <p className="text-xs text-slate-500 font-medium mt-0.5">Update your account password</p>
                </div>
                <KeyRound className="w-4 h-4 text-slate-600" />
              </div>

              {[
                { label: 'Current Password',     key: 'current',  ph: 'Enter current password' },
                { label: 'New Password',          key: 'next',     ph: 'At least 6 characters' },
                { label: 'Confirm New Password',  key: 'confirm',  ph: 'Repeat new password' },
              ].map(({ label, key, ph }) => (
                <div key={key}>
                  <label className="field-label">{label}</label>
                  <div className="relative mt-1.5">
                    <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-600" />
                    <input
                      type={showPw ? 'text' : 'password'}
                      value={pwForm[key as keyof typeof pwForm]}
                      onChange={e => setPwForm(f => ({ ...f, [key]: e.target.value }))}
                      placeholder={ph}
                      className={`${getSafeInputClass(theme)} pl-10 ${
                        key === 'confirm' && pwForm.confirm && pwForm.confirm !== pwForm.next
                          ? 'border-rose-500/50 focus:border-rose-500/50' : ''
                      }`}
                    />
                  </div>
                  {key === 'confirm' && pwForm.confirm && pwForm.confirm !== pwForm.next && (
                    <p className="text-[10px] text-rose-400 font-bold mt-1">Passwords do not match</p>
                  )}
                </div>
              ))}

              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={showPw} onChange={e => setShowPw(e.target.checked)}
                  className="w-3.5 h-3.5 accent-blue-500" />
                <span className="text-xs text-slate-500 font-medium">Show passwords</span>
              </label>

              {/* Security badges */}
              <div className={`p-4 rounded-xl border space-y-2 transition-all ${
                theme === 'dark' ? 'bg-slate-950/50 border-white/5' : 'bg-slate-50 border-slate-200'
              }`}>
                <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">Password Requirements</p>
                {[
                  ['At least 6 characters', pwForm.next.length >= 6],
                  ['Contains a number', /\d/.test(pwForm.next)],
                  ['Passwords match', pwForm.next === pwForm.confirm && pwForm.next.length > 0],
                ].map(([label, met]) => (
                  <div key={label as string} className="flex items-center gap-2">
                    <div className={`w-1.5 h-1.5 rounded-full ${met ? 'bg-emerald-500' : 'bg-slate-400'}`} />
                    <span className={`text-xs font-medium ${met ? (theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600') : 'text-slate-500'}`}>{label as string}</span>
                  </div>
                ))}
              </div>

              <button type="submit" disabled={savingPw}
                className="flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-black text-xs uppercase tracking-widest rounded-xl transition-all shadow-lg shadow-blue-600/20">
                {savingPw
                  ? <span className="animate-spin w-4 h-4 border-2 border-white/30 border-t-white rounded-full" />
                  : <><ShieldCheck className="w-4 h-4" /> Update Password</>}
              </button>
            </motion.form>
          )}
        </div>
      </div>
    </div>
  );
};

const InfoRow = ({ icon, label, value, green, theme }: { icon: React.ReactNode; label: string; value: string; green?: boolean; theme?: 'light' | 'dark' }) => (
  <div className="flex items-center justify-between">
    <div className="flex items-center gap-2 text-slate-500">
      {icon}
      <span className="text-xs font-bold uppercase tracking-wider">{label}</span>
    </div>
    <span className={`text-xs font-black ${green ? 'text-emerald-400' : (theme === 'dark' ? 'text-slate-300' : 'text-slate-700')}`}>{value}</span>
  </div>
);
