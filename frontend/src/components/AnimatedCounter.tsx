import { useEffect, useRef } from 'react';
import { useInView, useMotionValue, useSpring } from 'framer-motion';

export function AnimatedCounter({ 
  value, 
  direction = 'up',
  decimals = 2
}: { 
  value: number; 
  direction?: 'up' | 'down'; 
  decimals?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const motionValue = useMotionValue(direction === 'down' ? value + 100 : value - 100);
  const springValue = useSpring(motionValue, {
    damping: 60,
    stiffness: 400,
  });
  const isInView = useInView(ref, { once: true, margin: "-100px" });

  useEffect(() => {
    if (isInView) {
      motionValue.set(value);
    }
  }, [motionValue, isInView, value]);

  useEffect(() => {
    return springValue.on("change", (latest) => {
      if (ref.current) {
        ref.current.textContent = Intl.NumberFormat("en-US", {
           minimumFractionDigits: decimals,
           maximumFractionDigits: decimals
        }).format(latest);
      }
    });
  }, [springValue, decimals]);

  return <span ref={ref} />;
}
