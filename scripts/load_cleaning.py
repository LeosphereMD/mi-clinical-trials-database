"""Load approved registry-cleaning values into the database (SPEC.md "Registry cleaning").

Usage:
    .venv\\Scripts\\python scripts\\load_cleaning.py

What goes in:
  - interventions.generic_name: exact registry MeSH matches (automatic), plus
    rows of review/drug_names.csv that the owner approved or corrected
  - interventions.intervention_role (DRUG/BIOLOGICAL): comparator for approved
    placebo, a "role: ..." comment in drug_names.csv, or the owner's entry in
    review/intervention_roles.csv (decision 21)
  - trials.sponsor_name_clean / sponsor_group: approved rows of review/sponsors.csv
  - trials.why_stopped_category, why_stopped_secondary_category and
    why_stopped_source: approved rows of review/why_stopped.csv
Rows without a decision are left out (their database value stays empty).

The review files are the record of the owner's decisions, so the cleaning
columns are rebuilt from them on every run. One transaction: if any row has
an unknown decision or category, nothing is changed.
"""

import re
import sqlite3
import sys
from collections import Counter, defaultdict

from create_database import DB_PATH, WHY_CATEGORIES, connect
from draft_roles import ROLE_SHEET, ROLES, roles_from_comments
from review_files import REVIEW_DIR, decision_of, read_csv

SPONSOR_GROUPS = {"industry", "academic or hospital",
                  "research network or cooperative group", "government",
                  "individual investigator"}
REASON_SOURCES = {"registry", "paper"}
DOI = re.compile(r"(?<!\d)10\.\d{4,9}/\S+")   # also finds "DOI10.1093/..."
PAGE = re.compile(r"\b(?:p|pp|page|pages)\.?\s*\d+", re.IGNORECASE)


class StopError(Exception):
    pass


def chosen_value(row, draft_col, corrected_col, where):
    """The value the owner chose: the draft if approved, the correction if corrected."""
    decision = decision_of(row)
    if decision == "approve":
        return (row.get(draft_col) or "").strip()
    if decision == "correct":
        value = (row.get(corrected_col) or "").strip()
        if not value:
            raise StopError(f"{where}: decision is 'correct' but {corrected_col} is empty.")
        return value
    raise StopError(f"{where}: unknown decision '{row.get('decision')}' "
                    "(use approve, correct, or leave it blank).")


def load_file(filename):
    path = REVIEW_DIR / filename
    if not path.exists():
        raise StopError(f"{path} does not exist. Run scripts\\draft_cleaning.py first.")
    return read_csv(path)


