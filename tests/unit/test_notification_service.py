import asyncio

from services.notification_service import NotificationService
from tests.fakes.fake_http import FakeAsyncHttpClient, FakeHttpResponse


def make_service(monkeypatch, token="123456789012345678901234567890:token", chat_id="12345", allowed="111,222"):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", chat_id)
    monkeypatch.setenv("TELEGRAM_ALLOWED_CHAT_IDS", allowed)
    return NotificationService()


def test_status_and_allowed_chat_logic(monkeypatch):
    service = make_service(monkeypatch)

    status = service.telegram_status()

    assert status["configured"] is True
    assert status["token_format_ok"] is True
    assert status["chat_id_format_ok"] is True
    assert service.is_chat_allowed("111") is True
    assert service.is_chat_allowed("12345") is True
    assert service.is_chat_allowed("999") is False


def test_build_helpers(monkeypatch):
    service = make_service(monkeypatch)

    assert service._telegram_url("sendMessage").endswith("/sendMessage")
    assert "CryptoStream AI Alert" in service._alert_text("Hello")
    payload = service._build_message_payload("1", "x" * 5000, reply_markup={"k": 1})
    assert payload["text"] == "x" * 3900
    assert payload["reply_markup"] == {"k": 1}


def test_make_async_client_and_status_when_missing(monkeypatch):
    service = make_service(monkeypatch, token="short", chat_id="abc", allowed="")

    default_client = service._make_async_client()
    timed_client = service._make_async_client(timeout=3)
    try:
        status = service.telegram_status()
        assert isinstance(default_client, object)
        assert isinstance(timed_client, object)
        assert status["configured"] is True
        assert status["token_format_ok"] is False
        assert status["chat_id_format_ok"] is False
        assert service.is_chat_allowed("1") is False
    finally:
        asyncio.run(default_client.aclose())
        asyncio.run(timed_client.aclose())


def test_status_marks_missing_fields(monkeypatch):
    service = make_service(monkeypatch, token="", chat_id="", allowed="")

    status = service.telegram_status()

    assert status["configured"] is False
    assert status["missing"] == ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    assert status["polling_ready"] is False


def test_extract_response_error_handles_json_and_plain_text(monkeypatch):
    service = make_service(monkeypatch)
    from_json = service._extract_response_error(FakeHttpResponse(status_code=400, payload={"error_code": 401, "description": "bad"}))
    from_text = service._extract_response_error(FakeHttpResponse(status_code=500, payload=ValueError("nojson"), text="server exploded"))

    assert from_json == {"status_code": 400, "error_code": 401, "description": "bad"}
    assert from_text["description"] == "server exploded"


def test_send_alert_missing_target_sets_error(monkeypatch):
    service = make_service(monkeypatch, token="", chat_id="")

    result = asyncio.run(service.send_telegram_alert("hello"))

    assert result is False
    assert service.last_error == {"reason": "missing_token_or_chat_id"}


def test_send_alert_success_and_failure(monkeypatch):
    service = make_service(monkeypatch)
    success_client = FakeAsyncHttpClient(post_response=FakeHttpResponse(status_code=200))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: success_client)

    success = asyncio.run(service.send_telegram_alert("hello", reply_markup={"inline_keyboard": []}))

    assert success is True
    assert success_client.requests[0]["timeout"] == 5
    assert success_client.requests[0]["json"]["parse_mode"] == "Markdown"

    failure_client = FakeAsyncHttpClient(post_response=FakeHttpResponse(status_code=403, payload={"error_code": 403, "description": "forbidden"}))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: failure_client)
    failure = asyncio.run(service.send_telegram_alert("hello"))
    assert failure is False
    assert service.last_error["description"] == "forbidden"


def test_send_message_and_callback_query(monkeypatch):
    service = make_service(monkeypatch)
    client = FakeAsyncHttpClient(post_response=FakeHttpResponse(status_code=200))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: client)

    sent = asyncio.run(service.send_telegram_message("777", "hello world"))
    answered = asyncio.run(service.answer_callback_query("cbid", "ok"))

    assert sent is True
    assert answered is True
    assert client.requests[0]["json"]["disable_web_page_preview"] is True
    assert client.requests[1]["json"]["text"] == "ok"


def test_send_message_exception_and_delete_webhook_failure(monkeypatch):
    service = make_service(monkeypatch)
    error_client = FakeAsyncHttpClient(post_error=RuntimeError("network down"))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: error_client)

    sent = asyncio.run(service.send_telegram_message("777", "hello world"))
    assert sent is False
    assert service.last_error["reason"] == "exception"

    failure_client = FakeAsyncHttpClient(post_response=FakeHttpResponse(status_code=500, payload=ValueError("bad"), text="oops"))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: failure_client)
    deleted = asyncio.run(service.delete_webhook())
    assert deleted is False
    assert service.last_error["status_code"] == 500


def test_send_message_missing_target_and_error_response(monkeypatch):
    service = make_service(monkeypatch, token="", chat_id="")
    assert asyncio.run(service.send_telegram_message("", "hello")) is False
    assert service.last_error == {"reason": "missing_token_or_chat_id"}

    service = make_service(monkeypatch)
    failure_client = FakeAsyncHttpClient(post_response=FakeHttpResponse(status_code=400, payload={"error_code": 400, "description": "bad request"}))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: failure_client)
    assert asyncio.run(service.send_telegram_message("777", "hello")) is False
    assert service.last_error["error_code"] == 400


