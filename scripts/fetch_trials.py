"""Download every trial matching SPEC.md from ClinicalTrials.gov and load it into the database.

Usage:
    .venv\\Scripts\\python scripts\\fetch_trials.py --count   # only print how many trials match
    .venv\\Scripts\\python scripts\\fetch_trials.py           # download and load

What it does (full run):
  1. Asks the ClinicalTrials.gov API v2 for all matching trials, page by page,
     waiting briefly between requests.
  2. Saves each trial's raw API record to data/raw/<NCT ID>.json before reading it.
  3. Checks each trial against the SPEC.md inclusion rules again, locally.
  4. Loads it into data/ami_trials.db. A trial already in the database is
     updated (matched by NCT ID), never added twice.
The whole load is one transaction: if anything goes wrong, the script stops
with a clear message and the database is left exactly as it was.

Inclusion rules (SPEC.md decisions 1-4):
  - MeSH condition term "Myocardial Infarction" (or a child term, i.e. a term
    whose ancestor is "Myocardial Infarction") or "Acute Coronary Syndrome"
  - Phase 3 or Phase 2/3
  - At least one DRUG or BIOLOGICAL intervention
  - Start date (actual or estimated) on or after 2010-01-01; trials without a
    start date are excluded and counted
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from create_database import DB_PATH, connect

API_URL = "https://clinicaltrials.gov/api/v2/studies"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PAGE_SIZE = 100
WAIT_SECONDS = 1.0
TIMEOUT_SECONDS = 60

CONDITION_RULE = (
    '(AREA[ConditionMeshTerm]"Myocardial Infarction"'
    ' OR AREA[ConditionAncestorTerm]"Myocardial Infarction"'
    ' OR AREA[ConditionMeshTerm]"Acute Coronary Syndrome")'
)
BASE_RULE = (CONDITION_RULE
             + " AND AREA[Phase]PHASE3"
             + " AND AREA[InterventionType](DRUG OR BIOLOGICAL)")
QUERY = BASE_RULE + " AND AREA[StartDate]RANGE[2010-01-01,MAX]"
NO_START_DATE_QUERY = BASE_RULE + " AND AREA[StartDate]MISSING"


class StopError(Exception):
    """A problem that must stop the script, with a message for the user."""


# ---------------------------------------------------------------- API access

_first_request = True


def get_json(params):
    """One API request. Waits briefly before every request except the first."""
    global _first_request
    if not _first_request:
        time.sleep(WAIT_SECONDS)
    _first_request = False
    try:
        response = requests.get(API_URL, params=params, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        raise StopError(f"Could not reach ClinicalTrials.gov: {e}")
    if response.status_code != 200:
        raise StopError(f"ClinicalTrials.gov answered with error {response.status_code}: "
                        f"{response.text[:300]}")
    try:
        return response.json()
    except ValueError:
        raise StopError("ClinicalTrials.gov sent a reply that is not valid JSON.")


def count_matches(query):
    data = get_json({"filter.advanced": query, "countTotal": "true", "pageSize": 1})
    if "totalCount" not in data:
        raise StopError("The API reply did not include a total count.")
    return data["totalCount"]


def download_all():
    """Download every matching trial, saving each raw record before parsing."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    studies, total, token, page = [], None, None, 0
    while True:
        params = {"filter.advanced": QUERY, "pageSize": PAGE_SIZE, "countTotal": "true"}
        if token:
            params["pageToken"] = token
        data = get_json(params)
        page += 1
        if total is None:
            total = data.get("totalCount")
        for study in data.get("studies", []):
            nct_id = (study.get("protocolSection", {})
                      .get("identificationModule", {}).get("nctId"))
            if not nct_id:
                raise StopError(f"A trial on page {page} has no NCT ID.")
            (RAW_DIR / f"{nct_id}.json").write_text(
                json.dumps(study, ensure_ascii=False, indent=2), encoding="utf-8")
            studies.append((nct_id, study))
        print(f"  page {page}: {len(studies)} of {total} trials downloaded")
        token = data.get("nextPageToken")
        if not token:
            break
    if total is not None and len(studies) != total:
        raise StopError(f"The API said {total} trials match but {len(studies)} were "
                        "downloaded. The registry may have changed during the download; "
                        "please run the script again.")
    return studies


