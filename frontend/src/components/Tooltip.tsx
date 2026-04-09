import { useState, useRef, ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { HelpCircle } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';

const DICTIONARY: Record<string, string> = {
  'VWAP': 'Volume-Weighted Average Price ราคาเฉลี่ยถ่วงน้ำหนักด้วยปริมาณการซื้อขาย ใช้ดูเทรนด์หลักของสถาบัน',
  'Whale': 'นักลงทุนรายใหญ่ที่มีทุนมหาศาล (เช่น โอน >0.5 BTC) การขยับของวาฬมักทำให้ราคาผันผวน',
  'Order Book': 'สมุดคำสั่งซื้อขาย แสดงแรงซื้อ (Bid) และแรงขาย (Ask) ที่รอจับคู่',
  'Bid/Ask': 'Bid คือราคารับซื้อสูงสุด, Ask คือราคาขายต่ำสุด ส่วนต่างเรียก Spread',
  'Confidence': 'ระดับความมั่นใจของ AI ที่คำนวณจาก Volume Surge, Price Momentum และ Order Book',
  'Bullish': 'ตลาดขาขึ้น (กระทิง) แนวโน้มราคาปรับตัวสูงขึ้น',
  'Bearish': 'ตลาดขาลง (หมี) แนวโน้มราคาปรับตัวลดลง',
  'Volatility': 'ความผันผวนของราคา ถ้ายิ่งสูง แปลว่าราคาสวิงขึ้นลงแรง',
  'Regime': 'สภาวะตลาดโดยรวมในปัจจุบัน (เช่น ขาขึ้น, ขาลง, หรือไซด์เวย์)',
};

export const FinancialTerm = ({ term, children }: { term: string; children?: ReactNode }) => {
  const [open, setOpen] = useState(false);
  const { isRetail } = useMode();
  const def = DICTIONARY[term];

  if (!isRetail || !def) return <>{children || term}</>;

  return (
    <span 
      className="relative inline-flex items-center cursor-help group/term"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <span className="underline decoration-blue-500/50 decoration-dashed underline-offset-4 group-hover/term:text-blue-400 transition-colors">
        {children || term}
      </span>
      <HelpCircle className="w-3 h-3 text-blue-500/50 ml-1 group-hover/term:text-blue-400" />

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 5, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 5, scale: 0.95 }}
            transition={{ duration: 0.15 }}
            className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-48 p-3 rounded-xl bg-slate-800/95 backdrop-blur-xl border border-white/10 shadow-2xl z-[99999]"
          >
            <p className="text-[10px] font-black text-white mb-1 uppercase tracking-widest">{term}</p>
            <p className="text-[11px] text-slate-300 font-medium leading-relaxed">{def}</p>
            {/* Triangle pointing down */}
            <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-slate-800/95" />
          </motion.div>
        )}
      </AnimatePresence>
    </span>
  );
};
