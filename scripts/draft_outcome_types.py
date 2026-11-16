"""Draft the primary outcome type review file (SPEC.md "Registry cleaning", part 4).

Usage:
    .venv\\Scripts\\python scripts\\draft_outcome_types.py

Reads Claude's draft type for every registered primary outcome from
review/outcome_type_suggestions_claude.csv and writes review/outcome_types.csv
with the rows the project owner checks:
  - every uncertain draft
  - every primary outcome without a draft (e.g. new or reworded in a later download)
  - a random 15% (rounded up) of the sure drafts, drawn with a fixed seed.
    Each sure draft gets a fixed random number from the seed and its id, and
    the lowest 15% are drawn, so a change to a few drafts leaves the rest of
    the sample as it was.
Sure drafts that are not drawn go into the database without review
(load_outcome_types.py).

Rows that already have a decision are never changed. Nothing is written to
the database. Only outcome_types.csv is written, so this can run while the
owner is working on the other review files.
"""

import hashlib
import math
import sqlite3
import sys
from collections import Counter

from create_database import DB_PATH, connect
from draft_cleaning import EXCEL_CELL_LIMIT, merge_with_existing, trial_link
from review_files import REVIEW_DIR, read_csv, write_csv

SUGGESTIONS = REVIEW_DIR / "outcome_type_suggestions_claude.csv"
REVIEW_FILE = REVIEW_DIR / "outcome_types.csv"
SEED = 20261115
SAMPLE_SHARE = 0.15

REASON_UNCERTAIN = "uncertain draft"
REASON_NO_DRAFT = "no draft yet"
REASON_SAMPLE = "random check of a sure draft"
REASON_ORDER = {REASON_UNCERTAIN: 0, REASON_NO_DRAFT: 1, REASON_SAMPLE: 2}

# Column order of the review sheet: what the owner reads and fills in first,
# long registry text and technical ids last.
COLUMNS = ["review_reason", "ctgov_link", "measure", "draft_category",
           "draft_composite_with_surrogate", "draft_note", "decision",
           "corrected_category", "corrected_composite_with_surrogate", "comment",
           "time_frame", "description", "registered_outcome_id", "nct_id"]
OWNER_COLUMNS = ["decision", "corrected_category", "corrected_composite_with_surrogate",
                 "comment"]


def load_suggestions():
    """{registered_outcome_id: (measure, category, confidence, note, composite_with_surrogate)}"""
    if not SUGGESTIONS.exists():
        return {}
    return {r["registered_outcome_id"]: (r["measure"], r["suggested_category"],
                                         r["confidence"], r["note"],
                                         r.get("composite_with_surrogate") or "")
            for r in read_csv(SUGGESTIONS)}


def sample_order(outcome_id):
    """A fixed random number for this outcome, from the seed and its id."""
    return hashlib.sha256(f"{SEED}-{outcome_id}".encode()).hexdigest()


def one_line(text):
    """Registry text on one line, so each sheet row has normal height in Excel."""
    return " ".join((text or "").split())


def primary_outcomes(con):
    return con.execute(
        "SELECT registered_outcome_id, nct_id, measure, time_frame, description "
        "FROM registered_outcomes WHERE outcome_type = 'primary' "
        "ORDER BY nct_id, registered_outcome_id").fetchall()


def matching_suggestion(suggestions, outcome_id, measure):
    """Claude's draft, only if it was made for this exact outcome text."""
    s = suggestions.get(str(outcome_id))
    return s if s and s[0] == (measure or "") else None


def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    suggestions = load_suggestions()
    con = connect()
    try:
        outcomes = primary_outcomes(con)
    except sqlite3.Error as e:
        print(f"STOPPED: {e}")
        print("Summary: records in 0, out 0, skipped 0 (stopped; no file written)")
        sys.exit(1)
    finally:
        con.close()

    reasons, drafts = {}, {}
    sure = []
    for oid, nct_id, measure, _, _ in outcomes:
        s = matching_suggestion(suggestions, oid, measure)
        drafts[oid] = s
        if s is None:
            reasons[oid] = REASON_NO_DRAFT
        elif s[2] == "uncertain":
            reasons[oid] = REASON_UNCERTAIN
        else:
            sure.append(oid)
    n_sample = math.ceil(len(sure) * SAMPLE_SHARE)
    for oid in sorted(sure, key=sample_order)[:n_sample]:
        reasons[oid] = REASON_SAMPLE

    rows = []
    for oid, nct_id, measure, time_frame, description in outcomes:
        if oid not in reasons:
            continue
        s = drafts[oid]
        description = one_line(description)
        if len(description) > EXCEL_CELL_LIMIT:
            description = description[:EXCEL_CELL_LIMIT] + " [cut here: full text in raw file]"
        rows.append({
            "review_reason": reasons[oid], "ctgov_link": trial_link(nct_id),
            "measure": one_line(measure),
            "draft_category": s[1] if s else "",
            "draft_composite_with_surrogate": s[4] if s else "",
            "draft_note": s[3] if s else "",
            "decision": "", "corrected_category": "",
            "corrected_composite_with_surrogate": "", "comment": "",
            "time_frame": one_line(time_frame), "description": description,
            "registered_outcome_id": str(oid), "nct_id": nct_id})
    rows.sort(key=lambda r: (REASON_ORDER[r["review_reason"]], r["nct_id"],
                             int(r["registered_outcome_id"])))

    merged, counts = merge_with_existing(REVIEW_FILE, ["registered_outcome_id"], rows,
                                         OWNER_COLUMNS)
    try:
        write_csv(REVIEW_FILE, COLUMNS, merged)
    except PermissionError:
        print(f"STOPPED: {REVIEW_FILE} is open in another program (probably Excel). "
              "Save and close it, then run this script again.")
        print("Summary: no file written")
        sys.exit(1)

    # In this file a row leaves the sheet when it is no longer selected for review.
    counts = {k.replace("no longer in the database", "no longer selected for review"): v
              for k, v in counts.items()}
    not_selected = len(outcomes) - len(rows)
    print(f"Primary outcomes in the database: {len(outcomes)}")
    print("Claude's drafts: " + ", ".join(
        f"{k} {v}" for k, v in Counter(d[1] for d in drafts.values() if d).most_common())
          + f"; composite with surrogate part: "
          f"{sum(1 for d in drafts.values() if d and d[4] == 'yes')}")
    print("On the review sheet: " + ", ".join(
        f"{k} {v}" for k, v in Counter(reasons.values()).most_common())
          + f" (random checks: {n_sample} of {len(sure)} sure drafts, seed {SEED})")
    print(f"Sure drafts not drawn (go in without review): {not_selected}")
    print(f"{REVIEW_FILE.name}: {len(merged)} rows "
          f"({', '.join(f'{k} {v}' for k, v in counts.items())})")
    print(f"Summary: records in {len(outcomes)} primary outcomes, out {len(merged)} rows "
          f"in the review file, skipped {not_selected} (sure drafts not drawn for review)")


if __name__ == "__main__":
    main()
