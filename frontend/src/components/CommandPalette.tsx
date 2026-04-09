import { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, TrendingUp, BarChart3, MessageSquare, Shield, Brain, HelpCircle, RefreshCcw, Download } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

interface CommandItem {
  id: string;
  label: string;
  sublabel?: string;
  icon: any;
  action: () => void;
  category: string;
  keywords: string[];
}

interface Props {
  open: boolean;
  onClose: () => void;
  onNavigate: (tab: string) => void;
}

export const CommandPalette = ({ open, onClose, onNavigate }: Props) => {
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const { isInstitutional } = useMode();

  const COMMANDS: CommandItem[] = [
    { id: 'trends', label: 'Market Trends', sublabel: 'Real-time price feed', icon: TrendingUp, category: 'Navigation', keywords: ['market', 'price', 'trend', 'btc', 'eth'], action: () => { onNavigate('Market Trends'); onClose(); } },
    { id: 'intelligence', label: 'Intelligence Hub', sublabel: 'AI signals & regime detection', icon: Brain, category: 'Navigation', keywords: ['ai', 'signal', 'intelligence', 'regime', 'buy', 'sell'], action: () => { onNavigate('Intelligence Hub'); onClose(); } },
    { id: 'whale', label: 'Whale Tracker', sublabel: 'Institutional flow monitor', icon: BarChart3, category: 'Navigation', keywords: ['whale', 'flow', 'institutional', 'large', 'order'], action: () => { onNavigate('Whale Tracker'); onClose(); } },
    { id: 'risk', label: 'Risk Audits', sublabel: 'Pipeline health & DQ metrics', icon: Shield, category: 'Navigation', keywords: ['risk', 'audit', 'health', 'pipeline', 'dq'], action: () => { onNavigate('Risk Audits'); onClose(); } },
    { id: 'chat', label: 'Strategy Chat', sublabel: 'Ask AI anything about the market', icon: MessageSquare, category: 'Navigation', keywords: ['chat', 'ask', 'ai', 'gemini', 'strategy', 'query'], action: () => { onNavigate('Strategy Chat'); onClose(); } },
    { id: 'refresh', label: 'Refresh Signal Feed', sublabel: 'Re-fetch /api/signals', icon: RefreshCcw, category: 'Action', keywords: ['refresh', 'reload', 'signal', 'fetch'], action: () => { window.location.reload(); onClose(); } },
    { id: 'export', label: 'Export Whale Data (CSV)', sublabel: 'Download current whale transactions', icon: Download, category: 'Action', keywords: ['export', 'csv', 'download', 'whale', 'data'], action: () => {
      const link = document.createElement('a');
      link.href = '/api/data/whales?format=csv';
      link.download = `whale_data_${Date.now()}.csv`;
      link.click();
      onClose();
    }},
  ];

  const filtered = query.trim()
    ? COMMANDS.filter(c =>
        c.label.toLowerCase().includes(query.toLowerCase()) ||
        c.keywords.some(k => k.includes(query.toLowerCase()))
      )
    : COMMANDS;

  useEffect(() => {
    if (open) {
      setQuery('');
      setSelected(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => { setSelected(0); }, [query]);

  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowDown') setSelected(s => Math.min(s + 1, filtered.length - 1));
      if (e.key === 'ArrowUp') setSelected(s => Math.max(s - 1, 0));
      if (e.key === 'Enter' && filtered[selected]) filtered[selected].action();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, filtered, selected, onClose]);

  if (!isInstitutional) return null;

  const grouped = filtered.reduce((acc, cmd) => {
    acc[cmd.category] = [...(acc[cmd.category] || []), cmd];
    return acc;
  }, {} as Record<string, CommandItem[]>);

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/70 backdrop-blur-md z-[9998]"
          />

          {/* Palette */}
          <motion.div
            initial={{ opacity: 0, scale: 0.94, y: -20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -10 }}
            transition={{ type: 'spring', stiffness: 500, damping: 35 }}
            className="fixed top-[20%] left-1/2 -translate-x-1/2 z-[9999] w-full max-w-lg"
          >
            <div className="bg-slate-900/95 backdrop-blur-3xl border border-white/10 rounded-[1.5rem] shadow-2xl shadow-black/60 overflow-hidden">
              {/* Search input */}
              <div className="flex items-center gap-4 px-5 py-4 border-b border-white/5">
                <Search className="w-4 h-4 text-slate-400 shrink-0" />
                <input
                  ref={inputRef}
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Search commands..."
                  className="flex-1 bg-transparent text-sm text-white placeholder:text-slate-500 font-bold focus:outline-none"
                />
                <kbd className="text-[9px] text-slate-600 font-black border border-slate-700 rounded px-1.5 py-0.5">ESC</kbd>
              </div>

              {/* Results */}
              <div className="max-h-80 overflow-y-auto py-2 custom-scrollbar">
                {filtered.length === 0 ? (
                  <div className="flex flex-col items-center gap-2 py-10">
                    <HelpCircle className="w-6 h-6 text-slate-600" />
                    <p className="text-[11px] text-slate-500 font-bold uppercase tracking-widest">No commands found</p>
                  </div>
                ) : (
                  Object.entries(grouped).map(([cat, items]) => (
                    <div key={cat}>
                      <p className="px-4 py-2 text-[9px] font-black text-slate-600 uppercase tracking-widest">{cat}</p>
                      {items.map((cmd) => {
                        const Icon = cmd.icon;
                        const globalIdx = filtered.indexOf(cmd);
                        const isSelected = globalIdx === selected;
                        return (
                          <button
                            key={cmd.id}
                            onClick={cmd.action}
                            onMouseEnter={() => setSelected(globalIdx)}
                            className={`w-full flex items-center gap-3 px-4 py-3 transition-all text-left ${
                              isSelected ? 'bg-blue-600/15 text-white' : 'text-slate-300 hover:bg-white/5'
                            }`}
                          >
                            <div className={`p-1.5 rounded-lg border ${isSelected ? 'bg-blue-600/20 border-blue-500/30' : 'bg-slate-800 border-white/5'}`}>
                              <Icon className={`w-3.5 h-3.5 ${isSelected ? 'text-blue-400' : 'text-slate-400'}`} />
                            </div>
                            <div className="flex-1">
                              <p className="text-[12px] font-black">{cmd.label}</p>
                              {cmd.sublabel && <p className="text-[10px] text-slate-500 font-medium">{cmd.sublabel}</p>}
                            </div>
                            {isSelected && (
                              <kbd className="text-[9px] text-blue-400 font-black border border-blue-500/30 rounded px-1.5 py-0.5">↵</kbd>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  ))
                )}
              </div>

              {/* Footer */}
              <div className="px-4 py-3 border-t border-white/5 flex items-center gap-4">
                <div className="flex items-center gap-1.5">
                  <kbd className="text-[9px] text-slate-600 font-black border border-slate-700 rounded px-1 py-0.5">↑↓</kbd>
                  <span className="text-[9px] text-slate-600 font-bold">Navigate</span>
                </div>
                <div className="flex items-center gap-1.5">
                  <kbd className="text-[9px] text-slate-600 font-black border border-slate-700 rounded px-1 py-0.5">↵</kbd>
                  <span className="text-[9px] text-slate-600 font-bold">Select</span>
                </div>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};
