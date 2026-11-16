"""Load the registry hand-check decisions (SPEC.md "Registry hand-check", step 2b).

Usage:
    .venv\\Scripts\\python scripts\\load_registry_check.py

Reads review/registry_check.xlsx and adds each decision to the
registry_checks table. Rows are only ever added, never edited or deleted:
  - a decision that is the same as the latest one already stored for that
    trial and field is skipped, so loading the same sheet twice adds nothing;
  - a changed decision (e.g. the owner changed their mind) is added as a new
    row, and the latest row counts.
The trials table is never changed: a correction lives only in
registry_checks, because the next download would undo it.
"""

import sqlite3
import sys
from collections import Counter

from create_database import DB_PATH, connect
from draft_registry_check import DECISIONS, SHEET_FILE, read_sheet

COMPARED = ["db_value", "decision", "corrected_value", "comment"]


def blank_to_none(value):
    value = (value or "").strip()
    return value or None


def latest_checks(con):
    """{(nct_id, field): {column: value}} for the latest stored decision."""
    latest = {}
    for row in con.execute(
            "SELECT nct_id, field, db_value, decision, corrected_value, comment "
            "FROM registry_checks ORDER BY decided_at, check_id"):
        latest[(row[0], row[1])] = dict(zip(COMPARED, row[2:]))
    return latest


def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    if not SHEET_FILE.exists():
        print(f"STOPPED: {SHEET_FILE} does not exist. Run draft_registry_check.py first.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    try:
        rows = read_sheet(SHEET_FILE)
    except (KeyError, OSError) as e:
        print(f"STOPPED: could not read {SHEET_FILE.name} ({e}).")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)

    con = connect()
    skipped = Counter()
    added = Counter()
    try:
        trial_ids = {r[0] for r in con.execute("SELECT nct_id FROM trials")}
        latest = latest_checks(con)
        to_add = []
        for r in rows:
            decision = (r.get("decision") or "").strip().lower()
            if not decision:
                skipped["not reviewed yet"] += 1
                continue
            if decision not in DECISIONS:
                skipped[f"unknown decision '{r['decision']}'"] += 1
                print(f"  skipped {r['nct_id']} {r['field']}: unknown decision "
                      f"'{r['decision']}' (use {' / '.join(DECISIONS)})")
                continue
            new = {"db_value": blank_to_none(r.get("db_value")), "decision": decision,
                   "corrected_value": blank_to_none(r.get("corrected_value")),
                   "comment": blank_to_none(r.get("comment"))}
            if decision == "correct" and new["corrected_value"] is None:
                skipped["'correct' without a corrected value"] += 1
                print(f"  skipped {r['nct_id']} {r['field']}: 'correct' needs a "
                      "corrected_value")
                continue
            if r["nct_id"] not in trial_ids:
                skipped["trial not in the database"] += 1
                print(f"  skipped {r['nct_id']} {r['field']}: trial not in the database")
                continue
            if latest.get((r["nct_id"], r["field"])) == new:
                skipped["already loaded (same as the latest stored decision)"] += 1
                continue
            run_id = (r.get("fetch_run_id") or "").strip()
            to_add.append((r["nct_id"], r["field"], new["db_value"],
                           blank_to_none(r.get("selection_reason")),
                           int(run_id) if run_id.isdigit() else None,
                           decision, new["corrected_value"], new["comment"]))
            added[decision] += 1
        with con:
            con.executemany(
                "INSERT INTO registry_checks (nct_id, field, db_value, selection_reason, "
                "fetch_run_id, decision, corrected_value, comment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", to_add)
        total = con.execute("SELECT COUNT(*) FROM registry_checks").fetchone()[0]
    except sqlite3.Error as e:
        print(f"STOPPED: {e}. Nothing was added.")
        print(f"Summary: records in {len(rows)}, out 0, skipped {len(rows)} (stopped)")
        sys.exit(1)
    finally:
        con.close()

    print(f"Rows on the sheet: {len(rows)}")
    print("Decisions added: " + (", ".join(f"{k} {v}" for k, v in added.items()) or "none"))
    print(f"registry_checks now holds {total} rows")
    n_skipped = sum(skipped.values())
    print(f"Summary: records in {len(rows)} sheet rows, out {sum(added.values())} decisions "
          f"added, skipped {n_skipped}"
          + (f" ({', '.join(f'{k} {v}' for k, v in skipped.items())})" if n_skipped else ""))


if __name__ == "__main__":
    main()