# ------------------------------------------------------------ reading a trial

def clean(value):
    """Missing or blank stays empty (NULL)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return value


def rule_failure(study):
    """Re-check the SPEC.md inclusion rules. Returns the reason it fails, or None."""
    p = study.get("protocolSection", {})
    browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    meshes = {m.get("term") for m in browse.get("meshes", [])}
    ancestors = {a.get("term") for a in browse.get("ancestors", [])}
    if not ({"Myocardial Infarction", "Acute Coronary Syndrome"} & meshes
            or "Myocardial Infarction" in ancestors):
        return "no qualifying MeSH condition term"
    if "PHASE3" not in p.get("designModule", {}).get("phases", []):
        return "not Phase 3 or Phase 2/3"
    types = {i.get("type") for i in p.get("armsInterventionsModule", {})
             .get("interventions", [])}
    if not types & {"DRUG", "BIOLOGICAL"}:
        return "no drug or biological intervention"
    start = clean(p.get("statusModule", {}).get("startDateStruct", {}).get("date"))
    if start is None:
        return "no start date"
    # Dates can be "2015-03" or "2015-03-01"; comparing year-month is exact here
    # because the cutoff is the first day of a month.
    if start[:7] < "2010-01":
        return "start date before 2010-01-01"
    return None


STEMI_MESH = "ST Elevation Myocardial Infarction"
NSTEMI_MESH = "Non-ST Elevated Myocardial Infarction"
ACS_MESH = {"Acute Coronary Syndrome", "Angina, Unstable"}
# NSTEMI words: NSTEMI, N-STEMI, non-STEMI, non-ST-elevation,
# non-ST-segment elevation (hyphen or space)
NSTEMI_WORDS = re.compile(
    r"\b(?:N[\s-]?STEMI|non[\s-]?STEMI|non[\s-]?ST[\s-](?:segment[\s-])?elevation)\b",
    re.IGNORECASE)
# STEMI words: STEMI, ST-elevation, ST-segment elevation. Searched only after
# NSTEMI words are removed, so NSTEMI wording can never count as STEMI.
STEMI_WORDS = re.compile(r"\b(?:STEMI|ST[\s-](?:segment[\s-])?elevation)\b",
                         re.IGNORECASE)
EXCLUSION_HEADING = re.compile(r"exclusion\s+criteria", re.IGNORECASE)


def label_from_text(text):
    """STEMI / NSTEMI / STEMI + NSTEMI from free text, or None if neither appears."""
    if not text:
        return None
    has_nstemi = bool(NSTEMI_WORDS.search(text))
    has_stemi = bool(STEMI_WORDS.search(NSTEMI_WORDS.sub(" ", text)))
    if has_stemi and has_nstemi:
        return "STEMI + NSTEMI"
    if has_stemi:
        return "STEMI"
    if has_nstemi:
        return "NSTEMI"
    return None


def inclusion_criteria(eligibility_text):
    """Text before the 'Exclusion Criteria' heading, or None if there is no heading."""
    if not eligibility_text:
        return None
    heading = EXCLUSION_HEADING.search(eligibility_text)
    return eligibility_text[:heading.start()] if heading else None


def population(study):
    """Population label and its source, following SPEC.md "Population label"."""
    p = study["protocolSection"]
    browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    meshes = {m.get("term") for m in browse.get("meshes", [])}
    if meshes & ACS_MESH:
        return "ACS mixed", "mesh"
    if STEMI_MESH in meshes and NSTEMI_MESH in meshes:
        return "STEMI + NSTEMI", "mesh"
    if STEMI_MESH in meshes:
        return "STEMI", "mesh"
    if NSTEMI_MESH in meshes:
        return "NSTEMI", "mesh"
    ident = p.get("identificationModule", {})
    texts = [
        ("title", " | ".join(t for t in (ident.get("briefTitle"),
                                         ident.get("officialTitle")) if t)),
        ("conditions", " | ".join(p.get("conditionsModule", {}).get("conditions", []))),
        ("eligibility", inclusion_criteria(
            p.get("eligibilityModule", {}).get("eligibilityCriteria"))),
    ]
    for source, text in texts:
        label = label_from_text(text)
        if label:
            return label, source
    return "MI unspecified", "mesh"


def countries(study):
    """Distinct countries from the registry's location list (sorted)."""
    locations = (study["protocolSection"].get("contactsLocationsModule", {})
                 .get("locations", []))
    return sorted({clean(loc.get("country")) for loc in locations} - {None})


