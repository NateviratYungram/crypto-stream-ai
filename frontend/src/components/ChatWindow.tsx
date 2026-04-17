import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Terminal, Sparkles, User, ChevronDown, ChevronUp, Database, Zap, Brain, TrendingUp, Activity, ShieldCheck, Plus, Trash2, AlertCircle, Circle, CheckCircle } from 'lucide-react';
import { marked, Renderer } from 'marked';

// Custom renderer: code blocks get a copy button + special style for trade confirmations
const _renderer = new Renderer();
_renderer.code = ({ text, lang }: { text: string; lang?: string }) => {
  const isConfirm = text.trim().startsWith('ยืนยัน ');
  const escaped = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  if (isConfirm) {
    return `<div class="confirm-block">
      <span class="confirm-label">คำสั่งยืนยัน — คัดลอกแล้วส่งในแชท</span>
      <div class="confirm-inner">
        <code class="confirm-code">${escaped}</code>
        <button class="confirm-copy-btn" onclick="navigator.clipboard.writeText('${text.trim()}').then(()=>{this.textContent='✓ Copied!';setTimeout(()=>{this.textContent='Copy'},1500)})">Copy</button>
      </div>
    </div>`;
  }
  return `<div class="code-block-wrap">
    <button class="code-copy-btn" onclick="navigator.clipboard.writeText(this.closest('.code-block-wrap').querySelector('code').innerText).then(()=>{this.textContent='✓';setTimeout(()=>{this.textContent='⎘'},1500)})">⎘</button>
    <pre><code class="language-${lang||''}">${escaped}</code></pre>
  </div>`;
};
marked.use({ renderer: _renderer });
import { HoverGlowCard } from './HoverGlowCard';
import { useMode } from '../contexts/ModeContext';
import TradingViewWidget from './TradingViewWidget';

interface PulseData {
  sentiment: { fear_greed: number; crypto_fg: number; label: string };
  leadership: { top_sector: string; top_sector_chg: number; summary: string };
  climate: { 
    score: number; 
    regime: string; 
    threat_level: string; 
    color: string; 
    summary: string;
  };
}

interface MLScore {
  win_pct: number;
  n_samples: number;
  roc_auc: number;
  side: string;
  symbol: string;
}

interface Message {
  role: 'user' | 'ai';
  content: string;
  sql?: string;
  chart?: string;
  tvSymbol?: string;
  intent?: 'GENERAL' | 'ANALYZE';
  streaming?: boolean;
  status?: string;
  mlScore?: MLScore;
  toolCalls?: { name: string; args: any; symbol?: string }[];
  toolResults?: { tool: string; content: any }[];
}

interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

const HISTORY_KEY = 'skip_delete_confirmation';

const STORAGE_KEY = 'cs_chat_sessions_v2';

const loadSessions = (): ChatSession[] => {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed) || parsed.length === 0) {
      return [{ id: 'default', title: 'Strategy Briefing', messages: [], updatedAt: Date.now() }];
    }
    return parsed;
  } catch { 
    return [{ id: 'default', title: 'Strategy Briefing', messages: [], updatedAt: Date.now() }]; 
  }
};

interface ChatWindowProps {
  initialMessage?: string;
  onClearInitialMessage?: () => void;
}

