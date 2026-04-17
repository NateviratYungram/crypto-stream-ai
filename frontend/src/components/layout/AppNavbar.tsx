import React from 'react';
import { Bell, Command, Search, ShieldCheck, User } from 'lucide-react';
import { motion } from 'framer-motion';

interface AppNavbarProps {
  mode: 'institutional' | 'retail';
  setMode: (mode: 'institutional' | 'retail') => void;
  onOpenCommand: () => void;
  isAuthorized: boolean;
  onLogout: () => void;
}

export const AppNavbar: React.FC<AppNavbarProps> = ({ mode, setMode, onOpenCommand, isAuthorized, onLogout }) => {
  return (
    <header className="h-16 border-b border-white/5 bg-slate-950/50 backdrop-blur-xl flex items-center justify-between px-6 shrink-0 z-50">
      {/* Brand / Logo */}
      <div 
        className="flex items-center gap-3 cursor-pointer active:scale-95 transition-all" 
        onClick={() => {
          console.log('Logo clicked - Logging out');
          onLogout();
        }}
      >
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-blue-700 flex items-center justify-center shadow-lg shadow-blue-500/20">
          <span className="text-white font-black text-sm">C</span>
        </div>
        <div className="hidden md:block text-left">
          <h2 className="text-sm font-black text-white tracking-tighter uppercase">CryptoStream</h2>
          <p className="text-[9px] text-slate-500 font-bold uppercase tracking-[0.2em] -mt-1">Tactical Intelligence</p>
        </div>
      </div>

      {/* Global Search / Command Bar */}
      <div className="flex-1 max-w-xl px-12 hidden md:block">
        <button 
          onClick={onOpenCommand}
          className="w-full h-10 bg-white/5 border border-white/5 rounded-xl px-4 flex items-center justify-between group hover:border-blue-500/30 transition-all shadow-inner active:scale-[0.99]"
        >
          <div className="flex items-center gap-3">
            <Search className="w-4 h-4 text-slate-500 group-hover:text-blue-400 transition-colors" />
            <span className="text-xs font-bold text-slate-500 group-hover:text-slate-300 transition-colors">Search functions or market data...</span>
          </div>
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white/5 border border-white/10">
            <Command className="w-3 h-3 text-slate-600" />
            <span className="text-[10px] font-black text-slate-300">K</span>
          </div>
        </button>
      </div>

      {/* Control Panel */}
      <div className="flex items-center gap-3">
        {/* Mode Toggle */}
        <button
          onClick={() => setMode(mode === 'institutional' ? 'retail' : 'institutional')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest border transition-all shadow-lg relative group active:scale-95 ${
            mode === 'retail'
              ? 'bg-blue-600/10 border-blue-500/20 text-blue-400'
              : 'bg-emerald-600/10 border-emerald-500/20 text-emerald-500 font-black'
          }`}
        >
          <div className={`w-1.5 h-1.5 rounded-full ${mode === 'retail' ? 'bg-blue-400' : 'bg-emerald-400'} animate-pulse`} />
          {mode === 'retail' ? '🌐 Trading' : '🏦 Institutional'}
        </button>

        <div className="w-px h-6 bg-white/5 mx-1" />

        <button className="p-2.5 rounded-xl hover:bg-white/5 text-slate-500 hover:text-white transition-all relative active:scale-90">
          <Bell className="w-5 h-5" />
          <span className="absolute top-2.5 right-2.5 w-2 h-2 bg-blue-500 rounded-full border-2 border-slate-950" />
        </button>

        <button 
          onClick={() => {
            console.log('Sign Out clicked');
            onLogout();
          }}
          className="flex items-center gap-2 p-1 pr-3 rounded-2xl bg-white/10 hover:bg-white/20 transition-all text-slate-200 hover:text-white border border-white/20 active:scale-95 shadow-xl"
        >
          <div className="w-8 h-8 rounded-xl bg-slate-900 border border-white/10 flex items-center justify-center overflow-hidden">
            <User className="w-5 h-5" />
          </div>
          <span className="text-[10px] font-black uppercase tracking-widest hidden md:block">Sign Out</span>
        </button>
      </div>
    </header>
  );
};
