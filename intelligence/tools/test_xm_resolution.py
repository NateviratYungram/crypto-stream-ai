import sys
import os
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from intelligence.tools.market_tools import _normalize_broker_symbol

def test_xm_resolution():
    print("--- Testing XM Broker Symbol Resolution ---")

    # Mock XM Global account
    mock_acc_xm = {"company": "XM Global Limited"}

    with patch('intelligence.mt5_connector.get_mt5_account_info', return_value=mock_acc_xm), \
         patch('intelligence.mt5_connector._MT5_AVAILABLE', True):

        print("\n1. Testing Indices (NASDAQ)...")
        res = _normalize_broker_symbol("NASDAQ")
        print(f"Candidates for NASDAQ: {res}")
        assert "US100Cash" in res
        print("OK: US100Cash found.")

        print("\n2. Testing Stocks (NVDA)...")
        res = _normalize_broker_symbol("NVDA")
        print(f"Candidates for NVDA: {res}")
        assert "NVDA#" in res
        print("OK: NVDA# found.")

        print("\n3. Testing Gold (XAUUSD)...")
        res = _normalize_broker_symbol("GOLD")
        print(f"Candidates for GOLD: {res}")
        assert "GOLD" in res
        print("OK: GOLD found.")

        print("\n4. Testing Crypto (BTC)...")
        res = _normalize_broker_symbol("BTC")
        print(f"Candidates for BTC: {res}")
        assert "BTCUSD" in res
        print("OK: BTCUSD found.")

    # Mock non-XM account
    mock_acc_other = {"company": "Generic Broker"}
    with patch('intelligence.mt5_connector.get_mt5_account_info', return_value=mock_acc_other), \
         patch('intelligence.mt5_connector._MT5_AVAILABLE', True):

        print("\n5. Testing non-XM account (NASDAQ)...")
        res = _normalize_broker_symbol("NASDAQ")
        print(f"Candidates for NASDAQ: {res}")
        assert "US100Cash" not in res[:1] # Should not be the top priority
        print("OK: Generic resolution applied.")

if __name__ == "__main__":
    try:
        test_xm_resolution()
        print("\n[FINAL RESULT] ALL XM RESOLUTION TESTS PASSED! ✅")
    except Exception as e:
        print(f"\n[FINAL RESULT] TEST FAILED: {e}")
        sys.exit(1)
