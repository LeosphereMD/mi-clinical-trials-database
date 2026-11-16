"""Remove stored trials that fail the SPEC.md inclusion rules (e.g. after a rule change).

Usage:
    .venv\\Scripts\\python scripts\\apply_inclusion_rule.py          # show what would go
    .venv\\Scripts\\python scripts\\apply_inclusion_rule.py --apply  # remove it

Each trial in the database is checked again against its raw file in data/raw/
with fetch_trials.rule_failure. For every trial that fails:
  1. Review files: its rows are removed from drug_names.csv, why_stopped.csv,
     outcome_types.csv and registry_check.xlsx. In sponsors.csv only sponsors
     left with no trials are removed. Every removed row that holds a decision
     is first copied to review/archive/excluded_trial_decisions.csv with the
     date and the reason.
  2. Database: the trial and its rows in every related table are deleted, in
     one transaction (all or nothing).
It stops without changing anything if a failing trial has decisions stored in
the database (registry_checks, or extracted values with review decisions),
because those are never deleted. Back up the database before using --apply.
"""

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from openpyxl import load_workbook

from create_database import DB_PATH, connect
from draft_registry_check import SHEET_FILE
from fetch_trials import rule_failure
from review_files import REVIEW_DIR, has_decision, read_csv, write_csv

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = REVIEW_DIR / "archive" / "excluded_trial_decisions.csv"
PER_TRIAL_FILES = ["drug_names.csv", "why_stopped.csv", "outcome_types.csv"]
SPONSOR_FILE = "sponsors.csv"
# Child tables first, trials last.
TABLES = ["outcome_comparisons", "extracted_values", "registry_checks", "trial_publications",
          "registered_outcomes", "arms", "interventions", "intervention_mesh",
          "conditions", "trial_countries", "trials"]


def failing_trials(con):
    """({nct_id: reason}, [nct_ids whose raw file is missing])."""
    failing, missing = {}, []
    for nct_id, raw_file in con.execute("SELECT nct_id, raw_json_file FROM trials "
                                        "ORDER BY nct_id"):
        path = ROOT / raw_file if raw_file else None
        if not path or not path.exists():
            missing.append(nct_id)
            continue
        reason = rule_failure(json.loads(path.read_text(encoding="utf-8")))
        if reason:
            failing[nct_id] = reason
    return failing, missing


def blockers(con, ids):
    q = ",".join("?" * len(ids))
    checks = [r[0] for r in con.execute(
        f"SELECT DISTINCT nct_id FROM registry_checks WHERE nct_id IN ({q})", ids)]
    decided = [r[0] for r in con.execute(
        f"SELECT DISTINCT e.nct_id FROM extracted_values e JOIN review_decisions d "
        f"ON d.value_id = e.value_id WHERE e.nct_id IN ({q})", ids)]
    return sorted(set(checks) | set(decided))


def sheet_rows(path):
    """(header, [(excel row number, {column: value})]) of registry_check.xlsx."""
    ws = load_workbook(path)["Checks"]
    header = [c.value for c in ws[1]]
    rows = []
    for n, cells in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        row = {h: ("" if v is None else str(v)) for h, v in zip(header, cells) if h}
        rows.append((n, row))
    return header, rows


def plan_review_changes(failing, sponsors_left):
    """What to remove from each review file, and the decided rows to archive."""
    plan, archive = {}, []
    today = date.today().isoformat()

    def to_archive(file_name, row, reason):
        archive.append({"archived_on": today, "source_file": file_name, "reason": reason,
                        **row})

    for name in PER_TRIAL_FILES:
        path = REVIEW_DIR / name
        if not path.exists():
            continue
        rows = read_csv(path)
        keep, gone = [], 0
        for r in rows:
            if r.get("nct_id") in failing:
                gone += 1
                if has_decision(r):
                    to_archive(name, r, f"trial excluded: {failing[r['nct_id']]}")
            else:
                keep.append(r)
        plan[name] = (rows, keep, gone)

    path = REVIEW_DIR / SPONSOR_FILE
    if path.exists():
        rows = read_csv(path)
        keep, gone = [], 0
        for r in rows:
            excluded = sponsors_left.get(r.get("lead_sponsor"))
            if excluded is not None and excluded["left"] == 0:
                gone += 1
                if has_decision(r):
                    to_archive(SPONSOR_FILE, r, "sponsor left with no trials after excluding "
                               + ", ".join(excluded["ids"]))
            else:
                keep.append(r)
        plan[SPONSOR_FILE] = (rows, keep, gone)

    if SHEET_FILE.exists():
        header, rows = sheet_rows(SHEET_FILE)
        gone_rows = [n for n, r in rows if r.get("nct_id") in failing]
        for n, r in rows:
            if r.get("nct_id") in failing and has_decision(r):
                to_archive(SHEET_FILE.name, r, f"trial excluded: {failing[r['nct_id']]}")
        plan[SHEET_FILE.name] = (None, gone_rows, len(gone_rows))
    return plan, archive


