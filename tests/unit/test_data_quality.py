"""
Unit tests for data_quality_dag.py — assertion structure validation.

These tests verify the ASSERTIONS list is correctly defined without
connecting to any database. They catch config mistakes like wrong severity,
missing SQL, or a table being omitted from quality checks.
"""
from data_quality_dag import ASSERTIONS

KNOWN_TABLES = {"enriched_trades", "market_ohlcv", "daily_summary"}
REQUIRED_KEYS = {"name", "table", "severity", "sql", "expected", "error_reason"}
VALID_SEVERITIES = {"CRITICAL", "WARNING"}


def test_all_assertions_have_required_keys():
    for check in ASSERTIONS:
        missing = REQUIRED_KEYS - check.keys()
        assert not missing, f"Assertion '{check.get('name')}' is missing keys: {missing}"


def test_severity_values_are_valid():
    for check in ASSERTIONS:
        assert check["severity"] in VALID_SEVERITIES, (
            f"'{check['name']}' has invalid severity: '{check['severity']}'"
        )


def test_expected_is_zero_for_all_checks():
    """Every DQ assertion tests for zero failing rows."""
    for check in ASSERTIONS:
        assert check["expected"] == 0, (
            f"'{check['name']}' expected={check['expected']} — should always be 0"
        )


def test_sql_is_non_empty():
    for check in ASSERTIONS:
        assert check["sql"].strip(), f"'{check['name']}' has an empty SQL string"


def test_error_reason_has_no_spaces():
    """error_reason is used as a DB column value — must be snake_case."""
    for check in ASSERTIONS:
        assert " " not in check["error_reason"], (
            f"'{check['name']}' error_reason contains spaces: '{check['error_reason']}'"
        )


def test_assertion_names_are_unique():
    names = [c["name"] for c in ASSERTIONS]
    duplicates = {n for n in names if names.count(n) > 1}
    assert not duplicates, f"Duplicate assertion names: {duplicates}"


def test_assertion_names_match_table_prefix():
    """Convention: name must start with the table it checks."""
    for check in ASSERTIONS:
        assert check["name"].startswith(check["table"]), (
            f"'{check['name']}' should start with table name '{check['table']}'"
        )


def test_every_table_has_at_least_one_critical_check():
    """Each tracked table must have at least one pipeline-blocking CRITICAL check."""
    critical_tables = {c["table"] for c in ASSERTIONS if c["severity"] == "CRITICAL"}
    missing = KNOWN_TABLES - critical_tables
    assert not missing, f"No CRITICAL checks defined for tables: {missing}"


def test_at_least_one_warning_check_exists():
    """WARNING checks provide early signals before data becomes critically bad."""
    warning_checks = [c for c in ASSERTIONS if c["severity"] == "WARNING"]
    assert len(warning_checks) >= 1, "No WARNING-severity checks found"
