import asyncio
import os
import logging
from dotenv import load_dotenv
from google import genai
from intelligence.tools.market_tools import get_market_analysis
from intelligence.agents.master_agent import create_master_agent

logging.basicConfig(level=logging.INFO)

async def run_test():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found.")
        return

    client = genai.Client(api_key=api_key)
    
    print("1. Fetching Market Analysis (Triggering Whale Pulse, Technicals, ML)...")
    # This might be sync or async depending on the current version of get_market_analysis
    # We'll just call it normally if it's sync.
    state = get_market_analysis("BTC", "15m", "CRYPTO")
    
    print("2. Synthesizing data through Master Agent (Triggering Macro Shield, Reflector Bias, Confluence)...")
    master = create_master_agent(client)
    result = master(state)
    
    print("\n\n" + "="*50)
    print("FINAL INSTITUTIONAL REPORT")
    print("="*50)
    print(result.get("master_report", "FAILED TO GENERATE REPORT"))
    
if __name__ == "__main__":
    asyncio.run(run_test())
