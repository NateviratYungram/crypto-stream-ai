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
  return `
    <div class="code-block-wrap theme-${document.documentElement.classList.contains('light') ? 'light' : 'dark'}">
      <button class="code-copy-btn" onclick="navigator.clipboard.writeText(this.closest('.code-block-wrap').querySelector('code').innerText).then(()=>{this.textContent='✓';setTimeout(()=>{this.textContent='⎘'},1500)})">⎘</button>
      <pre shadow-xl><code class="language-${lang||''}">${escaped}</code></pre>
    </div>`;
};
marked.use({ renderer: _renderer });
import { HoverGlowCard } from './HoverGlowCard';
import { useLanguage } from '../contexts/LanguageContext';
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
  const [sessions, setSessions] = useState<ChatSession[]>(() => loadSessions());
  const [activeId, setActiveId] = useState<string>(() => {
    const local = loadSessions();
    return local[0]?.id || 'default';
  });
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [pulse, setPulse] = useState<PulseData | null>(null);
  
  // Smart Deletion State
  const [showDeleteModal, setShowDeleteModal] = useState<string | null>(null);
  const [dontShowAgain, setDontShowAgain] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [isTranslating, setIsTranslating] = useState(false);

  const activeSession = sessions.find(s => s.id === activeId) || sessions[0];
  const messages = activeSession?.messages || [];

  const { lang, t } = useLanguage();
  const { theme, isRetail } = useMode();
  const scrollRef = useRef<HTMLDivElement>(null);
  const hasTriggeredInitial = useRef(false);

  // Always-current refs for use inside effects without stale closures
  const sessionsRef = useRef(sessions);
  sessionsRef.current = sessions;
  const activeIdRef = useRef(activeId);
  activeIdRef.current = activeId;
  const prevLangRef = useRef(lang);

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
        const authKey = localStorage.getItem('crypto_terminal_key') || 'demo';
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
              updatedAt: Number(s.updatedAt)
            }));
            setSessions(fullSessions);
            setActiveId(fullSessions[0].id);
          } else {
            // No sessions on server, try localStorage fallback
            const local = loadSessions();
            setSessions(local);
            setActiveId(local[0].id);
          }
        } else {
          // Server error, try localStorage fallback
          const local = loadSessions();
          setSessions(local);
          setActiveId(local[0].id);
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
    if (initialMessage && isInitialized) {
      // Use the ref to get the absolute latest activeId even if state hasn't painted yet
      const targetId = activeIdRef.current;
      console.log(`🚀 Triggering initial message for session ${targetId}: ${initialMessage}`);
      sendMessage(initialMessage);
      onClearInitialMessage?.();
    }
  }, [initialMessage, isInitialized]);

  // Translate current session history when language changes
  useEffect(() => {
    if (prevLangRef.current === lang) return;
    prevLangRef.current = lang;

    const currentSessions = sessionsRef.current;
    const currentActiveId = activeIdRef.current;
    const sess = currentSessions.find(s => s.id === currentActiveId);
    const msgs = sess?.messages.filter(m => !m.streaming && m.content) ?? [];
    if (msgs.length === 0) return;

    const authKey = localStorage.getItem('crypto_terminal_key') || 'demo';
    setIsTranslating(true);

    fetch('/api/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': authKey },
      body: JSON.stringify({
        messages: msgs.map(m => ({ role: m.role, content: m.content })),
        language: lang,
      }),
    })
      .then(r => r.json())
      .then(data => {
        const map: Record<number, string> = {};
        for (const t of data.translations ?? []) map[t.idx] = t.content;

        setSessions(prev => prev.map(s => {
          if (s.id !== currentActiveId) return s;
          let msgIdx = -1;
          const newMsgs = s.messages.map(m => {
            if (!m.streaming && m.content) msgIdx++;
            const translated = map[msgIdx];
            return translated ? { ...m, content: translated } : m;
          });
          return { ...s, messages: newMsgs };
        }));
      })
      .catch(() => {/* silently keep original */})
      .finally(() => setIsTranslating(false));
  }, [lang]);

  const syncSessionToServer = async (sess: ChatSession) => {
    try {
      const authKey = localStorage.getItem('crypto_terminal_key') || 'demo';
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
    // ONLY save to localStorage if we have successfully initialized from server/fallback
    // This prevents overwriting server data with default empty state on mount.
    if (isInitialized && sessions.length > 0) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
    }
  }, [sessions, isInitialized]);

  const updateActiveSession = (updater: (msgs: Message[]) => Message[]) => {
    setSessions(prev => {
      const newSess = prev.map(s => {
        if (s.id !== activeIdRef.current) return s;
        const newMsgs = updater(s.messages);
        let newTitle = s.title;
        if (s.title === 'Strategy Briefing' && newMsgs.length > 0) {
          const firstUser = newMsgs.find(m => m.role === 'user');
          if (firstUser) {
            newTitle = firstUser.content.substring(0, 30) + (firstUser.content.length > 30 ? '...' : '');
          }
        }
        const updated = { ...s, messages: newMsgs, title: newTitle, updatedAt: Date.now() };
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
        const authKey = localStorage.getItem('crypto_terminal_key') || 'demo';
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
      const authKey = localStorage.getItem('crypto_terminal_key') || 'demo';
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
        body: JSON.stringify({ 
          message: userMsg, 
          session_id: activeIdRef.current, 
          history: historyToSend,
          language: lang 
        }),
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

      // Flush any remaining buffered content after stream ends
      if (buffer.trim()) {
        try {
          const data = JSON.parse(buffer);
          if (data.type === 'chunk' && data.content) {
            fullText += data.content;
          } else if (data.type === 'metadata') {
            if (data.tv_symbol) tvSymbolData = data.tv_symbol;
            if (data.tv_symbols) tvSymbolsData = data.tv_symbols;
            if (data.intent) intentData = data.intent;
          }
        } catch { /* incomplete line, ignore */ }
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
          ? { role: 'ai', content: isAbort ? t('chat.timeout') : `⚠️ SYSTEM ALERT: ${err instanceof Error ? err.message : 'Uplink Failed'}`, streaming: false }
          : m
      ));
    } finally {
      clearTimeout(streamTimeout);
      setLoading(false);
      // Sync to server after message is finalized
      const currentSess = sessionsRef.current.find(s => s.id === activeIdRef.current);
      if (currentSess) syncSessionToServer(currentSess);
    }
  };

  const quickActions = isRetail
    ? [
        { label: t('chat.qa_retail_gold_label'),  q: t('chat.qa_retail_gold_q')  },
        { label: t('chat.qa_retail_entry_label'), q: t('chat.qa_retail_entry_q') },
        { label: t('chat.qa_retail_tpsl_label'),  q: t('chat.qa_retail_tpsl_q')  },
        { label: t('chat.qa_retail_news_label'),  q: t('chat.qa_retail_news_q')  },
        { label: t('chat.qa_retail_risk_label'),  q: t('chat.qa_retail_risk_q')  },
      ]
    : [
        { label: t('chat.qa_inst_gold_label'),    q: t('chat.qa_inst_gold_q')    },
        { label: t('chat.qa_inst_entry_label'),   q: t('chat.qa_inst_entry_q')   },
        { label: t('chat.qa_inst_signal_label'),  q: t('chat.qa_inst_signal_q')  },
        { label: t('chat.qa_inst_news_label'),    q: t('chat.qa_inst_news_q')    },
        { label: t('chat.qa_inst_risk_label'),    q: t('chat.qa_inst_risk_q')    },
      ];

  return (
    <div className={`flex flex-1 w-full h-full overflow-hidden transition-all duration-700 ${
      theme === 'dark' ? 'bg-[#030712]' : 'bg-slate-50'
    }`}>
      {/* Institutional Background Elements for Light Mode */}
      {lang === 'th' && !isRetail && theme === 'light' && (
        <div className="absolute inset-0 pointer-events-none opacity-40">
          <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-blue-100/30 blur-[120px] rounded-full" />
          <div className="absolute bottom-0 right-1/4 w-[400px] h-[400px] bg-indigo-100/20 blur-[100px] rounded-full" />
        </div>
      )}

      {/* Strategic Session Sidebar — flex sibling with width animation (avoids CSS transform context issue) */}
      <motion.div
        animate={{ width: sidebarOpen ? 320 : 0 }}
        transition={{ duration: 0.35, ease: [0.4, 0, 0.2, 1] }}
        className={`shrink-0 overflow-hidden border-r flex flex-col z-30 ${
          theme === 'dark' 
            ? 'bg-[#030712] border-white/5 shadow-[4px_0_30px_rgba(0,0,0,0.5)]' 
            : 'bg-white border-slate-200 shadow-[4px_0_20px_rgba(0,0,0,0.06)]'
        }`}
        style={{ minWidth: 0 }}
      >
        {/* Fixed-width inner so content doesn't squish during animation */}
        <div className="w-[320px] h-full flex flex-col">
          <div className={`p-8 border-b flex items-center justify-between ${
            theme === 'dark' ? 'border-white/5' : 'border-slate-200'
          }`}>
            <div className="flex items-center gap-3">
              <div className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              <span className={`text-[11px] font-black uppercase tracking-[0.3em] ${
                theme === 'dark' ? 'text-slate-500' : 'text-slate-900'
              }`}>Strategy Vault</span>
            </div>
            <button 
              onClick={createNewChat}
              className={`p-2 rounded-xl border transition-all ${
                theme === 'dark' ? 'bg-blue-600/10 border-blue-500/20 text-blue-400' : 'bg-blue-50 border-blue-100 text-blue-600'
              }`}
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto px-4 py-8 space-y-6 custom-scrollbar">
            <div className="px-4">
              <p className={`text-[10px] font-bold uppercase tracking-[0.2em] opacity-30 ${theme === 'dark' ? 'text-white' : 'text-slate-900'}`}>Intelligence History</p>
            </div>
            {sessions.map(s => (
              <div key={s.id} className="px-2 group/session">
                <div className={`flex items-center gap-2 rounded-2xl transition-all border ${
                  activeId === s.id 
                  ? (theme === 'dark' ? 'bg-blue-600/10 border-blue-500/40' : 'bg-blue-50 border-blue-200 shadow-sm') 
                  : (theme === 'dark' ? 'hover:bg-white/[0.02] border-transparent' : 'hover:bg-slate-50 border-transparent')
                }`}>
                  <button
                    onClick={() => switchSession(s.id)}
                    className={`flex-1 text-left p-3 rounded-2xl transition-all ${
                      activeId === s.id 
                      ? (theme === 'dark' ? 'text-white' : 'text-blue-700') 
                      : (theme === 'dark' ? 'text-slate-500' : 'text-slate-500')
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${activeId === s.id ? 'bg-blue-500' : 'bg-slate-400/40'}`} />
                      <div className="flex flex-col min-w-0">
                        <span className="text-[12px] font-bold truncate tracking-tight">{s.title}</span>
                        <span className="text-[9px] font-mono opacity-50 mt-0.5">{new Date(s.updatedAt).toLocaleTimeString()}</span>
                      </div>
                    </div>
                  </button>
                  <button
                    onClick={(e) => handleDeleteClick(e, s.id)}
                    className={`shrink-0 p-2 mr-1 rounded-xl opacity-0 group-hover/session:opacity-100 transition-all hover:bg-red-500/10 ${
                      theme === 'dark' ? 'text-slate-600 hover:text-red-400' : 'text-slate-400 hover:text-red-500'
                    }`}
                    title="Delete session"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          <div className={`p-5 border-t mt-auto shrink-0 ${
            theme === 'dark' ? 'bg-black/40 border-white/5' : 'bg-slate-50 border-slate-200'
          }`}>
            <div className={`flex items-center gap-4 px-5 py-4 rounded-[1.5rem] border ${
              theme === 'dark' ? 'bg-slate-900 border-white/5' : 'bg-white border-slate-200 shadow-sm'
            }`}>
              <Brain className="w-4 h-4 text-blue-500" />
              <div className="flex flex-col">
                <span className={`text-[10px] font-black uppercase tracking-widest ${theme === 'dark' ? 'text-slate-400' : 'text-slate-600'}`}>Neural Link Active</span>
                <span className="text-[8px] text-emerald-500 font-bold uppercase tracking-widest mt-1">● Encrypted Node</span>
              </div>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Translating overlay */}
        <AnimatePresence>
          {isTranslating && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className={`absolute inset-0 z-[100] backdrop-blur-md flex items-center justify-center ${
                theme === 'dark' ? 'bg-slate-950/80' : 'bg-white/80'
              }`}
            >
              <div className={`flex flex-col items-center gap-4 px-10 py-8 border rounded-[2.5rem] shadow-2xl scale-110 ${
                theme === 'dark' ? 'bg-slate-900 border-blue-500/30' : 'bg-white border-blue-500/20'
              }`}>
                <div className="relative">
                  <div className="w-12 h-12 border-4 border-blue-500/20 border-t-blue-500 rounded-full animate-spin" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-blue-400 animate-pulse" />
                  </div>
                </div>
                <span className="text-sm font-black text-blue-400 uppercase tracking-[0.3em]">
                  {lang === 'th' ? 'กำลังปรับแต่งข้อมูล...' : 'Synthesizing...'}
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Toggle Sidebar Button — absolute within the relative main chat area */}
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className={`absolute left-5 top-5 z-50 p-3 backdrop-blur-xl border rounded-2xl hover:scale-105 transition-all duration-300 group shadow-xl ${
            theme === 'dark' 
              ? 'bg-slate-900/90 border-white/20 text-slate-400' 
              : 'bg-white/90 border-slate-200 text-slate-500'
          }`}
        >
          <Terminal className={`w-4 h-4 transition-colors ${sidebarOpen ? 'text-blue-500' : 'group-hover:text-blue-500'}`} />
        </button>

        {/* Dynamic Context Marquee (Enhanced Institutional) */}
        <AnimatePresence>
          {pulse && (
          <motion.div 
            initial={{ y: -50, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            exit={{ y: -50, opacity: 0 }}
            className={`w-full backdrop-blur-3xl border-b h-16 flex items-center justify-between z-50 sticky top-0 transition-all duration-500 ${
              theme === 'dark' ? 'bg-[#030712]/95 border-white/5' : 'bg-white/90 border-slate-200'
            }`}
          >
            <div className="flex items-center gap-6 flex-1 h-full overflow-hidden">
              <div className={`flex items-center gap-3 shrink-0 px-5 py-2 rounded-2xl border shadow-xl z-20 ml-24 ${
                theme === 'dark' ? 'bg-slate-950/60 border-white/10' : 'bg-slate-100/80 border-slate-200/80'
              }`}>
                <div className={`w-2 h-2 rounded-full animate-pulse bg-${pulse.climate.color}-500 shadow-[0_0_12px_rgba(var(--${pulse.climate.color}-500),0.8)]`} />
                <span className={`text-[10px] font-black uppercase tracking-[0.25em] text-${pulse.climate.color}-400 whitespace-nowrap`}>
                  Threat: {pulse.climate.threat_level}
                </span>
              </div>

              <div className={`h-5 w-px shrink-0 z-20 ${
                theme === 'dark' ? 'bg-white/10' : 'bg-slate-200'
              }`} />

              <div className="flex-1 overflow-hidden relative z-10 h-full flex items-center [mask-image:linear-gradient(to_right,transparent_0,black_60px,black_calc(100%-60px),transparent_100%)]">
                <div className="flex items-center gap-20 animate-marquee-slow whitespace-nowrap min-w-full">
                  <div className="flex items-center gap-4 shrink-0">
                    <span className={`text-[10px] font-black uppercase tracking-widest ${
                      theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                    }`}>Sentiment Profile:</span>
                    <span className={`text-[10px] font-black uppercase tracking-widest px-3 py-1 rounded-lg ${
                      pulse.sentiment.fear_greed > 60 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' :
                      pulse.sentiment.fear_greed < 40 ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' : 
                      'bg-slate-500/10 text-slate-400 border border-slate-500/20'
                    }`}>
                      {pulse.sentiment.label} <span className="opacity-60 ml-1">({pulse.sentiment.fear_greed})</span>
                    </span>
                  </div>

                  <div className="flex items-center gap-4 shrink-0">
                    <span className={`text-[10px] font-black uppercase tracking-widest ${
                      theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                    }`}>Active Regime:</span>
                    <span className="text-[10px] font-black text-blue-400 uppercase tracking-[0.15em] bg-blue-500/5 border border-blue-500/10 px-3 py-1 rounded-lg">
                      {pulse.climate.regime}
                    </span>
                  </div>

                  <div className="flex items-center gap-4 shrink-0">
                    <span className={`text-[10px] font-black uppercase tracking-widest ${
                      theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                    }`}>Macro Intel:</span>
                    <span className={`text-[10px] font-bold italic tracking-tight ${
                      theme === 'dark' ? 'text-slate-300' : 'text-slate-600'
                    }`}>
                      {pulse.climate.summary}
                    </span>
                  </div>

                  <div className="flex items-center gap-4 shrink-0">
                    <span className={`text-[10px] font-black uppercase tracking-widest ${
                      theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                    }`}>Capital Rotation:</span>
                    <span className="text-[10px] font-black text-indigo-400 uppercase tracking-widest bg-indigo-500/5 border border-indigo-500/10 px-3 py-1 rounded-lg">
                      {pulse.leadership.top_sector} <span className="opacity-60 ml-1">({pulse.leadership.top_sector_chg > 0 ? '+' : ''}{pulse.leadership.top_sector_chg}%)</span>
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <div className="hidden lg:flex items-center gap-6 shrink-0 px-8">
              <div className="flex flex-col items-end">
                <span className={`text-[9px] font-black uppercase tracking-[0.2em] ${
                  theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                }`}>Risk Score</span>
                <span className={`text-[13px] font-black font-mono tracking-widest ${
                  theme === 'dark' ? 'text-white' : 'text-slate-900'
                }`}>{pulse.climate.score}%</span>
              </div>
              <div className={`w-px h-8 ${
                theme === 'dark' ? 'bg-white/10' : 'bg-slate-200'
              }`} />
              <div className={`flex items-center gap-3 px-4 py-2 border rounded-xl shadow-lg transition-all hover:shadow-blue-500/5 group/shield ${
                theme === 'dark' ? 'bg-black/40 border-white/5' : 'bg-slate-50 border-slate-200'
              }`}>
                <ShieldCheck className="w-4 h-4 text-emerald-500 group-hover/shield:scale-110 transition-transform" />
                <span className={`text-[10px] font-black uppercase tracking-[0.2em] ${
                  theme === 'dark' ? 'text-slate-300' : 'text-slate-600'
                }`}>Macro Shield Enabled</span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div ref={scrollRef} className={`flex-1 overflow-y-auto px-6 py-8 space-y-8 scroll-smooth custom-scrollbar relative z-10 transition-all duration-700 ${
        theme === 'dark' ? 'text-white' : 'text-slate-900'
      }`}>
        {messages.length === 0 && (
          <div className="h-full flex flex-col items-center justify-center text-center space-y-8 px-4">
            <motion.div 
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              className="relative"
            >
              <div className={`w-20 h-20 rounded-[1.75rem] flex items-center justify-center border shadow-xl relative z-10 hover:scale-105 transition-transform duration-500 ${
                theme === 'dark' ? 'bg-blue-600/10 border-blue-500/20' : 'bg-blue-500/5 border-blue-200/80'
              }`}>
                <Database className={`w-9 h-9 glow-bloom ${
                  theme === 'dark' ? 'text-blue-400' : 'text-blue-600'
                }`} />
              </div>
              <div className={`absolute inset-0 blur-3xl rounded-full scale-150 -z-10 animate-pulse ${
                theme === 'dark' ? 'bg-blue-500/20' : 'bg-blue-400/8'
              }`} />
            </motion.div>
            <div className="space-y-2">
              <h2 className={`text-2xl font-black tracking-tighter uppercase italic leading-none ${
                theme === 'dark' ? 'text-white' : 'text-slate-900'
              }`}>
                {t('chat.empty_title')}
              </h2>
              <p className={`text-sm max-w-sm font-medium leading-relaxed ${
                theme === 'dark' ? 'text-slate-500' : 'text-slate-500'
              }`}>
                {t('chat.empty_subtitle')}
              </p>
            </div>
            
            <div className="flex flex-wrap items-center justify-center gap-2 max-w-xl px-4">
              {quickActions.map(({ label, q }) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className={`px-4 py-2.5 rounded-xl text-[11px] font-bold uppercase tracking-wider transition-all active:scale-95 border ${
                    theme === 'dark'
                      ? 'bg-slate-900/60 border-white/5 text-slate-400 hover:text-blue-400 hover:border-blue-500/30 hover:bg-blue-600/10'
                      : 'bg-white border-slate-200 text-slate-600 hover:text-blue-600 hover:border-blue-500/40 hover:bg-blue-50 shadow-sm'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <p className={`text-[10px] font-bold uppercase tracking-widest max-w-xs leading-relaxed opacity-50 ${
              theme === 'dark' ? 'text-amber-500' : 'text-amber-600'
            }`}>
              {t('chat.disclaimer')}
            </p>
          </div>
        )}

        <AnimatePresence mode="popLayout">
          {messages.map((m, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, x: m.role === 'user' ? 30 : -30, y: 20 }}
              animate={{ opacity: 1, x: 0, y: 0 }}
              transition={{ type: 'spring', damping: 28, stiffness: 180 }}
              className={`flex gap-4 ${m.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
            >
              <div className={`w-9 h-9 rounded-2xl flex items-center justify-center shrink-0 border transition-all duration-300 ${
                m.role === 'user'
                  ? 'bg-blue-600 border-blue-400/30 shadow-lg shadow-blue-900/20'
                  : (theme === 'dark' ? 'bg-slate-900 border-white/10 shadow-md' : 'bg-white border-slate-200 shadow-sm')
              }`}>
                {m.role === 'user' ? <User className="w-4 h-4 text-white" /> : <Zap className={`w-4 h-4 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />}
              </div>
               <div className={`max-w-full lg:max-w-[88%] space-y-3 ${m.role === 'user' ? 'text-right' : ''}`}>
                 {m.role === 'ai' ? (
                   <div className="flex flex-col gap-4 group/msg">
                      {/* Metadata — compact row */}
                      <div className="flex items-center justify-between px-1 mb-1 opacity-50 group-hover/msg:opacity-100 transition-all duration-500">
                        <div className="flex items-center gap-2">
                          <Brain className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'} ${m.streaming ? 'animate-pulse' : ''}`} />
                          <span className={`text-[10px] font-black uppercase tracking-widest ${theme === 'dark' ? 'text-slate-500' : 'text-slate-500'}`}>{t('chat.contextual_inference')}</span>
                          <span className="opacity-30">·</span>
                          <span className={`text-[10px] font-bold uppercase tracking-wider ${theme === 'dark' ? 'text-blue-400/60' : 'text-blue-600/70'}`}>{t('chat.bank_grade_audit')}</span>
                        </div>
                        <div className={`flex items-center gap-1.5 px-2 py-0.5 rounded-lg border text-[10px] font-bold ${
                          m.streaming ? 'border-blue-500/30 text-blue-400' : (theme === 'dark' ? 'border-white/5 text-slate-600' : 'border-slate-200 text-slate-400')
                        } ${theme === 'dark' ? 'bg-black/20' : 'bg-slate-50'}`}>
                          <div className={`w-1.5 h-1.5 rounded-full ${m.streaming ? 'bg-blue-400 animate-pulse' : 'bg-slate-500/40'}`} />
                          <span className="uppercase tracking-widest">{m.streaming && !m.content ? t('chat.initiating') : m.streaming ? t('chat.analyzing') : t('chat.intel')}</span>
                        </div>
                      </div>

                      {/* Dynamic Status / Thought Capsule */}
                      {m.streaming && m.status && (
                        <motion.div 
                          initial={{ opacity: 0, y: -10 }}
                          animate={{ opacity: 1, y: 0 }}
                          className={`mx-6 px-6 py-3 border rounded-2xl flex items-center gap-4 shadow-sm backdrop-blur-md ${
                            theme === 'dark' ? 'bg-blue-600/5 border-blue-500/10' : 'bg-blue-500/5 border-blue-200/60'
                          }`}
                        >
                          <Activity className={`w-4 h-4 animate-pulse ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
                          <span className={`text-[11px] font-black uppercase tracking-[0.15em] leading-relaxed ${
                            theme === 'dark' ? 'text-blue-400/80' : 'text-blue-600'
                          }`}>
                            {m.status}
                          </span>
                        </motion.div>
                      )}

                      {/* Tool call reasoning trace */}
                      {m.streaming && m.toolCalls && m.toolCalls.length > 0 && (
                        <div className={`flex flex-col gap-2 px-6 mb-4 border-l-[3px] ml-8 py-1 ${
                          theme === 'dark' ? 'border-blue-500/30' : 'border-blue-300/60'
                        }`}>
                          {m.toolCalls.map((t, ti) => (
                            <motion.div 
                              key={ti}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              className="flex items-center gap-3"
                            >
                              <div className={`w-5 h-5 rounded-full flex items-center justify-center border ${
                                theme === 'dark' ? 'bg-blue-500/20 border-blue-400/20' : 'bg-blue-100 border-blue-400/20'
                              }`}>
                                <Activity className={`w-3 h-3 animate-pulse ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
                              </div>
                                <span className={`text-[11px] font-black uppercase tracking-widest font-mono ${
                                  theme === 'dark' ? 'text-blue-400/80' : 'text-blue-600'
                                }`}>
                                  {t.name.replace(/_/g, ' ')} <span className={`font-bold opacity-60 ${
                                    theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                                  }`}>· Uplink Processing...</span>
                                </span>
                            </motion.div>
                          ))}
                        </div>
                      )}

                      {/* Completed tool call chips */}
                      {!m.streaming && m.toolCalls && m.toolCalls.length > 0 && (
                        <div className="flex flex-wrap gap-3 px-6 mb-2">
                          {m.toolCalls.map((t, ti) => (
                            <span key={ti} className={`inline-flex items-center gap-2 px-4 py-1.5 rounded-full border text-[10px] font-black uppercase tracking-widest shadow-sm transition-colors cursor-default ${
                              theme === 'dark' ? 'bg-blue-500/5 border-blue-500/10 text-blue-400 hover:bg-blue-500/10' : 'bg-blue-50 border-blue-200/80 text-blue-600 hover:bg-blue-100'
                            }`}>
                              <ShieldCheck className="w-3 h-3 text-emerald-500" />
                              {t.name.replace(/_/g, ' ')}
                            </span>
                          ))}
                        </div>
                      )}

                      <HoverGlowCard className={`p-6 rounded-2xl backdrop-blur-xl relative group overflow-hidden shadow-lg transition-all duration-500 border ${
                        theme === 'dark' 
                          ? 'bg-slate-900/60 border-white/10 hover:shadow-blue-500/10 border-t-white/10' 
                          : 'bg-white border-slate-200 hover:shadow-slate-300/80 border-t-blue-100'
                      }`}>
                        <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-20 transition-all duration-1000 pointer-events-none group-hover:scale-110 group-hover:rotate-12">
                          <Sparkles className={`w-16 h-12 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
                        </div>

                        {m.chart && !m.tvSymbol && (
                          <motion.div
                            initial={{ opacity: 0, scale: 0.98, y: 10 }}
                            animate={{ opacity: 1, scale: 1, y: 0 }}
                            className={`mb-12 rounded-[2rem] overflow-hidden border shadow-2xl transition-all hover:scale-[1.01] duration-500 ${
                              theme === 'dark' ? 'bg-black/60 border-white/10' : 'bg-slate-50 border-slate-200'
                            }`}
                          >
                            <img
                              src={`data:image/png;base64,${m.chart}`}
                              alt="Technical analysis"
                              className="w-full h-auto block"
                            />
                          </motion.div>
                        )}

                        <div
                          className={`prose prose-sm max-w-none leading-relaxed font-normal transition-colors duration-500 ${
                            theme === 'dark' ? 'prose-invert text-slate-200' : 'prose-slate text-slate-700'
                          }`}
                          dangerouslySetInnerHTML={{ __html: marked.parse(
                            (typeof m.content === 'string' ? m.content : '')
                              .replace(/^\s*\]\s*$/gm, '')
                              .trimEnd()
                          ) as string }}
                        />

                        {m.streaming && !m.content && (
                          <div className="space-y-4 py-4 animate-pulse">
                            <div className={`h-2.5 rounded-full w-4/5 ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-200'}`} />
                            <div className={`h-2.5 rounded-full w-3/5 ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-200'}`} />
                            <div className={`h-2.5 rounded-full w-2/3 ${theme === 'dark' ? 'bg-white/5' : 'bg-slate-200'}`} />
                          </div>
                        )}

                        {m.streaming && (
                          <motion.span
                            animate={{ opacity: [1, 0.4, 1], scale: [1, 1.2, 1] }}
                            transition={{ duration: 1, repeat: Infinity }}
                            className="inline-block w-2.5 h-5 bg-blue-500 ml-3 rounded-sm align-middle shadow-[0_0_20px_rgba(59,130,246,0.8)]"
                          />
                        )}
                        {m.sql && !m.streaming && <div className={`mt-6 pt-5 border-t ${
                          theme === 'dark' ? 'border-white/5' : 'border-slate-200/60'
                        }`}><SQLDisclosure query={m.sql} /></div>}
                      </HoverGlowCard>

                      {/* Chart — shown when intent is ANALYZE */}
                      {m.intent === 'ANALYZE' && !m.streaming && (
                        m.tvSymbols && m.tvSymbols.length > 1 ? (
                          <div className="mt-6 grid grid-cols-1 xl:grid-cols-2 gap-6">
                            {m.tvSymbols.map((sym, idx) => (
                              <div key={`${sym}-${idx}`} className={`relative group/chart border rounded-[2.5rem] overflow-hidden shadow-2xl transition-all hover:scale-[1.01] duration-500 ${
                                theme === 'dark' ? 'bg-black/40 border-white/10' : 'bg-slate-50 border-slate-200'
                              }`}>
                                <div className={`absolute top-6 left-6 z-10 flex items-center gap-3 backdrop-blur-3xl px-5 py-2.5 rounded-full border shadow-2xl opacity-0 group-hover/chart:opacity-100 transform -translate-y-4 group-hover/chart:translate-y-0 transition-all duration-500 pointer-events-none ${
                                  theme === 'dark' ? 'bg-slate-900/95 border-white/10 text-slate-100' : 'bg-white/95 border-slate-200 text-slate-900'
                                }`}>
                                  <TrendingUp className={`w-4 h-4 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
                                  <span className="text-[12px] font-black uppercase tracking-[0.2em]">{sym.split(':').pop()}</span>
                                </div>
                                <TradingViewWidget symbol={sym} />
                              </div>
                            ))}
                          </div>
                        ) : m.tvSymbol ? (
                          <div className={`mt-4 relative group/chart border rounded-[2.5rem] overflow-hidden shadow-2xl transition-all hover:scale-[1.01] duration-500 ${
                            theme === 'dark' ? 'bg-black/40 border-white/10' : 'bg-slate-50 border-slate-200'
                          }`}>
                            <div className={`absolute top-6 left-6 z-10 flex items-center gap-3 backdrop-blur-3xl px-5 py-2.5 rounded-full border shadow-2xl opacity-0 group-hover/chart:opacity-100 transform -translate-y-4 group-hover/chart:translate-y-0 transition-all duration-500 pointer-events-none ${
                              theme === 'dark' ? 'bg-slate-900/95 border-white/10 text-slate-100' : 'bg-white/95 border-slate-200 text-slate-900'
                            }`}>
                              <TrendingUp className={`w-4 h-4 ${theme === 'dark' ? 'text-blue-400' : 'text-blue-600'}`} />
                              <span className="text-[12px] font-black uppercase tracking-[0.2em]">{m.tvSymbol.split(':').pop()}</span>
                            </div>
                            <TradingViewWidget symbol={m.tvSymbol} />
                          </div>
                        ) : null
                      )}

                      {/* ML Edge Score Badge */}
                      {m.mlScore && (
                        <motion.div
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          className={`mt-4 mx-2 flex items-center gap-5 px-6 py-5 rounded-[2rem] border backdrop-blur-3xl transition-all hover:shadow-blue-500/10 duration-700 shadow-xl ${
                            theme === 'dark' ? 'bg-blue-950/40 border-blue-500/30' : 'bg-blue-50/90 border-blue-200'
                          }`}
                        >
                          <div className={`flex flex-col items-center justify-center w-16 h-16 rounded-2xl border shrink-0 shadow-inner ${
                            theme === 'dark' ? 'bg-blue-500/10 border-blue-500/20' : 'bg-blue-500/5 border-blue-200'
                          }`}>
                            <span className={`text-2xl font-black tabular-nums ${m.mlScore.win_pct >= 60 ? 'text-emerald-400' : m.mlScore.win_pct >= 45 ? 'text-amber-400' : 'text-red-400'}`}>
                              {m.mlScore.win_pct}%
                            </span>
                            <span className="text-[9px] font-black text-slate-500 uppercase tracking-[0.2em] mt-1">WIN</span>
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-3 mb-2">
                              <span className={`text-[11px] font-black uppercase tracking-[0.2em] ${
                                theme === 'dark' ? 'text-blue-400' : 'text-blue-600'
                              }`}>Neural Edge Protocol</span>
                              <span className={`px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-widest border shadow-sm ${m.mlScore.side === 'BUY' ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400 shadow-emerald-500/10' : 'bg-red-500/10 border-red-500/20 text-red-400 shadow-red-500/10'}`}>
                                {m.mlScore.side} SIGNAL
                              </span>
                            </div>
                            {/* Win probability bar */}
                            <div className={`w-full h-2 rounded-full overflow-hidden mb-3 shadow-inner ${
                              theme === 'dark' ? 'bg-white/5' : 'bg-slate-200'
                            }`}>
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${m.mlScore.win_pct}%` }}
                                transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }}
                                className={`h-full rounded-full shadow-[0_0_10px_currentColor] ${m.mlScore.win_pct >= 60 ? 'bg-emerald-500' : m.mlScore.win_pct >= 45 ? 'bg-amber-500' : 'bg-red-500'}`}
                              />
                            </div>
                            <span className={`text-[10px] font-black font-mono uppercase tracking-widest opacity-80 ${
                              theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                            }`}>
                              {m.mlScore.n_samples.toLocaleString()} historical setups · AUC {m.mlScore.roc_auc} · {m.mlScore.symbol}
                            </span>
                          </div>
                        </motion.div>
                      )}

                      {/* Institutional Verification Footer */}
                      {!m.streaming && (
                        <div className="flex items-center gap-3 px-2 py-1.5 opacity-0 group-hover/msg:opacity-100 transition-all duration-500">
                          <div className={`flex items-center gap-2 px-3 py-1 border rounded-xl shrink-0 shadow-sm ${
                            theme === 'dark' ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-emerald-50 border-emerald-100'
                          }`}>
                            <ShieldCheck className={`w-3.5 h-3.5 ${theme === 'dark' ? 'text-emerald-400' : 'text-emerald-600'}`} />
                            <span className={`text-[10px] font-black uppercase tracking-[0.2em] whitespace-nowrap ${
                              theme === 'dark' ? 'text-emerald-400' : 'text-emerald-700'
                            }`}>Risk-Audited Report</span>
                          </div>
                          <span className={`text-[10px] font-black uppercase tracking-[0.2em] italic whitespace-nowrap overflow-hidden text-ellipsis opacity-60 ${
                            theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
                          }`}>
                            Report synthesized by CS-Financial Agent Autonomous Enclave
                          </span>
                        </div>
                      )}
                    </div>
                  ) : (
                   <div className={`px-5 py-3.5 rounded-2xl rounded-tr-sm text-sm font-semibold leading-relaxed border transition-all cursor-default inline-block text-left shadow-md max-w-lg ${
                     theme === 'dark'
                       ? 'bg-blue-600 text-white border-blue-500/40 shadow-blue-900/20'
                       : 'bg-blue-600 border-blue-700/20 text-white shadow-blue-500/15'
                   }`}>
                     {m.content}
                   </div>

                 )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {/* Input */}
      <div className={`p-5 border-t relative z-30 transition-all duration-500 shrink-0 ${
        theme === 'dark' 
          ? 'bg-slate-950/95 border-white/5' 
          : 'bg-white/95 border-slate-200'
      }`}>
        <div className="max-w-4xl mx-auto relative">
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && (e.preventDefault(), handleSend())}
            placeholder={t('chat.placeholder')}
            className={`w-full border rounded-2xl px-5 py-3.5 pr-14 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500/40 transition-all resize-none font-medium custom-scrollbar leading-relaxed duration-300 ${
              theme === 'dark'
                ? 'bg-slate-900/80 border-white/10 text-white placeholder:text-slate-500 shadow-lg hover:bg-slate-900'
                : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 shadow-sm hover:border-slate-300'
            }`}
            rows={1}
          />
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              className={`w-9 h-9 bg-blue-600 hover:bg-blue-500 disabled:opacity-25 disabled:grayscale text-white rounded-xl transition-all shadow-md active:scale-95 flex items-center justify-center group/btn ${
                theme === 'dark' ? 'shadow-blue-600/20' : 'shadow-blue-600/10'
              }`}
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <Send className="w-4 h-4 group-active/btn:scale-90 transition-transform" />
              )}
            </button>
          </div>
        </div>
        <div className="mt-2 flex items-center justify-center gap-4 opacity-25">
           <div className="h-px w-8 bg-gradient-to-r from-transparent to-slate-500" />
           <p className={`text-[10px] font-bold uppercase tracking-widest whitespace-nowrap ${
             theme === 'dark' ? 'text-slate-600' : 'text-slate-400'
           }`}>
              {isRetail ? 'SECURE DATA LINK' : 'INSTITUTIONAL GRADE · SECURE ENCLAVE'}
           </p>
           <div className="h-px w-8 bg-gradient-to-l from-transparent to-slate-500" />
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
              className={`relative w-full max-w-sm border rounded-[2.5rem] p-8 shadow-2xl overflow-hidden ${
                theme === 'dark' ? 'bg-slate-900 border-white/10' : 'bg-white border-slate-200'
              }`}
            >
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-red-500/0 via-red-500/50 to-red-500/0" />
              
              <div className="flex flex-col items-center text-center space-y-6">
                <div className="w-16 h-16 bg-red-500/10 rounded-2xl flex items-center justify-center border border-red-500/20">
                  <AlertCircle className="w-8 h-8 text-red-500" />
                </div>
                
                <div className="space-y-2">
                  <h3 className={`text-xl font-black uppercase tracking-tight ${
                    theme === 'dark' ? 'text-white' : 'text-slate-900'
                  }`}>Confirm Purge?</h3>
                  <p className={`text-xs leading-relaxed max-w-[240px] mx-auto font-medium ${
                    theme === 'dark' ? 'text-slate-400' : 'text-slate-600'
                  }`}>
                    This action will permanently erase this strategy session from the persistent enclave.
                  </p>
                </div>

                <button 
                  onClick={() => setDontShowAgain(!dontShowAgain)}
                  className={`flex items-center gap-3 px-4 py-2 rounded-xl transition-all ${
                    theme === 'dark' ? 'hover:bg-white/5' : 'hover:bg-slate-50'
                  }`}
                >
                  {dontShowAgain ? (
                    <CheckCircle className="w-4 h-4 text-emerald-400" />
                  ) : (
                    <Circle className={`w-4 h-4 ${theme === 'dark' ? 'text-slate-600' : 'text-slate-300'}`} />
                  )}
                  <span className={`text-[10px] font-black uppercase tracking-widest leading-none ${
                    theme === 'dark' ? 'text-slate-500' : 'text-slate-400'
                  }`}>Don't show this again</span>
                </button>

                <div className="flex w-full gap-3 pt-2">
                  <button
                    onClick={() => setShowDeleteModal(null)}
                    className={`flex-1 py-4 px-6 rounded-2xl border text-[11px] font-black uppercase tracking-widest transition-all ${
                      theme === 'dark' 
                        ? 'border-white/5 bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white' 
                        : 'border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100 hover:text-slate-900'
                    }`}
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
  const { theme } = useMode();
  return (
    <div className={`border rounded-2xl overflow-hidden transition-all duration-500 ${
      theme === 'dark' ? 'border-white/5 bg-black/40' : 'border-slate-200 bg-slate-50/50'
    }`}>
      <button onClick={() => setOpen(!open)} className={`w-full flex items-center justify-between px-4 py-2.5 transition-colors ${
        theme === 'dark' ? 'hover:bg-white/5' : 'hover:bg-slate-100/50'
      }`}>
        <div className={`flex items-center gap-2.5 text-xs font-black uppercase tracking-widest ${
          theme === 'dark' ? 'text-slate-500' : 'text-slate-500'
        }`}>
          <Terminal className="w-3.5 h-3.5" />
          <span>Execution Trace</span>
        </div>
        {open ? <ChevronUp className="w-3.5 h-3.5 text-slate-500" /> : <ChevronDown className="w-3.5 h-3.5 text-slate-500" />}
      </button>
      {open && (
        <div className={`px-4 py-3 border-t ${
          theme === 'dark' ? 'bg-black/60 border-white/5' : 'bg-white border-slate-200'
        }`}>
          <code className={`text-[11px] font-mono font-bold whitespace-pre-wrap break-all leading-relaxed ${
            theme === 'dark' ? 'text-blue-300' : 'text-blue-600'
          }`}>{query}</code>
        </div>
      )}
    </div>
  );
};
