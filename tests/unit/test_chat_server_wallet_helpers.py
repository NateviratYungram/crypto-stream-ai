from chat_server_wallet_helpers import (
    _build_eth_assets,
    _build_eth_identity,
    _build_eth_portfolio_result,
    _is_eth_address,
)


def test_is_eth_address_validates_hex_wallets():
    assert _is_eth_address("0x" + "a" * 40)
    assert not _is_eth_address("0x123")
    assert not _is_eth_address("btc-wallet")


def test_build_eth_assets_filters_dust_and_computes_allocations():
    assets, total_usd = _build_eth_assets(
        {
            "ETH": {"balance": 2, "price": {"rate": 3000, "diff": 1.5}},
            "tokens": [
                {
                    "balance": "5000000",
                    "tokenInfo": {
                        "symbol": "usdc",
                        "name": "USD Coin",
                        "decimals": "6",
                        "address": "0x1",
                        "image": "logo",
                        "price": {"rate": 1.0, "diff": -0.1},
                    },
                },
                {
                    "balance": "100000000000000000",
                    "tokenInfo": {
                        "symbol": "dust",
                        "decimals": "18",
                        "price": {"rate": 0},
                    },
                },
            ],
        }
    )

    assert total_usd == 6005.0
    assert assets[0]["symbol"] == "ETH"
    assert assets[1]["symbol"] == "USDC"
    assert assets[1]["usd_value"] == 5.0
    assert assets[0]["allocation"] > assets[1]["allocation"]


def test_build_eth_assets_handles_bad_decimals_and_zero_balances():
    assets, total_usd = _build_eth_assets(
        {
            "tokens": [
                {"balance": 0, "tokenInfo": {"symbol": "skip", "price": {"rate": 1}}},
                {"balance": "25", "tokenInfo": {"symbol": "bad", "decimals": "oops", "price": {"rate": 2}}},
                {"balance": "0.5", "tokenInfo": {"symbol": "tiny", "price": {"rate": 1}}},
            ]
        }
    )

    assert total_usd == 50.0
    assert len(assets) == 1
    assert assets[0]["symbol"] == "BAD"


def test_build_eth_identity_and_result_shape_payload():
    identity = _build_eth_identity({"display_name": "Whale", "twitter": "@whale"}, "https://etherscan.io/address/0xabc")
    assert _build_eth_identity(None, "https://etherscan.io/address/0xabc") is None
    result = _build_eth_portfolio_result(
        address="0xabc",
        explorer_url="https://etherscan.io/address/0xabc",
        assets=[{"symbol": "ETH", "usd_value": 10}],
        total_usd=10.0,
        identity={"display_name": "Whale"},
    )

    assert identity["display_name"] == "Whale"
    assert identity["explorer_url"].endswith("0xabc")
    assert result["chain"] == "ETH"
    assert result["identity"]["display_name"] == "Whale"
