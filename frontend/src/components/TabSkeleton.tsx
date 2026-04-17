/**
 * TabSkeleton — Professional shimmer skeleton loader for tab transitions.
 * Used in all data-heavy tabs to prevent "blank screen" confusion.
 */
import { motion } from 'framer-motion';

interface Props {
  rows?: number;
  cards?: number;
  variant?: 'cards' | 'table' | 'feed';
}

const shimmer = "animate-pulse bg-gradient-to-r from-slate-800/60 via-slate-700/40 to-slate-800/60 rounded-2xl";

const CardSkeleton = ({ delay = 0 }: { delay?: number }) => (
  <motion.div
    initial={{ opacity: 0, y: 8 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay: delay * 0.08 }}
    className={`${shimmer} h-60 w-full border border-white/5`}
  />
);

const RowSkeleton = ({ delay = 0 }: { delay?: number }) => (
  <motion.div
    initial={{ opacity: 0, x: -8 }}
    animate={{ opacity: 1, x: 0 }}
    transition={{ delay: delay * 0.06 }}
    className="flex items-center gap-4 p-4"
  >
    <div className={`${shimmer} w-10 h-10 rounded-xl shrink-0`} />
    <div className="flex-1 space-y-2">
      <div className={`${shimmer} h-3 w-1/3 rounded-lg`} />
      <div className={`${shimmer} h-2.5 w-2/3 rounded-lg`} />
    </div>
    <div className={`${shimmer} h-6 w-16 rounded-xl`} />
  </motion.div>
);

export const TabSkeleton = ({ rows = 5, cards = 6, variant = 'cards' }: Props) => {
  if (variant === 'cards') {
    return (
      <div className="p-10 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8 w-full max-w-[1600px] mx-auto">
        {Array.from({ length: cards }).map((_, i) => <CardSkeleton key={i} delay={i} />)}
      </div>
    );
  }

  if (variant === 'feed') {
    return (
      <div className="p-8 space-y-3 w-full">
        <div className={`${shimmer} h-8 w-48 mb-6 rounded-xl`} />
        {Array.from({ length: rows }).map((_, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: i * 0.07 }}
            className={`${shimmer} h-20 w-full border border-white/5`}
          />
        ))}
      </div>
    );
  }

  // table variant
  return (
    <div className="w-full">
      <div className={`${shimmer} h-20 w-full mb-0.5 rounded-none`} />
      <div className="divide-y divide-white/5">
        {Array.from({ length: rows }).map((_, i) => <RowSkeleton key={i} delay={i} />)}
      </div>
    </div>
  );
};
