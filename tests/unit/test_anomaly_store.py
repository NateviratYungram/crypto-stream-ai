from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from intelligence.ml import anomaly_store


class FakeCursor:
    def __init__(self, fetchall_result=None, fetchone_result=None, rowcounts=None):
        self.fetchall_result = fetchall_result or []
        self.fetchone_result = fetchone_result
        self.rowcounts = list(rowcounts or [])
        self.executed = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.rowcounts:
            self.rowcount = self.rowcounts.pop(0)

    def fetchall(self):
        return self.fetchall_result

    def fetchone(self):
        return self.fetchone_result


class SequenceCursor(FakeCursor):
    def __init__(self, fetchone_results=None, fetchall_results=None):
        super().__init__()
        self._fetchone_results = list(fetchone_results or [])
        self._fetchall_results = list(fetchall_results or [])

    def fetchone(self):
        return self._fetchone_results.pop(0)

    def fetchall(self):
        return self._fetchall_results.pop(0)


class FakeConn:
    def __init__(self, cursors):
        self.cursors = list(cursors)
        self.commit_calls = 0

    def cursor(self, cursor_factory=None):
        return self.cursors.pop(0)

    def commit(self):
        self.commit_calls += 1


def test_db_config_prefers_env_values(monkeypatch):
    monkeypatch.setenv("DB_HOST", "db.internal")
    monkeypatch.setenv("DB_PORT", "15432")
    monkeypatch.setenv("DB_NAME", "main_db")
    monkeypatch.setenv("DB_USER", "reader")
    monkeypatch.setenv("DB_PASS", "secret")

    config = anomaly_store.db_config()

    assert config == {
        "host": "db.internal",
        "port": 15432,
        "dbname": "main_db",
        "user": "reader",
        "password": "secret",
    }


def test_connect_delegates_to_psycopg(monkeypatch):
    captured = {}
    monkeypatch.setattr(anomaly_store.psycopg2, "connect", lambda **kwargs: captured.update(kwargs) or "CONN")

    result = anomaly_store.connect()

    assert result == "CONN"
    assert captured["dbname"]


def test_json_default_handles_decimal_datetime_and_fallback():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

    assert anomaly_store.json_default(Decimal("1.25")) == 1.25
    assert anomaly_store.json_default(ts) == ts.isoformat()
    assert anomaly_store.json_default(object()).startswith("<object object")


def test_ensure_anomaly_schema_executes_ddl_and_commits():
    cursor = FakeCursor()
    conn = FakeConn([cursor])

    anomaly_store.ensure_anomaly_schema(conn)

    assert len(cursor.executed) == 3
    assert conn.commit_calls == 1


def test_fetch_recent_ohlcv_returns_plain_dict_rows():
    rows = [
        {
            "symbol": "BTCUSD",
            "timeframe": "1m",
            "ts": "2026-01-01T00:00:00+00:00",
            "open": 1,
            "high": 2,
            "low": 0.5,
            "close": 1.5,
            "volume": 100,
        }
    ]
    conn = FakeConn([FakeCursor(fetchall_result=rows)])

    result = anomaly_store.fetch_recent_ohlcv(conn, lookback_hours=48, max_rows=500)

    assert result == rows


def test_persist_anomaly_events_with_details_tracks_inserted_and_duplicates(monkeypatch):
    monkeypatch.setattr(anomaly_store, "ensure_anomaly_schema", lambda conn: None)
    cursor = FakeCursor(rowcounts=[1, 0])
    conn = FakeConn([cursor])
    events = [
        {
            "event_key": "btc-1",
            "symbol": "BTCUSD",
            "timeframe": "1m",
            "event_ts": "2026-01-01T00:00:00+00:00",
            "anomaly_type": "volume_spike",
            "severity": "CRITICAL",
            "score": 9.8,
            "metric_value": Decimal("120.5"),
            "baseline_value": Decimal("40.1"),
            "details": {"ratio": Decimal("3.0")},
        },
        {
            "event_key": "btc-2",
            "symbol": "BTCUSD",
            "timeframe": "5m",
            "event_ts": "2026-01-01T00:05:00+00:00",
            "anomaly_type": "price_return_spike",
            "severity": "HIGH",
            "score": 4.1,
            "metric_value": 2.3,
            "baseline_value": 0.4,
            "details": {"ratio": 5},
        },
    ]

    inserted, inserted_events = anomaly_store.persist_anomaly_events_with_details(conn, events)

    assert inserted == 1
    assert inserted_events == [events[0]]
    assert conn.commit_calls == 1
    assert len(cursor.executed) == 2


