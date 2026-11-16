"""Load timing after MI into the trials table (SPEC.md "Timing after MI").

Usage:
    .venv\\Scripts\\python scripts\\load_timing.py

For every trial:
  - on review/timing_after_mi.csv with a decision: the owner's value
    (approve = the draft; correct = corrected_timing: acute / recent / prior,
    or "none" when the trial has no index MI), source "owner approved";
  - on the sheet without a decision: left empty until reviewed;
  - not on the sheet (a sure "acute" draft whose evidence quote was found):
    "acute", source "Claude draft, not reviewed".
The evidence quote is stored with the label. Run draft_timing.py first.
"""

import sqlite3
import sys
from collections import Counter

from create_database import DB_PATH, connect
from draft_timing import LABELS, REVIEW_FILE, drafts
from review_files import decision_of, read_csv

SOURCE_DRAFT = "Claude draft, not reviewed"
SOURCE_OWNER = "owner approved"


def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    sheet = {r["nct_id"]: r for r in read_csv(REVIEW_FILE)} if REVIEW_FILE.exists() else {}
    con = connect()
    stats, problems = Counter(), []
    try:
        items = drafts(con)
        updates = []
        for nct_id, _, s, found, _, reason in items:
            evidence = (s["evidence"] or None) if s else None
            if reason is None and nct_id not in sheet:
                updates.append(("acute", evidence, SOURCE_DRAFT, nct_id))
                stats["acute, Claude draft (not reviewed)"] += 1
                continue
            row = sheet.get(nct_id)
            decision = decision_of(row) if row else ""
            if not row or not decision:
                updates.append((None, None, None, nct_id))
                stats["waiting for review (left empty)"] += 1
                continue
            if decision == "approve":
                value = row.get("draft_timing", "").strip()
            elif decision == "correct":
                value = row.get("corrected_timing", "").strip().lower()
                if value == "none":
                    value = ""
                elif value not in LABELS:
                    problems.append(f"{nct_id}: 'correct' needs corrected_timing "
                                    f"acute / recent / prior / none (found '{value}')")
                    updates.append((None, None, None, nct_id))
                    continue
            else:
                problems.append(f"{nct_id}: unknown decision '{row['decision']}'")
                updates.append((None, None, None, nct_id))
                continue
            updates.append((value or None, row.get("evidence") or None, SOURCE_OWNER, nct_id))
            stats[f"{value or 'none (no index MI)'}, owner approved"] += 1
        with con:
            con.executemany("UPDATE trials SET timing_after_mi = ?, "
                            "timing_after_mi_evidence = ?, timing_after_mi_source = ? "
                            "WHERE nct_id = ?", updates)
    except sqlite3.Error as e:
        print(f"STOPPED: {e}. Nothing was changed.")
        sys.exit(1)
    finally:
        con.close()

    for p in problems:
        print(f"  skipped {p}")
    for k, v in stats.most_common():
        print(f"  {k}: {v}")
    print(f"Summary: records in {len(items)} trials, out {sum(stats.values())} set "
          f"({sum(v for k, v in stats.items() if 'waiting' not in k)} with a value), "
          f"skipped {len(problems)} (decision problems listed above)")


if __name__ == "__main__":
    main()