def test_callback_and_webhook_cover_missing_and_exception_paths(monkeypatch):
    service = make_service(monkeypatch, token="", chat_id="12345")
    assert asyncio.run(service.answer_callback_query("cbid")) is False
    assert asyncio.run(service.delete_webhook()) is False

    service = make_service(monkeypatch)
    error_client = FakeAsyncHttpClient(post_error=RuntimeError("callback exploded"))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: error_client)
    assert asyncio.run(service.answer_callback_query("cbid")) is False
    assert service.last_error["reason"] == "exception"

    success_client = FakeAsyncHttpClient(post_response=FakeHttpResponse(status_code=200))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: success_client)
    assert asyncio.run(service.delete_webhook()) is True
    assert service.last_error is None


def test_get_updates_handles_missing_token_failure_and_success(monkeypatch):
    service = make_service(monkeypatch, token="", chat_id="12345")
    assert asyncio.run(service.get_updates()) == []
    assert service.last_error == {"reason": "missing_token"}

    service = make_service(monkeypatch)
    bad_client = FakeAsyncHttpClient(get_response=FakeHttpResponse(status_code=429, payload={"error_code": 429, "description": "slow down"}))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: bad_client)
    assert asyncio.run(service.get_updates(timeout=11, limit=9)) == []
    assert service.last_error["error_code"] == 429

    good_client = FakeAsyncHttpClient(get_response=FakeHttpResponse(status_code=200, payload={"result": [{"update_id": 3}, {"update_id": 7}, {"x": 1}]}))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: good_client)
    updates = asyncio.run(service.get_updates(timeout=11, limit=9))
    assert len(updates) == 3
    assert service.last_update_id == 7
    assert good_client.requests[0]["params"] == {"timeout": 11, "limit": 9}

    updates = asyncio.run(service.get_updates(timeout=11, limit=9))
    assert good_client.requests[1]["params"]["offset"] == 8


def test_empty_allowed_chat_ids_are_rejected(monkeypatch):
    service = make_service(monkeypatch, allowed="")

    assert service.allowed_chat_ids == {"12345"}
    service.allowed_chat_ids.clear()
    assert service.is_chat_allowed("12345") is False


def test_send_alert_exception_path_sets_last_error(monkeypatch):
    service = make_service(monkeypatch)
    error_client = FakeAsyncHttpClient(post_error=RuntimeError("alert exploded"))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: error_client)

    sent = asyncio.run(service.send_telegram_alert("boom"))

    assert sent is False
    assert service.last_error == {"reason": "exception", "description": "alert exploded"}


def test_answer_callback_non_200_sets_error(monkeypatch):
    service = make_service(monkeypatch)
    client = FakeAsyncHttpClient(
        post_response=FakeHttpResponse(
            status_code=409,
            payload={"error_code": 409, "description": "already answered"},
        )
    )
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: client)

    answered = asyncio.run(service.answer_callback_query("cbid"))

    assert answered is False
    assert service.last_error["error_code"] == 409


def test_delete_webhook_exception_sets_last_error(monkeypatch):
    service = make_service(monkeypatch)
    client = FakeAsyncHttpClient(post_error=RuntimeError("webhook exploded"))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: client)

    deleted = asyncio.run(service.delete_webhook())

    assert deleted is False
    assert service.last_error == {"reason": "exception", "description": "webhook exploded"}


def test_get_updates_exception_path(monkeypatch):
    service = make_service(monkeypatch)
    error_client = FakeAsyncHttpClient(get_error=RuntimeError("poll failed"))
    monkeypatch.setattr(service, "_make_async_client", lambda timeout=None: error_client)

    assert asyncio.run(service.get_updates()) == []
    assert service.last_error["reason"] == "exception"


def test_broadcast_and_template_notifications(monkeypatch):
    service = make_service(monkeypatch)
    sent_messages = []

    async def fake_alert(message, chat_id=None, reply_markup=None):
        sent_messages.append(message)
        return True

    monkeypatch.setattr(service, "send_telegram_alert", fake_alert)

    assert asyncio.run(service.broadcast("hello")) is True
    assert asyncio.run(service.notify_paper_trade_opened("BTCUSD", "BUY", 100.5, 0.72, "abcdef123456")) is True
    assert asyncio.run(service.notify_paper_trade_closed("BTCUSD", "WIN", "tp", exit_price=101.2, pnl_usd=1.25)) is True
    assert asyncio.run(service.notify_whale({"symbol": "ETHUSD", "quantity": 2, "price": 1000})) is True
    assert asyncio.run(service.notify_risk("high volatility")) is True
    assert asyncio.run(service.notify_trade_draft("BTCUSD", "SELL", "draft-1", 99.9)) is True
    assert asyncio.run(service.notify_alert_triggered("BTCUSD", "RSI > 70", "71")) is True
    assert asyncio.run(service.notify_market_opened("US Stocks")) is True
    assert asyncio.run(service.notify_market_closed("US Stocks", "Holiday")) is True
    assert asyncio.run(service.notify_system_startup()) is True

    assert len(sent_messages) == 10
    assert any("Paper Trade Opened" in msg for msg in sent_messages)
    assert any("System Online" in msg for msg in sent_messages)


def test_trade_closed_template_omits_optional_lines(monkeypatch):
    service = make_service(monkeypatch)
    sent_messages = []

    async def fake_alert(message, chat_id=None, reply_markup=None):
        sent_messages.append(message)
        return True

    monkeypatch.setattr(service, "send_telegram_alert", fake_alert)

    assert asyncio.run(service.notify_paper_trade_closed("BTCUSD", "LOSS", "sl")) is True
    assert "Exit:" not in sent_messages[0]
    assert "PnL:" not in sent_messages[0]