def write_archive(new_rows):
    """Append to the archive file, keeping every column of earlier and new rows."""
    old = read_csv(ARCHIVE) if ARCHIVE.exists() else []
    # A row already archived (e.g. by a run that stopped halfway) is not added again.
    # Copies are counted: two identical rows in a review file stay two rows here.
    def same(r):
        return tuple(sorted((k, v) for k, v in r.items() if k and k != "archived_on" and v))
    already = Counter(same(r) for r in old)
    unique = []
    for r in new_rows:
        if already[same(r)] > 0:
            already[same(r)] -= 1
        else:
            unique.append(r)
    new_rows = unique
    first =["archived_on", "source_file", "reason", "nct_id", "lead_sponsor"]
    columns = list(first)
    for r in old + new_rows:
        for c in r:
            if c and c not in columns:
                columns.append(c)
    ARCHIVE.parent.mkdir(parents=True, exist_ok=True)
    write_csv(ARCHIVE, columns, old + new_rows)


def apply_review_changes(plan):
    for name, (rows, keep, gone) in plan.items():
        if not gone:
            continue
        if name == SHEET_FILE.name:
            wb = load_workbook(SHEET_FILE)
            ws = wb["Checks"]
            for n in sorted(keep, reverse=True):   # here 'keep' holds the rows to delete
                ws.delete_rows(n)
            wb.save(SHEET_FILE)
        else:
            columns = [c for c in rows[0].keys() if c]
            write_csv(REVIEW_DIR / name, columns, keep)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="remove the failing trials")
    args = parser.parse_args()
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)

    con = connect()
    try:
        before = con.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        failing, missing = failing_trials(con)
        print(f"Trials in the database: {before}")
        if missing:
            print(f"WARNING: raw file missing, not checked (kept): {', '.join(missing)}")
        print(f"Trials failing the inclusion rules: {len(failing)}")
        for nct_id, reason in failing.items():
            print(f"  {nct_id}: {reason}")
        if not failing:
            print(f"Summary: records in {before} trials, out {before} kept, "
                  f"skipped 0 (nothing to remove)")
            return
        ids = list(failing)
        blocked = blockers(con, ids)
        if blocked:
            print("STOPPED: these trials have decisions stored in the database, which are "
                  f"never deleted: {', '.join(blocked)}. Nothing was changed.")
            print(f"Summary: records in {before} trials, out {before}, skipped 0 (stopped)")
            sys.exit(1)

        q = ",".join("?" * len(ids))
        sponsors_left = {}
        for sponsor, n_failing in con.execute(
                f"SELECT lead_sponsor, COUNT(*) FROM trials WHERE nct_id IN ({q}) "
                f"GROUP BY lead_sponsor", ids):
            total = con.execute("SELECT COUNT(*) FROM trials WHERE lead_sponsor = ?",
                                (sponsor,)).fetchone()[0]
            sponsors_left[sponsor] = {
                "left": total - n_failing,
                "ids": [i for i in ids if con.execute(
                    "SELECT lead_sponsor FROM trials WHERE nct_id = ?", (i,)).fetchone()[0]
                        == sponsor]}
        table_counts = {t: con.execute(f"SELECT COUNT(*) FROM {t} WHERE nct_id IN ({q})",
                                       ids).fetchone()[0] for t in TABLES}
        plan, archive = plan_review_changes(failing, sponsors_left)

        if not args.apply:
            print("\nWould remove (nothing changed; run with --apply):")
            for t, n in table_counts.items():
                print(f"  table {t}: {n} rows")
            for name, (_, _, gone) in plan.items():
                print(f"  {name}: {gone} rows")
            print(f"  decided rows to archive first: {len(archive)}")
            print(f"Summary: records in {before} trials, out {before} (dry run), "
                  f"skipped {len(failing)} would be removed")
            return

        # Check every file we will write is free (not open in Excel) before writing any.
        targets = [ARCHIVE] if archive else []
        targets += [SHEET_FILE if name == SHEET_FILE.name else REVIEW_DIR / name
                    for name, (_, _, gone) in plan.items() if gone]
        locked = []
        for path in targets:
            if path.exists():
                try:
                    with open(path, "r+b"):
                        pass
                except PermissionError:
                    locked.append(path.name)
        if locked:
            print(f"STOPPED: open in another program (probably Excel): {', '.join(locked)}. "
                  "Save and close, then run again. Nothing was changed.")
            sys.exit(1)
        # Review files first: if writing one fails we stop before touching the database.
        try:
            if archive:
                write_archive(archive)
            apply_review_changes(plan)
        except PermissionError as e:
            print(f"STOPPED: a review file is open in another program ({e.filename}). "
                  "Close it and run again. The database was not changed.")
            sys.exit(1)
        with con:
            for t in TABLES:
                con.execute(f"DELETE FROM {t} WHERE nct_id IN ({q})", ids)
        after = con.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        phases = con.execute("SELECT phase_label, COUNT(*) FROM trials "
                             "GROUP BY phase_label ORDER BY phase_label").fetchall()
    except sqlite3.Error as e:
        print(f"STOPPED: {e}. The database was not changed.")
        sys.exit(1)
    finally:
        con.close()

    print(f"\nTrials before: {before}, after: {after}")
    print("After, by phase: " + ", ".join(f"{p} {n}" for p, n in phases))
    print("Rows removed per table:")
    for t, n in table_counts.items():
        print(f"  {t}: {n}")
    print("Rows removed per review file:")
    for name, (_, _, gone) in plan.items():
        print(f"  {name}: {gone}")
    print(f"Decided rows archived to {ARCHIVE.relative_to(ROOT)}: {len(archive)} "
          f"({', '.join(f'{k} {v}' for k, v in Counter(a['source_file'] for a in archive).items()) or 'none'})")
    print(f"Summary: records in {before} trials, out {after} kept, "
          f"skipped {len(failing)} removed (failed the inclusion rules)")


if __name__ == "__main__":
    main()
