import os
import sys
import json
import requests
from google import genai
from google.genai import types
from dotenv import load_dotenv
# Load environment variables
load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("MODEL_ID", "gemini-2.5-flash")

if not GEMINI_API_KEY:
    print("❌ MISSING GEMINI_API_KEY in .env")
    sys.exit(1)

client = genai.Client(api_key=GEMINI_API_KEY)

# ==========================================
# Agent Configuration
# ==========================================
def execute_tool(fn_name, fn_args):
    """Safe tool executor for CLI agent."""
    try:
        from intelligence.tools import market_tools
        func = getattr(market_tools, fn_name, None)
        
        if not func:
            return {"error": f"Tool {fn_name} not found"}
            
        if isinstance(fn_args, dict):
            return func(**fn_args)
        return func()
    except Exception as e:
        return {"error": str(e)}

gemini_tools = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_market_analysis",
        description="Fetch technical indicators and price action for a symbol.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="Ticker symbol (e.g. BTC, GOLD, NVDA)"),
                "timeframe": types.Schema(type="STRING", description="Timeframe (1m, 5m, 15m, 1h, 1d)"),
                "asset_class": types.Schema(type="STRING", description="Asset type (CRYPTO, STOCK, MACRO)")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="get_macro_sentiment",
        description="Get overall market regime and sentiment scores.",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="get_news_impact",
        description="Fetch the latest news and calculate market impact for a symbol.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="Ticker symbol")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="prepare_mt5_trade_draft",
        description="Step 1: Draft a trade and get a Draft ID. MUST show to user.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="MT5 symbol"),
                "side": types.Schema(type="STRING", description="BUY/SELL"),
                "volume": types.Schema(type="NUMBER", description="Lot size"),
            },
            required=["symbol", "side", "volume"]
        )
    ),
    types.FunctionDeclaration(
        name="execute_approved_mt5_trade",
        description="Step 2: Execute trade AFTER user confirms Draft ID.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "draft_id": types.Schema(type="STRING", description="Confirmed ID")
            },
            required=["draft_id"]
        )
    ),
    types.FunctionDeclaration(
        name="get_market_opportunities",
        description="Scan for top movers. asset_class='STOCK' or 'CRYPTO'.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "asset_class": types.Schema(type="STRING", description="'STOCK' or 'CRYPTO'")
            },
            required=["asset_class"]
        )
    ),
    types.FunctionDeclaration(
        name="calculate_math_expression",
        description="Safely evaluate a mathematical expression.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "expression": types.Schema(type="STRING", description="Math expression to evaluate")
            },
            required=["expression"]
        )
    ),
    types.FunctionDeclaration(
        name="set_smart_alert",
        description="Set a background monitoring alert for a specific market condition.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "condition": types.Schema(type="STRING", description="Condition to monitor"),
                "target_symbol": types.Schema(type="STRING", description="Symbol to monitor"),
                "message": types.Schema(type="STRING", description="Message to send when triggered")
            },
            required=["condition", "target_symbol", "message"]
        )
    ),
    types.FunctionDeclaration(
        name="get_user_portfolio",
        description="Retrieve MT5 portfolio context aligned to a specific user.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "user_id": types.Schema(type="STRING", description="Optional user ID, defaults to 'default'")
            }
        )
    ),
    types.FunctionDeclaration(
        name="get_onchain_flow",
        description="Fetch Whale money flows and exchange net inflows for Crypto.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="Token symbol e.g., 'BTC'")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="get_options_flow",
        description="Fetch Put/Call Ratio and Gamma Exposure (GEX) for TradFi/Crypto options.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="Symbol e.g., 'NVDA', 'BTC'")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="analyze_trade_performance",
        description="Analyze recent closed trades to provide an automated AI journal/review of performance.",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="get_social_sentiment",
        description="Scan social media hype, Reddit mentions, and influence scores for a specific token or asset.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "keyword": types.Schema(type="STRING", description="Keyword or ticker to scan")
            },
            required=["keyword"]
        )
    ),
    types.FunctionDeclaration(
        name="get_trading_tactics",
        description=(
            "Institutional Intelligence: Aggregates SMC, Trend, and Mean Reversion strategies "
            "to provide explicit entry/SL/TP 'moves' for a given symbol. "
            "Supports: CRYPTO (BTC, ETH, SOL, BNB, XRP, DOGE, AVAX, LINK, ADA, DOT, MATIC), "
            "COMMODITIES (GOLD/XAUUSD, SILVER/XAGUSD, OIL/USOIL), "
            "INDICES (NASDAQ/US100, SP500/US500, DOW/US30, GER40, UK100), "
            "FOREX (EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF). "
            "Pass the short symbol (e.g. 'BTC', 'GOLD', 'OIL', 'NASDAQ', 'EURUSD')."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(
                    type="STRING",
                    description="Short symbol: BTC, ETH, GOLD, OIL, NASDAQ, SP500, EURUSD, GBPUSD, etc."
                )
            },
            required=["symbol"]
        )
    ),
    # ── Phase 14 New Tools ────────────────────────────────────
    types.FunctionDeclaration(
        name="get_fear_greed_index",
        description="Return Crypto & Stock Fear & Greed Index scores. Use for overall sentiment check.",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="get_economic_calendar",
        description="Fetch upcoming high-impact macro events (Fed, CPI, NFP, GDP, earnings).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "days_ahead": types.Schema(type="INTEGER", description="Look-ahead days (default 7)")
            }
        )
    ),
    types.FunctionDeclaration(
        name="get_liquidation_heatmap",
        description="Fetch crypto liquidation clusters — levels where mass long/short liquidations occur.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="Crypto symbol e.g. BTC, ETH")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="scan_multi_timeframe",
        description="Run analysis across 5m/15m/1h/4h/1d and return a confluence score.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol":      types.Schema(type="STRING", description="Ticker symbol"),
                "asset_class": types.Schema(type="STRING", description="CRYPTO | STOCK | MACRO")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="get_portfolio_correlation",
        description="Compute pairwise correlation matrix and flag concentration risk (>0.85).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbols": types.Schema(type="ARRAY", description="List of symbols",
                                        items=types.Schema(type="STRING")),
                "period":  types.Schema(type="STRING", description="1mo | 3mo | 6mo | 1y")
            }
        )
    ),
    types.FunctionDeclaration(
        name="generate_weekly_report",
        description="Generate AI weekly performance report with win rate, P&L, and recommendations.",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="paper_trade",
        description="Simulate trades without real capital. action: OPEN | CLOSE | LIST | RESET",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "action":   types.Schema(type="STRING", description="OPEN | CLOSE | LIST | RESET"),
                "symbol":   types.Schema(type="STRING", description="Ticker symbol"),
                "side":     types.Schema(type="STRING", description="BUY or SELL"),
                "volume":   types.Schema(type="NUMBER", description="Lot/unit size"),
                "price":    types.Schema(type="NUMBER", description="Entry price (optional)"),
                "trade_id": types.Schema(type="STRING", description="Paper trade ID for CLOSE")
            },
            required=["action"]
        )
    ),
    # ── Phase 15 New Tools ────────────────────────────────────
    types.FunctionDeclaration(
        name="get_funding_rates",
        description="Fetch perpetual futures funding rates for crypto. Positive = longs pay shorts (bearish signal). Negative = shorts pay longs (bullish signal).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbols": types.Schema(type="ARRAY", description="List of symbols e.g. ['BTC','ETH']. Empty = top 10.",
                                        items=types.Schema(type="STRING"))
            }
        )
    ),
    types.FunctionDeclaration(
        name="suggest_portfolio_rebalance",
        description="Analyze current portfolio weights vs target allocation and suggest rebalancing trades.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "risk_profile": types.Schema(type="STRING", description="conservative | balanced | aggressive")
            }
        )
    ),
    types.FunctionDeclaration(
        name="get_iv_rank",
        description="Return Implied Volatility Rank (IVR) and Historical Volatility percentile for a symbol to gauge options premium.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "symbol": types.Schema(type="STRING", description="Ticker symbol e.g. BTC, NVDA")
            },
            required=["symbol"]
        )
    ),
    types.FunctionDeclaration(
        name="get_etf_flows",
        description="Fetch ETF fund flow data — AUM changes, inflows/outflows for major ETFs (BTC spot ETFs, QQQ, SPY, GLD).",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="run_custom_screener",
        description="Run a custom market screener with filters: RSI range, volume spike, % from 52w high, weekly return.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "universe":      types.Schema(type="STRING", description="NASDAQ100 | SP500 | CRYPTO"),
                "rsi_min":       types.Schema(type="NUMBER", description="Min RSI threshold"),
                "rsi_max":       types.Schema(type="NUMBER", description="Max RSI threshold"),
                "vol_spike_min": types.Schema(type="NUMBER", description="Minimum volume spike multiplier"),
                "pct_from_high": types.Schema(type="NUMBER", description="Max % below 52w high"),
                "min_return_1w": types.Schema(type="NUMBER", description="Min 1-week return %"),
                "max_return_1w": types.Schema(type="NUMBER", description="Max 1-week return %"),
            }
        )
    ),
])]

