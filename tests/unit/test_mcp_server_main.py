from contextlib import contextmanager
from types import SimpleNamespace
import asyncio

from fastapi.testclient import TestClient
import pytest

from mcp_server import main as mcp_main


class DummyPool:
    def __init__(self, conn):
        self.conn = conn
        self.put_back = []
        self.get_calls = 0

    def getconn(self):
        self.get_calls += 1
        return self.conn

    def putconn(self, conn):
        self.put_back.append(conn)


class DummyConn:
    def __init__(self, cursor=None):
        self.cursor_obj = cursor
        self.sessions = []

    def set_session(self, readonly, autocommit):
        self.sessions.append((readonly, autocommit))

    def cursor(self, cursor_factory=None):
        return self.cursor_obj


class DummyCursor:
    def __init__(self, rows=None, execute_error=None):
        self.rows = rows or []
        self.execute_error = execute_error
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.execute_error:
            raise self.execute_error

    def fetchall(self):
        return self.rows


def test_get_api_key_accepts_and_rejects_known_value(monkeypatch):
    monkeypatch.setattr(mcp_main, "MCP_API_KEY", "secret")

    accepted = asyncio.run(mcp_main.get_api_key("secret"))
    assert accepted == "secret"

    try:
        asyncio.run(mcp_main.get_api_key("wrong"))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
    else:
        raise AssertionError("expected invalid API key to be rejected")


def test_validate_select_only_allows_safe_select_and_blocks_dangerous_patterns():
    assert mcp_main.validate_select_only("SELECT * FROM table_name") is True
    assert mcp_main.validate_select_only("  ") is False
    assert mcp_main.validate_select_only(123) is False
    assert mcp_main.validate_select_only("DELETE FROM table_name") is False
    assert mcp_main.validate_select_only("SELECT * FROM x; DROP TABLE y") is False
    assert mcp_main.validate_select_only("SELECT * FROM x -- hidden") is False


def test_get_db_pool_initializes_once(monkeypatch):
    created = {}

    def fake_pool(**kwargs):
        created["kwargs"] = kwargs
        return "pool-object"

    monkeypatch.setattr(mcp_main.pg_pool, "ThreadedConnectionPool", lambda minconn, maxconn, **kwargs: fake_pool(minconn=minconn, maxconn=maxconn, **kwargs))
    monkeypatch.setattr(mcp_main, "_db_pool", None)
    monkeypatch.setenv("DB_HOST", "db.example")
    monkeypatch.setenv("DB_PORT", "9999")
    monkeypatch.setenv("DB_NAME", "lake")
    monkeypatch.setenv("DB_USER_READONLY", "readonly")
    monkeypatch.setenv("DB_PASS", "pw")

    first = mcp_main.get_db_pool()
    second = mcp_main.get_db_pool()

    assert first == "pool-object"
    assert second == "pool-object"
    assert created["kwargs"]["host"] == "db.example"
    assert created["kwargs"]["port"] == "9999"
    assert created["kwargs"]["user"] == "readonly"


def test_get_db_conn_sets_read_only_and_returns_connection(monkeypatch):
    conn = DummyConn()
    pool = DummyPool(conn)
    monkeypatch.setattr(mcp_main, "get_db_pool", lambda: pool)

    with mcp_main.get_db_conn(read_only=True) as got:
        assert got is conn

    assert conn.sessions == [(True, False)]
    assert pool.put_back == [conn]


def test_get_db_conn_supports_write_sessions_and_returns_connection_on_error(monkeypatch):
    conn = DummyConn()
    pool = DummyPool(conn)
    monkeypatch.setattr(mcp_main, "get_db_pool", lambda: pool)

    with pytest.raises(RuntimeError, match="boom"):
        with mcp_main.get_db_conn(read_only=False):
            raise RuntimeError("boom")

    assert conn.sessions == [(False, True)]
    assert pool.put_back == [conn]


def test_log_audit_query_hashes_key_and_inserts(monkeypatch):
    cursor = DummyCursor()
    conn = DummyConn(cursor)

    @contextmanager
    def fake_db_conn(read_only=False):
        assert read_only is False
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)

    mcp_main.log_audit_query("secret", "SELECT 1", 2, 15, "127.0.0.1")

    sql, params = cursor.executed[0]
    assert "INSERT INTO mcp_audit_log" in sql
    assert params[0] != "secret"
    assert params[1:] == ("SELECT 1", 2, 15, "127.0.0.1")


