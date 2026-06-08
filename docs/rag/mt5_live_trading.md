# MT5 Live Trading Knowledge

The MetaTrader 5 integration is split into two parts because Docker cannot directly use the Windows MT5 terminal runtime. The Docker app talks to a local HTTP bridge running on the Windows host. The bridge imports the `MetaTrader5` Python package, talks to the logged-in terminal, and exposes controlled endpoints for health, account info, quotes, rates, positions, order placement, close, and modify actions.

The bridge is protected by `MT5_BRIDGE_API_KEY`. Docker calls it through `MT5_BRIDGE_URL`, usually `http://host.docker.internal:8765`. When using that Docker host alias, the bridge should bind to `0.0.0.0` on Windows so the container can reach it. Live order placement is controlled by `MT5_BRIDGE_ENABLE_LIVE_TRADING`. If live trading is disabled, read-only checks can still work but trade requests should be rejected.

Live trading readiness requires:

- MT5 terminal installed on Windows.
- Broker account logged in inside MT5.
- Python `MetaTrader5` package installed in the host Python used by the bridge.
- Bridge process running on the configured port.
- Docker `chat-server` configured with matching bridge URL and API key.
- Account endpoint returning connected status.
- Quote endpoint returning bid/ask for the requested symbol.
- Live trading flag enabled only after safety checks pass.

The safest workflow before a real order is:

- Confirm `/api/mt5/account` shows the expected demo or live account.
- Confirm `/api/mt5/quote?symbol=...` returns a fresh bid and ask.
- Confirm there are no unexpected open positions.
- Validate symbol, side, volume, stop loss, take profit, and deviation.
- Use the smallest safe test volume on a demo account first.
- Never place an order without explicit user confirmation of symbol, side, volume, and risk parameters.

RAG should explain MT5 behavior but should not decide to trade by itself. Trading actions must use live MT5 endpoints and risk logic. RAG can answer "how does the MT5 bridge work?" or "what checks are required before trading?" but current account balance and quotes must come from live APIs.

In Thai: MT5 bridge คือสะพานระหว่าง Docker กับโปรแกรม MetaTrader 5 บน Windows. RAG ช่วยอธิบายวิธีทำงานและ checklist ความปลอดภัย แต่การส่งคำสั่งจริงต้องใช้ API สดและต้องให้ผู้ใช้ยืนยันรายละเอียดคำสั่งก่อน.
