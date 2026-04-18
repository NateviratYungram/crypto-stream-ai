import requests
import pandas as pd
import json
import os
import logging
import re
from io import StringIO

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ticker_refresh")

# Use absolute paths context
WORKSPACE_DIR = r"c:\Users\pea01\OneDrive\Desktop\crypto-stream-ai"
DATA_DIR = os.path.join(WORKSPACE_DIR, "intelligence", "market_data")
OUTPUT_FILE = os.path.join(DATA_DIR, "index_tickers.json")

def fetch_nasdaq_tickers():
    """Fetch symbols from Nasdaq's official directory."""
    logger.info("📡 Fetching NASDAQ symbols...")
    url = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        lines = resp.text.splitlines()
        # Symbol|Security Name|Market Category...
        symbols = [line.split('|')[0] for line in lines[1:-1] if '|' in line]
        return [s.strip() for s in symbols if s.strip() and not s.startswith("File")]
    except Exception as e:
        logger.error(f"❌ Failed to fetch NASDAQ: {e}")
        return []

def fetch_other_tickers():
    """Fetch symbols from NYSE/AMEX listed in the official directory."""
    logger.info("📡 Fetching NYSE/AMEX symbols...")
    url = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        lines = resp.text.splitlines()
        # ACT Symbol|Security Name|Exchange...
        symbols = [line.split('|')[0] for line in lines[1:-1] if '|' in line]
        return [s.strip() for s in symbols if s.strip() and not s.startswith("File")]
    except Exception as e:
        logger.error(f"❌ Failed to fetch Other: {e}")
        return []

def fetch_sp500_tickers():
    """Fetch symbols from Wikipedia's S&P 500 list with headers to avoid 403."""
    logger.info("📡 Fetching S&P 500 from Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        df = tables[0]
        symbols = [str(s).replace('.', '-') for s in df['Symbol'].tolist()]
        return symbols
    except Exception as e:
        logger.error(f"❌ Failed SP500: {e}")
        return []

def fetch_nasdaq100_tickers():
    """Fetch symbols from Wikipedia's NASDAQ 100 list with headers to avoid 403."""
    logger.info("📡 Fetching NASDAQ 100 from Wikipedia...")
    try:
        url = "https://en.wikipedia.org/wiki/Nasdaq-100"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text))
        for df in tables:
            if 'Ticker' in df.columns:
                return [str(s).replace('.', '-') for s in df['Ticker'].tolist()]
    except Exception as e:
        logger.error(f"❌ Failed NQ100: {e}")
        return []

def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

    nasdaq = fetch_nasdaq_tickers()
    other  = fetch_other_tickers()
    sp500  = fetch_sp500_tickers()
    nq100  = fetch_nasdaq100_tickers()

    data = {
        "updated_at": pd.Timestamp.now().isoformat(),
        "indices": {
            "SP500": sorted(list(set(sp500))),
            "NASDAQ_100": sorted(list(set(nq100)))
        },
        "exchanges": {
            "NASDAQ": sorted(list(set(nasdaq))),
            "NYSE_AMEX": sorted(list(set(other)))
        }
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.info(f"✅ Success! Saved to {OUTPUT_FILE}")
    logger.info(f"Summary: SP500({len(sp500)}), NQ100({len(nq100)}), NASDAQ Total({len(nasdaq)}), Other Total({len(other)})")

if __name__ == "__main__":
    main()