def test_log_audit_query_swallows_insert_failures(monkeypatch):
    cursor = DummyCursor(execute_error=RuntimeError("write failed"))
    conn = DummyConn(cursor)
    errors = []

    @contextmanager
    def fake_db_conn(read_only=False):
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)
    monkeypatch.setattr(mcp_main.logger, "error", lambda message: errors.append(message))

    mcp_main.log_audit_query("secret", "SELECT 1", 2, 15, "127.0.0.1")

    assert errors == ["Failed to insert audit log: write failed"]


def test_health_and_schema_endpoints(monkeypatch):
    rows = [
        {"table_name": "orders", "column_name": "id", "data_type": "integer"},
        {"table_name": "orders", "column_name": "symbol", "data_type": "text"},
        {"table_name": "fills", "column_name": "id", "data_type": "integer"},
    ]
    cursor = DummyCursor(rows=rows)
    conn = DummyConn(cursor)

    @contextmanager
    def fake_db_conn(read_only=True):
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)
    monkeypatch.setattr(mcp_main, "MCP_API_KEY", "secret")
    client = TestClient(mcp_main.app)

    health = client.get("/health")
    schemas = client.get("/api/v1/schemas", headers={"X-API-Key": "secret"})

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert schemas.status_code == 200
    assert schemas.json() == [
        {"table_name": "orders", "columns": [{"name": "id", "type": "integer"}, {"name": "symbol", "type": "text"}]},
        {"table_name": "fills", "columns": [{"name": "id", "type": "integer"}]},
    ]


def test_execute_query_endpoint_success_and_guards(monkeypatch):
    cursor = DummyCursor(rows=[{"value": 1}])
    conn = DummyConn(cursor)
    logged = {}

    @contextmanager
    def fake_db_conn(read_only=True):
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)
    monkeypatch.setattr(mcp_main, "log_audit_query", lambda api_key, query, row_count, duration_ms, client_ip: logged.update({"api_key": api_key, "query": query, "row_count": row_count, "client_ip": client_ip}))
    monkeypatch.setattr(mcp_main, "MCP_API_KEY", "secret")
    client = TestClient(mcp_main.app)

    good = client.post("/api/v1/query", headers={"X-API-Key": "secret"}, json={"sql": "SELECT 1", "max_rows": 5})
    bad_sql = client.post("/api/v1/query", headers={"X-API-Key": "secret"}, json={"sql": "UPDATE table SET x=1", "max_rows": 5})
    bad_semicolon = client.post("/api/v1/query", headers={"X-API-Key": "secret"}, json={"sql": "SELECT 1; SELECT 2", "max_rows": 5})

    assert good.status_code == 200
    assert good.json()["row_count"] == 1
    assert "LIMIT 5" in cursor.executed[0][0]
    assert logged["row_count"] == 1
    assert bad_sql.status_code == 403
    assert bad_semicolon.status_code == 403


def test_execute_query_returns_400_on_database_error(monkeypatch):
    class FakePsycopgError(Exception):
        pass

    monkeypatch.setattr(mcp_main.psycopg2, "Error", FakePsycopgError)
    cursor = DummyCursor(execute_error=FakePsycopgError("boom"))
    conn = DummyConn(cursor)

    @contextmanager
    def fake_db_conn(read_only=True):
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)
    monkeypatch.setattr(mcp_main, "MCP_API_KEY", "secret")
    client = TestClient(mcp_main.app)

    response = client.post("/api/v1/query", headers={"X-API-Key": "secret"}, json={"sql": "SELECT 1", "max_rows": 5})

    assert response.status_code == 400
    assert "boom" in response.json()["detail"]


def test_execute_query_returns_400_on_generic_error(monkeypatch):
    monkeypatch.setattr(mcp_main.psycopg2, "Error", type("FakePsycopgError", (Exception,), {}))
    cursor = DummyCursor(execute_error=RuntimeError("unexpected boom"))
    conn = DummyConn(cursor)

    @contextmanager
    def fake_db_conn(read_only=True):
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)
    monkeypatch.setattr(mcp_main, "MCP_API_KEY", "secret")
    client = TestClient(mcp_main.app)

    response = client.post("/api/v1/query", headers={"X-API-Key": "secret"}, json={"sql": "SELECT 1", "max_rows": 5})

    assert response.status_code == 400
    assert response.json()["detail"] == "unexpected boom"


