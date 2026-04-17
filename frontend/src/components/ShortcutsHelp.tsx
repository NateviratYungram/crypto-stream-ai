import { motion, AnimatePresence } from 'framer-motion';
import { X, Keyboard } from 'lucide-react';

interface ShortcutsHelpProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS = [
  { group: 'Navigation', items: [
    { key: 'Ctrl + K',  desc: 'Command Palette' },
    { key: '?',         desc: 'Show this help' },
    { key: 'Esc',       desc: 'Close any modal' },
  ]},
  { group: 'Quick Jump', items: [
    { key: 'G + T',     desc: 'Go to Market Trends' },
    { key: 'G + C',     desc: 'Go to Strategy Chat' },
    { key: 'G + W',     desc: 'Go to Whale Tracker' },
    { key: 'G + S',     desc: 'Go to Screener' },
    { key: 'G + J',     desc: 'Go to Trading Journal' },
    { key: 'G + F',     desc: 'Go to Funding Rates' },
    { key: 'G + E',     desc: 'Go to ETF Flows' },
    { key: 'G + L',     desc: 'Go to Watchlist' },
    { key: 'G + P',     desc: 'Go to AI Persona' },
  ]},
  { group: 'Quick Symbols (in Chat)', items: [
    { key: '/btc',      desc: 'Analyze BTC instantly' },
    { key: '/eth',      desc: 'Analyze ETH instantly' },
    { key: '/gold',     desc: 'Analyze GOLD instantly' },
    { key: '/nvda',     desc: 'Analyze NVDA instantly' },
    { key: '/scan',     desc: 'Open Custom Screener' },
    { key: '/funding',  desc: 'Show Funding Rates' },
    { key: '/whale',    desc: 'Show Whale Tracker' },
    { key: '/report',   desc: 'Generate Weekly Report' },
  ]},
];

export const ShortcutsHelp = ({ open, onClose }: ShortcutsHelpProps) => (
  <AnimatePresence>
    {open && (
      <>
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 bg-black/70 backdrop-blur-sm z-[9990]"
        />
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 20 }}
          transition={{ type: 'spring', damping: 25 }}
          className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[9991] w-full max-w-2xl max-h-[80vh] overflow-y-auto bg-slate-900/95 backdrop-blur-3xl border border-white/10 rounded-[2rem] shadow-2xl p-8"
        >
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-blue-600/20 border border-blue-500/30 rounded-xl flex items-center justify-center">
                <Keyboard className="w-4 h-4 text-blue-400" />
              </div>
              <div>
                <h2 className="text-lg font-black text-white">Keyboard Shortcuts</h2>
                <p className="text-xs text-slate-500 font-bold uppercase tracking-widest">Tactical Terminal</p>
              </div>
            </div>
            <button onClick={onClose} className="p-2 text-slate-500 hover:text-white transition-colors rounded-xl hover:bg-white/5">
              <X className="w-5 h-5" />
            </button>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {SHORTCUTS.map(group => (
              <div key={group.group} className="space-y-3">
                <p className="text-[11px] font-black text-slate-500 uppercase tracking-widest">{group.group}</p>
                <div className="space-y-2">
                  {group.items.map(s => (
                    <div key={s.key} className="flex items-center justify-between gap-4">
                      <span className="text-sm text-slate-400 font-bold">{s.desc}</span>
                      <kbd className="px-2.5 py-1 bg-slate-800 border border-white/10 rounded-lg text-[11px] font-black text-slate-300 font-mono whitespace-nowrap shrink-0">
                        {s.key}
                      </kbd>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 pt-6 border-t border-white/5 text-center">
            <p className="text-xs text-slate-600 font-bold">กด <kbd className="px-1.5 py-0.5 bg-slate-800 rounded text-[10px] border border-white/10">Esc</kbd> หรือ click นอกกรอบเพื่อปิด</p>
          </div>
        </motion.div>
      </>
    )}
  </AnimatePresence>
);