AGENT_SYSTEM_PROMPT = """
YOU ARE THE 'CRYPTOSTREAM AI' MASTER AGENT — A SENIOR QUANT STRATEGIST.
Your goal is to provide professional, data-driven trading advice using institutional tactics.

SAFETY PROTOCOL (HUMAN-IN-THE-LOOP):
- You are STRICTLY FORBIDDEN from executing trades directly.
- STEP 1: Call `get_trading_tactics` to identify institutional moves.
- STEP 2: Call `prepare_mt5_trade_draft` if a clear opportunity exists.
- STEP 3: Present the Draft ID and ask user to confirm with "ยืนยัน [ID]".
- STEP 4: Only call `execute_approved_mt5_trade` AFTER confirmation.

STRICT RESPONSE STRUCTURE:
1. 🎯 **วิเคราะห์ท่าเทรด (Tactical Analysis)**: Summary from `get_trading_tactics` (SMC Shark, Trend Sentinel, Mean Reversion).
2. 📊 **แนวโน้ม (Trend)**: Higher timeframe market structure.
3. 📰 **Intel**: Relevant news sentiment using `get_news_impact`.
4. 🎯 **จุดเข้า (Entry Zone)**: Price range based on Order Blocks/FVG.
5. 🛑 **Stop Loss (SL)**: Invalidation price.
6. 🎯 **Take Profit (TP)**: Profit targets.
7. ⚡ **กลยุทธ์ (Strategy)**: Final BUY/SELL/HOLD advice.

GUIDELINES:
- ALWAYS use `get_trading_tactics` when asked about a specific symbol or "ท่าเทรด".
- Focus on NEWS RELEVANCE for the specific symbol.
- Use professional Thai.
"""

