from chat_server_telegram_helpers import (
    _telegram_extract_profile_patch,
    _telegram_format_readiness,
    _telegram_profile_text,
)


def test_telegram_extract_profile_patch_updates_preferences():
    patch = _telegram_extract_profile_patch(
        "remember BTC GOLD lot 0.01 risk 1% answer in english short",
        lambda text: ["BTC", "GOLD"],
        user={"username": "alice", "first_name": "Alice"},
    )

    assert patch["username"] == "alice"
    assert patch["first_name"] == "Alice"
    assert patch["language"] == "en"
    assert patch["answer_style"] == "concise"
    assert patch["preferred_symbols"] == ["BTC", "GOLD"]
    assert patch["default_lot"] == 0.01
    assert patch["risk_pct"] == 1.0


def test_telegram_extract_profile_patch_handles_thai_and_detailed():
    patch = _telegram_extract_profile_patch(
        "จำ BTC ใช้ lot 0.5 เสี่ยง 12% ละเอียด",
        lambda text: ["BTC"],
    )

    assert patch["language"] == "th"
    assert patch["answer_style"] == "detailed"
    assert patch["preferred_symbols"] == ["BTC"]
    assert patch["default_lot"] == 0.5
    assert patch["risk_pct"] == 10.0


def test_telegram_profile_text_renders_defaults_and_values():
    rendered = _telegram_profile_text(
        {
            "preferred_symbols": ["BTC", "GOLD"],
            "default_lot": 0.01,
            "risk_pct": 1.0,
            "language": "en",
            "answer_style": "detailed",
        }
    )

    assert "BTC, GOLD" in rendered
    assert "0.01" in rendered
    assert "1.0%" in rendered
    assert "Language: en" in rendered


def test_telegram_format_readiness_summarizes_flags():
    rendered = _telegram_format_readiness(
        {
            "overall_percent": 88,
            "ready_for_users": True,
            "ready_for_notifications": False,
            "ready_for_mt5_execution": True,
            "ready_for_live_ai_trading": False,
            "checks": {
                "mt5": {"connected": True},
                "ai_trading_quality": {"mode": "shadow", "blockers": ["paper_labels_low", "mt5_history"]},
            },
        }
    )

    assert "Overall: 88%" in rendered
    assert "User chat: READY" in rendered
    assert "Telegram: NOT READY" in rendered
    assert "AI mode: shadow" in rendered
    assert "paper_labels_low, mt5_history" in rendered
