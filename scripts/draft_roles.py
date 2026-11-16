"""Draft the intervention role sheet (SPEC.md "Registry cleaning", part 1, decision 21).

Usage:
    .venv\\Scripts\\python scripts\\draft_roles.py

Every DRUG or BIOLOGICAL intervention gets a role in
interventions.intervention_role: study drug / comparator / background.
Roles come only from the project owner (load_cleaning.py fills them):
  1. placebo: an intervention whose approved generic name is "placebo" is a
     comparator (source "owner placebo decision");
  2. a comment in review/drug_names.csv that says "role: study drug",
     "role: comparator" or "role: background" (source "owner comment");
  3. the owner's decision in review/intervention_roles.csv (approve = the
     draft_role, correct = corrected_role; source "owner role sheet").
This script writes review/intervention_roles.csv with every DRUG or
BIOLOGICAL intervention that has no role from 1 or 2. It shows the registry
arms each intervention belongs to, a hint from the arm types, and a
draft_role from the hint (only experimental arms = study drug; only
"Active comparator" arms, when every other arm is placebo, sham or no
intervention = study drug; other comparator-only = comparator; every arm =
background; mixed or no arms = empty). Nothing goes into the database without the owner's decision.
Rows come sorted with the mixed and every-arm rows first.

A row with a decision is never changed on re-runs.
Nothing is written to the database. Run load_cleaning.py first, so the
generic names are current.
"""

import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from create_database import DB_PATH, connect
from draft_cleaning import merge_with_existing, trial_link
from review_files import REVIEW_DIR, decision_of, read_csv, write_csv

ROOT = Path(__file__).resolve().parent.parent
ROLE_SHEET = REVIEW_DIR / "intervention_roles.csv"
DRUG_FILE = REVIEW_DIR / "drug_names.csv"
ROLES = ["study drug", "comparator", "background"]
ROLE_IN_COMMENT = re.compile(r"\brole:\s*(study drug|comparator|background)\b", re.IGNORECASE)
KEY = ["nct_id", "intervention_type", "intervention_name"]
COLUMNS = ["nct_id", "ctgov_link", "intervention_type", "intervention_name", "generic_name",
           "registry_arms", "arm_hint", "draft_role", "decision", "corrected_role", "comment"]
OWNER_COLUMNS = ["decision", "corrected_role", "comment"]
HINT_MIXED = "mixed arm types: check"
HINT_EVERY = "in every arm: possibly background"
HINT_EXPERIMENTAL = "only in experimental arms: possibly study drug"
HINT_COMPARATOR = "only in comparator arms: possibly comparator"
HINT_ACTIVE_VS_PLACEBO = ("only in Active comparator arms, compared only with placebo or no "
                          "intervention: possibly study drug")
DRAFT_FROM_HINT = {HINT_EXPERIMENTAL: "study drug", HINT_COMPARATOR: "comparator",
                   HINT_EVERY: "background", HINT_ACTIVE_VS_PLACEBO: "study drug"}
HINT_ORDER = {HINT_MIXED: 0, HINT_EVERY: 1, HINT_ACTIVE_VS_PLACEBO: 2, HINT_EXPERIMENTAL: 3,
              HINT_COMPARATOR: 4}
INACTIVE_ARMS = {"PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION"}


def roles_from_comments():
    """{(nct_id, type, name): role} from decided drug_names.csv rows."""
    out = {}
    if DRUG_FILE.exists():
        for row in read_csv(DRUG_FILE):
            hit = ROLE_IN_COMMENT.search(row.get("comment") or "")
            if hit and decision_of(row):
                out[(row["nct_id"], row["intervention_type"], row["intervention_name"])] = \
                    hit.group(1).lower()
    return out