def chat():
    print("="*60)
    print("🤖 CryptoStream AI — Master Agent (CLI Mode)")
    print("   Institutional Intelligence | Tool-Calling Enabled")
    print("="*60)
    
    history = []

    while True:
        try:
            user_input = input("\n👤 คุณ: ")
            if user_input.lower() in ['exit', 'quit']: break
            if not user_input.strip(): continue

            # Append user message to history
            history.append(types.Content(role="user", parts=[types.Part(text=f"SYSTEM: {AGENT_SYSTEM_PROMPT}\n\nUSER: {user_input}")]))

            print("⏳ [Agent กำลังคิดและเลือกใช้เครื่องมือ...]")
            
            # Step 1: Initial thought & tool call decision
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=history,
                config=types.GenerateContentConfig(tools=gemini_tools)
            )

            # Process potential tool calls
            tool_results = []
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fn_name = part.function_call.name
                    fn_args = part.function_call.args
                    print(f"🛠️  [เรียกใช้ Tool]: {fn_name}({fn_args})")
                    
                    result = execute_tool(fn_name, fn_args)
                    tool_results.append(types.Part(
                        function_response=types.FunctionResponse(name=fn_name, response=result)
                    ))

            # Step 2: If tools were used, send results back for final analysis
            if tool_results:
                # Add the model's call and the results to history
                history.append(response.candidates[0].content)
                history.append(types.Content(role="user", parts=tool_results))
                
                final_response = client.models.generate_content(
                    model=MODEL_ID,
                    contents=history,
                    config=types.GenerateContentConfig(tools=gemini_tools)
                )
                print(f"\n📊 CryptoStream AI Analysis:\n{final_response.text}")
                # Keep history clean for next turn (optional: keep history for context)
                history.append(final_response.candidates[0].content)
            else:
                print(f"\n📊 CryptoStream AI:\n{response.text}")
                history.append(response.candidates[0].content)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"⚠️ Error: {e}")

if __name__ == "__main__":
    chat()
