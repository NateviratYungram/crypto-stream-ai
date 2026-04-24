import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# Ensure the root directory is in the path
sys.path.append(os.getcwd())

from intelligence.execution_bridge import execute_signal
from intelligence.persistence_utils import delete_trade_draft, get_trade_draft


class TestUnifiedDrafting(unittest.TestCase):
    def setUp(self):
        self.mock_state_crypto = {
            "master_decision": "LONG",
            "symbol": "BTC",
            "timeframe": "H4",
            "master_confidence": 0.85,
            "entry_zone": {"low": 60000, "high": 61000},
            "stop_loss": {"price": 59000},
            "take_profit": {"tp1": 65000},
            "indicator_summary": {
                "asset_class": "CRYPTO",
                "price": 60500
            }
        }

        self.mock_state_stock = {
            "master_decision": "LONG",
            "symbol": "AAPL",
            "timeframe": "Daily",
            "master_confidence": 0.90,
            "entry_zone": {"low": 170, "high": 175},
            "stop_loss": {"price": 160},
            "take_profit": {"tp1": 200},
            "indicator_summary": {
                "asset_class": "STOCK",
                "price": 172
            }
        }

    @patch("intelligence.mt5_connector._MT5_AVAILABLE", True)
    @patch("intelligence.mt5_connector.get_mt5_account_info")
    @patch("intelligence.mt5_connector.initialize_mt5")
    @patch("intelligence.mt5_connector.mt5")
    @patch("intelligence.guard_layer.create_guard_agent")
    def test_crypto_draft_persistence(self, mock_guard_create, mock_mt5, mock_init, mock_acc):
        # Mock XM Broker
        mock_acc.return_value = {"company": "XM Global Limited", "balance": 10000}
        mock_init.return_value = True

        # Mock Guard
        mock_guard = MagicMock()
        mock_guard.return_value = {"guard_passed": True, "guard_override_reason": ""}
        mock_guard_create.return_value = mock_guard

        # Mock MT5 symbol_info to return something for BTCUSD
        mock_symbol_info = MagicMock()
        mock_symbol_info.name = "BTCUSD"
        mock_mt5.symbol_info.side_effect = lambda x: mock_symbol_info if x == "BTCUSD" else None

        # Execute Crypto Signal
        result = execute_signal(self.mock_state_crypto, dry_run=False, confirmation_required=True)

        self.assertEqual(result["status"], "DRAFT")
        self.assertIn("BTCUSD-TRADE-PLAN-", result["draft_id"])

        # Check DB
        draft = get_trade_draft(result["draft_id"])
        self.assertIsNotNone(draft)
        self.assertEqual(draft["symbol"], "BTCUSD")

        # Cleanup
        delete_trade_draft(result["draft_id"])

    @patch("intelligence.mt5_connector._MT5_AVAILABLE", True)
    @patch("intelligence.mt5_connector.get_mt5_account_info")
    @patch("intelligence.mt5_connector.initialize_mt5")
    def test_stock_hodl_protection(self, mock_init, mock_acc):
        # Mock ANY Broker
        mock_acc.return_value = {"company": "Generic Broker", "balance": 10000}
        mock_init.return_value = True

        # Execute Stock Signal
        result = execute_signal(self.mock_state_stock, dry_run=False, confirmation_required=True)

        # Status should be HODL, NO Draft ID created
        self.assertEqual(result["status"], "HODL")
        self.assertNotIn("draft_id", result)
        self.assertIn("recommended for long-term accumulation", result["reason"])

if __name__ == "__main__":
    unittest.main()
