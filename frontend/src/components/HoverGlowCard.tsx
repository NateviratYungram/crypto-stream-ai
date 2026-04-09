import React, { useRef, useState, useEffect } from 'react';

interface HoverGlowCardProps {
  children: React.ReactNode;
  className?: string;
}

export const HoverGlowCard: React.FC<HoverGlowCardProps> = ({ children, className = "" }) => {
  const cardRef = useRef<HTMLDivElement>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!cardRef.current) return;
    const rect = cardRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setMousePos({ x, y });
  };

  return (
    <div
      ref={cardRef}
      onMouseMove={handleMouseMove}
      className={`glass-card glass-glow group transition-all duration-300 hover:border-blue-500/30 ${className}`}
      style={{
        // @ts-ignore
        '--mouse-x': `${mousePos.x}px`,
        '--mouse-y': `${mousePos.y}px`,
      } as React.CSSProperties}
    >
      {/* Dynamic Overlay Glow */}
      <div className="absolute inset-0 bg-blue-500/0 group-hover:bg-blue-500/[0.02] transition-colors pointer-events-none" />
      
      {/* Content wrapper to stay above the glass glow effect if needed */}
      <div className="relative z-10 w-full h-full">
        {children}
      </div>
    </div>
  );
};
