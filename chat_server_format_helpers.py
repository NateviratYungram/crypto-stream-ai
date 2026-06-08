from __future__ import annotations


def _format_historical_stock_rankings(summary: dict, language: str = "th") -> str:
    if summary.get("status") != "SUCCESS":
        error = summary.get("error", "unknown error")
        if language == "en":
            return f"I couldn't rank the historical stock performers yet: {error}"
        return f"ผมยังจัดอันดับหุ้นย้อนหลังให้ไม่ได้ครับ: {error}"

    years = int(summary.get("years") or 10)
    direction = summary.get("direction") or "top"
    universe = summary.get("universe") or "COMBINED"
    as_of = summary.get("as_of") or "-"
    results = list(summary.get("results") or [])
    if not results:
        return "No ranking data returned." if language == "en" else "ยังไม่มีข้อมูลอันดับส่งกลับมาครับ"

    universe_label = {
        "NASDAQ100": "NASDAQ 100",
        "SP500": "S&P 500",
        "COMBINED": "NASDAQ 100 + S&P 500",
    }.get(str(universe).upper(), str(universe))

    if language == "en":
        title = (
            f"Top {len(results)} best-performing stocks over the last {years} years"
            if direction == "top"
            else f"Top {len(results)} biggest stock losers over the last {years} years"
        )
        lines = [f"{title} from the tracked {universe_label} universe (as of {as_of}):"]
        for idx, item in enumerate(results, start=1):
            lines.append(
                f"{idx}. {item['symbol']}: total return {item['total_return_pct']:+.2f}%, "
                f"CAGR {item['cagr_pct']:+.2f}%, max drawdown {item['max_drawdown_pct']:.2f}%"
            )
        if summary.get("full_window_only"):
            lines.append("Note: this ranking only includes stocks with near-full history across the requested window.")
        return "\n".join(lines)

    title = (
        f"หุ้น {len(results)} ตัวแรกที่ขึ้นมากที่สุดในช่วง {years} ปี"
        if direction == "top"
        else f"หุ้น {len(results)} ตัวแรกที่ลงมากที่สุดในช่วง {years} ปี"
    )
    lines = [f"{title} จากจักรวาลหุ้น {universe_label} ที่ระบบติดตามอยู่ (ข้อมูลล่าสุดถึง {as_of}):"]
    for idx, item in enumerate(results, start=1):
        lines.append(
            f"{idx}. {item['symbol']}: ผลตอบแทนรวม {item['total_return_pct']:+.2f}%, "
            f"CAGR {item['cagr_pct']:+.2f}% ต่อปี, max drawdown {item['max_drawdown_pct']:.2f}%"
        )
    if summary.get("full_window_only"):
        lines.append("หมายเหตุ: รอบนี้นับเฉพาะหุ้นที่มีข้อมูลใกล้ครบทั้งช่วงเวลาที่ขอ เพื่อไม่ให้หุ้นที่เพิ่งเข้าตลาดมาปนครับ")
    return "\n".join(lines)


def _format_index_historical_summary(summary: dict, language: str = "th") -> str:
    if summary.get("status") != "SUCCESS":
        error = summary.get("error", "unknown error")
        if language == "en":
            return f"I couldn't pull the historical index summary yet: {error}"
        return f"ผมยังดึงสรุปดัชนีย้อนหลังไม่ได้ครับ: {error}"

    years = int(summary.get("years") or 10)
    indices = summary.get("indices") or {}
    ranking = summary.get("ranking") or list(indices.keys())
    if not indices:
        return "No index summary data returned." if language == "en" else "ยังไม่มีข้อมูลสรุปดัชนีส่งกลับมาครับ"

    def trend_label(value: str) -> str:
        mapping_en = {"bullish": "bullish", "mixed": "mixed", "bearish": "bearish"}
        mapping_th = {"bullish": "ยังเป็นขาขึ้น", "mixed": "ผสม", "bearish": "อ่อนแรง"}
        return (mapping_en if language == "en" else mapping_th).get(str(value or "").lower(), str(value or "-"))

    ordered = [key for key in ranking if key in indices]
    if language == "en":
        lines = [f"{years}-year view of the requested US indices (latest data through {indices[ordered[0]].get('end_date')}):"]
        for idx, key in enumerate(ordered, start=1):
            item = indices[key]
            lines.append(
                f"{idx}. {item['label']}: total return {item['total_return_pct']:+.2f}%, "
                f"CAGR {item['cagr_pct']:+.2f}%, max drawdown {item['max_drawdown_pct']:.2f}%"
            )
        lines.append("Current snapshot:")
        for key in ordered:
            item = indices[key]
            vs200 = item.get("current_vs_ma200_pct")
            vs50 = item.get("current_vs_ma50_pct")
            lines.append(
                f"- {item['label']}: {trend_label(item.get('trend'))}, "
                f"{vs200:+.2f}% vs MA200 and {vs50:+.2f}% vs MA50"
            )
        best_key = summary.get("best_index")
        worst_key = summary.get("worst_index")
        if best_key in indices and worst_key in indices:
            lines.append(
                f"Summary: {indices[best_key]['label']} led this {years}-year period, while {indices[worst_key]['label']} lagged the group."
            )
        return "\n".join(lines)

    lines = [f"ภาพรวมย้อนหลัง {years} ปีของดัชนีที่ถามมา (ข้อมูลล่าสุดถึง {indices[ordered[0]].get('end_date')}):"]
    for idx, key in enumerate(ordered, start=1):
        item = indices[key]
        lines.append(
            f"{idx}. {item['label']}: ผลตอบแทนรวม {item['total_return_pct']:+.2f}%, "
            f"CAGR {item['cagr_pct']:+.2f}% ต่อปี, max drawdown {item['max_drawdown_pct']:.2f}%"
        )
    lines.append("ภาพปัจจุบัน:")
    for key in ordered:
        item = indices[key]
        vs200 = item.get("current_vs_ma200_pct")
        vs50 = item.get("current_vs_ma50_pct")
        lines.append(
            f"- {item['label']}: {trend_label(item.get('trend'))}, "
            f"อยู่ {vs200:+.2f}% เทียบ MA200 และ {vs50:+.2f}% เทียบ MA50"
        )
    best_key = summary.get("best_index")
    worst_key = summary.get("worst_index")
    if best_key in indices and worst_key in indices:
        lines.append(
            f"สรุป: ช่วง {years} ปีนี้ {indices[best_key]['label']} ทำผลงานเด่นสุด ส่วน {indices[worst_key]['label']} อ่อนกว่ากลุ่ม"
        )
    return "\n".join(lines)
