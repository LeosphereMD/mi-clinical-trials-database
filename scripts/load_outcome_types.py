"""Load primary outcome types into the database (SPEC.md "Registry cleaning", part 4).

Usage:
    .venv\\Scripts\\python scripts\\load_outcome_types.py

What goes in:
  - registered_outcomes.outcome_category, composite_with_surrogate (yes/no) and
    outcome_comment (the owner's comment on the sheet, if any)
    for every primary outcome:
      on the review sheet with a decision -> the owner's value ("owner approved")
      on the review sheet, no decision yet -> empty
      not on the sheet, Claude's sure draft -> the draft ("Claude draft, not sampled")
  - trials.primary_outcome_type, by rule from the trial's primary outcomes:
      clinical only          every primary outcome is a clinical event
      surrogate only         every primary outcome is a surrogate or lab measure
      patient-reported only  every primary outcome is patient-reported
      mixed                  more than one type
      other                  every primary outcome is "other" (nothing else fits)
    Empty if any of the trial's primary outcomes has no type yet, or if the
    trial registers no primary outcome.

The columns are rebuilt on every run. One transaction: if any row has an
unknown decision or category, nothing is changed.
"""

import sqlite3
import sys
from collections import Counter

from create_database import DB_PATH, OUTCOME_CATEGORIES, connect
from draft_outcome_types import (REVIEW_FILE, load_suggestions, matching_suggestion,
                                 primary_outcomes)
from load_cleaning import StopError, chosen_value
from review_files import decision_of, read_csv

SINGLE_TYPE = {"clinical event": "clinical only",
               "surrogate or lab measure": "surrogate only",
               "patient-reported": "patient-reported only",
               "other": "other"}
FLAGS = {"yes", "no"}
# Short forms the owner may type that can mean only one type (each use is printed).
SHORT_FORMS = {"surrogate": "surrogate or lab measure"}


def trial_type(categories):
    kinds = set(categories)
    if len(kinds) > 1:
        return "mixed"
    return SINGLE_TYPE[kinds.pop()]


def owner_values(row, where):
    """(category, composite_with_surrogate) chosen by the owner. With 'correct',
    a blank corrected column keeps the draft value for that column."""
    decision = decision_of(row)
    draft = ((row.get("draft_category") or "").strip(),
             (row.get("draft_composite_with_surrogate") or "").strip().lower())
    if decision == "approve":
        return draft
    if decision == "correct":
        category = (row.get("corrected_category") or "").strip()
        flag = (row.get("corrected_composite_with_surrogate") or "").strip().lower()
        if not category and not flag:
            raise StopError(f"{where}: decision is 'correct' but both corrected columns are empty.")
        return category or draft[0], flag or draft[1]
    return chosen_value(row, "", "", where)  # raises the unknown-decision message


