import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BellRing, Plus, X, CheckCircle2, Trash2, Bell } from 'lucide-react';

interface Alert {
  id: string;
  symbol: string;
  condition: 'above' | 'below';
  price: number;
  enabled: boolean;
  triggered: boolean;
}

interface AlertToast {
  id: string;
  message: string;
}

const STORAGE_KEY = 'cs_price_alerts';

const loadAlerts = (): Alert[] => {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'); }
  catch { return []; }
};

const saveAlerts = (alerts: Alert[]) => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(alerts));
};

interface Props {
  currentPrices: Record<string, number>;
  onToast: (msg: string) => void;
}

export const AlertManager = ({ currentPrices, onToast }: Props) => {
  const [alerts, setAlerts] = useState<Alert[]>(loadAlerts);
  const [open, setOpen] = useState(false);
  const [newSymbol, setNewSymbol] = useState('BTCUSDT');
  const [newCondition, setNewCondition] = useState<'above' | 'below'>('above');
  const [newPrice, setNewPrice] = useState('');

  // Check alerts on each price update
  useEffect(() => {
    setAlerts(prev => {
      const updated = prev.map(alert => {
        if (alert.triggered || !alert.enabled) return alert;
        const current = currentPrices[alert.symbol];
        if (!current) return alert;
        const fired =
          (alert.condition === 'above' && current >= alert.price) ||
          (alert.condition === 'below' && current <= alert.price);
        if (fired) {
          const msg = `🔔 ${alert.symbol} is now ${alert.condition === 'above' ? 'above' : 'below'} $${alert.price.toLocaleString()} (Current: $${current.toLocaleString()})`;
          onToast(msg);
          // Browser notification
          if (Notification.permission === 'granted') {
            new Notification('CryptoStream Alert', { body: msg, icon: '/favicon.ico' });
          }
          return { ...alert, triggered: true };
        }
        return alert;
      });
      saveAlerts(updated);
      return updated;
    });
  }, [currentPrices, onToast]);

  const addAlert = () => {
    const price = parseFloat(newPrice);
    if (!newPrice || isNaN(price) || price <= 0) return;
    // Request notification permission
    if (Notification.permission === 'default') {
      Notification.requestPermission();
    }
    const alert: Alert = {
      id: Date.now().toString(),
      symbol: newSymbol,
      condition: newCondition,
      price,
      enabled: true,
      triggered: false,
    };
    const updated = [...alerts, alert];
    setAlerts(updated);
    saveAlerts(updated);
    setNewPrice('');
  };

  const deleteAlert = (id: string) => {
    const updated = alerts.filter(a => a.id !== id);
    setAlerts(updated);
    saveAlerts(updated);
  };

  const resetAlert = (id: string) => {
    const updated = alerts.map(a => a.id === id ? { ...a, triggered: false } : a);
    setAlerts(updated);
    saveAlerts(updated);
  };

  const activeCount = alerts.filter(a => a.enabled && !a.triggered).length;

  return (
    <>
      {/* Bell trigger */}
      <button
        onClick={() => setOpen(o => !o)}
        className="relative flex items-center gap-2 px-3 py-1.5 rounded-xl border border-white/10 hover:border-amber-500/30 bg-slate-900/50 hover:bg-amber-500/5 transition-all"
      >
        <BellRing className="w-3.5 h-3.5 text-slate-400" />
        {activeCount > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-amber-500 rounded-full text-[8px] font-black text-black flex items-center justify-center">
            {activeCount}
          </span>
        )}
      </button>

      {/* Alert panel */}
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-[998]"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: -10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: -10 }}
              transition={{ type: 'spring', stiffness: 500, damping: 35 }}
              className="absolute top-12 right-4 z-[999] w-80 bg-slate-900/95 backdrop-blur-3xl border border-white/10 rounded-[1.5rem] shadow-2xl shadow-black/60 overflow-hidden"
            >
              <div className="p-5 border-b border-white/5">
                <div className="flex items-center gap-2 mb-4">
                  <Bell className="w-4 h-4 text-amber-400" />
                  <h3 className="text-sm font-black text-white">Price Alerts</h3>
                </div>

                {/* Add alert form */}
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <select
                      value={newSymbol}
                      onChange={e => setNewSymbol(e.target.value)}
                      className="bg-slate-800 border border-white/10 rounded-xl px-3 py-2 text-xs text-white font-bold focus:outline-none focus:ring-1 focus:ring-amber-500/40"
                    >
                      {['BTCUSDT','ETHUSDT','SOLUSDT','BNBUSDT','XRPUSDT'].map(s => (
                        <option key={s} value={s}>{s.replace('USDT','')}</option>
                      ))}
                    </select>
                    <select
                      value={newCondition}
                      onChange={e => setNewCondition(e.target.value as 'above' | 'below')}
                      className="bg-slate-800 border border-white/10 rounded-xl px-3 py-2 text-xs text-white font-bold focus:outline-none focus:ring-1 focus:ring-amber-500/40"
                    >
                      <option value="above">Above ≥</option>
                      <option value="below">Below ≤</option>
                    </select>
                  </div>
                  <div className="flex gap-2">
                    <input
                      type="number"
                      value={newPrice}
                      onChange={e => setNewPrice(e.target.value)}
                      placeholder="Target price (USD)"
                      className="flex-1 bg-slate-800 border border-white/10 rounded-xl px-3 py-2 text-xs text-white font-mono font-bold placeholder:text-slate-600 focus:outline-none focus:ring-1 focus:ring-amber-500/40"
                    />
                    <button
                      onClick={addAlert}
                      disabled={!newPrice}
                      className="p-2 bg-amber-500/20 border border-amber-500/30 hover:bg-amber-500/30 text-amber-400 rounded-xl transition-all disabled:opacity-30"
                    >
                      <Plus className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>

              {/* Alert list */}
              <div className="p-3 max-h-52 overflow-y-auto custom-scrollbar space-y-2">
                {alerts.length === 0 ? (
                  <p className="text-center text-[10px] text-slate-600 font-bold uppercase tracking-widest py-4">No alerts set</p>
                ) : alerts.map(alert => (
                  <div
                    key={alert.id}
                    className={`flex items-center gap-2 p-3 rounded-xl border ${
                      alert.triggered ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-white/5 bg-slate-900/50'
                    }`}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-[10px] font-black text-slate-200 truncate">
                        {alert.symbol.replace('USDT','')} {alert.condition === 'above' ? '≥' : '≤'} ${alert.price.toLocaleString()}
                      </p>
                      <p className={`text-[9px] font-bold uppercase tracking-widest mt-0.5 ${alert.triggered ? 'text-emerald-400' : 'text-slate-600'}`}>
                        {alert.triggered ? '✅ Triggered' : '⏳ Watching'}
                      </p>
                    </div>
                    <div className="flex gap-1.5">
                      {alert.triggered && (
                        <button onClick={() => resetAlert(alert.id)} className="p-1 hover:text-amber-400 text-slate-600 transition-colors">
                          <CheckCircle2 className="w-3.5 h-3.5" />
                        </button>
                      )}
                      <button onClick={() => deleteAlert(alert.id)} className="p-1 hover:text-rose-400 text-slate-600 transition-colors">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
};