def trial_row(nct_id, study):
    p = study["protocolSection"]
    status = p.get("statusModule", {})
    design = p.get("designModule", {})
    design_info = design.get("designInfo", {})
    sponsor = p.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {})
    enrollment = design.get("enrollmentInfo", {})
    types = {i.get("type") for i in p.get("armsInterventionsModule", {})
             .get("interventions", [])}
    has_results = study.get("hasResults")
    pop_label, pop_source = population(study)
    n_countries = len(countries(study)) or None   # no locations listed -> empty
    return {
        "population": pop_label,
        "population_source": pop_source,
        "n_countries": n_countries,
        "nct_id": nct_id,
        "title": clean(p.get("identificationModule", {}).get("briefTitle")),
        "phase_label": clean("/".join(design.get("phases", []))),
        "overall_status": clean(status.get("overallStatus")),
        "why_stopped": clean(status.get("whyStopped")),
        "start_date": clean(status.get("startDateStruct", {}).get("date")),
        "start_date_type": clean(status.get("startDateStruct", {}).get("type")),
        "completion_date": clean(status.get("completionDateStruct", {}).get("date")),
        "completion_date_type": clean(status.get("completionDateStruct", {}).get("type")),
        "enrollment": enrollment.get("count"),
        "enrollment_type": clean(enrollment.get("type")),
        "lead_sponsor": clean(sponsor.get("name")),
        "sponsor_class": clean(sponsor.get("class")),
        "has_device_or_procedure": int(bool(types & {"DEVICE", "PROCEDURE"})),
        "allocation": clean(design_info.get("allocation")),
        "masking": clean(design_info.get("maskingInfo", {}).get("masking")),
        "has_results": None if has_results is None else int(bool(has_results)),
        "last_updated": clean(status.get("lastUpdatePostDateStruct", {}).get("date")),
        "raw_json_file": f"data/raw/{nct_id}.json",
    }


def condition_rows(study):
    conds = study["protocolSection"].get("conditionsModule", {}).get("conditions", [])
    browse = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    rows = [(clean(c), None, None, None) for c in conds]
    rows += [(None, clean(m.get("term")), clean(m.get("id")), "direct term")
             for m in browse.get("meshes", [])]
    rows += [(None, clean(a.get("term")), clean(a.get("id")), "parent term")
             for a in browse.get("ancestors", [])]
    return rows


def intervention_rows(study):
    items = study["protocolSection"].get("armsInterventionsModule", {}).get("interventions", [])
    return [(clean(i.get("type")), clean(i.get("name")),
             clean("; ".join(i.get("otherNames", []))), clean(i.get("description")))
            for i in items]


def arm_rows(study):
    groups = study["protocolSection"].get("armsInterventionsModule", {}).get("armGroups", [])
    return [(g.get("label"), clean(g.get("type")), clean(g.get("description")))
            for g in groups if clean(g.get("label"))]


def outcome_rows(study):
    out = study["protocolSection"].get("outcomesModule", {})
    rows = []
    for key, kind in (("primaryOutcomes", "primary"), ("secondaryOutcomes", "secondary")):
        for o in out.get(key, []):
            rows.append((kind, clean(o.get("measure")), clean(o.get("timeFrame")),
                         clean(o.get("description"))))
    return rows