def main():
    if not DB_PATH.exists():
        raise StopError(f"{DB_PATH} does not exist.")
    if not REVIEW_FILE.exists():
        raise StopError(f"{REVIEW_FILE} does not exist. Run scripts\\draft_outcome_types.py first.")
    review = read_csv(REVIEW_FILE)
    suggestions = load_suggestions()
    outcome_report, trial_report = Counter(), Counter()

    con = connect()
    try:
        outcomes = primary_outcomes(con)
        measures = {str(oid): measure or "" for oid, _, measure, _, _ in outcomes}

        # The owner's decisions on the review sheet
        owner, on_sheet, comments = {}, set(), {}
        for line, row in enumerate(review, start=2):
            oid = (row.get("registered_outcome_id") or "").strip()
            where = f"outcome_types.csv line {line}"
            # A reworded outcome gets a new id, so the id alone is enough
            # (the text itself may be changed by Excel when it saves).
            if oid not in measures:
                outcome_report["review row skipped: outcome no longer in the database"] += 1
                continue
            on_sheet.add(oid)
            if not decision_of(row):
                continue
            category, flag = owner_values(row, where)
            if category.lower() in SHORT_FORMS:
                print(f"  {where} (outcome {oid}): '{category}' read as "
                      f"'{SHORT_FORMS[category.lower()]}'")
                category = SHORT_FORMS[category.lower()]
                outcome_report["of these: short form 'surrogate' accepted"] += 1
            if category not in OUTCOME_CATEGORIES:
                raise StopError(f"{where}: '{category}' is not an outcome type. "
                                f"Use one of: {', '.join(OUTCOME_CATEGORIES)}.")
            if flag not in FLAGS:
                raise StopError(f"{where}: composite_with_surrogate '{flag}' must be yes or no.")
            owner[oid] = (category, flag)
            comments[oid] = (row.get("comment") or "").strip() or None

        con.execute("UPDATE registered_outcomes SET outcome_category = NULL, "
                    "outcome_category_source = NULL, composite_with_surrogate = NULL, "
                    "outcome_comment = NULL")
        for oid, comment in comments.items():
            if comment:
                con.execute("UPDATE registered_outcomes SET outcome_comment = ? "
                            "WHERE registered_outcome_id = ?", (comment, oid))
                outcome_report["of these: owner comment stored"] += 1
        con.execute("UPDATE trials SET primary_outcome_type = NULL")

        per_trial = {}
        for oid, nct_id, measure, _, _ in outcomes:
            key = str(oid)
            category = source = flag = None
            if key in owner:
                (category, flag), source = owner[key], "owner approved"
            elif key in on_sheet:
                outcome_report["empty: on the review sheet, not reviewed yet"] += 1
            else:
                s = matching_suggestion(suggestions, oid, measure)
                if s and s[2] == "sure":
                    if s[1] not in OUTCOME_CATEGORIES or s[4] not in FLAGS:
                        raise StopError(f"suggestion for outcome {oid}: '{s[1]}' / '{s[4]}' "
                                        "is not a valid type / yes-no flag.")
                    category, flag, source = s[1], s[4], "Claude draft, not sampled"
                else:
                    outcome_report["empty: no usable draft (run draft_outcome_types.py)"] += 1
            if category:
                con.execute("UPDATE registered_outcomes SET outcome_category = ?, "
                            "outcome_category_source = ?, composite_with_surrogate = ? "
                            "WHERE registered_outcome_id = ?", (category, source, flag, oid))
                if flag == "yes":
                    outcome_report["of these: composite with a surrogate part"] += 1
                outcome_report[f"loaded ({source})"] += 1
            per_trial.setdefault(nct_id, []).append(category)

        for nct_id, categories in per_trial.items():
            if None in categories:
                trial_report["empty: a primary outcome has no type yet"] += 1
                continue
            value = trial_type(categories)
            con.execute("UPDATE trials SET primary_outcome_type = ? WHERE nct_id = ?",
                        (value, nct_id))
            trial_report[value] += 1
        n_trials = con.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        if n_trials - len(per_trial):
            trial_report["empty: no primary outcome registered"] += n_trials - len(per_trial)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    print(f"Review sheet: {len(review)} rows, {len(owner)} with a decision")
    print("Primary outcomes: " + ", ".join(f"{k} {v}" for k, v in outcome_report.items()))
    print("Trials (primary_outcome_type): " + ", ".join(f"{k} {v}" for k, v in trial_report.items()))
    loaded = sum(v for k, v in outcome_report.items() if k.startswith("loaded"))
    skipped = {k: v for k, v in outcome_report.items()
               if not k.startswith(("loaded", "of these"))}
    print(f"Summary: records in {len(outcomes)} primary outcomes, out {loaded} typed, "
          f"skipped {sum(skipped.values())} "
          f"({', '.join(f'{k}: {v}' for k, v in skipped.items()) or 'none'})")


if __name__ == "__main__":
    try:
        main()
    except (StopError, sqlite3.Error, OSError, KeyError) as e:
        print(f"STOPPED: {e}")
        print("Nothing was changed in the database.")
        print("Summary: stopped on error; see the message above.")
        sys.exit(1)
