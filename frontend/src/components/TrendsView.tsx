import React, { useEffect, useRef } from 'react';
import { AreaChart, RefreshCcw } from 'lucide-react';
import { useMode } from '../contexts/ModeContext';
import { useWebSocket } from '../hooks/useWebSocket';

// Generic Component specifically for injecting TradingView Widget scripts securely
const TVWidget = ({ src, config, className = '' }: { src: string, config: any, className?: string }) => {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    // Clear previous
    container.current.innerHTML = '';
    
    // Create new script template
    const script = document.createElement("script");
    script.src = src;
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify(config);
    
    // Widget container wrapping
    const div = document.createElement("div");
    div.className = "tradingview-widget-container__widget w-full h-full";
    container.current.appendChild(div);
    container.current.appendChild(script);
  }, [src, JSON.stringify(config)]);

  return (
    <div className={`tradingview-widget-container flex-1 overflow-hidden relative ${className}`} ref={container} />
  );
};

export const TrendsView = () => {
  const { isConnected } = useWebSocket();

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950/20 overflow-y-auto pb-8 custom-scrollbar">
      {/* Header */}
      <header className="h-20 border-b border-white/5 flex items-center justify-between px-8 bg-slate-950/40 backdrop-blur-3xl z-30 sticky top-0 shrink-0 shadow-2xl">
        <div className="flex items-center gap-5">
          <div className="w-12 h-12 bg-blue-600/10 rounded-2xl flex items-center justify-center border border-blue-500/20 shadow-inner">
            <AreaChart className="w-6 h-6 text-blue-400" />
          </div>
          <div className="space-y-0.5">
            <h1 className="text-2xl font-black text-white tracking-tighter uppercase italic">Institutional Macro Hub</h1>
            <div className="flex items-center gap-3">
              <span className="text-xs font-black text-slate-400 uppercase tracking-widest leading-none flex items-center gap-2">
                <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-500 shadow-[0_0_8px_#10b981] animate-pulse' : 'bg-slate-600'}`} />
                {isConnected ? 'LIVE DATA SYNC · TRADINGVIEW ENGINE' : 'OFFLINE'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Dashboard Grid */}
      <div className="p-8 max-w-[1920px] mx-auto w-full flex flex-col gap-6">
        
        {/* Top Row: Main Highlight & Indices */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6" style={{ minHeight: '520px' }}>
          {/* Top-Left: Global Main Highlight (Spans 2 columns) */}
          <div className="lg:col-span-2 rounded-2xl border border-white/5 overflow-hidden bg-slate-900/40 shadow-2xl flex relative">
            <TVWidget 
              src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js"
              config={{
                "autosize": true,
                "symbol": "BINANCE:BTCUSDT",
                "interval": "D",
                "timezone": "Etc/UTC",
                "theme": "dark",
                "style": "1",
                "locale": "th",
                "enable_publishing": false,
                "allow_symbol_change": true,
                "calendar": false,
                "support_host": "https://www.tradingview.com"
              }}
            />
          </div>

          {/* Top-Right: Global Indices List */}
          <div className="rounded-2xl border border-white/5 overflow-hidden bg-slate-900/40 shadow-2xl flex relative">
            <TVWidget 
              src="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js"
              config={{
                "colorTheme": "dark",
                "dateRange": "12M",
                "showChart": true,
                "locale": "th",
                "width": "100%",
                "height": "100%",
                "isTransparent": true,
                "showSymbolLogo": true,
                "showFloatingTooltip": true,
                "plotLineColorGrowing": "rgba(41, 98, 255, 1)",
                "plotLineColorFalling": "rgba(41, 98, 255, 1)",
                "gridLineColor": "rgba(240, 243, 250, 0)",
                "scaleFontColor": "rgba(106, 109, 120, 1)",
                "belowLineFillColorGrowing": "rgba(41, 98, 255, 0.12)",
                "belowLineFillColorFalling": "rgba(41, 98, 255, 0.12)",
                "belowLineFillColorGrowingBottom": "rgba(41, 98, 255, 0)",
                "belowLineFillColorFallingBottom": "rgba(41, 98, 255, 0)",
                "symbolActiveColor": "rgba(41, 98, 255, 0.12)",
                "tabs": [
                  {
                    "title": "ดัชนีหลักโลก",
                    "symbols": [
                      { "s": "FOREXCOM:SPXUSD", "d": "S&P 500" },
                      { "s": "FOREXCOM:NSXUSD", "d": "NASDAQ 100" },
                      { "s": "FOREXCOM:DJI", "d": "DOW JONES" },
                      { "s": "OANDA:JP225USD", "d": "JAPAN 225" },
                      { "s": "OANDA:UK100GBP", "d": "FTSE 100" },
                      { "s": "OANDA:EU50EUR", "d": "EURO STOXX 50" }
                    ],
                    "originalTitle": "Indices"
                  }
                ]
              }}
            />
          </div>
        </div>

        {/* Bottom Row: Crypto, FX, US Tech */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6" style={{ minHeight: '520px' }}>
          {/* Bottom-Left: Crypto Macro */}
          <div className="rounded-2xl border border-white/5 overflow-hidden bg-slate-900/40 shadow-2xl flex relative">
            <TVWidget 
              src="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js"
              config={{
                "colorTheme": "dark",
                "dateRange": "1M",
                "showChart": true,
                "locale": "th",
                "width": "100%",
                "height": "100%",
                "isTransparent": true,
                "showSymbolLogo": true,
                "showFloatingTooltip": true,
                "plotLineColorGrowing": "rgba(41, 98, 255, 1)",
                "plotLineColorFalling": "rgba(41, 98, 255, 1)",
                "gridLineColor": "rgba(240, 243, 250, 0)",
                "scaleFontColor": "rgba(106, 109, 120, 1)",
                "belowLineFillColorGrowing": "rgba(41, 98, 255, 0.12)",
                "belowLineFillColorFalling": "rgba(41, 98, 255, 0.12)",
                "belowLineFillColorGrowingBottom": "rgba(41, 98, 255, 0)",
                "belowLineFillColorFallingBottom": "rgba(41, 98, 255, 0)",
                "symbolActiveColor": "rgba(41, 98, 255, 0.12)",
                "tabs": [
                  {
                    "title": "เจาะลึก คริปโต",
                    "symbols": [
                      { "s": "CRYPTOCAP:TOTAL", "d": "Market Cap กองรวม" },
                      { "s": "CRYPTOCAP:BTC.D", "d": "Bitcoin Dominance" },
                      { "s": "BINANCE:BTCUSDT", "d": "Bitcoin" },
                      { "s": "BINANCE:ETHUSDT", "d": "Ethereum" },
                      { "s": "BINANCE:SOLUSDT", "d": "Solana" }
                    ],
                    "originalTitle": "Crypto"
                  }
                ]
              }}
            />
          </div>

          {/* Bottom-Middle: FX & Commodities */}
          <div className="rounded-2xl border border-white/5 overflow-hidden bg-slate-900/40 shadow-2xl flex relative">
            <TVWidget 
              src="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js"
              config={{
                "colorTheme": "dark",
                "dateRange": "1M",
                "showChart": true,
                "locale": "th",
                "width": "100%",
                "height": "100%",
                "isTransparent": true,
                "showSymbolLogo": true,
                "showFloatingTooltip": true,
                "plotLineColorGrowing": "rgba(16, 185, 129, 1)",
                "plotLineColorFalling": "rgba(244, 63, 94, 1)",
                "gridLineColor": "rgba(240, 243, 250, 0)",
                "scaleFontColor": "rgba(106, 109, 120, 1)",
                "belowLineFillColorGrowing": "rgba(16, 185, 129, 0.12)",
                "belowLineFillColorFalling": "rgba(244, 63, 94, 0.12)",
                "belowLineFillColorGrowingBottom": "rgba(16, 185, 129, 0)",
                "belowLineFillColorFallingBottom": "rgba(244, 63, 94, 0)",
                "symbolActiveColor": "rgba(41, 98, 255, 0.12)",
                "tabs": [
                  {
                    "title": "FX & สินค้าโภคภัณฑ์",
                    "symbols": [
                      { "s": "FX_IDC:USDTHB", "d": "USD ต่อ THB" },
                      { "s": "OANDA:XAUUSD", "d": "ทองคำตลาดโลก" },
                      { "s": "OANDA:NATGASUSD", "d": "ก๊าซธรรมชาติ" },
                      { "s": "OANDA:XCUUSD", "d": "ทองแดง" },
                      { "s": "TVC:USOIL", "d": "น้ำมันดิบครูด (WTI)" }
                    ]
                  }
                ]
              }}
            />
          </div>

          {/* Bottom-Right: US Tech & Top Stocks */}
          <div className="rounded-2xl border border-white/5 overflow-hidden bg-slate-900/40 shadow-2xl flex relative">
            <TVWidget 
              src="https://s3.tradingview.com/external-embedding/embed-widget-market-overview.js"
              config={{
                "colorTheme": "dark",
                "dateRange": "1M",
                "showChart": true,
                "locale": "th",
                "width": "100%",
                "height": "100%",
                "isTransparent": true,
                "showSymbolLogo": true,
                "showFloatingTooltip": true,
                "plotLineColorGrowing": "rgba(245, 158, 11, 1)",
                "plotLineColorFalling": "rgba(245, 158, 11, 1)",
                "gridLineColor": "rgba(240, 243, 250, 0)",
                "scaleFontColor": "rgba(106, 109, 120, 1)",
                "belowLineFillColorGrowing": "rgba(245, 158, 11, 0.12)",
                "belowLineFillColorFalling": "rgba(245, 158, 11, 0.12)",
                "belowLineFillColorGrowingBottom": "rgba(245, 158, 11, 0)",
                "belowLineFillColorFallingBottom": "rgba(245, 158, 11, 0)",
                "symbolActiveColor": "rgba(41, 98, 255, 0.12)",
                "tabs": [
                  {
                    "title": "หุ้น Big Tech สหรัฐฯ",
                    "symbols": [
                      { "s": "NASDAQ:AAPL", "d": "Apple Inc." },
                      { "s": "NASDAQ:MSFT", "d": "Microsoft Corp" },
                      { "s": "NASDAQ:NVDA", "d": "NVIDIA Corp" },
                      { "s": "NASDAQ:TSLA", "d": "Tesla Inc." },
                      { "s": "NASDAQ:GOOGL", "d": "Alphabet (Google)" }
                    ]
                  }
                ]
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