# ------------------------------------------------------------ saving a trial

TRIAL_COLUMNS = ["nct_id", "title", "phase_label", "overall_status", "why_stopped",
                 "start_date", "start_date_type", "completion_date",
                 "completion_date_type", "enrollment", "enrollment_type",
                 "lead_sponsor", "sponsor_class", "population",
                 "population_source", "n_countries", "has_device_or_procedure",
                 "allocation", "masking", "has_results", "last_updated",
                 "raw_json_file"]


def upsert_trial(con, row, run_id):
    """Insert a new trial, or update the registry fields of an existing one.
    publication_status and first_seen_run are never overwritten. Population is
    worked out again from the registry each run; the owner's corrections live
    in registry_checks, so they are not lost."""
    cols = ", ".join(TRIAL_COLUMNS)
    marks = ", ".join(f":{c}" for c in TRIAL_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in TRIAL_COLUMNS if c != "nct_id")
    con.execute(
        f"INSERT INTO trials ({cols}, publication_status, first_seen_run, last_seen_run) "
        f"VALUES ({marks}, 'not yet searched', :run_id, :run_id) "
        f"ON CONFLICT(nct_id) DO UPDATE SET {updates}, last_seen_run = excluded.last_seen_run",
        {**row, "run_id": run_id})


def sync_rows(con, table, id_col, cols, nct_id, new_rows, stats):
    """Make a trial's rows in `table` match the registry: identical rows stay as
    they are, new ones are added, ones no longer in the registry are removed,
    except rows that other tables point to, which are kept and counted."""
    col_list = ", ".join(cols)
    existing = con.execute(f"SELECT {id_col}, {col_list} FROM {table} WHERE nct_id = ?",
                           (nct_id,)).fetchall()
    wanted = Counter(new_rows)
    for row_id, *values in existing:
        values = tuple(values)
        if wanted[values] > 0:
            wanted[values] -= 1
        else:
            try:
                con.execute(f"DELETE FROM {table} WHERE {id_col} = ?", (row_id,))
                stats[table]["removed"] += 1
            except sqlite3.IntegrityError:
                stats[table]["kept (used elsewhere)"] += 1
    marks = ", ".join("?" for _ in cols)
    for values, n in wanted.items():
        for _ in range(n):
            con.execute(f"INSERT INTO {table} (nct_id, {col_list}) VALUES (?, {marks})",
                        (nct_id, *values))
            stats[table]["added"] += 1


def sync_arms(con, nct_id, new_rows, stats):
    """Arms are matched by label (extracted values point to them by label)."""
    labels = set()
    for label, arm_type, description in new_rows:
        labels.add(label)
        old = con.execute("SELECT arm_type, description FROM arms "
                          "WHERE nct_id = ? AND arm_label = ?", (nct_id, label)).fetchone()
        if old is None:
            con.execute("INSERT INTO arms (nct_id, arm_label, arm_type, description) "
                        "VALUES (?, ?, ?, ?)", (nct_id, label, arm_type, description))
            stats["arms"]["added"] += 1
        elif tuple(old) != (arm_type, description):
            con.execute("UPDATE arms SET arm_type = ?, description = ? "
                        "WHERE nct_id = ? AND arm_label = ?",
                        (arm_type, description, nct_id, label))
            stats["arms"]["updated"] += 1
    for (label,) in con.execute("SELECT arm_label FROM arms WHERE nct_id = ?",
                                (nct_id,)).fetchall():
        if label not in labels:
            try:
                con.execute("DELETE FROM arms WHERE nct_id = ? AND arm_label = ?",
                            (nct_id, label))
                stats["arms"]["removed"] += 1
            except sqlite3.IntegrityError:
                stats["arms"]["kept (used elsewhere)"] += 1