def test_execute_query_uses_unknown_client_when_request_client_missing(monkeypatch):
    cursor = DummyCursor(rows=[{"value": 1}])
    conn = DummyConn(cursor)
    logged = {}

    @contextmanager
    def fake_db_conn(read_only=True):
        yield conn

    monkeypatch.setattr(mcp_main, "get_db_conn", fake_db_conn)
    monkeypatch.setattr(mcp_main, "log_audit_query", lambda *args: logged.update({"args": args}))

    request = SimpleNamespace(client=None)
    response = mcp_main.execute_query.__wrapped__(mcp_main.QueryRequest(sql="SELECT 1", max_rows=1), request, api_key="secret")

    assert response.row_count == 1
    assert logged["args"][-1] == "unknown"


def test_validate_select_only_covers_parser_edge_cases(monkeypatch):
    class FakeStatement:
        def __init__(self, tokens, flattened=None):
            self.tokens = tokens
            self._flattened = flattened or []

        def flatten(self):
            return list(self._flattened)

    class FakeToken:
        def __init__(self, value=None, ttype=None, is_whitespace=False):
            self.value = value
            self.ttype = ttype
            self.is_whitespace = is_whitespace

    errors = []
    monkeypatch.setattr(mcp_main.logger, "warning", lambda message: errors.append(message))

    monkeypatch.setattr(mcp_main.sqlparse, "parse", lambda sql: [])
    assert mcp_main.validate_select_only("SELECT 1") is False

    monkeypatch.setattr(mcp_main.sqlparse, "parse", lambda sql: [FakeStatement([FakeToken(is_whitespace=True)])])
    assert mcp_main.validate_select_only("SELECT 1") is False

    monkeypatch.setattr(
        mcp_main.sqlparse,
        "parse",
        lambda sql: [FakeStatement([FakeToken("UPDATE", ttype=mcp_main.DML)])],
    )
    assert mcp_main.validate_select_only("SELECT 1") is False

    monkeypatch.setattr(
        mcp_main.sqlparse,
        "parse",
        lambda sql: [FakeStatement([FakeToken("WITH")])],
    )
    assert mcp_main.validate_select_only("SELECT 1") is False

    class NoValueToken:
        is_whitespace = False
        ttype = None

    monkeypatch.setattr(
        mcp_main.sqlparse,
        "parse",
        lambda sql: [FakeStatement([NoValueToken()])],
    )
    assert mcp_main.validate_select_only("SELECT 1") is False

    monkeypatch.setattr(
        mcp_main.sqlparse,
        "parse",
        lambda sql: [FakeStatement([FakeToken("SELECT", ttype=mcp_main.DML)], [FakeToken("drop", ttype="Keyword")])],
    )
    assert mcp_main.validate_select_only("SELECT 1") is False

    monkeypatch.setattr(mcp_main.sqlparse, "parse", lambda sql: (_ for _ in ()).throw(RuntimeError("parse failed")))
    assert mcp_main.validate_select_only("SELECT 1") is False

    assert any("Non-SELECT DML detected: UPDATE" == message for message in errors)
    assert any("Query must start with SELECT, found: WITH" == message for message in errors)
    assert any("Forbidden keyword detected: drop" == message for message in errors)


def test_validate_select_only_allows_forbidden_words_as_identifiers(monkeypatch):
    class FakeStatement:
        def __init__(self, tokens, flattened):
            self.tokens = tokens
            self._flattened = flattened

        def flatten(self):
            return list(self._flattened)

    class FakeToken:
        def __init__(self, value=None, ttype=None, is_whitespace=False):
            self.value = value
            self.ttype = ttype
            self.is_whitespace = is_whitespace

    statement = FakeStatement(
        [FakeToken("SELECT", ttype=mcp_main.DML)],
        [
            FakeToken("drop", ttype=mcp_main.sqlparse.tokens.Name),
            FakeToken("safe", ttype=mcp_main.sqlparse.tokens.Literal.String.Single),
        ],
    )
    monkeypatch.setattr(mcp_main.sqlparse, "parse", lambda sql: [statement])

    assert mcp_main.validate_select_only("SELECT drop, 'safe'") is True


def test_validate_select_only_accepts_select_keyword_without_dml_token(monkeypatch):
    class FakeStatement:
        def __init__(self, tokens):
            self.tokens = tokens

        def flatten(self):
            return []

    class FakeToken:
        def __init__(self, value=None, ttype=None, is_whitespace=False):
            self.value = value
            self.ttype = ttype
            self.is_whitespace = is_whitespace

    monkeypatch.setattr(
        mcp_main.sqlparse,
        "parse",
        lambda sql: [FakeStatement([FakeToken("SELECT", ttype=None)])],
    )

    assert mcp_main.validate_select_only("SELECT 1") is True
