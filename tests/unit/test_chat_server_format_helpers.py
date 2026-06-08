from chat_server_format_helpers import (
    _format_historical_stock_rankings,
    _format_index_historical_summary,
)


def test_format_historical_stock_rankings_handles_error_and_empty():
    assert "couldn't rank" in _format_historical_stock_rankings({"status": "ERROR", "error": "down"}, language="en")
    assert "ยังไม่มีข้อมูล" in _format_historical_stock_rankings({"status": "SUCCESS", "results": []}, language="th")


def test_format_historical_stock_rankings_renders_en_and_th():
    summary = {
        "status": "SUCCESS",
        "years": 5,
        "direction": "top",
        "universe": "NASDAQ100",
        "as_of": "2026-05-26",
        "full_window_only": True,
        "results": [
            {"symbol": "NVDA", "total_return_pct": 120.0, "cagr_pct": 17.5, "max_drawdown_pct": 22.0},
            {"symbol": "MSFT", "total_return_pct": 80.0, "cagr_pct": 12.0, "max_drawdown_pct": 18.0},
        ],
    }

    rendered_en = _format_historical_stock_rankings(summary, language="en")
    rendered_th = _format_historical_stock_rankings(summary, language="th")

    assert "Top 2 best-performing stocks" in rendered_en
    assert "NVDA" in rendered_en
    assert "Note:" in rendered_en
    assert "หุ้น 2 ตัวแรกที่ขึ้นมากที่สุด" in rendered_th
    assert "MSFT" in rendered_th


def test_format_index_historical_summary_handles_error_and_empty():
    assert "couldn't pull" in _format_index_historical_summary({"status": "ERROR", "error": "down"}, language="en")
    assert "ยังไม่มีข้อมูล" in _format_index_historical_summary({"status": "SUCCESS", "indices": {}}, language="th")


def test_format_index_historical_summary_renders_snapshots_and_summary():
    summary = {
        "status": "SUCCESS",
        "years": 10,
        "ranking": ["NASDAQ_100", "SP500"],
        "best_index": "NASDAQ_100",
        "worst_index": "SP500",
        "indices": {
            "NASDAQ_100": {
                "label": "NASDAQ 100",
                "end_date": "2026-05-26",
                "total_return_pct": 250.0,
                "cagr_pct": 13.0,
                "max_drawdown_pct": 28.0,
                "trend": "bullish",
                "current_vs_ma200_pct": 8.5,
                "current_vs_ma50_pct": 3.2,
            },
            "SP500": {
                "label": "S&P 500",
                "end_date": "2026-05-26",
                "total_return_pct": 150.0,
                "cagr_pct": 9.0,
                "max_drawdown_pct": 24.0,
                "trend": "mixed",
                "current_vs_ma200_pct": 2.1,
                "current_vs_ma50_pct": -0.4,
            },
        },
    }

    rendered_en = _format_index_historical_summary(summary, language="en")
    rendered_th = _format_index_historical_summary(summary, language="th")

    assert "10-year view of the requested US indices" in rendered_en
    assert "Summary: NASDAQ 100 led this 10-year period" in rendered_en
    assert "ภาพรวมย้อนหลัง 10 ปีของดัชนีที่ถามมา" in rendered_th
    assert "สรุป: ช่วง 10 ปีนี้ NASDAQ 100 ทำผลงานเด่นสุด" in rendered_th