# ---------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", action="store_true",
                        help="only print how many trials match, then stop")
    args = parser.parse_args()

    if args.count:
        total = count_matches(QUERY)
        print(f"Trials matching SPEC.md: {total}")
        print("Summary: records in 0, out 0, skipped 0 (count only; nothing downloaded or saved)")
        return

    if not DB_PATH.exists():
        raise StopError(f"{DB_PATH} does not exist. Run scripts\\create_database.py first.")

    print("Downloading matching trials from ClinicalTrials.gov ...")
    no_start_date = count_matches(NO_START_DATE_QUERY)
    studies = download_all()

    con = connect()
    try:
        run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        run_id = con.execute("INSERT INTO fetch_runs (run_date, query_used) VALUES (?, ?)",
                             (run_date, QUERY)).lastrowid
        skipped, seen = Counter(), set()
        new_trials = updated_trials = 0
        stats = {t: Counter() for t in
                 ("conditions", "interventions", "arms", "registered_outcomes",
                  "trial_countries")}
        populations = Counter()
        for nct_id, study in studies:
            if nct_id in seen:
                skipped["appeared twice in the download"] += 1
                continue
            seen.add(nct_id)
            reason = rule_failure(study)
            if reason:
                skipped[f"failed local check: {reason}"] += 1
                continue
            exists = con.execute("SELECT 1 FROM trials WHERE nct_id = ?",
                                 (nct_id,)).fetchone()
            row = trial_row(nct_id, study)
            upsert_trial(con, row, run_id)
            populations[f"{row['population']} (from {row['population_source']})"] += 1
            if exists:
                updated_trials += 1
            else:
                new_trials += 1
            sync_rows(con, "conditions", "condition_id",
                      ["condition_text", "mesh_term", "mesh_id", "match_type"],
                      nct_id, condition_rows(study), stats)
            sync_rows(con, "interventions", "intervention_id",
                      ["intervention_type", "name", "other_names", "description"],
                      nct_id, intervention_rows(study), stats)
            sync_arms(con, nct_id, arm_rows(study), stats)
            sync_rows(con, "registered_outcomes", "registered_outcome_id",
                      ["outcome_type", "measure", "time_frame", "description"],
                      nct_id, outcome_rows(study), stats)
            sync_rows(con, "trial_countries", "rowid", ["country"],
                      nct_id, [(c,) for c in countries(study)], stats)

        kept = new_trials + updated_trials
        reasons = dict(skipped)
        reasons["excluded by the search: no start date (not downloaded)"] = no_start_date
        con.execute("UPDATE fetch_runs SET records_in = ?, records_kept = ?, "
                    "records_skipped = ?, skip_reasons = ? WHERE run_id = ?",
                    (len(studies), kept, sum(skipped.values()),
                     json.dumps(reasons), run_id))
        not_seen = con.execute("SELECT COUNT(*) FROM trials WHERE last_seen_run <> ?",
                               (run_id,)).fetchone()[0]
        con.commit()
    except Exception:
        con.rollback()
        con.close()
        raise
    con.close()

    print()
    print(f"Run {run_id} on {run_date}")
    print(f"Raw files saved in: {RAW_DIR}")
    for table, c in stats.items():
        detail = ", ".join(f"{k} {v}" for k, v in c.items()) or "no changes"
        print(f"  {table}: {detail}")
    print("Population labels:")
    for label, n in sorted(populations.items()):
        print(f"  {label}: {n}")
    if not_seen:
        print(f"Trials in the database that no longer match the search: {not_seen} "
              "(kept, not deleted)")
    print(f"Excluded for having no start date: {no_start_date}")
    print(f"Summary: records in {len(studies)}, out {kept} "
          f"({new_trials} new, {updated_trials} updated), "
          f"skipped {sum(skipped.values())}"
          + (f" ({', '.join(f'{k}: {v}' for k, v in skipped.items())})" if skipped else ""))


if __name__ == "__main__":
    try:
        main()
    except (StopError, sqlite3.Error, OSError) as e:
        print(f"\nSTOPPED: {e}")
        print("Nothing was changed in the database.")
        print("Summary: stopped on error; see the message above.")
        sys.exit(1)