export const ChatWindow: React.FC<ChatWindowProps> = ({ initialMessage, onClearInitialMessage }) => {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeId, setActiveId] = useState<string>('default');
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [pulse, setPulse] = useState<PulseData | null>(null);
  
  // Smart Deletion State
  const [showDeleteModal, setShowDeleteModal] = useState<string | null>(null);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);

  const activeSession = sessions.find(s => s.id === activeId) || sessions[0];
  const messages = activeSession?.messages || [];

  const scrollRef = useRef<HTMLDivElement>(null);
  const { isRetail } = useMode();
  const hasTriggeredInitial = useRef(false);

  useEffect(() => {
    // Initial Pulse Load
    const fetchPulse = async () => {
      try {
        const res = await fetch('/api/market/pulse');
        if (res.ok) {
          const data = await res.json();
          if (data?.climate && data?.sentiment && data?.leadership) {
            setPulse(data);
          }
        }
      } catch (e) { console.error('Pulse error:', e); }
    };
    fetchPulse();
    const timer = setInterval(fetchPulse, 60000); // 1 min update
    return () => clearInterval(timer);
  }, []);

  // Proactive trigger removed — let user start the conversation naturally

  useEffect(() => {
    const freshId = Date.now().toString();

    // If launched with an initial message (e.g. from Watchlist), spin up a
    // fresh session immediately so sendMessage has a valid activeId without
    // waiting for the server history fetch.
    if (initialMessage) {
      setSessions([{ id: freshId, title: 'Strategy Briefing', messages: [], updatedAt: Date.now() }]);
      setActiveId(freshId);
      setIsInitialized(true);
      return;
    }

    const initHistory = async () => {
      try {
        const authKey = localStorage.getItem('APP_API_KEY') || 'demo';
        const res = await fetch('/api/history', {
          headers: { 'X-API-Key': authKey }
        });
        if (res.ok) {
          const serverSessions = await res.json();
          if (serverSessions.length > 0) {
            const firstSess = serverSessions[0];
            const msgRes = await fetch(`/api/history/${firstSess.id}`, {
              headers: { 'X-API-Key': authKey }
            });
            const msgs = msgRes.ok ? await msgRes.json() : [];
            const fullSessions = serverSessions.map((s: any, i: number) => ({
              ...s,
              messages: i === 0 ? msgs : [],
              updatedAt: new Date(s.updatedAt).getTime()
            }));
            setSessions(fullSessions);
            setActiveId(fullSessions[0].id);
          } else {
            const defId = Date.now().toString();
            setSessions([{ id: defId, title: 'Strategy Briefing', messages: [], updatedAt: Date.now() }]);
            setActiveId(defId);
          }
        }
      } catch (e) {
        console.error("History sync error:", e);
        setSessions([{ id: 'default', title: 'Strategy Briefing', messages: [], updatedAt: Date.now() }]);
      } finally {
        setIsInitialized(true);
      }
    };
    initHistory();
  }, []);

  useEffect(() => {
    if (initialMessage && !hasTriggeredInitial.current && isInitialized) {
      hasTriggeredInitial.current = true;
      sendMessage(initialMessage);
      onClearInitialMessage?.();
    }
  }, [initialMessage, isInitialized]);

  const syncSessionToServer = async (sess: ChatSession) => {
    try {
      const authKey = localStorage.getItem('APP_API_KEY') || 'demo';
      await fetch('/api/history', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-API-Key': authKey
        },
        body: JSON.stringify(sess)
      });
    } catch (e) { console.error("Sync failed:", e); }
  };

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
  }, [sessions]);

  const updateActiveSession = (updater: (msgs: Message[]) => Message[]) => {
    setSessions(prev => {
      const newSess = prev.map(s => {
        if (s.id !== activeId) return s;
        const newMsgs = updater(s.messages);
        let newTitle = s.title;
        if (s.title === 'Strategy Briefing' && newMsgs.length > 0) {
          const firstUser = newMsgs.find(m => m.role === 'user');
          if (firstUser) {
            newTitle = firstUser.content.substring(0, 30) + (firstUser.content.length > 30 ? '...' : '');
          }
        }
        const updated = { ...s, messages: newMsgs, title: newTitle, updatedAt: Date.now() };
        // Background sync to server
        syncSessionToServer(updated);
        return updated;
      });
      return newSess;
    });
  };

  const createNewChat = () => {
    const newId = Date.now().toString();
    const newSess: ChatSession = {
      id: newId,
      title: 'Strategy Briefing',
      messages: [],
      updatedAt: Date.now()
    };
    setSessions(prev => [newSess, ...prev]);
    setActiveId(newId);
    syncSessionToServer(newSess);
  };

  const switchSession = async (id: string) => {
    if (id === activeId) return;
    const target = sessions.find(s => s.id === id);
    if (target && target.messages.length === 0) {
      // Lazy load messages
      try {
        const authKey = localStorage.getItem('APP_API_KEY') || 'demo';
        const res = await fetch(`/api/history/${id}`, {
          headers: { 'X-API-Key': authKey }
        });
        const msgs = res.ok ? await res.json() : [];
        setSessions(prev => prev.map(s => s.id === id ? { ...s, messages: msgs } : s));
      } catch (e) { console.error("Load failed:", e); }
    }
    setActiveId(id);
  };

  const handleDeleteClick = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    const skip = localStorage.getItem(HISTORY_KEY) === 'true';
    if (skip) {
      confirmDelete(id);
    } else {
      setShowDeleteModal(id);
    }
  };

  const confirmDelete = async (id: string) => {
    try {
      const authKey = localStorage.getItem('APP_API_KEY') || 'demo';
      await fetch(`/api/history/${id}`, { 
        method: 'DELETE',
        headers: { 'X-API-Key': authKey }
      });
      
      let nextId: string | null = null;
      setSessions(prev => {
        const remaining = prev.filter(s => s.id !== id);
        
        // If we deleted the active one, decide what to switch to
        if (activeId === id) {
          nextId = remaining.length > 0 ? remaining[0].id : null;
        }

        if (remaining.length === 0) {
          const newId = Date.now().toString();
          const def = { id: newId, title: 'Strategy Briefing', messages: [], updatedAt: Date.now() };
          syncSessionToServer(def);
          nextId = newId;
          return [def];
        }
        return remaining;
      });

      if (nextId) {
        setActiveId(nextId);
      }
      
      if (dontShowAgain) {
        localStorage.setItem(HISTORY_KEY, 'true');
      }
      setShowDeleteModal(null);
    } catch (e) { console.error("Delete failed:", e); }
  };

  const handleSend = () => sendMessage(input);

  const sendMessage = async (userMsg: string) => {
    if (!userMsg.trim() || loading) return;

    updateActiveSession(prev => [...prev, { role: 'user', content: userMsg.trim() }]);
    setInput('');
    setLoading(true);

    // Retrieve Auth Key from LocalStorage (Resolved 403)
    const authKey = localStorage.getItem('crypto_terminal_key') || '';

    updateActiveSession(prev => [...prev, { role: 'ai', content: '', streaming: true, toolCalls: [], toolResults: [] }]);

    const abortController = new AbortController();
    const streamTimeout = setTimeout(() => abortController.abort(), 60_000);

    try {
      // Build conversation history (last 25 messages for deep memory)
      const historyToSend = messages
        .filter(m => !m.streaming)
        .slice(-25)
        .map(m => ({
          role: m.role,
          content: String(m.content || '').substring(0, 1000),
          tool_calls: m.toolCalls,
          tool_results: m.toolResults
        }));
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': authKey
        },
        body: JSON.stringify({ message: userMsg, session_id: activeId, history: historyToSend }),
        signal: abortController.signal,
      });

      if (res.status === 403) {
        throw new Error("Access Denied: Invalid Institutional Key");
      }
      if (res.status === 429) {
        throw new Error("⏱️ Rate limit reached — please wait a moment before sending another message.");
      }
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      if (!res.body) throw new Error("No response body from intelligence enclave");

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      
      let fullText = '';
      let sqlQuery = undefined;
      let chartData = undefined;
      let tvSymbolData = undefined;
      let tvSymbolsData: string[] = [];
      let intentData: 'GENERAL' | 'ANALYZE' = 'GENERAL';
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        buffer += chunk;

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.trim() === '') continue;
          try {
            const data = JSON.parse(line);
            if (data.type === 'metadata') {
              sqlQuery = data.sql_query;
              if (data.tv_symbol) tvSymbolData = data.tv_symbol;
              if (data.tv_symbols) tvSymbolsData = data.tv_symbols;
              if (data.intent) intentData = data.intent;
            } else if (data.type === 'status') {
              updateActiveSession(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming ? { ...m, status: data.content } : m
              ));
            } else if (data.type === 'tool_call') {
              updateActiveSession(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming
                  ? { ...m, toolCalls: [...(m.toolCalls || []), { name: data.tool, args: data.args || {}, symbol: data.symbol }] }
                  : m
                ));
            } else if (data.type === 'tool_result') {
              updateActiveSession(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming
                  ? { ...m, toolResults: [...(m.toolResults || []), { tool: data.tool, content: data.content }] }
                  : m
                ));
            } else if (data.type === 'ml_score') {
              updateActiveSession(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming
                  ? { ...m, mlScore: { win_pct: data.win_pct, n_samples: data.n_samples, roc_auc: data.roc_auc, side: data.side, symbol: data.symbol } }
                  : m
              ));
            } else if (data.type === 'chart' && data.content) {
              chartData = data.content;
              updateActiveSession(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming ? { ...m, chart: data.content } : m
              ));
            } else if (data.type === 'chunk' && data.content) {
              fullText += data.content;
              const current = fullText;
              updateActiveSession(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming ? { ...m, content: current } : m
              ));
            }
          } catch (e) {
             console.debug('JSON parse error:', e, line.substring(0, 50));
          }
        }
      }

      // Finalize message state
      updateActiveSession(prev => prev.map((m, idx) =>
        idx === prev.length - 1 && m.streaming
          ? {
              role: 'ai',
              content: fullText || '⚠️ ระบบไม่ได้รับข้อมูลจาก AI — กรุณาลองใหม่อีกครั้ง',
              sql: sqlQuery,
              chart: chartData,
              tvSymbol: tvSymbolData,
              tvSymbols: tvSymbolsData,
              selectedSymbol: tvSymbolData,
              intent: intentData,
              streaming: false
            }
          : m
      ));

    } catch (err) {
      const isAbort = err instanceof DOMException && err.name === 'AbortError';
      updateActiveSession(prev => prev.map((m, idx) =>
        idx === prev.length - 1 && m.streaming
          ? { role: 'ai', content: isAbort ? '⏱️ หมดเวลา — AI ใช้เวลานานเกินไป กรุณาลองใหม่' : `⚠️ SYSTEM ALERT: ${err instanceof Error ? err.message : 'Uplink Failed'}`, streaming: false }
          : m
      ));
    } finally {
      clearTimeout(streamTimeout);
      setLoading(false);
    }
  };

  const quickActions = isRetail 
    ? [
        { label: '📈 Analyze Gold', q: 'ตอนนี้ทองคำแนวโน้มเป็นยังไง?' },
        { label: '🎯 Find Entry', q: 'มีจุดเข้า buy ทองมั้ย?' },
        { label: '🛑 TP/SL Setup', q: 'เข้า buy ทอง ควรตั้ง TP/SL เท่าไหร่?' },
        { label: '📰 Market News', q: 'วันนี้มีข่าวอะไรมีผลกับทอง?' },
        { label: '💰 Risk Calc', q: 'ถ้ามีทุน 1000 ควรเปิด lot เท่าไหร่?' },
      ]
    : [
        { label: 'Analyze Gold', q: 'Analyze current Gold trend and bias' },
        { label: 'Find Entry', q: 'Find potential entry zones for NASDAQ' },
        { label: 'Today Signal', q: 'Are there any trade signals for BTC today?' },
        { label: 'Market News', q: 'High impact news events for this session' },
        { label: 'Risk Calculator', q: 'Calculate lot size for 2% risk on $10k' },
      ];

  return (
    <div className="flex h-full w-full bg-[#030712] overflow-hidden relative">
      {/* Strategic Session Sidebar (Gemini-style) */}
      <AnimatePresence>
        {sidebarOpen && (
          <motion.div 
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 280, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            className="h-full border-r border-white/5 bg-slate-950/40 backdrop-blur-3xl flex flex-col shrink-0"
          >
            <div className="p-4 border-b border-white/5 flex items-center justify-between">
              <span className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">Strategy Vault</span>
              <button 
                onClick={createNewChat}
                className="p-2 bg-blue-600/10 border border-blue-500/20 rounded-xl hover:bg-blue-600/20 transition-all group"
                title="New Strategic Session"
              >
                <Plus className="w-3.5 h-3.5 text-blue-400 group-hover:scale-110 transition-transform" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar">
              {sessions.map(s => (
                <div key={s.id} className="relative group">
                  <button
                    onClick={() => switchSession(s.id)}
                    className={`w-full text-left p-3 rounded-2xl transition-all relative overflow-hidden flex items-center justify-between ${
                      activeId === s.id 
                      ? 'bg-blue-600/10 border border-blue-500/30' 
                      : 'hover:bg-white/5 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${activeId === s.id ? 'bg-blue-400 animate-pulse' : 'bg-slate-600'}`} />
                      <div className="flex flex-col min-w-0">
                        <span className={`text-[11px] font-bold truncate tracking-tight uppercase ${activeId === s.id ? 'text-white' : 'text-slate-400 group-hover:text-slate-300'}`}>
                          {s.title}
                        </span>
                        <span className="text-[8px] font-mono text-slate-600 uppercase">
                          {new Date(s.updatedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                    </div>
                  </button>
                  
                  <button
                    onClick={(e) => handleDeleteClick(e, s.id)}
                    className={`absolute right-2 top-1/2 -translate-y-1/2 p-2 hover:bg-red-500/20 rounded-lg text-slate-600 hover:text-red-400 transition-all opacity-0 group-hover:opacity-100 ${activeId === s.id ? 'bg-blue-900/40' : ''}`}
                    title="Delete Session"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>

                  {activeId === s.id && (
                    <motion.div 
                      layoutId="active-sess"
                      className="absolute inset-0 bg-blue-500/5 -z-10"
                    />
                  )}
                </div>
              ))}
            </div>

            <div className="p-4 border-t border-white/5 bg-black/20">
              <div className="flex items-center gap-3 px-3 py-2 rounded-xl bg-white/5 border border-white/5">
                <Brain className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-[10px] font-black text-slate-400 uppercase tracking-widest">Neural Link Active</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Toggle Sidebar Button */}
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="absolute left-4 top-4 z-[70] p-2.5 bg-slate-900/90 backdrop-blur-md border border-white/20 rounded-xl hover:border-blue-500/50 transition-all group shadow-2xl"
        >
          <Terminal className={`w-4 h-4 text-slate-400 transition-colors ${sidebarOpen ? 'text-blue-400' : 'group-hover:text-blue-400'}`} />
        </button>

        {/* Dynamic Context Marquee (Enhanced) */}
        <AnimatePresence>
          {pulse && (
          <motion.div 
            initial={{ y: -50, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -50, opacity: 0 }}
            className="w-full bg-[#030712]/95 backdrop-blur-3xl border-b border-white/5 h-16 flex items-center justify-between z-50 sticky top-0"
          >
            <div className="flex items-center gap-4 flex-1 h-full overflow-hidden">
              <div className="flex items-center gap-3 shrink-0 bg-slate-950/50 px-4 py-1.5 rounded-xl border border-white/5 shadow-2xl z-20 ml-20">
                <div className={`w-2 h-2 rounded-full animate-pulse bg-${pulse.climate.color}-500 shadow-[0_0_8px_rgba(var(--${pulse.climate.color}-500),0.6)]`} />
                <span className={`text-[10px] font-black uppercase tracking-[0.2em] text-${pulse.climate.color}-400 whitespace-nowrap`}>
                  Threat Level: {pulse.climate.threat_level}
                </span>
              </div>

              <div className="h-4 w-px bg-white/10 shrink-0 z-20" />

              <div className="flex-1 overflow-hidden relative group/marquee z-10 h-full flex items-center [mask-image:linear-gradient(to_right,transparent_0,black_40px,black_calc(100%-40px),transparent_100%)]">
                <div className="flex items-center gap-16 animate-marquee-slow whitespace-nowrap min-w-full">
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Sentiment:</span>
                    <span className={`text-[10px] font-black uppercase tracking-widest ${
                      pulse.sentiment.fear_greed > 60 ? 'text-emerald-400' :
                      pulse.sentiment.fear_greed < 40 ? 'text-rose-400' : 'text-slate-400'
                    }`}>
                      {pulse.sentiment.label} ({pulse.sentiment.fear_greed})
                    </span>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Regime:</span>
                    <span className="text-[10px] font-black text-blue-400 uppercase tracking-widest">
                      {pulse.climate.regime}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Macro Climate:</span>
                    <span className="text-[10px] font-medium text-slate-300 italic">
                      {pulse.climate.summary}
                    </span>
                  </div>

                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Sector Lead:</span>
                    <span className="text-[10px] font-black text-indigo-400 uppercase tracking-widest">
                      {pulse.leadership.top_sector} ({pulse.leadership.top_sector_chg > 0 ? '+' : ''}{pulse.leadership.top_sector_chg}%)
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="hidden lg:flex items-center gap-5 shrink-0">
              <div className="flex flex-col items-end">
                <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest">Global Risk Score</span>
                <span className="text-xs font-mono font-bold text-white tracking-widest">{pulse.climate.score}%</span>
              </div>
              <div className="w-px h-6 bg-white/10" />
              <div className="flex items-center gap-2 px-3 py-1 bg-black/40 border border-white/5 rounded-lg">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                <span className="text-[9px] font-black text-slate-300 uppercase tracking-tighter">Macro Shield Active</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-8 space-y-12 scroll-smooth custom-scrollbar">
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center space-y-8">
            <motion.div 
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="relative"
            >
              <div className="w-24 h-24 bg-blue-600/10 rounded-[2.5rem] flex items-center justify-center border border-blue-500/20 shadow-2xl relative z-10">
                <Database className="w-10 h-10 text-blue-400 glow-bloom" />
              </div>
              <div className="absolute inset-0 bg-blue-500/20 blur-[80px] rounded-full scale-150 -z-10 animate-pulse" />
            </motion.div>
            <div className="space-y-3">
              <h2 className="text-3xl font-black text-white tracking-tighter uppercase italic">
                {isRetail ? 'ถามอะไรก็ได้เกี่ยวกับ Crypto ✨' : 'Query Intelligence Lakehouse'}
              </h2>
              <p className="text-sm text-slate-500 max-w-sm font-medium leading-relaxed">
                {isRetail
                  ? 'พิมพ์คำถามเป็นภาษาไทยหรืออังกฤษก็ได้ AI ของเราวิเคราะห์ข้อมูลแบบ real-time'
                  : 'วิเคราะห์ตลาดด้วย AI — Whale Flow, Signals, และข้อมูล Real-time'}
              </p>
            </div>
            <p className="text-[10px] text-amber-500/60 font-bold uppercase tracking-widest">
              ⚠ AI ให้ข้อมูลเพื่อการศึกษาเท่านั้น — ไม่ใช่คำแนะนำทางการเงิน
            </p>
            <div className="flex flex-wrap items-center justify-center gap-2.5 max-w-md">
              {quickActions.map(({ label, q }) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="bg-slate-900/50 border border-white/5 hover:border-blue-500/30 hover:bg-blue-600/10 px-5 py-3 rounded-2xl text-xs font-black text-slate-400 hover:text-blue-400 transition-all uppercase tracking-widest shadow-lg shadow-black/20 active:scale-95"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {messages.map((m, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: m.role === 'user' ? 20 : -20, y: 10 }}
              animate={{ opacity: 1, x: 0, y: 0 }}
              transition={{ type: 'spring', damping: 25, stiffness: 200 }}
              className={`flex gap-6 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
            >
              <div className={`w-10 h-10 rounded-2xl flex items-center justify-center shrink-0 border transition-all ${
                m.role === 'user'
                  ? 'bg-blue-600 border-blue-400/30 shadow-[0_0_20px_rgba(37,99,235,0.2)]'
                  : 'bg-slate-900 border-white/5 group-hover:border-blue-500/30'
              }`}>
                {m.role === 'user' ? <User className="w-5 h-5 text-white" /> : <Zap className="w-5 h-5 text-blue-400" />}
              </div>
               <div className={`max-w-full lg:max-w-[95%] space-y-4 ${m.role === 'user' ? 'text-right' : ''}`}>
                 {m.role === 'ai' ? (
                   <div className="flex flex-col gap-3 group/msg">
                      {/* Floating Minimalist Metadata Header */}
                      <div className="flex items-center justify-between px-4 opacity-40 group-hover/msg:opacity-100 transition-all duration-500">
                        <div className="flex items-center gap-3">
                          <div className="p-2 bg-blue-500/10 border border-blue-400/20 rounded-xl">
                            <Brain className={`w-3.5 h-3.5 text-blue-400 ${m.streaming ? 'animate-pulse' : ''}`} />
                          </div>
                          <div className="flex flex-col">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-black text-white/90 uppercase tracking-[0.2em] font-sans">Contextual Inference</span>
                              <div className="w-1 h-1 rounded-full bg-blue-400/50" />
                              <span className="text-[11px] font-bold text-blue-400/80 tracking-tighter uppercase whitespace-nowrap">Bank-Grade Audit</span>
                            </div>
                          </div>
                        </div>
                        
                        <div className={`px-2.5 py-1 rounded-lg border border-white/5 bg-white/5 backdrop-blur-md flex items-center gap-2 transition-all duration-700 ${m.streaming ? 'shadow-[0_0_20px_rgba(30,58,138,0.4)] border-blue-500/30' : ''}`}>
                          <div className={`w-1.5 h-1.5 rounded-full ${m.streaming ? 'bg-blue-400 animate-pulse' : 'bg-slate-500/50'}`} />
                          <span className="text-xs font-black text-slate-300 uppercase tracking-widest">{m.streaming && !m.content ? 'Initiating Neural Enclave...' : m.streaming ? 'Analyzing Enclave Pipeline...' : 'Financial Intelligence'}</span>
                        </div>
                      </div>

                      {/* Dynamic Status / Thought Capsule (Hidden on complete) */}
                      {m.streaming && m.status && (
                        <motion.div 
                          initial={{ opacity: 0, y: -5 }}
                          animate={{ opacity: 1, y: 0 }}
                          className="mx-4 px-4 py-2 bg-blue-600/5 border border-blue-500/10 rounded-xl flex items-center gap-3"
                        >
                          <Activity className="w-3 h-3 text-blue-400 animate-pulse" />
                          <span className="text-[10px] font-bold text-blue-400/80 uppercase tracking-widest leading-relaxed">
                            {m.status}
                          </span>
                        </motion.div>
                      )}

                      {/* Tool call reasoning trace (Phase 2 Evolution) */}
                      {m.streaming && m.toolCalls && m.toolCalls.length > 0 && (
                        <div className="flex flex-col gap-1.5 px-4 mb-3 border-l-2 border-blue-500/30 ml-4 py-1">
                          {m.toolCalls.map((t, ti) => (
                            <motion.div 
                              key={ti}
                              initial={{ opacity: 0, x: -5 }}
                              animate={{ opacity: 1, x: 0 }}
                              className="flex items-center gap-2.5"
                            >
                              <div className="w-4 h-4 rounded-full bg-blue-500/20 flex items-center justify-center">
                                <Activity className="w-2.5 h-2.5 text-blue-400 animate-pulse" />
                              </div>
                                <span className="text-[10px] font-black text-blue-400/80 uppercase tracking-widest font-mono">
                                  {t.name.replace(/_/g, ' ')} <span className="text-slate-500">Executing...</span>
                                </span>
                            </motion.div>
                          ))}
                        </div>
                      )}

                      {/* Completed tool call chips */}
                      {!m.streaming && m.toolCalls && m.toolCalls.length > 0 && (
                        <div className="flex flex-wrap gap-2 px-1 mb-2">
                          {m.toolCalls.map((t, ti) => (
                            <span key={ti} className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-[10px] font-black text-blue-400 uppercase tracking-widest">
                              <ShieldCheck className="w-2.5 h-2.5 text-emerald-500" />
                              {t.name.replace(/_/g, ' ')}
                            </span>
                          ))}
                        </div>
                      )}

                      <HoverGlowCard className="p-7 rounded-[2.5rem] border-white/10 bg-slate-900/40 backdrop-blur-2xl relative group overflow-hidden shadow-2xl transition-all duration-500 hover:shadow-blue-500/5">
                        <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-30 transition-opacity pointer-events-none">
                          <Sparkles className="w-12 h-12 text-blue-400" />
                        </div>

                        {m.chart && !m.tvSymbol && (
                          <motion.div
                            initial={{ opacity: 0, scale: 0.98 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className="mb-10 rounded-2xl overflow-hidden border border-white/5 shadow-2xl bg-black/40"
                          >
                            <img
                              src={`data:image/png;base64,${m.chart}`}
                              alt="Technical analysis"
                              className="w-full h-auto block"
                            />
                          </motion.div>
                        )}

                        <div
                          className="prose prose-invert prose-sm max-w-none text-slate-200 leading-relaxed font-medium tracking-tight px-1"
                          dangerouslySetInnerHTML={{ __html: marked.parse(
                            (typeof m.content === 'string' ? m.content : '')
                              .replace(/^\s*\]\s*$/gm, '')   // strip stray ] lines from override leakage
                              .trimEnd()
                          ) as string }}
                        />

                        {m.streaming && !m.content && (
                          <div className="space-y-3 py-2 animate-pulse">
                            <div className="h-2 bg-white/5 rounded-full w-3/4" />
                            <div className="h-2 bg-white/5 rounded-full w-1/2" />
                            <div className="h-2 bg-white/5 rounded-full w-2/3" />
                          </div>
                        )}

                        {m.streaming && (
                          <motion.span
                            animate={{ opacity: [1, 0.4, 1], scale: [1, 1.1, 1] }}
                            transition={{ duration: 1.2, repeat: Infinity }}
                            className="inline-block w-2 h-4 bg-blue-500/80 ml-2 rounded-sm align-middle shadow-[0_0_15px_rgba(59,130,246,0.5)]"
                          />
                        )}
                        {m.sql && !m.streaming && <div className="mt-8 pt-6 border-t border-white/5"><SQLDisclosure query={m.sql} /></div>}
                      </HoverGlowCard>

                      {/* Chart — shown when intent is ANALYZE */}
                      {m.intent === 'ANALYZE' && !m.streaming && (
                        m.tvSymbols && m.tvSymbols.length > 1 ? (
                          <div className="mt-4 grid grid-cols-1 xl:grid-cols-2 gap-4">
                            {m.tvSymbols.map((sym, idx) => (
                              <div key={`${sym}-${idx}`} className="relative group/chart border border-white/5 rounded-2xl overflow-hidden shadow-inner bg-black/20">
                                <div className="absolute top-4 left-4 z-10 flex items-center gap-2 bg-slate-900/95 backdrop-blur-2xl px-4 py-2 rounded-full border border-white/10 opacity-0 group-hover/chart:opacity-100 transform -translate-y-2 group-hover/chart:translate-y-0 transition-all duration-300 pointer-events-none shadow-2xl">
                                  <TrendingUp className="w-3.5 h-3.5 text-blue-400" />
                                  <span className="text-[11px] font-black text-slate-100 uppercase tracking-[0.15em]">{sym.split(':').pop()}</span>
                                </div>
                                <TradingViewWidget symbol={sym} />
                              </div>
                            ))}
                          </div>
                        ) : m.tvSymbol ? (
                          <div className="mt-3 relative group/chart border border-white/5 rounded-2xl overflow-hidden shadow-inner bg-black/20">
                            <div className="absolute top-4 left-4 z-10 flex items-center gap-2 bg-slate-900/95 backdrop-blur-2xl px-4 py-2 rounded-full border border-white/10 opacity-0 group-hover/chart:opacity-100 transform -translate-y-2 group-hover/chart:translate-y-0 transition-all duration-300 pointer-events-none shadow-2xl">
                              <TrendingUp className="w-3.5 h-3.5 text-blue-400" />
                              <span className="text-[11px] font-black text-slate-100 uppercase tracking-[0.15em]">{m.tvSymbol.split(':').pop()}</span>
                            </div>
                            <TradingViewWidget symbol={m.tvSymbol} />
                          </div>
                        ) : null
                      )}

                      {/* ML Edge Score Badge */}
                      {m.mlScore && (
                        <motion.div
                          initial={{ opacity: 0, y: 6 }}
                          animate={{ opacity: 1, y: 0 }}
                          className="mt-3 mx-1 flex items-center gap-3 px-4 py-3 rounded-2xl border border-blue-500/20 bg-blue-950/30 backdrop-blur-xl"
                        >
                          <div className="flex flex-col items-center justify-center w-14 h-14 rounded-xl bg-blue-500/10 border border-blue-500/20 shrink-0">
                            <span className={`text-xl font-black tabular-nums ${m.mlScore.win_pct >= 60 ? 'text-emerald-400' : m.mlScore.win_pct >= 45 ? 'text-amber-400' : 'text-red-400'}`}>
                              {m.mlScore.win_pct}%
                            </span>
                            <span className="text-[8px] font-black text-slate-500 uppercase tracking-widest mt-0.5">WIN</span>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-[10px] font-black text-blue-400 uppercase tracking-widest">ML Edge Score</span>
                              <span className={`px-2 py-0.5 rounded-full text-[9px] font-black uppercase tracking-widest border ${m.mlScore.side === 'BUY' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400' : 'bg-red-500/10 border-red-500/20 text-red-400'}`}>
                                {m.mlScore.side}
                              </span>
                            </div>
                            {/* Win probability bar */}
                            <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden mb-2">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${m.mlScore.win_pct}%` }}
                                transition={{ duration: 0.8, ease: 'easeOut' }}
                                className={`h-full rounded-full ${m.mlScore.win_pct >= 60 ? 'bg-emerald-500' : m.mlScore.win_pct >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                              />
                            </div>
                            <span className="text-[9px] text-slate-500 font-mono">
                              {m.mlScore.n_samples.toLocaleString()} historical setups · AUC {m.mlScore.roc_auc} · {m.mlScore.symbol}
                            </span>
                          </div>
                        </motion.div>
                      )}

                      {/* Institutional Verification Footer */}
                      {!m.streaming && (
                        <div className="flex items-center gap-3 px-6 py-2 opacity-0 group-hover/msg:opacity-100 transition-all duration-500 -mt-1">
                          <div className="flex items-center gap-1.5 px-2 py-0.5 bg-emerald-500/10 border border-emerald-500/20 rounded-md shrink-0">
                            <ShieldCheck className="w-3 h-3 text-emerald-400" />
                            <span className="text-[9px] font-black text-emerald-400 uppercase tracking-widest whitespace-nowrap">Risk-Audited Analysis</span>
                          </div>
                          <span className="text-[9px] font-bold text-slate-600 uppercase tracking-[0.15em] italic whitespace-nowrap overflow-hidden text-ellipsis">
                            Report synthesized by CS-Financial Agent Autonomous Enclave
                          </span>
                        </div>
                      )}
                    </div>
                  ) : (
                   <div className="bg-blue-600 hover:bg-blue-500 px-6 py-4 rounded-[2rem] rounded-tr-none text-white text-sm font-black shadow-2xl shadow-blue-900/30 leading-relaxed border border-blue-400/20 transition-all cursor-default inline-block text-left">
                     {m.content}
                   </div>
                 )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Input */}
      <div className="p-10 bg-gradient-to-t from-slate-950 via-slate-950/95 to-transparent border-t border-white/5 relative z-30">
        <div className="max-w-4xl mx-auto relative group">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())}
            placeholder={isRetail ? 'ถามอะไรก็ได้... เช่น "BTC จะขึ้นไหม?"' : 'Execute institutional multi-asset query...'}
            className="w-full bg-slate-900/40 backdrop-blur-3xl border border-white/10 rounded-[2.5rem] px-10 py-7 pr-24 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500/40 transition-all resize-none shadow-[0_20px_50px_rgba(0,0,0,0.5)] font-bold custom-scrollbar leading-[2.5rem]"
            rows={1}
          />
          <div className="absolute right-6 top-1/2 -translate-y-1/2 flex items-center gap-4">
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              className="w-12 h-12 bg-blue-600 hover:bg-blue-500 disabled:opacity-20 disabled:grayscale text-white rounded-full transition-all shadow-xl shadow-blue-600/30 active:scale-95 flex items-center justify-center group/btn"
            >
              {loading ? (
                <div className="w-5 h-5 border-3 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <Send className="w-5 h-5 -translate-x-0.5 translate-y-0.5 group-active/btn:scale-90 transition-transform" />
              )}
            </button>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-center gap-6 opacity-30 group-hover:opacity-50 transition-opacity">
           <div className="h-px w-12 bg-gradient-to-r from-transparent to-slate-500" />
           <p className="text-xs text-slate-500 font-black uppercase tracking-[0.3em] whitespace-nowrap">
              {isRetail ? 'SECURE DATA LINK · MULTI-ASSET' : 'INSTITUTIONAL GRADE INTELLIGENCE · SECURE ENCLAVE'}
           </p>
           <div className="h-px w-12 bg-gradient-to-l from-transparent to-slate-500" />
        </div>
      </div>
      </div>
      <AnimatePresence>
        {showDeleteModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowDeleteModal(null)}
              className="absolute inset-0 bg-black/80 backdrop-blur-md"
            />
            <motion.div
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              className="relative w-full max-w-sm bg-slate-900 border border-white/10 rounded-[2.5rem] p-8 shadow-2xl overflow-hidden"
            >
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-red-500/0 via-red-500/50 to-red-500/0" />
              
              <div className="flex flex-col items-center text-center space-y-6">
                <div className="w-16 h-16 bg-red-500/10 rounded-2xl flex items-center justify-center border border-red-500/20">
                  <AlertCircle className="w-8 h-8 text-red-500" />
                </div>
                
                <div className="space-y-2">
                  <h3 className="text-xl font-black text-white uppercase tracking-tight">Confirm Purge?</h3>
                  <p className="text-xs text-slate-400 leading-relaxed max-w-[240px] mx-auto font-medium">
                    This action will permanently erase this strategy session from the persistent enclave.
                  </p>
                </div>

                <button 
                  onClick={() => setDontShowAgain(!dontShowAgain)}
                  className="flex items-center gap-3 px-4 py-2 hover:bg-white/5 rounded-xl transition-all"
                >
                  {dontShowAgain ? (
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Circle className="w-4 h-4 text-slate-600" />
                  )}
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest leading-none">Don't show this again</span>
                </button>

                <div className="flex w-full gap-3 pt-2">
                  <button
                    onClick={() => setShowDeleteModal(null)}
                    className="flex-1 py-4 px-6 rounded-2xl border border-white/5 bg-white/5 text-[11px] font-black text-slate-400 uppercase tracking-widest hover:bg-white/10 transition-all hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => confirmDelete(showDeleteModal)}
                    className="flex-1 py-4 px-6 rounded-2xl bg-red-600 shadow-[0_0_20px_rgba(220,38,38,0.3)] text-[11px] font-black text-white uppercase tracking-widest hover:bg-red-500 transition-all active:scale-95"
                  >
                    Purge
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {showDeleteModal && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            <motion.div 
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setShowDeleteModal(null)}
              className="absolute inset-0 bg-black/80 backdrop-blur-md"
            />
            <motion.div
              initial={{ scale: 0.9, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.9, opacity: 0, y: 20 }}
              className="relative w-full max-w-sm bg-slate-900 border border-white/10 rounded-[2.5rem] p-8 shadow-2xl overflow-hidden"
            >
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-red-500/0 via-red-500/50 to-red-500/0" />
              
              <div className="flex flex-col items-center text-center space-y-6">
                <div className="w-16 h-16 bg-red-500/10 rounded-2xl flex items-center justify-center border border-red-500/20">
                  <AlertCircle className="w-8 h-8 text-red-500" />
                </div>
                
                <div className="space-y-2">
                  <h3 className="text-xl font-black text-white uppercase tracking-tight">Confirm Purge?</h3>
                  <p className="text-xs text-slate-400 leading-relaxed max-w-[240px] mx-auto font-medium">
                    This action will permanently erase this strategy session from the persistent enclave.
                  </p>
                </div>

                <button 
                  onClick={() => setDontShowAgain(!dontShowAgain)}
                  className="flex items-center gap-3 px-4 py-2 hover:bg-white/5 rounded-xl transition-all"
                >
                  {dontShowAgain ? (
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Circle className="w-4 h-4 text-slate-600" />
                  )}
                  <span className="text-[10px] font-black text-slate-500 uppercase tracking-widest leading-none">Don't show this again</span>
                </button>

                <div className="flex w-full gap-3 pt-2">
                  <button
                    onClick={() => setShowDeleteModal(null)}
                    className="flex-1 py-4 px-6 rounded-2xl border border-white/5 bg-white/5 text-[11px] font-black text-slate-400 uppercase tracking-widest hover:bg-white/10 transition-all hover:text-white"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => confirmDelete(showDeleteModal)}
                    className="flex-1 py-4 px-6 rounded-2xl bg-red-600 shadow-[0_0_20px_rgba(220,38,38,0.3)] text-[11px] font-black text-white uppercase tracking-widest hover:bg-red-500 transition-all active:scale-95"
                  >
                    Purge
                  </button>
                </div>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
};

const SQLDisclosure = ({ query }: { query: string }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-white/5 rounded-2xl overflow-hidden bg-black/40">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-white/5 transition-colors">
        <div className="flex items-center gap-2.5 text-xs text-slate-500 font-black uppercase tracking-widest">
          <Terminal className="w-3.5 h-3.5" />
          <span>Execution Trace</span>
        </div>
        {open ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
      </button>
      {open && (
        <div className="px-4 py-3 bg-black/60 border-t border-white/5">
          <code className="text-[11px] text-blue-300 font-mono font-bold whitespace-pre-wrap break-all leading-relaxed">{query}</code>
        </div>
      )}
    </div>
  );
};
