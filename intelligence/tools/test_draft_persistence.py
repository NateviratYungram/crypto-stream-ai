import os
import sqlite3
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from intelligence.tools.market_tools import (
    execute_approved_mt5_trade,
    prepare_mt5_trade_draft,
)


def test_persistence():
    print("--- Testing Trade Draft Persistence ---")

    # 1. Create a draft
    print("\n1. Creating a draft for BTC...")
    res = prepare_mt5_trade_draft(symbol="BTC", side="BUY", volume=0.01, session_id="test_session")

    if "error" in res:
        print(f"[FAIL] Failed to create draft: {res['error']}")
        return

    draft_id = res["draft_id"]
    print(f"[SUCCESS] Draft created with ID: {draft_id}")

    # 2. Check DB manually
    print("\n2. Checking SQLite DB directly...")
    conn = sqlite3.connect("persistence.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_drafts WHERE id = ?", (draft_id,))
    row = cursor.fetchone()
    conn.close()

    if row:
        print(f"[SUCCESS] Draft found in DB: {row}")
    else:
        print("[FAIL] Draft NOT found in DB!")
        return

    # 3. Execute the draft
    print(f"\n3. Executing draft {draft_id}...")
    exec_res = execute_approved_mt5_trade(draft_id=draft_id)

    if "error" in exec_res:
        print(f"[FAIL] Execution failed: {exec_res['error']}")
    else:
        print(f"[SUCCESS] Execution success: {exec_res['status']}")

    # 4. Verify deletion
    print("\n4. Verifying atomic deletion...")
    conn = sqlite3.connect("persistence.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_drafts WHERE id = ?", (draft_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        print("[SUCCESS] Draft deleted successfully after execution.")
    else:
        print("[FAIL] Draft still exists in DB after execution!")

if __name__ == "__main__":
    test_persistence()
