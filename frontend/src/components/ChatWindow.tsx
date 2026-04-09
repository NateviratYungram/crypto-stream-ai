import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Terminal, Sparkles, User, ChevronDown, ChevronUp, Database, Zap, Brain } from 'lucide-react';
import { marked } from 'marked';
import { HoverGlowCard } from './HoverGlowCard';
import { useMode } from '../contexts/ModeContext';

interface Message {
  role: 'user' | 'ai';
  content: string;
  sql?: string;
  streaming?: boolean;
}

const STORAGE_KEY = 'cs_chat_history';

const loadHistory = (): Message[] => {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
};

export const ChatWindow = () => {
  const [messages, setMessages] = useState<Message[]>(loadHistory);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const { isRetail } = useMode();

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(messages.filter(m => !m.streaming)));
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;

    const userMsg = input.trim();
    setMessages(prev => [...prev, { role: 'user', content: userMsg }]);
    setInput('');
    setLoading(true);

    // Retrieve Auth Key from LocalStorage (Resolved 403)
    const authKey = localStorage.getItem('crypto_terminal_key') || '';

    const streamingId = Date.now();
    setMessages(prev => [...prev, { role: 'ai', content: '', streaming: true }]);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-API-Key': authKey // CRITICAL FIX: Add the security header
        },
        body: JSON.stringify({ message: userMsg }),
      });

      if (res.status === 403) {
        throw new Error("Access Denied: Invalid Institutional Key");
      }
      if (!res.ok) throw new Error(`HTTP error ${res.status}`);
      if (!res.body) throw new Error("No response body from intelligence enclave");

      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      
      let fullText = '';
      let sqlQuery = undefined;
      
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n').filter(l => l.trim() !== '');
        
        for (const line of lines) {
          try {
            const data = JSON.parse(line);
            if (data.type === 'metadata') {
              sqlQuery = data.sql_query;
            } else if (data.type === 'chunk' && data.content) {
              fullText += data.content;
              const current = fullText;
              setMessages(prev => prev.map((m, idx) =>
                idx === prev.length - 1 && m.streaming ? { ...m, content: current } : m
              ));
            }
          } catch (e) {
             // Silence parsing errors for incomplete chunks
          }
        }
      }

      // Finalize message state
      setMessages(prev => prev.map((m, idx) =>
        idx === prev.length - 1 && m.streaming
          ? { role: 'ai', content: fullText, sql: sqlQuery, streaming: false }
          : m
      ));

    } catch (err) {
      setMessages(prev => prev.map((m, idx) =>
        idx === prev.length - 1 && m.streaming
          ? { role: 'ai', content: `⚠️ SYSTEM ALERT: ${err instanceof Error ? err.message : 'Uplink Failed'}`, streaming: false }
          : m
      ));
    } finally {
      setLoading(false);
    }
  };

  const quickActions = isRetail 
    ? [
        { label: '📈 ราคา BTC ตอนนี้?', q: 'ราคา BTC ตอนนี้เป็นยังไง?' },
        { label: '🐋 มีวาฬซื้อล่าสุดไหม?', q: 'มีวาฬซื้อหรือขาย BTC ล่าสุดไหม?' },
        { label: '🎯 ควรซื้อตอนนี้ไหม?', q: 'ตอนนี้ควรซื้อหรือขาย BTC?' },
      ]
    : [
        { label: 'Show Whale Transactions', q: 'Show latest whale transactions' },
        { label: 'Market Volatility Analysis', q: 'Analyze current market volatility' },
        { label: 'BTC Price Trends', q: 'What are the current BTC price trends?' },
      ];

  return (
    <div className="flex-1 flex flex-col h-full min-w-0 bg-slate-950/20 custom-scrollbar">
      {/* Header */}
      <header className="h-20 border-b border-white/5 flex items-center justify-between px-8 bg-slate-900/10 backdrop-blur-xl z-20 sticky top-0">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 bg-blue-600/10 rounded-xl flex items-center justify-center border border-blue-500/20 shadow-[0_0_20px_rgba(59,130,246,0.1)]">
            <Sparkles className="w-5 h-5 text-blue-400 glow-bloom" />
          </div>
          <div>
            <h3 className="text-sm font-black text-slate-100 tracking-tight">
              {isRetail ? 'ถามอะไรก็ได้เกี่ยวกับตลาด Crypto' : 'Institutional Quant Strategist'}
            </h3>
            <p className="text-[10px] text-slate-500 font-bold uppercase tracking-widest leading-none mt-1 flex items-center gap-2">
              {isRetail ? 'AI วิเคราะห์ข้อมูล Real-time ให้คุณ' : 'L4 Autonomous Analysis'} 
              <span className="bg-white/5 px-1.5 py-0.5 rounded border border-white/10 text-[8px] text-slate-400">Gemini 2.5 Flash</span>
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button
              onClick={() => { setMessages([]); sessionStorage.removeItem(STORAGE_KEY); }}
              className="text-[9px] font-black text-slate-600 hover:text-rose-400 uppercase tracking-widest transition-colors"
            >
              Clear Terminal
            </button>
          )}
          <div className="flex items-center gap-2 px-3 py-1.5 bg-emerald-500/5 border border-emerald-500/10 rounded-xl">
            <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full shadow-[0_0_8px_rgba(16,185,129,0.5)] status-breath" />
            <span className="text-[10px] font-black text-emerald-500 uppercase tracking-widest">
              {isRetail ? 'Online' : 'Enclave Active'}
            </span>
          </div>
        </div>
      </header>

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
                  : 'Establish a secure uplink to the distributed execution engine. Synthesize whale behavior and strategic market flow.'}
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2.5 max-w-md">
              {quickActions.map(({ label, q }) => (
                <button
                  key={q}
                  onClick={() => setInput(q)}
                  className="bg-slate-900/50 border border-white/5 hover:border-blue-500/30 hover:bg-blue-600/10 px-5 py-3 rounded-2xl text-[10px] font-black text-slate-400 hover:text-blue-400 transition-all uppercase tracking-widest shadow-lg shadow-black/20 active:scale-95"
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
              <div className={`max-w-[92%] space-y-4 ${m.role === 'user' ? 'text-right' : ''}`}>
                {m.role === 'ai' ? (
                  <HoverGlowCard className="p-7 rounded-[2rem] border-white/5 bg-slate-900/50 backdrop-blur-md relative group overflow-hidden">
                    <div className="absolute top-0 right-0 p-4 opacity-10 group-hover:opacity-30 transition-opacity">
                       <Sparkles className="w-12 h-12 text-blue-400" />
                    </div>
                    {!isRetail && (
                      <div className="flex items-center gap-3 mb-5">
                        <div className="flex items-center gap-1.5 px-2.5 py-1 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                          <Brain className="w-3 h-3 text-blue-400" />
                          <span className="text-[9px] font-black text-blue-400 uppercase tracking-widest">
                             Contextual Inference
                          </span>
                        </div>
                        <div className="w-1 h-1 rounded-full bg-slate-700" />
                        <span className="text-[9px] font-bold text-slate-500 tracking-wider">Engine: 2.5-Flash</span>
                      </div>
                    )}
                    <div
                      className="prose prose-invert prose-base max-w-none text-slate-200 leading-relaxed font-medium tracking-tight"
                      dangerouslySetInnerHTML={{ __html: marked.parse(m.content || '') as string }}
                    />
                    {m.streaming && (
                      <motion.span 
                        animate={{ opacity: [1, 0, 1] }}
                        transition={{ duration: 0.8, repeat: Infinity }}
                        className="inline-block w-1.5 h-4 bg-blue-500 ml-1 rounded-sm align-middle shadow-[0_0_10px_rgba(59,130,246,0.5)]" 
                      />
                    )}
                    {m.sql && !m.streaming && <div className="mt-6"><SQLDisclosure query={m.sql} /></div>}
                  </HoverGlowCard>
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
            placeholder={isRetail ? 'ถามอะไรก็ได้... เช่น "BTC จะขึ้นไหม?"' : 'Execute autonomous quantum query...'}
            className="w-full bg-slate-900/40 backdrop-blur-3xl border border-white/10 rounded-[2.5rem] px-8 py-5 pr-20 text-sm text-white placeholder:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-500/40 transition-all resize-none shadow-[0_20px_50px_rgba(0,0,0,0.5)] font-bold custom-scrollbar"
            rows={2}
          />
          <div className="absolute right-4 bottom-4 flex items-center gap-2">
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              className="p-3.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-20 disabled:grayscale text-white rounded-[1.5rem] transition-all shadow-xl shadow-blue-600/30 active:scale-90 flex items-center justify-center"
            >
              {loading ? <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" /> : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-center gap-6 opacity-30 group-hover:opacity-50 transition-opacity">
           <div className="h-px w-12 bg-gradient-to-r from-transparent to-slate-500" />
           <p className="text-[10px] text-slate-500 font-black uppercase tracking-[0.3em] whitespace-nowrap">
              {isRetail ? 'SECURE DATA LINK · BINANCE' : 'LEVEL 4 AUTHENTICATION REQUIRED · QUANTUM ENCLAVE'}
           </p>
           <div className="h-px w-12 bg-gradient-to-l from-transparent to-slate-500" />
        </div>
      </div>
    </div>
  );
};

const SQLDisclosure = ({ query }: { query: string }) => {
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-white/5 rounded-2xl overflow-hidden bg-black/40">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-white/5 transition-colors">
        <div className="flex items-center gap-2.5 text-[10px] text-slate-500 font-black uppercase tracking-widest">
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