def main():
    if not DB_PATH.exists():
        raise StopError(f"{DB_PATH} does not exist.")
    drugs = load_file("drug_names.csv")
    sponsors = load_file("sponsors.csv")
    stopped = load_file("why_stopped.csv")
    report = defaultdict(Counter)
    roles_report = Counter()

    con = connect()
    try:
        # Rebuild the cleaning columns from scratch.
        con.execute("UPDATE interventions SET generic_name = NULL, generic_name_source = NULL")
        con.execute("UPDATE trials SET sponsor_name_clean = NULL, sponsor_group = NULL, "
                    "why_stopped_category = NULL, why_stopped_secondary_category = NULL, "
                    "why_stopped_source = NULL")

        # 1a. exact registry MeSH matches
        exact = con.execute("""
            UPDATE interventions SET
                generic_name = LOWER(TRIM(name)),
                generic_name_source = 'registry MeSH exact match'
            WHERE intervention_type IN ('DRUG', 'BIOLOGICAL')
              AND EXISTS (SELECT 1 FROM intervention_mesh m
                          WHERE m.nct_id = interventions.nct_id
                            AND m.match_type = 'direct term'
                            AND LOWER(m.mesh_term) = LOWER(TRIM(interventions.name)))
        """).rowcount

        # 1b. drug names approved by the owner
        for line, row in enumerate(drugs, start=2):
            if not decision_of(row):
                report["drug_names.csv"]["not reviewed yet"] += 1
                continue
            value = chosen_value(row, "suggested_generic", "corrected_generic",
                                 f"drug_names.csv line {line}")
            if not value:
                report["drug_names.csv"]["skipped: approved, but there is no suggestion"] += 1
                continue
            n = con.execute(
                "UPDATE interventions SET generic_name = ?, generic_name_source = 'owner approved' "
                "WHERE nct_id = ? AND intervention_type = ? AND name = ?",
                (value.lower(), row["nct_id"], row["intervention_type"],
                 row["intervention_name"])).rowcount
            report["drug_names.csv"]["loaded" if n else "skipped: not in the database"] += 1

        # 1c. intervention roles (decision 21): placebo decisions, "role:" comments,
        # then the owner's role sheet
        con.execute("UPDATE interventions SET intervention_role = NULL, "
                    "intervention_role_source = NULL")
        roles_report["comparator (owner placebo decision)"] = con.execute(
            "UPDATE interventions SET intervention_role = 'comparator', "
            "intervention_role_source = 'owner placebo decision' "
            "WHERE generic_name = 'placebo' AND intervention_type IN ('DRUG', 'BIOLOGICAL')"
        ).rowcount
        for (nct_id, itype, name), role in roles_from_comments().items():
            n = con.execute("UPDATE interventions SET intervention_role = ?, "
                            "intervention_role_source = 'owner comment' "
                            "WHERE nct_id = ? AND intervention_type = ? AND name = ?",
                            (role, nct_id, itype, name)).rowcount
            roles_report[f"{role} (owner comment)" if n
                                         else "skipped: not in the database"] += 1
        if ROLE_SHEET.exists():
            for line, row in enumerate(read_csv(ROLE_SHEET), start=2):
                role = (row.get("role") or "").strip().lower()
                if not role:
                    continue
                if role not in ROLES:
                    raise StopError(f"intervention_roles.csv line {line}: role '{row['role']}' "
                                    f"must be one of: {', '.join(ROLES)}.")
                n = con.execute("UPDATE interventions SET intervention_role = ?, "
                                "intervention_role_source = 'owner role sheet' "
                                "WHERE nct_id = ? AND intervention_type = ? AND name = ?",
                                (role, row["nct_id"], row["intervention_type"],
                                 row["intervention_name"])).rowcount
                roles_report[f"{role} (owner role sheet)" if n
                                             else "skipped: not in the database"] += 1
        roles_report["DRUG/BIOLOGICAL without a role"] = con.execute(
            "SELECT COUNT(*) FROM interventions WHERE intervention_type IN "
            "('DRUG', 'BIOLOGICAL') AND intervention_role IS NULL").fetchone()[0]

        # 2. sponsors
        for line, row in enumerate(sponsors, start=2):
            if not decision_of(row):
                report["sponsors.csv"]["not reviewed yet"] += 1
                continue
            where = f"sponsors.csv line {line}"
            if decision_of(row) == "correct" and not ((row.get("corrected_name_clean") or "").strip()
                                                     or (row.get("corrected_group") or "").strip()):
                raise StopError(f"{where}: decision is 'correct' but both corrected columns are empty.")
            if decision_of(row) not in ("approve", "correct"):
                chosen_value(row, "", "", where)  # raises the unknown-decision message
            name_clean = ((row.get("corrected_name_clean") or "").strip()
                          if decision_of(row) == "correct" else "") or row["draft_name_clean"].strip()
            group = ((row.get("corrected_group") or "").strip()
                     if decision_of(row) == "correct" else "") or row["draft_group"].strip()
            if group not in SPONSOR_GROUPS:
                raise StopError(f"{where}: '{group}' is not a sponsor group. "
                                f"Use one of: {', '.join(sorted(SPONSOR_GROUPS))}.")
            n = con.execute("UPDATE trials SET sponsor_name_clean = ?, sponsor_group = ? "
                            "WHERE lead_sponsor = ?",
                            (name_clean, group, row["lead_sponsor"])).rowcount
            report["sponsors.csv"]["loaded" if n else "skipped: not in the database"] += 1

        # 3. why_stopped categories
        for line, row in enumerate(stopped, start=2):
            if not decision_of(row):
                report["why_stopped.csv"]["not reviewed yet"] += 1
                continue
            where = f"why_stopped.csv line {line}"
            category = chosen_value(row, "draft_category", "corrected_category", where)
            secondary = (row.get("secondary_category") or "").strip() or None
            source = (row.get("reason_source") or "").strip().lower() or "registry"
            comment = row.get("comment") or ""
            for value, label in ((category, "category"), (secondary, "secondary_category")):
                if value is not None and value not in WHY_CATEGORIES:
                    raise StopError(f"{where}: '{value}' is not a valid {label}. "
                                    f"Use one of: {', '.join(WHY_CATEGORIES)}.")
            if secondary == category:
                raise StopError(f"{where}: secondary_category is the same as the main category.")
            if source not in REASON_SOURCES:
                raise StopError(f"{where}: reason_source '{source}' must be registry or paper.")
            if source == "paper" and not (DOI.search(comment) and PAGE.search(comment)):
                raise StopError(f"{where}: reason_source is 'paper', so the comment must "
                                "hold the DOI (10.xxxx/...) and the page (e.g. 'p. 5').")
            why = row.get("why_stopped") or None
            n = con.execute("UPDATE trials SET why_stopped_category = ?, "
                            "why_stopped_secondary_category = ?, why_stopped_source = ? "
                            "WHERE nct_id = ? AND why_stopped IS ?",
                            (category, secondary, source, row["nct_id"], why)).rowcount
            report["why_stopped.csv"]["loaded" if n else
                                      "skipped: the registry text changed (run draft_cleaning.py)"] += 1
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    print(f"Exact registry MeSH matches loaded as generic names: {exact}")
    for name, rows in (("drug_names.csv", drugs), ("sponsors.csv", sponsors),
                       ("why_stopped.csv", stopped)):
        print(f"{name}: {len(rows)} rows; " + ", ".join(f"{k} {v}" for k, v in report[name].items()))
    print("Intervention roles: " + ", ".join(f"{k} {v}" for k, v in roles_report.items()))
    total_in = len(drugs) + len(sponsors) + len(stopped)
    loaded = sum(report[f]["loaded"] for f in report)
    skipped = Counter()
    for counts in report.values():
        for reason, n in counts.items():
            if reason != "loaded":
                skipped[reason] += n
    print(f"Summary: records in {total_in} review rows, out {loaded} loaded "
          f"(+ {exact} exact matches), skipped {sum(skipped.values())} "
          f"({', '.join(f'{k}: {v}' for k, v in skipped.items()) or 'none'})")


if __name__ == "__main__":
    try:
        main()
    except (StopError, sqlite3.Error, OSError, KeyError) as e:
        print(f"STOPPED: {e}")
        print("Nothing was changed in the database.")
        print("Summary: stopped on error; see the message above.")
        sys.exit(1)
