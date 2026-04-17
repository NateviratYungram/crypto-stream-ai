import React, { useEffect, useRef, memo } from 'react';

interface TradingViewWidgetProps {
  symbol: string;
  interval?: string;
}

const TradingViewWidget: React.FC<TradingViewWidgetProps> = ({ symbol, interval = "15" }) => {
  const container = useRef<HTMLDivElement>(null);
  const isCreated = useRef(false);
  const containerId = useRef(`tv_chart_${Math.random().toString(36).substr(2, 9)}`);

  useEffect(() => {
    if (!container.current || isCreated.current) return;

    const timer = setTimeout(() => {
      if (!container.current) return;

      const script = document.createElement("script");
      script.src = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
      script.type = "text/javascript";
      script.async = true;
      script.innerHTML = JSON.stringify({
        "autosize": true,
        "symbol": symbol,
        "interval": interval,
        "timezone": "Etc/UTC",
        "theme": "dark",
        "style": "1",
        "locale": "en",
        "enable_publishing": false,
        "allow_symbol_change": true,
        "calendar": false,
        "support_host": "https://www.tradingview.com",
        "container_id": containerId.current
      });
      
      const widgetDiv = container.current.querySelector(`#${containerId.current}`);
      if (widgetDiv) {
        widgetDiv.appendChild(script);
        isCreated.current = true;
      }
    }, 150);

    return () => {
      clearTimeout(timer);
      isCreated.current = false;
      if (container.current) {
        const widgetDiv = container.current.querySelector(`#${containerId.current}`);
        if (widgetDiv) widgetDiv.innerHTML = "";
      }
    };
  }, [symbol, interval]);

  return (
    <div 
      className="tradingview-widget-container rounded-2xl overflow-hidden border border-white/5 shadow-[0_15px_35px_rgba(0,0,0,0.4)] bg-slate-900/40 relative group" 
      ref={container} 
      style={{ 
        height: "540px", 
        width: "100%", 
        minHeight: "350px",
        resize: "vertical",
        maxHeight: "1200px"
      }}
    >
      <div id={containerId.current} style={{ height: "100%", width: "100%" }}></div>
      
      {/* Visual Resize Handle (Optimized for Breathing Room) */}
      <div className="absolute bottom-1.5 left-1/2 -translate-x-1/2 w-12 h-1 bg-blue-500/20 rounded-full opacity-0 group-hover:opacity-100 group-hover:bg-blue-400 group-hover:shadow-[0_0_10px_rgba(59,130,246,0.4)] transition-all duration-500 pointer-events-none" />
    </div>
  );
}

export default memo(TradingViewWidget);
