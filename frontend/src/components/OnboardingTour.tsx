import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ChevronRight } from 'lucide-react';

const STEPS = [
  {
    title: '📈 Market Trends',
    body: 'ดูราคาสด BTC, ETH, SOL และเหรียญอื่นๆ แบบ real-time จาก Binance ทุก 1 วินาที',
    tab: 'Market Trends',
  },
  {
    title: '🐋 Whale Tracker',
    body: '"วาฬ" คือนักลงทุนรายใหญ่ที่ซื้อหรือขายมากกว่า 0.5 BTC ขึ้นไป การติดตามพวกเขาช่วยให้รู้แนวโน้มก่อนใคร',
    tab: 'Whale Tracker',
  },
  {
    title: '🧠 Intelligence Hub',
    body: 'AI วิเคราะห์ข้อมูลตลาดแบบ real-time แล้วสร้างสัญญาณซื้อ/ขาย พร้อม % ความมั่นใจ',
    tab: 'Intelligence Hub',
  },
  {
    title: '💬 Strategy Chat',
    body: 'ถามอะไรก็ได้เป็นภาษาไทยหรืออังกฤษ เช่น "วันนี้ BTC จะขึ้นหรือลง?" หรือ "มีวาฬซื้ออะไรล่าสุด?"',
    tab: 'Strategy Chat',
  },
  {
    title: '✅ พร้อมใช้งานแล้ว!',
    body: 'ยินดีต้อนรับสู่ CryptoStream — ศูนย์ข่าวกรองตลาด Crypto ระดับสถาบัน สนุกกับการใช้งานนะครับ!',
    tab: null,
  },
];

interface Props {
  onComplete: () => void;
  onTabChange?: (tab: string) => void;
}

export const OnboardingTour = ({ onComplete, onTabChange }: Props) => {
  const [step, setStep] = useState(0);
  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  const next = () => {
    if (isLast) {
      onComplete();
    } else {
      if (STEPS[step + 1].tab && onTabChange) {
        onTabChange(STEPS[step + 1].tab!);
      }
      setStep(s => s + 1);
    }
  };

  return (
    <div className="fixed inset-0 z-[9999] flex items-end justify-center pb-10 pointer-events-none">
      <AnimatePresence mode="wait">
        <motion.div
          key={step}
          initial={{ opacity: 0, y: 40, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -20, scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          className="pointer-events-auto w-full max-w-sm mx-4 bg-slate-900/95 backdrop-blur-3xl border border-blue-500/20 rounded-[2rem] shadow-2xl shadow-blue-900/30 overflow-hidden"
        >
          {/* Progress dots */}
          <div className="flex items-center gap-1.5 px-6 pt-5">
            {STEPS.map((_, i) => (
              <div
                key={i}
                className={`h-1 rounded-full transition-all duration-300 ${
                  i === step ? 'w-6 bg-blue-500' : i < step ? 'w-4 bg-blue-500/60' : 'w-4 bg-slate-700'
                }`}
              />
            ))}
          </div>

          <div className="p-6 space-y-4">
            <div>
              <h3 className="text-lg font-black text-white tracking-tight">{current.title}</h3>
              <p className="text-sm text-slate-300 font-medium leading-relaxed mt-2">{current.body}</p>
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={next}
                className="flex-1 h-11 bg-blue-600 hover:bg-blue-500 text-white rounded-xl flex items-center justify-center gap-2 font-black text-xs uppercase tracking-widest transition-all active:scale-95"
              >
                {isLast ? 'เริ่มใช้งาน!' : 'ถัดไป'}
                <ChevronRight className="w-4 h-4" />
              </button>
              <button
                onClick={onComplete}
                className="px-4 h-11 text-slate-500 hover:text-white text-xs font-bold uppercase tracking-widest transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </motion.div>
      </AnimatePresence>
    </div>
  );
};