def test_persist_anomaly_events_returns_insert_count(monkeypatch):
    monkeypatch.setattr(
        anomaly_store,
        "persist_anomaly_events_with_details",
        lambda conn, events: (3, [{"event_key": "x"}]),
    )

    assert anomaly_store.persist_anomaly_events(object(), [{"event_key": "x"}]) == 3


def test_persist_anomaly_events_with_details_returns_early_for_empty_events(monkeypatch):
    called = {"schema": 0}
    monkeypatch.setattr(
        anomaly_store,
        "ensure_anomaly_schema",
        lambda conn: called.__setitem__("schema", called["schema"] + 1),
    )

    inserted, events = anomaly_store.persist_anomaly_events_with_details(object(), [])

    assert inserted == 0
    assert events == []
    assert called["schema"] == 1


def test_notify_critical_anomalies_returns_false_when_disabled_or_no_critical(monkeypatch):
    monkeypatch.setenv("ANOMALY_NOTIFY_CRITICAL", "0")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    assert anomaly_store.notify_critical_anomalies([{"severity": "CRITICAL"}]) is False
    assert anomaly_store.notify_critical_anomalies([{"severity": "LOW"}]) is False


def test_notify_critical_anomalies_sends_telegram_payload(monkeypatch):
    monkeypatch.setenv("ANOMALY_NOTIFY_CRITICAL", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = data.decode("utf-8")
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(anomaly_store.urllib.request, "urlopen", fake_urlopen)

    result = anomaly_store.notify_critical_anomalies(
        [
            {"severity": "CRITICAL", "symbol": "BTCUSD", "timeframe": "1m", "anomaly_type": "volume_spike", "score": 9.0},
            {"severity": "CRITICAL", "symbol": "ETHUSD", "timeframe": "5m", "anomaly_type": "price_return_spike", "score": 4.0},
        ]
    )

    assert result is True
    assert captured["url"].endswith("/sendMessage")
    assert "BTCUSD" in captured["data"]
    assert captured["timeout"] == 5


def test_notify_critical_anomalies_returns_false_on_http_error(monkeypatch):
    monkeypatch.setenv("ANOMALY_NOTIFY_CRITICAL", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")

    class FakeResponse:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(anomaly_store.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())

    result = anomaly_store.notify_critical_anomalies(
        [{"severity": "CRITICAL", "symbol": "BTCUSD", "timeframe": "1m", "anomaly_type": "volume_spike", "score": 9.0}]
    )

    assert result is False


def test_fetch_anomaly_events_applies_filters_and_normalizes_values(monkeypatch):
    monkeypatch.setattr(anomaly_store, "ensure_anomaly_schema", lambda conn: None)
    rows = [
        {
            "symbol": "BTCUSD",
            "timeframe": "1m",
            "event_ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "anomaly_type": "volume_spike",
            "severity": "CRITICAL",
            "score": Decimal("9.1"),
            "metric_value": Decimal("11.2"),
            "baseline_value": Decimal("3.4"),
            "details": {"ratio": 3},
            "detected_at": datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        }
    ]
    cursor = FakeCursor(fetchall_result=rows)
    conn = FakeConn([cursor])

    result = anomaly_store.fetch_anomaly_events(conn, symbol="btcusd", severity="critical", hours=999, limit=500)

    assert result[0]["symbol"] == "BTCUSD"
    assert result[0]["score"] == 9.1
    assert result[0]["metric_value"] == 11.2
    assert result[0]["baseline_value"] == 3.4
    _, params = cursor.executed[0]
    assert params == [168, "BTCUSD", "CRITICAL", 100]


def test_fetch_anomaly_events_handles_optional_filters_and_none_values(monkeypatch):
    monkeypatch.setattr(anomaly_store, "ensure_anomaly_schema", lambda conn: None)
    rows = [
        {
            "symbol": "ETHUSD",
            "timeframe": "5m",
            "event_ts": None,
            "anomaly_type": "missing_candle_gap",
            "severity": "HIGH",
            "score": None,
            "metric_value": None,
            "baseline_value": Decimal("2.5"),
            "details": {},
            "detected_at": datetime(2026, 1, 1, 0, 3, tzinfo=timezone.utc),
        }
    ]
    cursor = FakeCursor(fetchall_result=rows)
    conn = FakeConn([cursor])

    result = anomaly_store.fetch_anomaly_events(conn, symbol=None, severity="high", hours=0, limit=0)

    assert result == [
        {
            "symbol": "ETHUSD",
            "timeframe": "5m",
            "event_ts": None,
            "anomaly_type": "missing_candle_gap",
            "severity": "HIGH",
            "score": None,
            "metric_value": None,
            "baseline_value": 2.5,
            "details": {},
            "detected_at": "2026-01-01T00:03:00+00:00",
        }
    ]
    _, params = cursor.executed[0]
    assert params == [1, "HIGH", 1]


def test_fetch_anomaly_events_handles_symbol_only_filter(monkeypatch):
    monkeypatch.setattr(anomaly_store, "ensure_anomaly_schema", lambda conn: None)
    cursor = FakeCursor(fetchall_result=[])
    conn = FakeConn([cursor])

    result = anomaly_store.fetch_anomaly_events(conn, symbol="solusd", severity=None, hours=24, limit=5)

    assert result == []
    _, params = cursor.executed[0]
    assert params == [24, "SOLUSD", 5]


def test_fetch_anomaly_summary_formats_counts_and_top_symbols(monkeypatch):
    monkeypatch.setattr(anomaly_store, "ensure_anomaly_schema", lambda conn: None)
    cursor = SequenceCursor(
        fetchone_results=[
            {
                "total": 5,
                "critical": 2,
                "high": 1,
                "price_spikes": 1,
                "volume_spikes": 2,
                "range_spikes": 1,
                "missing_gaps": 1,
                "last_detected_at": datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc),
            }
        ],
        fetchall_results=[
            [
                {"symbol": "BTCUSD", "count": Decimal("3"), "max_score": Decimal("9.7")},
                {"symbol": "ETHUSD", "count": 2, "max_score": Decimal("4.2")},
            ]
        ],
    )
    conn = FakeConn([cursor])

    result = anomaly_store.fetch_anomaly_summary(conn, hours=200)

    assert result["hours"] == 168
    assert result["summary"]["total"] == 5
    assert result["summary"]["last_detected_at"].startswith("2026-01-01T00:02:00")
    assert result["top_symbols"][0] == {"symbol": "BTCUSD", "count": 3, "max_score": 9.7}


def test_fetch_anomaly_summary_handles_missing_last_detected_and_scores(monkeypatch):
    monkeypatch.setattr(anomaly_store, "ensure_anomaly_schema", lambda conn: None)
    cursor = SequenceCursor(
        fetchone_results=[
            {
                "total": None,
                "critical": None,
                "high": None,
                "price_spikes": None,
                "volume_spikes": None,
                "range_spikes": None,
                "missing_gaps": None,
                "last_detected_at": None,
            }
        ],
        fetchall_results=[[{"symbol": "SOLUSD", "count": None, "max_score": None}]],
    )
    conn = FakeConn([cursor])

    result = anomaly_store.fetch_anomaly_summary(conn, hours=0)

    assert result == {
        "hours": 1,
        "summary": {
            "total": 0,
            "critical": 0,
            "high": 0,
            "price_spikes": 0,
            "volume_spikes": 0,
            "range_spikes": 0,
            "missing_gaps": 0,
            "last_detected_at": None,
        },
        "top_symbols": [{"symbol": "SOLUSD", "count": 0, "max_score": 0.0}],
    }