def registry_arms(raw_file, name):
    """('label [TYPE]; ...', hint) for the arms this intervention belongs to."""
    path = ROOT / raw_file if raw_file else None
    if not path or not path.exists():
        return "", "raw file missing"
    module = json.loads(path.read_text(encoding="utf-8"))["protocolSection"] \
        .get("armsInterventionsModule", {})
    arm_types = {a.get("label"): a.get("type") or "" for a in module.get("armGroups", [])}
    labels = next((i.get("armGroupLabels", []) for i in module.get("interventions", [])
                   if (i.get("name") or "").strip() == (name or "").strip()), [])
    text = "; ".join(f"{label} [{arm_types.get(label, '?')}]" for label in labels)
    types = {arm_types.get(label, "") for label in labels}
    if not labels:
        hint = "no arms listed for it"
    elif len(arm_types) > 1 and set(labels) >= set(arm_types):
        hint = HINT_EVERY
    elif types <= {"EXPERIMENTAL"}:
        hint = HINT_EXPERIMENTAL
    elif types == {"ACTIVE_COMPARATOR"} and all(
            t in INACTIVE_ARMS for label, t in arm_types.items() if label not in labels):
        # Registries often label the tested drug's arm "Active comparator" when
        # the only other arms are placebo or no intervention (decision 21).
        hint = HINT_ACTIVE_VS_PLACEBO
    elif types <= {"ACTIVE_COMPARATOR", "PLACEBO_COMPARATOR", "SHAM_COMPARATOR", "NO_INTERVENTION"}:
        hint = HINT_COMPARATOR
    else:
        hint = HINT_MIXED
    return text, hint


def main():
    if not DB_PATH.exists():
        print(f"STOPPED: {DB_PATH} does not exist.")
        print("Summary: records in 0, out 0, skipped 0 (stopped)")
        sys.exit(1)
    from_comments = roles_from_comments()
    con = connect()
    try:
        items = con.execute(
            "SELECT i.nct_id, i.intervention_type, i.name, i.generic_name, t.raw_json_file "
            "FROM interventions i JOIN trials t ON t.nct_id = i.nct_id "
            "WHERE i.intervention_type IN ('DRUG', 'BIOLOGICAL') "
            "ORDER BY i.nct_id, i.name").fetchall()
    except sqlite3.Error as e:
        print(f"STOPPED: {e}")
        print("Summary: records in 0, out 0, skipped 0 (stopped; no file written)")
        sys.exit(1)
    finally:
        con.close()

    rows, covered = [], Counter()
    for nct_id, itype, name, generic, raw_file in items:
        if generic == "placebo":
            covered["placebo decision (comparator)"] += 1
            continue
        if (nct_id, itype, name) in from_comments:
            covered["role in an owner comment"] += 1
            continue
        arms, hint = registry_arms(raw_file, name)
        rows.append({"nct_id": nct_id, "ctgov_link": trial_link(nct_id),
                     "intervention_type": itype, "intervention_name": name,
                     "generic_name": generic or "", "registry_arms": arms, "arm_hint": hint,
                     "draft_role": DRAFT_FROM_HINT.get(hint, ""),
                     "decision": "", "corrected_role": "", "comment": ""})
    merged, counts = merge_with_existing(ROLE_SHEET, KEY, rows, OWNER_COLUMNS)
    merged.sort(key=lambda r: (HINT_ORDER.get(r.get("arm_hint"), 5), r["nct_id"],
                               r["intervention_name"]))
    bad = [f"{r['nct_id']} {r['intervention_name']}: '{r['corrected_role']}'" for r in merged
           if r.get("corrected_role", "").strip()
           and r["corrected_role"].strip().lower() not in ROLES]
    try:
        write_csv(ROLE_SHEET, COLUMNS, merged)
    except PermissionError:
        print(f"STOPPED: {ROLE_SHEET} is open in another program (probably Excel). "
              "Save and close it, then run this script again.")
        print("Summary: no file written")
        sys.exit(1)

    filled = sum(1 for r in merged if decision_of(r))
    print(f"DRUG/BIOLOGICAL interventions: {len(items)}")
    print("Role already known from the owner's decisions: " +
          (", ".join(f"{k} {v}" for k, v in covered.items()) or "none"))
    print("Arm hints on the sheet: " + ", ".join(
        f"{k} {v}" for k, v in Counter(r["arm_hint"] for r in rows).most_common()))
    for b in bad:
        print(f"WARNING: unknown role (use {' / '.join(ROLES)}): {b}")
    print("Draft roles: " + ", ".join(f"{k or 'empty (check)'} {v}" for k, v in
                                     Counter(r["draft_role"] for r in rows).most_common()))
    print(f"{ROLE_SHEET.name}: {len(merged)} rows, {filled} with a decision "
          f"({', '.join(f'{k} {v}' for k, v in counts.items())})")
    print(f"Summary: records in {len(items)} interventions, out {len(merged)} rows on the "
          f"role sheet, skipped {sum(covered.values())} (role known from owner decisions)")


if __name__ == "__main__":
    main()
