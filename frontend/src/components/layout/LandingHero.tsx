import React, { useState, useMemo } from 'react';
import { Sparkles, Activity, ShieldCheck, RefreshCw, ChevronRight, Lock, Search, Globe, MessageSquare } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLanguage } from '../../contexts/LanguageContext';
import { useMode } from '../../contexts/ModeContext';

interface LandingHeroProps {
  onStartTrading: () => void;
  onTryDemo: () => void;
  onSearch: (query: string) => void;
  onNavigate: (key: 'chart' | 'markets' | 'news' | 'community' | 'more') => void;
  onLoginClick?: () => void;
}

export const LandingHero: React.FC<LandingHeroProps> = ({ onStartTrading, onTryDemo, onSearch, onNavigate, onLoginClick }) => {
  const { lang, setLang, t: translate } = useLanguage();
  const { theme } = useMode();
  const [searchFocused, setSearchFocused] = useState(false);
  const [query, setQuery] = useState('');

  // Generate a field of stars for the background
  const stars = useMemo(() => {
    return Array.from({ length: 80 }).map((_, i) => ({
      id: i,
      top: `${Math.random() * 100}%`,
      left: `${Math.random() * 100}%`,
      size: Math.random() * 2 + 0.5,
      delay: Math.random() * 5,
      duration: 2 + Math.random() * 3,
      opacity: Math.random() * 0.7 + 0.3,
      color: Math.random() > 0.8 ? 'bg-blue-400' : 'bg-white'
    }));
  }, []);

  const handleSearchSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (query.trim()) {
      onSearch(query.trim());
    }
  };

  const navItems = [
    { key: 'chart', label: translate('hero.nav_chart') },
    { key: 'markets', label: translate('hero.nav_markets') },
    { key: 'news', label: translate('hero.nav_news') },
    { key: 'community', label: translate('hero.nav_community') },
    { key: 'more', label: translate('hero.nav_more') },
  ] as const;

  const badges = [
    translate('hero.badge_fast'),
    translate('hero.badge_secure'),
    translate('hero.badge_clusters')
  ];

  return (
    <div className={`relative min-h-screen flex flex-col transition-colors duration-700 font-inter select-none overflow-x-hidden ${
      theme === 'dark' ? 'bg-slate-950 text-slate-200' : 'bg-slate-50 text-slate-800'
    }`}>
      {/* Navbar Overlay */}
      <nav className="fixed top-0 left-0 right-0 h-20 z-[100] px-8 flex items-center justify-between">
        <div className="flex items-center gap-8 lg:gap-12">
          {/* Logo */}
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-indigo-700 rounded-xl flex items-center justify-center shadow-[0_0_20px_rgba(59,130,246,0.5)]">
               <span className="text-white font-black text-xl italic">C</span>
            </div>
            <span className={`text-xl font-black tracking-widest hidden sm:block transition-colors duration-500 ${
              theme === 'dark' ? 'text-white' : 'text-slate-900'
            }`}>Capitradie</span>
          </div>

          {/* Nav Items */}
          <div className={`hidden md:flex items-center gap-1 px-1 py-1 rounded-full border backdrop-blur-md transition-all duration-500 ${
            theme === 'dark' ? 'border-white/5 bg-white/5' : 'border-slate-200 bg-white/80 shadow-sm'
          }`}>
            {navItems.map((item) => (
              <button 
                key={item.key} 
                onClick={() => onNavigate(item.key)}
                className={`px-5 py-2 rounded-full text-xs font-bold transition-all active:scale-95 ${
                  theme === 'dark' ? 'text-slate-400 hover:text-white hover:bg-white/5' : 'text-slate-500 hover:text-slate-900 hover:bg-slate-100'
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Language Toggle */}
          <button
            onClick={() => setLang(lang === 'en' ? 'th' : 'en')}
            className={`flex items-center gap-2 px-3 py-2 rounded-xl border transition-all text-[10px] font-black uppercase tracking-widest cursor-pointer ${
              theme === 'dark' ? 'border-white/10 hover:border-blue-500/50 text-slate-300 hover:text-white' : 'border-slate-200 hover:border-blue-500/30 text-slate-600 hover:text-slate-900 bg-white shadow-sm'
            }`}
          >
            <Globe className="w-3.5 h-3.5 text-blue-400" />
            {lang}
          </button>

          <button
            onClick={onLoginClick}
            className={`text-xs font-bold transition-colors ${
              theme === 'dark' ? 'text-slate-400 hover:text-white' : 'text-slate-500 hover:text-slate-900'
            }`}
          >
            {translate('hero.login')}
          </button>
          <button
            onClick={onStartTrading}
            className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-black text-xs uppercase tracking-widest transition-all shadow-[0_0_20px_rgba(59,130,246,0.3)]"
          >
            {translate('hero.trial')}
          </button>
        </div>
      </nav>

      {/* Background Effects */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className={`absolute top-[-20%] left-1/2 -translate-x-1/2 w-[80vw] h-[80vw] max-w-[1000px] max-h-[1000px] blur-[120px] rounded-full opacity-60 transition-colors duration-1000 ${
          theme === 'dark' ? 'bg-blue-600/10' : 'bg-blue-400/20'
        }`} />
        
        {/* Dynamic Star Field - only visible in dark mode or subtle in light mode */}
        <AnimatePresence>
          {theme === 'dark' && stars.map((star) => (
            <motion.div
              key={star.id}
              initial={{ opacity: 0 }}
              animate={{ 
                opacity: [star.opacity * 0.5, star.opacity, star.opacity * 0.5],
                scale: [0.8, 1.1, 0.8]
              }}
              exit={{ opacity: 0 }}
              transition={{
                duration: star.duration,
                repeat: Infinity,
                delay: star.delay,
                ease: "easeInOut"
              }}
              className={`absolute rounded-full ${star.color} shadow-[0_0_8px_rgba(255,255,255,0.3)]`}
              style={{
                top: star.top,
                left: star.left,
                width: `${star.size}px`,
                height: `${star.size}px`,
              }}
            />
          ))}
        </AnimatePresence>
      </div>

      {/* Hero Content */}
      <div className="relative z-10 flex-1 flex flex-col items-center justify-center pt-20 pb-32 px-6">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-full border backdrop-blur-md mb-8 transition-all duration-500 ${
            theme === 'dark' ? 'border-blue-500/20 bg-blue-950/20' : 'border-blue-200 bg-blue-50/50'
          }`}
        >
          <Sparkles className="w-3.5 h-3.5 text-blue-400" />
          <span className={`text-[10px] font-black uppercase tracking-widest ${
            theme === 'dark' ? 'text-blue-200' : 'text-blue-600'
          }`}>
            {translate('hero.ai_integration')}
          </span>
          <div className={`w-12 h-[2px] ml-2 rounded-full overflow-hidden ${
            theme === 'dark' ? 'bg-blue-500/20' : 'bg-blue-200'
          }`}>
             <motion.div 
               animate={{ x: [-48, 48] }}
               transition={{ duration: 1.5, repeat: Infinity }}
               className="w-full h-full bg-blue-400" 
             />
          </div>
        </motion.div>

        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className={`text-5xl md:text-8xl font-black text-center tracking-tighter max-w-6xl leading-[0.9] uppercase transition-colors duration-500 ${
            theme === 'dark' ? 'text-white' : 'text-slate-900'
          }`}
        >
          {lang === 'en' ? (
            <>
              {translate('hero.title_part1')} <br />
              {translate('hero.title_part2')} <br />
              {translate('hero.title_part3')}{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-b from-blue-400 to-indigo-600">
                {translate('hero.title_accent')}
              </span>
            </>
          ) : (
            <>
              {translate('hero.title_part1')} <br />
              {translate('hero.title_part2')} <br />
              {translate('hero.title_part3')}{' '}
              <span className="text-transparent bg-clip-text bg-gradient-to-b from-blue-400 to-indigo-600">
                {translate('hero.title_accent')}
              </span>
            </>
          )}
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className={`text-base md:text-lg text-center max-w-2xl mt-8 leading-relaxed font-medium transition-colors duration-500 ${
            theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
          }`}
        >
          {translate('hero.description')}
        </motion.p>

        {/* AI SEARCH BOX */}
        <motion.div
           initial={{ opacity: 0, y: 20 }}
           animate={{ opacity: 1, y: 0 }}
           transition={{ delay: 0.3 }}
           className="w-full max-w-lg mt-12 group"
        >
          <form 
            onSubmit={handleSearchSubmit}
            className={`relative flex items-center p-1 rounded-[1.5rem] border transition-all duration-300 backdrop-blur-2xl ${
              searchFocused 
                ? (theme === 'dark' ? 'border-blue-500/50 bg-blue-950/20 shadow-[0_0_40px_rgba(59,130,246,0.1)]' : 'border-blue-500/40 bg-white shadow-xl shadow-blue-500/10') 
                : (theme === 'dark' ? 'border-white/5 bg-white/5' : 'border-slate-200 bg-white shadow-sm')
            }`}
          >
            <div className="absolute left-6 text-blue-400">
              {searchFocused ? <MessageSquare className="w-5 h-5 animate-pulse" /> : <Search className="w-5 h-5 opacity-50" />}
            </div>
            <input 
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={translate('hero.search_placeholder')}
              onFocus={() => setSearchFocused(true)}
              onBlur={() => setSearchFocused(false)}
              className={`w-full bg-transparent border-none focus:outline-none pl-14 pr-6 py-4 text-sm font-bold transition-colors ${
                theme === 'dark' ? 'text-white placeholder:text-slate-600' : 'text-slate-900 placeholder:text-slate-400'
              }`}
            />
            <div className="pr-2">
              <button 
                type="submit"
                className="px-5 py-3 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white transition-all shadow-lg active:scale-95"
              >
                <ChevronRight className="w-5 h-5" />
              </button>
            </div>
          </form>
          <div className="flex justify-center gap-4 mt-4 overflow-x-auto pb-2 scrollbar-hide">
            {['BTC Trend', 'SOL Alpha', 'Whale Movements'].map(tag => (
              <button 
                key={tag} 
                onClick={() => {
                  setQuery(tag);
                  onSearch(tag);
                }}
                className={`px-3 py-1.5 rounded-full border transition-all uppercase tracking-widest whitespace-nowrap active:scale-95 text-[9px] font-black ${
                  theme === 'dark' ? 'border-white/5 bg-white/5 text-slate-500 hover:text-blue-400 hover:border-blue-500/30' : 'border-slate-200 bg-white text-slate-400 hover:text-blue-600 hover:border-blue-200 shadow-sm'
                }`}
              >
                #{tag}
              </button>
            ))}
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.4 }}
          className={`flex flex-wrap justify-center gap-8 mt-16 text-[10px] font-black uppercase tracking-[0.2em] transition-colors duration-500 ${
            theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
          }`}
        >
          {badges.map((badge, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="w-1 h-1 bg-blue-500 rounded-full" /> {badge}
            </div>
          ))}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5 }}
          className="flex flex-col md:flex-row items-center justify-center gap-4 mt-12 w-full max-w-sm"
        >
          <button 
            onClick={onStartTrading}
            className="w-full px-10 py-4 rounded-2xl bg-blue-600 hover:bg-blue-500 text-white font-black text-xs uppercase tracking-widest transition-all shadow-xl shadow-blue-600/30 flex items-center justify-center gap-3 group"
          >
             {translate('hero.start_trading')} <ChevronRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </button>
          <button
            onClick={onLoginClick}
            className={`w-full px-10 py-4 rounded-2xl border font-black text-xs uppercase tracking-widest transition-all flex items-center justify-center gap-3 backdrop-blur-sm ${
              theme === 'dark' ? 'border-white/10 bg-white/5 hover:bg-white/10 text-white' : 'border-slate-200 bg-white hover:bg-slate-50 text-slate-700 shadow-sm'
            }`}
          >
            {translate('hero.try_demo')}
          </button>
        </motion.div>
      </div>
    </div>
  );
};
