"""Apply infrastructure/schema.sql to the configured PostgreSQL database.

Use this after adding new tables when the Docker Postgres volume already
exists, because /docker-entrypoint-initdb.d scripts only run on first boot.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except Exception:
    def load_dotenv(*_args, **_kwargs):
        return False

def main() -> int:
    parser = argparse.ArgumentParser(description="Apply CryptoStream AI database schema")
    parser.add_argument(
        "--schema",
        default=str(ROOT / "infrastructure" / "schema.sql"),
        help="Path to SQL schema file",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    try:
        from intelligence.ml.anomaly_store import connect
    except ModuleNotFoundError as exc:
        print(
            f"Missing dependency: {exc.name}. Install project requirements before applying schema.",
            file=sys.stderr,
        )
        return 1

    schema_path = Path(args.schema)
    sql = schema_path.read_text(encoding="utf-8")

    try:
        conn = connect()
    except Exception as exc:
        print(f"Unable to connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print(f"Applied schema: {schema_path}")
        return 0
    except Exception as exc:
        conn.rollback()
        print(f"Failed to apply schema: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
