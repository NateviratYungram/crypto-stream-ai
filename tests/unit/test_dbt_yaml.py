"""
Unit tests for dbt model YAML structure.

Validates sources.yml and schema.yml files without a database or dbt CLI.
Catches common mistakes: undocumented models, missing not_null tests on key
columns, mart models referencing raw tables instead of staging models.
"""
import os
import re
from pathlib import Path

import pytest
import yaml

_DBT = Path(__file__).parents[2] / "dbt" / "models"
_STAGING_DIR = _DBT / "staging"
_MARTS_DIR = _DBT / "marts"


def _load(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _sql_files(directory: Path) -> set:
    return {p.stem for p in directory.glob("*.sql")}


# ── sources.yml ──────────────────────────────────────────────────────────────

class TestSources:
    def setup_method(self):
        self.data = _load(_DBT / "sources.yml")
        self.tables = {
            t["name"]
            for s in self.data["sources"]
            for t in s.get("tables", [])
        }

    def test_required_tables_declared(self):
        required = {
            "enriched_trades", "market_ohlcv", "daily_summary",
            "market_features", "market_regime", "macro_indicators",
        }
        missing = required - self.tables
        assert not missing, f"Missing source tables: {missing}"

    def test_all_columns_have_names(self):
        for source in self.data["sources"]:
            for table in source.get("tables", []):
                for col in table.get("columns", []):
                    assert col.get("name"), (
                        f"Unnamed column in source '{source['name']}.{table['name']}'"
                    )

    def test_enriched_trades_has_not_null_on_trade_id(self):
        trades = next(
            t for s in self.data["sources"]
            for t in s["tables"] if t["name"] == "enriched_trades"
        )
        trade_id_col = next(c for c in trades["columns"] if c["name"] == "trade_id")
        test_names = [
            t if isinstance(t, str) else list(t.keys())[0]
            for t in trade_id_col.get("tests", [])
        ]
        assert "not_null" in test_names
        assert "unique" in test_names


# ── staging schema.yml ───────────────────────────────────────────────────────

class TestStagingSchema:
    def setup_method(self):
        self.data = _load(_STAGING_DIR / "schema.yml")
        self.documented = {m["name"] for m in self.data.get("models", [])}
        self.sql_files = _sql_files(_STAGING_DIR)

    def test_all_sql_files_are_documented(self):
        undocumented = self.sql_files - self.documented
        assert not undocumented, f"Staging models without schema entry: {undocumented}"

    def test_no_orphan_schema_entries(self):
        orphans = self.documented - self.sql_files
        assert not orphans, f"Schema entries without a .sql file: {orphans}"

    def test_key_columns_have_not_null_test(self):
        key_col_names = {"trade_id", "symbol", "report_date", "date", "series_id"}
        for model in self.data.get("models", []):
            for col in model.get("columns", []):
                if col["name"] not in key_col_names:
                    continue
                test_names = [
                    t if isinstance(t, str) else list(t.keys())[0]
                    for t in col.get("tests", [])
                ]
                assert "not_null" in test_names, (
                    f"{model['name']}.{col['name']} is missing a not_null test"
                )


# ── marts schema.yml ─────────────────────────────────────────────────────────

class TestMartsSchema:
    def setup_method(self):
        self.data = _load(_MARTS_DIR / "schema.yml")
        self.documented = {m["name"] for m in self.data.get("models", [])}
        self.sql_files = _sql_files(_MARTS_DIR)

    def test_all_sql_files_are_documented(self):
        undocumented = self.sql_files - self.documented
        assert not undocumented, f"Mart models without schema entry: {undocumented}"

    def test_no_orphan_schema_entries(self):
        orphans = self.documented - self.sql_files
        assert not orphans, f"Schema entries without a .sql file: {orphans}"


# ── ref() coupling check ─────────────────────────────────────────────────────

class TestDbtRefCoupling:
    """Mart models must ref() staging (stg_*) models, not each other."""

    _REF = re.compile(r"\{\{\s*ref\(['\"](\w+)['\"]\)\s*\}\}")

    def test_mart_models_only_ref_staging(self):
        for sql_file in _MARTS_DIR.glob("*.sql"):
            content = sql_file.read_text()
            for match in self._REF.finditer(content):
                ref_name = match.group(1)
                assert ref_name.startswith("stg_"), (
                    f"{sql_file.name} refs '{ref_name}' directly — "
                    f"mart models should only ref stg_* staging models"
                )

    def test_staging_models_only_ref_other_staging(self):
        for sql_file in _STAGING_DIR.glob("*.sql"):
            content = sql_file.read_text()
            for match in self._REF.finditer(content):
                ref_name = match.group(1)
                assert ref_name.startswith("stg_"), (
                    f"{sql_file.name} refs '{ref_name}' — "
                    f"staging models should use source() not ref() for raw tables"
                )
